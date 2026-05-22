#!/usr/bin/env python3
"""
gdrive_backup.py — บีบอัดโฟลเดอร์/ไฟล์เป็น .tar.gz แล้วอัปโหลดขึ้น Google Drive ส่วนตัว
ใช้ Google Drive API v3 โดยตรง (ไม่ต้องใช้ rclone)

Usage:
    python gdrive_backup.py --source /path/to/folder
    python gdrive_backup.py --source /path/to/folder --dest-folder-id <FOLDER_ID>
    python gdrive_backup.py --source /path/to/folder --name my_backup --keep-local
    python gdrive_backup.py --source /path/to/folder --retention 7
    python gdrive_backup.py --list-backups
    python gdrive_backup.py --source /path/to/a.txt /path/to/b.log --name combined

Setup:
    1. pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client python-dotenv
    2. สร้างไฟล์ .env (ดู .env.example)
    3. วาง credentials.json จาก Google Cloud Console ไว้ในโฟลเดอร์เดียวกัน
    4. รันครั้งแรก — จะเปิด browser ให้ login Google เพื่อขอ OAuth token
"""

import argparse
import io
import logging
import os
import re
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

# ─────────────────────────────────────────────
# Config & constants
# ─────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)

# OAuth scopes — drive.file = เข้าถึงเฉพาะไฟล์ที่ app สร้างขึ้น (ปลอดภัยกว่า full drive)
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# ค่าจาก .env (ดู .env.example)
CREDENTIALS_FILE  = Path(os.getenv("GDRIVE_CREDENTIALS_FILE", BASE_DIR / "credentials.json"))
TOKEN_FILE        = Path(os.getenv("GDRIVE_TOKEN_FILE",       BASE_DIR / "token.json"))
DEFAULT_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "root")   # Google Drive folder ID ปลายทาง
LOG_FILE          = os.getenv("BACKUP_LOG_FILE", str(BASE_DIR / "backup.log"))
DEFAULT_RETENTION = int(os.getenv("BACKUP_RETENTION_DAYS", "0"))  # 0 = ไม่ลบอัตโนมัติ

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

def setup_logger(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if LOG_FILE:
        Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    return logging.getLogger("gdrive_backup")


# ─────────────────────────────────────────────
# Google Drive auth
# ─────────────────────────────────────────────

def get_drive_service():
    """ดึง authenticated Google Drive service — ใช้ token ที่แคชไว้, หรือ refresh/login ใหม่"""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"ไม่พบไฟล์ {CREDENTIALS_FILE}\n"
                    "โปรดดาวน์โหลด credentials.json จาก Google Cloud Console\n"
                    "  https://console.cloud.google.com/ → APIs & Services → Credentials → OAuth 2.0 Client IDs"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            # Headless / server mode — ไม่ต้องการ browser บนเครื่อง
            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
            auth_url, _ = flow.authorization_url(prompt="consent")
            print("\n" + "="*60)
            print("เปิด URL นี้บน browser เครื่องอื่น:")
            print(f"\n  {auth_url}\n")
            print("login Google → อนุญาต → copy authorization code")
            print("="*60)
            code = input("วาง authorization code ที่นี่: ").strip()
            flow.fetch_token(code=code)
            creds = flow.credentials

        # บันทึก token เพื่อใช้ครั้งต่อไป
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return build("drive", "v3", credentials=creds)


# ─────────────────────────────────────────────
# Core: compress → upload → cleanup
# ─────────────────────────────────────────────

def compress_to_stream(sources: list[Path], log: logging.Logger) -> io.BytesIO:
    """บีบอัด source paths เป็น tar.gz แล้วคืนค่าเป็น in-memory BytesIO (ไม่แตะ disk)"""
    buf = io.BytesIO()
    log.info(f"กำลังบีบอัด {len(sources)} รายการ (in-memory)...")
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for src in sources:
            log.debug(f"  + {src} → {src.name}")
            tar.add(str(src), arcname=src.name)
    buf.seek(0)
    size_mb = buf.getbuffer().nbytes / 1_048_576
    log.info(f"บีบอัดเสร็จ: {size_mb:.2f} MB")
    return buf


def compress_to_temp(sources: list[Path], log: logging.Logger) -> Path:
    """บีบอัดลง temp file (ใช้เมื่อ --keep-local หรือ --use-temp-file)"""
    fd, tmp_path = tempfile.mkstemp(suffix=".tar.gz")
    os.close(fd)
    tmp = Path(tmp_path)
    log.info(f"กำลังบีบอัด {len(sources)} รายการ → {tmp}")
    with tarfile.open(str(tmp), "w:gz") as tar:
        for src in sources:
            log.debug(f"  + {src} → {src.name}")
            tar.add(str(src), arcname=src.name)
    size_mb = tmp.stat().st_size / 1_048_576
    log.info(f"บีบอัดเสร็จ: {size_mb:.2f} MB")
    return tmp


def upload_to_drive(
    service,
    file_stream: io.IOBase,
    filename: str,
    folder_id: str,
    log: logging.Logger,
) -> dict:
    """อัปโหลดไฟล์ขึ้น Google Drive พร้อม resumable upload — คืน file metadata"""
    file_meta = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(file_stream, mimetype="application/gzip", resumable=True)

    log.info(f"กำลังอัปโหลด '{filename}' → folder_id={folder_id}")
    request = service.files().create(body=file_meta, media_body=media, fields="id,name,size,webViewLink")

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            log.debug(f"  อัปโหลด {pct}%...")

    log.info(f"✅ อัปโหลดสำเร็จ")
    log.info(f"   id   : {response['id']}")
    log.info(f"   link : {response.get('webViewLink', '-')}")
    return response


def delete_old_backups(
    service,
    folder_id: str,
    retention_days: int,
    prefix: str,
    log: logging.Logger,
):
    """ลบไฟล์ backup เก่ากว่า retention_days วัน ใน Drive folder"""
    if retention_days <= 0:
        return
    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    query = f"'{folder_id}' in parents and name contains '{prefix}' and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id,name,createdTime)",
        orderBy="createdTime asc",
    ).execute()
    for f in results.get("files", []):
        created = datetime.fromisoformat(f["createdTime"].replace("Z", "+00:00")).timestamp()
        if created < cutoff:
            service.files().delete(fileId=f["id"]).execute()
            log.info(f"🗑️  ลบ backup เก่า: {f['name']}  (id={f['id']})")


def list_backups(service, folder_id: str, log: logging.Logger):
    """แสดงรายการไฟล์ใน folder ปลายทาง"""
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id,name,size,createdTime,webViewLink)",
        orderBy="createdTime desc",
    ).execute()
    files = results.get("files", [])
    if not files:
        log.info("ไม่พบไฟล์ใน folder นี้")
        return
    log.info(f"\n{'ชื่อไฟล์':<50} {'ขนาด':>9}  {'สร้างเมื่อ':<20}  ID")
    log.info("-" * 110)
    for f in files:
        size  = int(f.get("size", 0))
        size_str = f"{size/1_048_576:.1f} MB" if size else "-"
        created  = f.get("createdTime", "")[:19].replace("T", " ")
        log.info(f"{f['name']:<50} {size_str:>9}  {created:<20}  {f['id']}")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="บีบอัดไฟล์/โฟลเดอร์แล้วอัปโหลดขึ้น Google Drive ส่วนตัว",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""ตัวอย่าง:
  # อัปโหลดโฟลเดอร์เดียว
  python gdrive_backup.py --source /data/myproject

  # ระบุ folder ID ปลายทางและตั้งชื่อเอง
  python gdrive_backup.py --source /data/myproject --dest-folder-id 1AbCdEf... --name myproject_v2

  # อัปโหลดหลายไฟล์พร้อมกัน
  python gdrive_backup.py --source /etc/nginx.conf /etc/hosts --name etc_configs

  # เก็บสำเนา .tar.gz ไว้บนเครื่องด้วย
  python gdrive_backup.py --source /data/myproject --keep-local

  # ลบ backup เก่ากว่า 30 วันใน Drive อัตโนมัติ
  python gdrive_backup.py --source /data/myproject --retention 30

  # ดูรายการ backup ใน Drive
  python gdrive_backup.py --list-backups
""",
    )
    p.add_argument("--source", "-s", nargs="+", metavar="PATH",
                   help="ไฟล์หรือโฟลเดอร์ที่ต้องการ backup (รับได้หลายรายการ)")
    p.add_argument("--dest-folder-id", "-d", default=DEFAULT_FOLDER_ID, metavar="FOLDER_ID",
                   help=f"Google Drive folder ID ปลายทาง (default จาก .env: {DEFAULT_FOLDER_ID})")
    p.add_argument("--name", "-n", default=None, metavar="NAME",
                   help="ชื่อไฟล์ backup (ไม่ต้องใส่ .tar.gz) — default: ชื่อ source + timestamp")
    p.add_argument("--keep-local", action="store_true",
                   help="เก็บไฟล์ .tar.gz ไว้บนเครื่องหลังอัปโหลด (default: ลบทันที)")
    p.add_argument("--retention", type=int, default=DEFAULT_RETENTION, metavar="DAYS",
                   help="ลบ backup เก่ากว่า N วันใน Drive อัตโนมัติ (0 = ไม่ลบ)")
    p.add_argument("--list-backups", action="store_true",
                   help="แสดงรายการไฟล์ใน folder ปลายทาง แล้วออก")
    p.add_argument("--use-temp-file", action="store_true",
                   help="บีบอัดลง temp file แทน in-memory (ใช้เมื่อ source ขนาดใหญ่มากจน RAM ไม่พอ)")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="แสดง log ละเอียด (debug)")
    return p.parse_args()


def main():
    args = parse_args()
    log  = setup_logger(args.verbose)

    try:
        service = get_drive_service()
    except FileNotFoundError as e:
        log.error(str(e))
        sys.exit(1)

    # ── list mode ──────────────────────────────────────────────────────────────
    if args.list_backups:
        list_backups(service, args.dest_folder_id, log)
        return

    # ── validate sources ───────────────────────────────────────────────────────
    if not args.source:
        log.error("ต้องระบุ --source อย่างน้อย 1 รายการ (หรือใช้ --list-backups)")
        sys.exit(1)

    sources = [Path(s) for s in args.source]
    missing = [s for s in sources if not s.exists()]
    if missing:
        for m in missing:
            log.error(f"ไม่พบ path: {m}")
        sys.exit(1)

    # ── ตั้งชื่อไฟล์ ───────────────────────────────────────────────────────────
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    basename = args.name or (sources[0].name if len(sources) == 1 else "backup")
    basename = re.sub(r"[^\w\-.]", "_", basename)   # sanitize
    filename = f"{basename}_{ts}.tar.gz"

    temp_path: Path | None = None
    try:
        if args.keep_local or args.use_temp_file:
            temp_path   = compress_to_temp(sources, log)
            file_stream: io.IOBase = open(temp_path, "rb")
        else:
            file_stream = compress_to_stream(sources, log)

        result = upload_to_drive(service, file_stream, filename, args.dest_folder_id, log)
        file_stream.close()

        delete_old_backups(service, args.dest_folder_id, args.retention, basename, log)

    except HttpError as e:
        log.error(f"Google Drive API error: {e}")
        sys.exit(1)
    finally:
        if temp_path and temp_path.exists():
            if args.keep_local:
                log.info(f"💾 เก็บไฟล์ไว้ที่: {temp_path}")
            else:
                temp_path.unlink()
                log.info(f"🗑️  ลบ temp file แล้ว")


if __name__ == "__main__":
    main()
# gdrive_backup — บีบอัด & อัปโหลด Google Drive

Python script สำหรับบีบอัดไฟล์/โฟลเดอร์เป็น `.tar.gz` แล้วอัปโหลดขึ้น Google Drive ส่วนตัวผ่าน Google Drive API v3 โดยตรง (ไม่ต้องติดตั้ง rclone)

## คุณสมบัติ

- **บีบอัด in-memory** — ไม่เขียนลง disk ระหว่างบีบอัด ประหยัด I/O
- **Resumable upload** — รองรับการอัปโหลดไฟล์ขนาดใหญ่อย่างเสถียร
- **OAuth 2.0 + token cache** — Login ครั้งแรกผ่าน browser, ครั้งต่อไปใช้ token ที่แคชไว้
- **หลาย source ในคราวเดียว** — ระบุไฟล์/โฟลเดอร์หลายรายการพร้อมกัน
- **Retention policy** — ลบ backup เก่ากว่า N วันใน Drive อัตโนมัติ
- **ดูรายการ backup** — แสดงไฟล์ใน folder ปลายทางพร้อมขนาดและวันที่
- **Scope ขั้นต่ำ** — ใช้ `drive.file` scope (เข้าถึงเฉพาะไฟล์ที่ app สร้างขึ้น)

## ความต้องการ

- Python >= 3.13
- Google Cloud project พร้อม Drive API v3 เปิดใช้งาน
- OAuth 2.0 credentials (`credentials.json`)

## การติดตั้ง

```bash
# ติดตั้ง dependencies ด้วย uv (แนะนำ)
uv sync

# หรือด้วย pip
pip install google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2 python-dotenv
```

## การตั้งค่า

### 1. สร้าง Google Cloud credentials

1. ไปที่ [Google Cloud Console](https://console.cloud.google.com/)
2. สร้าง project ใหม่ หรือเลือก project ที่มีอยู่
3. เปิดใช้งาน **Google Drive API v3**
4. ไปที่ **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client IDs**
5. เลือก Application type: **Desktop app**
6. ดาวน์โหลด `credentials.json` แล้ววางไว้ในโฟลเดอร์เดียวกับ script

### 2. สร้างไฟล์ .env

```bash
cp env.example .env
```

แก้ค่าใน `.env` ตามต้องการ:

```env
# Path ไปยัง credentials.json
GDRIVE_CREDENTIALS_FILE=./credentials.json

# Path ที่จะเก็บ OAuth token (สร้างอัตโนมัติ)
GDRIVE_TOKEN_FILE=./token.json

# Google Drive folder ID ปลายทาง
# เปิด Drive → เข้าโฟลเดอร์ → ดู URL → .../folders/<ID>
GDRIVE_FOLDER_ID=root

# Path ของ log file
BACKUP_LOG_FILE=./backup.log

# จำนวนวันที่เก็บ backup (0 = ไม่ลบอัตโนมัติ)
BACKUP_RETENTION_DAYS=0
```

### 3. Login ครั้งแรก

รัน script ครั้งแรก — จะเปิด browser ให้ล็อกอิน Google เพื่อขอสิทธิ์ OAuth และบันทึก `token.json` อัตโนมัติ

## การใช้งาน

```bash
# อัปโหลดโฟลเดอร์เดียว
python main.py --source /path/to/folder

# ระบุ folder ID ปลายทางและตั้งชื่อเอง
python main.py --source /path/to/folder --dest-folder-id 1AbCdEf... --name myproject_v2

# อัปโหลดหลายไฟล์พร้อมกัน
python main.py --source /etc/nginx.conf /etc/hosts --name etc_configs

# เก็บสำเนา .tar.gz ไว้บนเครื่องด้วย
python main.py --source /path/to/folder --keep-local

# ลบ backup เก่ากว่า 30 วันใน Drive อัตโนมัติ
python main.py --source /path/to/folder --retention 30

# ดูรายการ backup ใน Drive folder
python main.py --list-backups

# สำหรับไฟล์ขนาดใหญ่มาก (RAM ไม่พอ) — บีบอัดลง temp file แทน
python main.py --source /path/to/large-folder --use-temp-file

# แสดง log ละเอียด
python main.py --source /path/to/folder --verbose
```

### ตัวเลือกทั้งหมด

| ตัวเลือก | ย่อ | คำอธิบาย |
|---|---|---|
| `--source PATH [PATH ...]` | `-s` | ไฟล์หรือโฟลเดอร์ที่ต้องการ backup |
| `--dest-folder-id FOLDER_ID` | `-d` | Google Drive folder ID ปลายทาง |
| `--name NAME` | `-n` | ชื่อไฟล์ backup (ไม่ต้องใส่ .tar.gz) |
| `--keep-local` | | เก็บไฟล์ .tar.gz ไว้บนเครื่องหลังอัปโหลด |
| `--retention DAYS` | | ลบ backup เก่ากว่า N วัน (0 = ไม่ลบ) |
| `--list-backups` | | แสดงรายการไฟล์ใน folder ปลายทาง |
| `--use-temp-file` | | บีบอัดลง temp file แทน in-memory |
| `--verbose` | `-v` | แสดง log ละเอียด |

## รูปแบบชื่อไฟล์

ไฟล์ที่อัปโหลดจะตั้งชื่อโดยอัตโนมัติในรูปแบบ:

```
<ชื่อ source หรือ --name>_<YYYYMMDD_HHMMSS>.tar.gz
```

ตัวอย่าง: `myproject_20260522_143000.tar.gz`

## โครงสร้างโปรเจค

```
.
├── main.py          # script หลัก
├── pyproject.toml   # dependencies (uv/pip)
├── env.example      # ตัวอย่างไฟล์ .env
├── .gitignore       # ไม่ track .env, credentials.json, token.json
└── backup.log       # log file (สร้างอัตโนมัติ, ไม่ track ใน git)
```

## ความปลอดภัย

> **สำคัญ:** อย่า commit ไฟล์ต่อไปนี้ขึ้น git เด็ดขาด
> - `.env` — มี path ที่ sensitive
> - `credentials.json` — OAuth client secret
> - `token.json` — OAuth access/refresh token

ไฟล์เหล่านี้ถูก exclude ใน `.gitignore` แล้ว

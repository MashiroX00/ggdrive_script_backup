#!/bin/bash
WORKDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/"

# ── Setup ──────────────────────────────────────────────────────────────────────
echo "Activate Venv at $WORKDIR"
source "${WORKDIR}.venv/bin/activate"

echo "Running..."
uv sync
echo "Sync successfully"

# ── Helpers ────────────────────────────────────────────────────────────────────
run_backup() {
    local CMD=(uv run "${WORKDIR}main.py")

    # --source (required)
    CMD+=(--source "$source")

    # optional flags
    [[ -n "$backup_name" ]]              && CMD+=(--name "$backup_name")
    [[ -n "$dest_folder_id" ]]           && CMD+=(--dest-folder-id "$dest_folder_id")
    [[ "${retention:-0}" -gt 0 ]]        && CMD+=(--retention "$retention")
    [[ "${keep_local,,}" == "y" ]]       && CMD+=(--keep-local)
    [[ "${use_temp_file,,}" == "y" ]]    && CMD+=(--use-temp-file)
    [[ "${verbose,,}" == "y" ]]          && CMD+=(-v)

    echo ""
    echo "=========================================="
    echo " Starting backup: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=========================================="
    set -x
    "${CMD[@]}"
    EXIT_CODE=$?
    set +x

    echo ""
    if [[ $EXIT_CODE -eq 0 ]]; then
        echo "[OK] Backup completed successfully."
        if [[ "${show_list,,}" == "y" ]]; then
            echo ""
            echo "--- Backup list in Drive ---"
            uv run "${WORKDIR}main.py" --list-backups
        fi
    else
        echo "[FAILED] Backup exited with code $EXIT_CODE. Check backup.log for details."
        exit $EXIT_CODE
    fi
}

validate_source() {
    if [[ -z "$source" ]]; then
        echo "[ERROR] Path cannot be empty."
        exit 1
    fi
    if [[ ! -e "$source" ]]; then
        echo "[ERROR] Path not found: $source"
        exit 1
    fi
}

# ── Main menu ──────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "  gdrive_backup — Compress & Upload"
echo "=========================================="
echo "  1) Quick  — path + name only (verbose)"
echo "  2) Full   — all options"
echo "  3) List backups in Drive"
echo "  q) Quit"
echo "=========================================="
read -p "Select [1/2/3/q]: " mode
echo ""

case "${mode}" in

    # ── Quick profile ──────────────────────────────────────────────────────────
    1)
        read -p "Source path: " source
        validate_source

        read -p "Backup name (blank = auto): " backup_name

        # fixed options for quick profile
        dest_folder_id=""
        retention=0
        keep_local="n"
        use_temp_file="n"
        verbose="y"
        show_list="n"

        run_backup
        ;;

    # ── Full profile ───────────────────────────────────────────────────────────
    2)
        read -p "Source path: " source
        validate_source

        read -p "Backup name (blank = auto from path): " backup_name

        read -p "Destination folder ID (blank = use .env default): " dest_folder_id

        read -p "Delete backups older than N days [0 = keep all]: " retention
        retention="${retention:-0}"
        if ! [[ "$retention" =~ ^[0-9]+$ ]]; then
            echo "[ERROR] Retention must be a number."
            exit 1
        fi

        read -p "Use temp file instead of in-memory? [y/N]: " use_temp_file
        read -p "Keep local .tar.gz after upload? [y/N]: " keep_local
        read -p "Verbose output? [Y/n]: " verbose_input
        verbose="${verbose_input:-y}"
        read -p "Show Drive backup list after upload? [y/N]: " show_list

        run_backup
        ;;

    # ── List backups ───────────────────────────────────────────────────────────
    3)
        read -p "Folder ID to list (blank = use .env default): " list_folder_id

        LIST_CMD=(uv run "${WORKDIR}main.py" --list-backups)
        [[ -n "$list_folder_id" ]] && LIST_CMD+=(--dest-folder-id "$list_folder_id")

        echo ""
        echo "--- Backup list in Drive ---"
        "${LIST_CMD[@]}"
        ;;

    # ── Quit ───────────────────────────────────────────────────────────────────
    q|Q)
        echo "Bye."
        exit 0
        ;;

    *)
        echo "[ERROR] Invalid option: $mode"
        exit 1
        ;;
esac

#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: upload-drive.sh <result-dir> <job-id>" >&2
  exit 64
fi

RESULT_DIR="$1"
JOB_ID="$2"

if [ ! -d "$RESULT_DIR" ]; then
  echo "Result directory does not exist." >&2
  exit 66
fi
if [ -z "${RCLONE_CONFIG_B64:-}" ]; then
  echo "The Drive upload secret is not configured." >&2
  exit 65
fi
if ! [[ "$JOB_ID" =~ ^[a-z0-9][a-z0-9-]{5,63}$ ]]; then
  echo "Invalid job ID." >&2
  exit 65
fi
if [ -n "${DRIVE_TARGET_FOLDER_ID:-}" ] && ! [[ "$DRIVE_TARGET_FOLDER_ID" =~ ^[A-Za-z0-9_-]{10,}$ ]]; then
  echo "Invalid Drive target folder ID." >&2
  exit 65
fi

RCLONE_CONFIG_FILE="$(mktemp)"
trap 'rm -f "$RCLONE_CONFIG_FILE"' EXIT
printf '%s' "$RCLONE_CONFIG_B64" | base64 --decode > "$RCLONE_CONFIG_FILE"
chmod 600 "$RCLONE_CONFIG_FILE"

if ! rclone listremotes --config "$RCLONE_CONFIG_FILE" | grep -qx 'gdrive:'; then
  echo "The rclone configuration must contain a remote named gdrive." >&2
  exit 65
fi

python3 - "$RCLONE_CONFIG_FILE" <<'PY'
import configparser
import os
import sys

path = sys.argv[1]
parser = configparser.RawConfigParser()
parser.read(path)
if "gdrive" not in parser:
    raise SystemExit("The rclone configuration has no gdrive section.")
parser.remove_option("gdrive", "root_folder_id")
with open(path, "w", encoding="utf-8") as handle:
    parser.write(handle, space_around_delimiters=True)
os.chmod(path, 0o600)
PY

printf 'Upload completed at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$RESULT_DIR/upload-complete.txt"

if [ -n "${DRIVE_TARGET_FOLDER_ID:-}" ]; then
  rclone copy \
    "$RESULT_DIR" \
    "gdrive:" \
    --drive-root-folder-id "$DRIVE_TARGET_FOLDER_ID" \
    --config "$RCLONE_CONFIG_FILE" \
    --transfers 4 \
    --checkers 8 \
    --stats 0 \
    --log-level ERROR
else
  rclone copy \
    "$RESULT_DIR" \
    "gdrive:$JOB_ID" \
    --config "$RCLONE_CONFIG_FILE" \
    --transfers 4 \
    --checkers 8 \
    --stats 0 \
    --log-level ERROR
fi

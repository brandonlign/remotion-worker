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

CONFIG_FILE="$(mktemp)"
trap 'rm -f "$CONFIG_FILE"' EXIT
printf '%s' "$RCLONE_CONFIG_B64" | base64 --decode > "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

if ! rclone listremotes --config "$CONFIG_FILE" | grep -qx 'gdrive:'; then
  echo "The rclone configuration must contain a remote named gdrive." >&2
  exit 65
fi

TEMP_RENDER_ROOT_ID="1N9Fnpu3XEnpsl2DbWFnnW_cS7CMfASqU"
python3 - "$CONFIG_FILE" "$TEMP_RENDER_ROOT_ID" <<'PY'
import configparser
import os
import sys

path, folder_id = sys.argv[1:]
parser = configparser.RawConfigParser()
parser.read(path)
if "gdrive" not in parser:
    raise SystemExit("Missing [gdrive] remote")
parser.set("gdrive", "root_folder_id", folder_id)
with open(path, "w", encoding="utf-8") as handle:
    parser.write(handle, space_around_delimiters=True)
os.chmod(path, 0o600)
PY

printf 'Upload completed at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RESULT_DIR/upload-complete.txt"
rclone copy "$RESULT_DIR" "gdrive:$JOB_ID" \
  --config "$CONFIG_FILE" \
  --transfers 4 \
  --checkers 8 \
  --stats 0 \
  --log-level ERROR

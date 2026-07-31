#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: upload-drive.sh <result-dir> <job-id>" >&2
  exit 64
fi

RESULT_DIR="$1"
JOB_ID="$2"
EXPECTED_JOB_ID="20260731-qr-error-correction-v1"
TARGET_FOLDER_ID="1-_nyc8xIXQ541U5qxv2CTR5w6BCIMt1Y"

if [ ! -d "$RESULT_DIR" ]; then
  echo "Result directory does not exist." >&2
  exit 66
fi

if [ -z "${RCLONE_CONFIG_B64:-}" ]; then
  echo "The Drive upload secret is not configured." >&2
  exit 65
fi

if [ "$JOB_ID" != "$EXPECTED_JOB_ID" ]; then
  echo "This temporary worker branch is pinned to a different job ID." >&2
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

RCLONE_SCOPE="$(awk '
  /^\[gdrive\]$/ { in_remote=1; next }
  /^\[/ { if (in_remote) exit }
  in_remote && /^[[:space:]]*scope[[:space:]]*=/ {
    sub(/^[^=]*=[[:space:]]*/, "", $0)
    sub(/[[:space:]]*$/, "", $0)
    print
    exit
  }
' "$RCLONE_CONFIG_FILE")"

case "$RCLONE_SCOPE" in
  drive.file|https://www.googleapis.com/auth/drive.file|drive|https://www.googleapis.com/auth/drive) ;;
  *)
    echo "The configured Drive scope cannot perform this pinned private upload." >&2
    exit 65
    ;;
esac

python3 - "$RCLONE_CONFIG_FILE" "$TARGET_FOLDER_ID" <<'PY'
import configparser
import os
import sys

path, folder_id = sys.argv[1:]
parser = configparser.RawConfigParser()
parser.read(path)
if "gdrive" not in parser:
    raise SystemExit("The rclone configuration has no gdrive section.")
parser.set("gdrive", "root_folder_id", folder_id)
with open(path, "w", encoding="utf-8") as handle:
    parser.write(handle, space_around_delimiters=True)
os.chmod(path, 0o600)
PY

printf 'Upload completed at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$RESULT_DIR/upload-complete.txt"

rclone copy \
  "$RESULT_DIR" \
  "gdrive:" \
  --config "$RCLONE_CONFIG_FILE" \
  --transfers 4 \
  --checkers 8 \
  --stats 0 \
  --log-level ERROR

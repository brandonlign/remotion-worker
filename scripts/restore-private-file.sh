#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: restore-private-file.sh <source-folder> <remote-name> <destination>" >&2
  exit 64
fi

SOURCE_FOLDER="$1"
REMOTE_NAME="$2"
DESTINATION="$3"

if [ -z "${RCLONE_CONFIG_B64:-}" ]; then
  echo "The Drive restore secret is not configured." >&2
  exit 65
fi

for value in "$SOURCE_FOLDER" "$REMOTE_NAME" "$DESTINATION"; do
  if [[ "$value" == /* ]] || [[ "$value" == *".."* ]] || [[ "$value" == *\\* ]]; then
    echo "Private restore paths must be safe relative paths." >&2
    exit 65
  fi
done

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

mkdir -p "$(dirname "$DESTINATION")"
if ! rclone copyto "gdrive:$SOURCE_FOLDER/$REMOTE_NAME" "$DESTINATION" \
  --config "$CONFIG_FILE" --log-level ERROR; then
  echo "Private source restore failed." >&2
  exit 74
fi

echo "Private source package restored."

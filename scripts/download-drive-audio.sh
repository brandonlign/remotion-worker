#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: download-drive-audio.sh <private-source-dir> <job-id>" >&2
  exit 64
fi

SOURCE_DIR="$1"
JOB_ID="$2"

if [ ! -d "$SOURCE_DIR" ]; then
  echo "Private source directory does not exist." >&2
  exit 66
fi

if [ -z "${RCLONE_CONFIG_B64:-}" ]; then
  echo "The Drive credential is not configured." >&2
  exit 65
fi

if ! [[ "$JOB_ID" =~ ^[a-z0-9][a-z0-9-]{5,63}$ ]]; then
  echo "Invalid job ID." >&2
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

RENDER_FOLDER_ID="$(
  rclone lsjson gdrive: \
    --config "$RCLONE_CONFIG_FILE" \
    --dirs-only \
    --max-depth 1 \
    --log-level ERROR | \
    python3 -c '
import json
import sys
items = json.load(sys.stdin)
matches = [item for item in items if item.get("Name") == "Telic-Renders" and item.get("IsDir")]
if len(matches) != 1 or not matches[0].get("ID"):
    raise SystemExit("Expected exactly one Telic-Renders folder.")
print(matches[0]["ID"])
'
)"

python3 - "$RCLONE_CONFIG_FILE" "$RENDER_FOLDER_ID" <<'PY'
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

mkdir -p "$SOURCE_DIR/public/automation" "$SOURCE_DIR/automation/current"

rclone copyto "gdrive:$JOB_ID/voiceover.mp3" \
  "$SOURCE_DIR/public/automation/voiceover.mp3" \
  --config "$RCLONE_CONFIG_FILE" --stats 0 --log-level ERROR
rclone copyto "gdrive:$JOB_ID/alignment.json" \
  "$SOURCE_DIR/automation/current/alignment.json" \
  --config "$RCLONE_CONFIG_FILE" --stats 0 --log-level ERROR
rclone copyto "gdrive:$JOB_ID/audio-runtime.json" \
  "$SOURCE_DIR/automation/current/audio-runtime.json" \
  --config "$RCLONE_CONFIG_FILE" --stats 0 --log-level ERROR

for required in \
  "$SOURCE_DIR/public/automation/voiceover.mp3" \
  "$SOURCE_DIR/automation/current/alignment.json" \
  "$SOURCE_DIR/automation/current/audio-runtime.json"; do
  if [ ! -s "$required" ]; then
    echo "The prepared private voice package is incomplete." >&2
    exit 65
  fi
done

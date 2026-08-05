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

RCLONE_CONFIG_FILE="$(mktemp)"
trap 'rm -f "$RCLONE_CONFIG_FILE"' EXIT

printf '%s' "$RCLONE_CONFIG_B64" | base64 --decode > "$RCLONE_CONFIG_FILE"
chmod 600 "$RCLONE_CONFIG_FILE"

if ! rclone listremotes --config "$RCLONE_CONFIG_FILE" | grep -qx 'gdrive:'; then
  echo "The rclone configuration must contain a remote named gdrive." >&2
  exit 65
fi

if ! RCLONE_SCOPE="$(python3 - "$RCLONE_CONFIG_FILE" <<'PY'
import configparser
import re
import sys

parser = configparser.RawConfigParser()
parser.read(sys.argv[1])
raw = parser.get("gdrive", "scope", fallback="").strip().strip("\"'")
tokens = {token for token in re.split(r"[\s,]+", raw.replace("\\,", ",")) if token}
write_scopes = {
    "drive.file",
    "https://www.googleapis.com/auth/drive.file",
    "drive",
    "https://www.googleapis.com/auth/drive",
}
if not tokens.intersection(write_scopes):
    print(f"The gdrive remote has no supported write scope: {raw!r}", file=sys.stderr)
    raise SystemExit(65)
print(",".join(sorted(tokens)))
PY
)"; then
  exit 65
fi

resolve_unique_folder_id() {
  local expected_name="$1"
  rclone lsjson gdrive: \
    --config "$RCLONE_CONFIG_FILE" \
    --dirs-only \
    --max-depth 1 \
    --log-level ERROR | \
    python3 -c '
import json
import sys

expected = sys.argv[1]
items = json.load(sys.stdin)
matches = [item for item in items if item.get("Name") == expected and item.get("IsDir")]
if len(matches) != 1:
    print(f"Expected exactly one Drive folder named {expected!r}; found {len(matches)}.", file=sys.stderr)
    raise SystemExit(65)
folder_id = matches[0].get("ID")
if not folder_id:
    print("The resolved Drive folder has no provider ID.", file=sys.stderr)
    raise SystemExit(65)
print(folder_id)
' "$expected_name"
}

set_drive_root() {
  local folder_id="$1"
  python3 - "$RCLONE_CONFIG_FILE" "$folder_id" <<'PY'
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
}

RENDER_FOLDER_ID="$(resolve_unique_folder_id 'Telic-Renders')"
set_drive_root "$RENDER_FOLDER_ID"

DUPLICATE_JOB_FOLDERS="$(
  rclone lsjson gdrive: \
    --config "$RCLONE_CONFIG_FILE" \
    --dirs-only \
    --max-depth 1 \
    --log-level ERROR | \
    python3 -c '
import json
import sys

job_id = sys.argv[1]
items = json.load(sys.stdin)
print(sum(1 for item in items if item.get("Name") == job_id and item.get("IsDir")))
' "$JOB_ID"
)"

if [ "$DUPLICATE_JOB_FOLDERS" -gt 1 ]; then
  echo "Multiple render folders already exist for this job ID; refusing an ambiguous upload." >&2
  exit 65
fi

printf 'Upload completed at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$RESULT_DIR/upload-complete.txt"

rclone copy \
  "$RESULT_DIR" \
  "gdrive:$JOB_ID" \
  --config "$RCLONE_CONFIG_FILE" \
  --transfers 4 \
  --checkers 8 \
  --stats 0 \
  --log-level ERROR

#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: upload-preview-drive.sh <result-dir> <job-id> <revision>" >&2
  exit 64
fi

RESULT_DIR="$1"
JOB_ID="$2"
REVISION="$3"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$WORKER_ROOT/scripts/lib/rclone-common.sh"
source "$WORKER_ROOT/scripts/lib/channel-storage.sh"
trap rclone_cleanup EXIT

[ -d "$RESULT_DIR" ] || rclone_fail "Preview result directory does not exist." 66
validate_job_id
if ! [[ "$REVISION" =~ ^[1-9][0-9]{0,2}$ ]] || [ "$REVISION" -gt 1000 ]; then
  rclone_fail "Preview delivery requires revision 1 through 1000." 64
fi

# Preview packages must never masquerade as canonical delivery.
for forbidden in upload-complete.txt final.mp4 publish.json thumbnail.png; do
  if [ -e "$RESULT_DIR/$forbidden" ]; then
    rclone_fail "Preview package contains forbidden canonical artifact: $forbidden" 65
  fi
done

prepare_rclone_config "The Drive upload secret is not configured."
if ! python3 - "$RCLONE_CONFIG_FILE" <<'PY'
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
PY
then
  exit 65
fi

RENDER_ROOT_PATH="$(render_root_for_job_id "$JOB_ID")"
TARGET_PATH="$RENDER_ROOT_PATH/$JOB_ID/previews/revision-$REVISION"
rclone copy \
  "$RESULT_DIR" \
  "gdrive:$TARGET_PATH" \
  --config "$RCLONE_CONFIG_FILE" \
  --transfers 4 \
  --checkers 8 \
  --stats 0 \
  --log-level ERROR

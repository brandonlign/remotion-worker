#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: upload-drive.sh <result-dir> <job-id>" >&2
  exit 64
fi

RESULT_DIR="$1"
JOB_ID="$2"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$WORKER_ROOT/scripts/lib/rclone-common.sh"
source "$WORKER_ROOT/scripts/lib/channel-storage.sh"
trap rclone_cleanup EXIT

if [ ! -d "$RESULT_DIR" ]; then
  rclone_fail "Result directory does not exist." 66
fi
validate_job_id
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

# Storage routing is derived from the immutable channel prefix in the durable job
# ID. The worker never accepts an arbitrary Drive path from a public render PR.
RENDER_ROOT_PATH="$(render_root_for_job_id "$JOB_ID")"
JOB_TARGET_PATH="$RENDER_ROOT_PATH/$JOB_ID"

DUPLICATE_JOB_FOLDERS="$(
  rclone lsjson "gdrive:$RENDER_ROOT_PATH" \
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
  rclone_fail "Multiple render folders already exist for this job ID; refusing an ambiguous upload."
fi

printf 'Upload completed at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$RESULT_DIR/upload-complete.txt"

rclone copy \
  "$RESULT_DIR" \
  "gdrive:$JOB_TARGET_PATH" \
  --config "$RCLONE_CONFIG_FILE" \
  --transfers 4 \
  --checkers 8 \
  --stats 0 \
  --log-level ERROR

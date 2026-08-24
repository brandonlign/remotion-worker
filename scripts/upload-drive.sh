#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
  echo "Usage: upload-drive.sh <result-dir> <job-id> [success|diagnostics] [revision]" >&2
  exit 64
fi

RESULT_DIR="$1"
JOB_ID="$2"
DELIVERY_KIND="${3:-success}"
REVISION="${4:-}"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$WORKER_ROOT/scripts/lib/rclone-common.sh"
source "$WORKER_ROOT/scripts/lib/channel-storage.sh"
trap rclone_cleanup EXIT

if [ ! -d "$RESULT_DIR" ]; then
  rclone_fail "Result directory does not exist." 66
fi
validate_job_id
case "$DELIVERY_KIND" in
  success) ;;
  diagnostics)
    if ! [[ "$REVISION" =~ ^[1-9][0-9]{0,2}$ ]] || [ "$REVISION" -gt 1000 ]; then
      rclone_fail "Diagnostic delivery requires revision 1 through 1000." 64
    fi
    ;;
  *) rclone_fail "Delivery kind must be success or diagnostics." 64 ;;
esac
prepare_rclone_config "The Drive upload secret is not configured."
validate_drive_file_scope

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

if [ "$DELIVERY_KIND" = "success" ]; then
  # Only a successful requested stage may write the canonical completion marker.
  # Failed attempts are isolated under diagnostics/revision-N and can never make
  # the canonical job folder look complete.
  printf 'Upload completed at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "$RESULT_DIR/upload-complete.txt"
  TARGET_PATH="$JOB_TARGET_PATH"
else
  rm -f "$RESULT_DIR/upload-complete.txt"
  TARGET_PATH="$JOB_TARGET_PATH/diagnostics/revision-$REVISION"
fi

rclone copy \
  "$RESULT_DIR" \
  "gdrive:$TARGET_PATH" \
  --config "$RCLONE_CONFIG_FILE" \
  --transfers 4 \
  --checkers 8 \
  --stats 0 \
  --log-level ERROR

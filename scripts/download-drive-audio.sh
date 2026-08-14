#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "Usage: download-drive-audio.sh <private-source-dir> <job-id> [render|render-sequence]" >&2
  exit 64
fi

SOURCE_DIR="$1"
JOB_ID="$2"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUEST_FILE="$WORKER_ROOT/jobs/request.json"
REQUEST_MODE=""
if [ "$#" -eq 3 ]; then
  REQUEST_MODE="$3"
elif [ -s "$REQUEST_FILE" ]; then
  REQUEST_MODE="$(node - "$REQUEST_FILE" "$JOB_ID" <<'NODE'
const fs = require("node:fs");
const [requestFile, expectedJobId] = process.argv.slice(2);
try {
  const request = JSON.parse(fs.readFileSync(requestFile, "utf8"));
  if (request.jobId === expectedJobId && ["render", "render-sequence"].includes(request.mode)) {
    process.stdout.write(request.mode);
  }
} catch {}
NODE
)"
fi
RESTORE_MODE="${REQUEST_MODE:-render}"

source "$WORKER_ROOT/scripts/lib/rclone-common.sh"
source "$WORKER_ROOT/scripts/lib/channel-storage.sh"
DRIVE_RUNTIME_FILE="$(mktemp)"
MUSIC_ROWS_FILE="$(mktemp)"
trap 'rm -f "${DRIVE_RUNTIME_FILE}" "${MUSIC_ROWS_FILE}"; rclone_cleanup' EXIT

case "$RESTORE_MODE" in
  render|render-sequence) ;;
  *) rclone_fail "Unsupported audio restore mode: $RESTORE_MODE" 64 ;;
esac

if [ ! -d "$SOURCE_DIR" ]; then
  rclone_fail "Private source directory does not exist." 66
fi
validate_job_id
prepare_rclone_config "The Drive credential is not configured."

mkdir -p "$SOURCE_DIR/public/automation" "$SOURCE_DIR/automation/current"

# The durable voice package follows the same channel-owned render root as the
# final output. Never accept an arbitrary Drive locator from a public request.
VOICE_ROOT_PATH="$(render_root_for_job_id "$JOB_ID")/$JOB_ID"

copy_voice_artifact() {
  local name="$1"
  local destination="$2"
  rclone copyto "gdrive:$VOICE_ROOT_PATH/$name" "$destination" \
    --config "$RCLONE_CONFIG_FILE" \
    --stats 0 \
    --log-level ERROR
}

AUDIO_FILE="$SOURCE_DIR/public/automation/voiceover.mp3"
ALIGNMENT_FILE="$SOURCE_DIR/automation/current/alignment.json"
SOURCE_RUNTIME_FILE="$SOURCE_DIR/automation/current/audio-runtime.json"

copy_voice_artifact voiceover.mp3 "$AUDIO_FILE"

if [ "$RESTORE_MODE" = "render-sequence" ]; then
  if [ ! -s "$AUDIO_FILE" ]; then
    rclone_fail "The prepared private voiceover is incomplete."
  fi
  node "$WORKER_ROOT/scripts/verify-restored-audio.mjs" \
    --committed-long \
    "$SOURCE_RUNTIME_FILE" \
    "$AUDIO_FILE" \
    "$JOB_ID" \
    >/dev/null
else
  copy_voice_artifact alignment.json "$ALIGNMENT_FILE"
  copy_voice_artifact audio-runtime.json "$DRIVE_RUNTIME_FILE"

  for required in "$AUDIO_FILE" "$ALIGNMENT_FILE" "$DRIVE_RUNTIME_FILE"; do
    if [ ! -s "$required" ]; then
      rclone_fail "The prepared private voice package is incomplete."
    fi
  done

  RESTORE_FORMAT="$(node "$WORKER_ROOT/scripts/verify-restored-audio.mjs" \
    "$SOURCE_RUNTIME_FILE" \
    "$DRIVE_RUNTIME_FILE" \
    "$AUDIO_FILE")"

  case "$RESTORE_FORMAT" in
    long)
      ;;
    short)
      cp "$DRIVE_RUNTIME_FILE" "$SOURCE_RUNTIME_FILE"
      ;;
    *)
      rclone_fail "Audio restore verifier returned an unsupported format: $RESTORE_FORMAT"
      ;;
  esac
fi

# Productions may request approved channel music through private audio-design.json.
# The source validates the exact allowlist. This worker transports only those
# requested Drive files and never commits or logs proprietary media publicly.
MUSIC_REQUEST_FILE="$SOURCE_DIR/automation/current/audio-design.json"
if ! node "$WORKER_ROOT/scripts/read-private-music-request.mjs" "$MUSIC_REQUEST_FILE" > "$MUSIC_ROWS_FILE"; then
  rclone_fail "The private music restore request could not be validated."
fi
mapfile -t MUSIC_ROWS < "$MUSIC_ROWS_FILE"
RESTORED_MUSIC_COUNT=0
for row in "${MUSIC_ROWS[@]}"; do
  IFS=$'\t' read -r drive_folder_id drive_file_id file_name asset_path <<<"$row"
  if [ -z "$drive_folder_id" ] || [ -z "$drive_file_id" ] || [ -z "$file_name" ] || [ -z "$asset_path" ]; then
    rclone_fail "The private music restore request is incomplete."
  fi

  set_drive_root "$drive_folder_id"
  actual_id="$(rclone lsjson "gdrive:$file_name" \
    --config "$RCLONE_CONFIG_FILE" \
    --stat \
    --files-only \
    --log-level ERROR | python3 -c '
import json, sys
item = json.load(sys.stdin)
if not isinstance(item, dict) or not item.get("ID") or item.get("IsDir"):
    raise SystemExit(65)
print(item["ID"])
')"
  if [ "$actual_id" != "$drive_file_id" ]; then
    rclone_fail "The selected private channel music file failed provider identity verification."
  fi

  destination="$SOURCE_DIR/$asset_path"
  mkdir -p "$(dirname "$destination")"
  rclone copyto "gdrive:$file_name" "$destination" \
    --config "$RCLONE_CONFIG_FILE" \
    --stats 0 \
    --log-level ERROR
  if [ ! -s "$destination" ]; then
    rclone_fail "A selected private channel music file was not restored."
  fi
  RESTORED_MUSIC_COUNT=$((RESTORED_MUSIC_COUNT + 1))
done

if [ "$RESTORED_MUSIC_COUNT" -gt 0 ]; then
  echo "Restored $RESTORED_MUSIC_COUNT private channel music asset(s)."
fi

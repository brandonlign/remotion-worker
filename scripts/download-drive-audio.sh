#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: download-drive-audio.sh <private-source-dir> <job-id>" >&2
  exit 64
fi

SOURCE_DIR="$1"
JOB_ID="$2"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$WORKER_ROOT/scripts/lib/rclone-common.sh"
DRIVE_RUNTIME_FILE="$(mktemp)"
trap 'rm -f "${DRIVE_RUNTIME_FILE}"; rclone_cleanup' EXIT

if [ ! -d "$SOURCE_DIR" ]; then
  rclone_fail "Private source directory does not exist." 66
fi
validate_job_id
prepare_rclone_config "The Drive credential is not configured."
use_telic_renders_root

mkdir -p "$SOURCE_DIR/public/automation" "$SOURCE_DIR/automation/current"

copy_voice_artifact() {
  local name="$1"
  local destination="$2"
  rclone copyto "gdrive:$JOB_ID/$name" "$destination" \
    --config "$RCLONE_CONFIG_FILE" \
    --stats 0 \
    --log-level ERROR
}

AUDIO_FILE="$SOURCE_DIR/public/automation/voiceover.mp3"
ALIGNMENT_FILE="$SOURCE_DIR/automation/current/alignment.json"
SOURCE_RUNTIME_FILE="$SOURCE_DIR/automation/current/audio-runtime.json"

copy_voice_artifact voiceover.mp3 "$AUDIO_FILE"
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
    # The committed private-source runtime remains authoritative. The verifier
    # already proved the Drive copy is semantically identical and the MP3 hash
    # matches it, so do not overwrite the frozen source manifest.
    ;;
  short)
    # Preserve the legacy Short behavior: timing is restored from the private
    # Drive package because Shorts do not use the committed long-form freeze.
    cp "$DRIVE_RUNTIME_FILE" "$SOURCE_RUNTIME_FILE"
    ;;
  *)
    rclone_fail "Audio restore verifier returned an unsupported format: $RESTORE_FORMAT"
    ;;
esac

# Quality-v2 productions may request one or more approved Telic music tracks in
# their private audio-design.json. The private source validates the exact
# library allowlist. This worker only transports the requested Drive files and
# never commits or logs the proprietary assets publicly.
MUSIC_REQUEST_FILE="$SOURCE_DIR/automation/current/audio-design.json"
mapfile -t MUSIC_ROWS < <(node "$WORKER_ROOT/scripts/read-private-music-request.mjs" "$MUSIC_REQUEST_FILE")
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
    rclone_fail "The selected private Telic music file failed provider identity verification."
  fi

  destination="$SOURCE_DIR/$asset_path"
  mkdir -p "$(dirname "$destination")"
  rclone copyto "gdrive:$file_name" "$destination" \
    --config "$RCLONE_CONFIG_FILE" \
    --stats 0 \
    --log-level ERROR
  if [ ! -s "$destination" ]; then
    rclone_fail "A selected private Telic music file was not restored."
  fi
  RESTORED_MUSIC_COUNT=$((RESTORED_MUSIC_COUNT + 1))
done

if [ "$RESTORED_MUSIC_COUNT" -gt 0 ]; then
  echo "Restored $RESTORED_MUSIC_COUNT private Telic music asset(s)."
fi

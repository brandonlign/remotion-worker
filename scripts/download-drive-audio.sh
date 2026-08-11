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

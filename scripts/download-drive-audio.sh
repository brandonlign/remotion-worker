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
trap rclone_cleanup EXIT

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

copy_voice_artifact voiceover.mp3 "$SOURCE_DIR/public/automation/voiceover.mp3"
copy_voice_artifact alignment.json "$SOURCE_DIR/automation/current/alignment.json"
copy_voice_artifact audio-runtime.json "$SOURCE_DIR/automation/current/audio-runtime.json"

for required in \
  "$SOURCE_DIR/public/automation/voiceover.mp3" \
  "$SOURCE_DIR/automation/current/alignment.json" \
  "$SOURCE_DIR/automation/current/audio-runtime.json"; do
  if [ ! -s "$required" ]; then
    rclone_fail "The prepared private voice package is incomplete."
  fi
done

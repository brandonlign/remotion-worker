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

mkdir -p "$SOURCE_DIR/public/automation" "$SOURCE_DIR/automation/current" "$SOURCE_DIR/public/assets/current"

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

ASSET_MANIFEST="$SOURCE_DIR/automation/current/assets.json"
if [ -f "$ASSET_MANIFEST" ]; then
  while IFS=$'\t' read -r job_file output_path; do
    [ -n "$job_file" ] || continue
    if [[ "$job_file" == */* ]] || [[ "$job_file" == *".."* ]]; then
      rclone_fail "Drive asset jobFileName is not a safe file name."
    fi
    if [[ "$output_path" != public/assets/current/* ]] || [[ "$output_path" == *".."* ]]; then
      rclone_fail "Drive asset outputPath must stay under public/assets/current/."
    fi
    mkdir -p "$(dirname "$SOURCE_DIR/$output_path")"
    copy_voice_artifact "$job_file" "$SOURCE_DIR/$output_path"
  done < <(python3 - "$ASSET_MANIFEST" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
for asset in manifest.get("driveAssets", []):
    job_file = str(asset.get("jobFileName", "")).strip()
    output_path = str(asset.get("outputPath", "")).strip()
    if not job_file or not output_path:
        raise SystemExit("driveAssets entries require jobFileName and outputPath")
    print(f"{job_file}\t{output_path}")
PY
  )
fi

for required in \
  "$SOURCE_DIR/public/automation/voiceover.mp3" \
  "$SOURCE_DIR/automation/current/alignment.json" \
  "$SOURCE_DIR/automation/current/audio-runtime.json"; do
  if [ ! -s "$required" ]; then
    rclone_fail "The prepared private voice package is incomplete."
  fi
done

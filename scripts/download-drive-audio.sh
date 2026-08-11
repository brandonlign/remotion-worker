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

copy_job_artifact() {
  local name="$1"
  local destination="$2"
  rclone copyto "gdrive:$JOB_ID/$name" "$destination" \
    --config "$RCLONE_CONFIG_FILE" \
    --stats 0 \
    --log-level ERROR
}

copy_job_artifact voiceover.mp3 "$SOURCE_DIR/public/automation/voiceover.mp3"
copy_job_artifact alignment.json "$SOURCE_DIR/automation/current/alignment.json"
copy_job_artifact audio-runtime.json "$SOURCE_DIR/automation/current/audio-runtime.json"

music_asset_path="$(node --input-type=module - "$SOURCE_DIR/automation/current/audio-design.json" <<'NODE'
import fs from "node:fs";
import path from "node:path";

const designPath = process.argv[2];
const design = JSON.parse(fs.readFileSync(designPath, "utf8"));
const value = design?.music?.assetPath;
if (
  typeof value !== "string" ||
  !value.startsWith("public/assets/current/") ||
  path.isAbsolute(value) ||
  value.split(/[\\/]/).includes("..")
) {
  throw new Error("Private music asset path is invalid.");
}
process.stdout.write(value);
NODE
)"
mkdir -p "$(dirname "$SOURCE_DIR/$music_asset_path")"
copy_job_artifact music-bed.mp3 "$SOURCE_DIR/$music_asset_path"

for required in \
  "$SOURCE_DIR/public/automation/voiceover.mp3" \
  "$SOURCE_DIR/automation/current/alignment.json" \
  "$SOURCE_DIR/automation/current/audio-runtime.json" \
  "$SOURCE_DIR/$music_asset_path"; do
  if [ ! -s "$required" ]; then
    rclone_fail "The prepared private audio package is incomplete."
  fi
done

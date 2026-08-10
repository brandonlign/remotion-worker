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

mkdir -p "$SOURCE_DIR/public/automation" "$SOURCE_DIR/automation/current"

restore_declared_drive_assets() {
  local manifest="$SOURCE_DIR/automation/current/assets.json"
  if [ ! -f "$manifest" ]; then
    return 0
  fi

  local specs
  specs="$(python3 - "$manifest" <<'PY'
import json
import re
import sys
from pathlib import PurePosixPath
from urllib.parse import urlparse

manifest_path = sys.argv[1]
with open(manifest_path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)
assets = payload.get("driveAssets", [])
if not isinstance(assets, list) or len(assets) > 20:
    raise SystemExit("assets.json driveAssets must be a list with at most 20 entries.")

seen = set()
for asset in assets:
    if not isinstance(asset, dict):
        raise SystemExit("Each driveAsset must be an object.")
    asset_id = asset.get("id")
    source = asset.get("source")
    output = asset.get("outputPath")
    if not isinstance(asset_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", asset_id):
        raise SystemExit("Each driveAsset needs a stable lowercase id.")
    if asset_id in seen:
        raise SystemExit(f"Duplicate driveAsset id: {asset_id}")
    seen.add(asset_id)
    if not isinstance(source, str):
        raise SystemExit(f"driveAsset {asset_id} needs a Google Drive source URL.")
    match = re.fullmatch(r"https://drive\.google\.com/file/d/([A-Za-z0-9_-]+)/view(?:\?.*)?", source)
    if not match:
        raise SystemExit(f"driveAsset {asset_id} source must be a canonical Google Drive file URL.")
    if not isinstance(output, str) or not output.startswith("public/assets/current/"):
        raise SystemExit(f"driveAsset {asset_id} outputPath must stay under public/assets/current/.")
    posix = PurePosixPath(output)
    if posix.is_absolute() or ".." in posix.parts:
        raise SystemExit(f"driveAsset {asset_id} outputPath is unsafe.")
    print(f"{asset_id}\t{match.group(1)}\t{output}")
PY
)"

  if [ -z "$specs" ]; then
    return 0
  fi

  while IFS=$'\t' read -r asset_id drive_id output_path; do
    [ -n "$asset_id" ] || continue
    local destination="$SOURCE_DIR/$output_path"
    mkdir -p "$(dirname "$destination")"
    rclone backend copyid gdrive: "$drive_id" "$destination" \
      --config "$RCLONE_CONFIG_FILE" \
      --log-level ERROR \
      >/dev/null
    if [ ! -s "$destination" ]; then
      rclone_fail "A declared private Drive media asset could not be restored."
    fi
  done <<< "$specs"
}

# Restore declared library media by opaque Drive ID while the authenticated
# remote is still at its account root. Nothing is committed to the worker.
restore_declared_drive_assets

# Voice artifacts live beneath the private Telic-Renders root.
use_telic_renders_root

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

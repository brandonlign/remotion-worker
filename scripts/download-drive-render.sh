#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 4 ]; then
  echo "Usage: download-drive-render.sh <output-dir> <job-id> <reuse-revision> <render-source-sha>" >&2
  exit 64
fi

OUTPUT_DIR="$1"
JOB_ID="$2"
REUSE_REVISION="$3"
RENDER_SOURCE_SHA="$4"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$WORKER_ROOT/scripts/lib/rclone-common.sh"
source "$WORKER_ROOT/scripts/lib/channel-storage.sh"
trap rclone_cleanup EXIT

validate_job_id
if ! [[ "$REUSE_REVISION" =~ ^[1-9][0-9]{0,2}$ ]] || [ "$REUSE_REVISION" -gt 1000 ]; then
  rclone_fail "reuse revision must be 1 through 1000." 64
fi
if ! [[ "$RENDER_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  rclone_fail "render source SHA must be a complete lowercase commit SHA." 64
fi
prepare_rclone_config "The Drive credential is not configured."

RENDER_ROOT_PATH="$(render_root_for_job_id "$JOB_ID")"
SOURCE_PATH="$RENDER_ROOT_PATH/$JOB_ID/diagnostics/revision-$REUSE_REVISION"
mkdir -p "$OUTPUT_DIR"

rclone copy \
  "gdrive:$SOURCE_PATH" \
  "$OUTPUT_DIR" \
  --config "$RCLONE_CONFIG_FILE" \
  --transfers 4 \
  --checkers 8 \
  --stats 0 \
  --log-level ERROR

node - "$OUTPUT_DIR" "$JOB_ID" "$RENDER_SOURCE_SHA" "$REUSE_REVISION" <<'NODE'
const fs = require("node:fs");
const path = require("node:path");
const [outputDir, expectedJobId, expectedSourceSha, revision] = process.argv.slice(2);
const statusPath = path.join(outputDir, "status.json");
if (!fs.existsSync(statusPath)) throw new Error(`revision-${revision} has no render status.`);
const status = JSON.parse(fs.readFileSync(statusPath, "utf8"));
if (status.status !== "complete") throw new Error(`revision-${revision} render status is not complete.`);
if (status.jobId !== expectedJobId) throw new Error(`revision-${revision} belongs to a different job.`);
if (status.sourceSha !== expectedSourceSha) throw new Error(`revision-${revision} was rendered from a different source SHA.`);
if (typeof status.outputName !== "string" || !status.outputName || path.basename(status.outputName) !== status.outputName) {
  throw new Error(`revision-${revision} has an invalid output name.`);
}
const video = path.join(outputDir, `${status.outputName}.mp4`);
if (!fs.existsSync(video) || fs.statSync(video).size <= 0) throw new Error(`revision-${revision} has no reusable rendered MP4.`);
NODE

rm -f \
  "$OUTPUT_DIR/upload-complete.txt" \
  "$OUTPUT_DIR/publish.json" \
  "$OUTPUT_DIR/final.mp4" \
  "$OUTPUT_DIR/quality-gate.json" \
  "$OUTPUT_DIR/private-quality.log" \
  "$OUTPUT_DIR/checksums.txt"

echo "Restored rendered package from diagnostics/revision-$REUSE_REVISION for metadata-only finalization."

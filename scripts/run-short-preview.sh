#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: run-short-preview.sh <preview-request.json> <private-source-dir> <output-dir>" >&2
  exit 64
fi

REQUEST_FILE="$1"
SOURCE_DIR="$2"
OUTPUT_DIR="$3"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$WORKER_ROOT/scripts/lib/stage-common.sh"
trap stage_cleanup EXIT
prepare_private_source_stage "Short QC preview"

ENTRY_POINT="$(source_config_field entryPoint)"
COMPOSITION_ID="$(source_config_field compositionId)"
THUMBNAIL_COMPOSITION_ID="$(source_config_field thumbnailCompositionId)"
INSTALL_COMMAND="$(source_config_field installCommand)"
PREPARE_COMMAND="$(source_config_field prepareCommand)"
CHECK_COMMAND="$(source_config_field checkCommand)"
REMOTION_BIN="$SOURCE_DIR/node_modules/.bin/remotion"
PREVIEW_VIDEO="$OUTPUT_DIR/review.mp4"
PREVIEW_CRF=30
PREVIEW_SCALE="0.5"
PREVIEW_REVIEW_FRAME_LIMIT=20

JOB_FORMAT="$(node - "$SOURCE_DIR/automation/current/job.json" <<'NODE'
const fs = require('node:fs');
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(String(job?.format || ''));
NODE
)"
if [ "$JOB_FORMAT" != "short" ]; then
  stage_fail "Short QC preview refuses non-short source (found ${JOB_FORMAT:-unknown})." 65
fi

node "$WORKER_ROOT/scripts/validate-private-render-contract.mjs" \
  "$SOURCE_DIR" render "$COMPOSITION_ID" "$THUMBNAIL_COMPOSITION_ID" "$PREPARE_COMMAND" "$CHECK_COMMAND"

install_private_dependencies "$INSTALL_COMMAND"
cd "$SOURCE_DIR"
bash -o pipefail -c "$PREPARE_COMMAND"
# Preview is a pixel-verification loop, but source safety still matters. Keep the
# focused code checks and the Short contract; skip final-only metadata/handoff work.
npx eslint src
npx tsc --noEmit
npm run custom:contract:test

if [ ! -x "$REMOTION_BIN" ]; then
  stage_fail "The Remotion CLI was not installed by the configured install command." 69
fi

"$REMOTION_BIN" render \
  "$ENTRY_POINT" "$COMPOSITION_ID" "$PREVIEW_VIDEO" \
  --codec=h264 \
  --crf="$PREVIEW_CRF" \
  --scale="$PREVIEW_SCALE" \
  --log=error

# The preview itself is the review authority. Decode it once for a compact
# chronological contact sheet/keyframe set. No final.mp4, thumbnail, publish.json,
# completion marker, or controller handoff is created in preview mode.
TELIC_REUSE_SOURCE_AS_REVIEW=1 \
  bash "$WORKER_ROOT/scripts/create-review-assets.sh" \
    "$PREVIEW_VIDEO" "$OUTPUT_DIR" "$PREVIEW_REVIEW_FRAME_LIMIT"

for artifact in automation/current/alignment.json automation/current/audio-runtime.json automation/current/composition.json; do
  if [ -s "$SOURCE_DIR/$artifact" ]; then cp "$SOURCE_DIR/$artifact" "$OUTPUT_DIR/$(basename "$artifact")"; fi
done

node - "$OUTPUT_DIR/status.json" "$JOB_ID" "$SOURCE_SHA" <<'NODE'
const fs = require("node:fs");
const [outputFile, jobId, sourceSha] = process.argv.slice(2);
fs.writeFileSync(outputFile, `${JSON.stringify({
  status: "short-preview-complete",
  jobId,
  sourceSha,
  canonical: false,
  completedAt: new Date().toISOString(),
}, null, 2)}\n`);
NODE

write_checksums "$OUTPUT_DIR"

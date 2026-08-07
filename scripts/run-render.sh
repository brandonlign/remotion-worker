#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: run-render.sh <request.json> <private-source-dir> <output-dir>" >&2
  exit 64
fi

REQUEST_FILE="$1"
SOURCE_DIR="$2"
OUTPUT_DIR="$3"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$WORKER_ROOT/scripts/lib/stage-common.sh"
trap stage_cleanup EXIT
prepare_private_source_stage "Render"

ENTRY_POINT="$(source_config_field entryPoint)"
COMPOSITION_ID="$(source_config_field compositionId)"
THUMBNAIL_COMPOSITION_ID="$(source_config_field thumbnailCompositionId)"
OUTPUT_NAME="$(source_config_field outputName)"
INSTALL_COMMAND="$(source_config_field installCommand)"
PREPARE_COMMAND="$(source_config_field prepareCommand)"
CHECK_COMMAND="$(source_config_field checkCommand)"
CRF="$(source_config_field crf)"
FINAL_VIDEO="$OUTPUT_DIR/${OUTPUT_NAME}.mp4"
THUMBNAIL_FILE="$OUTPUT_DIR/thumbnail.png"
REMOTION_BIN="$SOURCE_DIR/node_modules/.bin/remotion"

cd "$SOURCE_DIR"
bash -o pipefail -c "$INSTALL_COMMAND"
bash -o pipefail -c "$PREPARE_COMMAND"
bash -o pipefail -c "$CHECK_COMMAND"

if [ ! -x "$REMOTION_BIN" ]; then
  stage_fail "The Remotion CLI was not installed by the configured install command." 69
fi

"$REMOTION_BIN" render \
  "$ENTRY_POINT" \
  "$COMPOSITION_ID" \
  "$FINAL_VIDEO" \
  --codec=h264 \
  --crf="$CRF" \
  --log=error

if [ -n "$THUMBNAIL_COMPOSITION_ID" ]; then
  "$REMOTION_BIN" still \
    "$ENTRY_POINT" \
    "$THUMBNAIL_COMPOSITION_ID" \
    "$THUMBNAIL_FILE" \
    --frame=0 \
    --log=error
fi

bash "$WORKER_ROOT/scripts/create-review-assets.sh" "$FINAL_VIDEO" "$OUTPUT_DIR"
node "$WORKER_ROOT/scripts/create-review-moments.mjs" \
  "$FINAL_VIDEO" \
  "$SOURCE_DIR/automation/current/composition.json" \
  "$OUTPUT_DIR/review-moments"

for artifact in \
  automation/current/alignment.json \
  automation/current/audio-runtime.json \
  automation/current/composition.json; do
  if [ -s "$SOURCE_DIR/$artifact" ]; then
    cp "$SOURCE_DIR/$artifact" "$OUTPUT_DIR/$(basename "$artifact")"
  fi
done

node - "$OUTPUT_DIR/status.json" "$JOB_ID" "$SOURCE_SHA" "$OUTPUT_NAME" "$THUMBNAIL_COMPOSITION_ID" <<'NODE'
const fs = require("node:fs");
const [outputFile, jobId, sourceSha, outputName, thumbnailCompositionId] = process.argv.slice(2);
fs.writeFileSync(outputFile, `${JSON.stringify({
  status: "complete",
  jobId,
  sourceSha,
  outputName,
  thumbnailCompositionId: thumbnailCompositionId || null,
  completedAt: new Date().toISOString(),
}, null, 2)}\n`);
NODE

node "$WORKER_ROOT/scripts/create-controller-handoff.mjs" \
  "$OUTPUT_DIR" \
  "$SOURCE_DIR/automation/current/youtube.json" \
  "$JOB_ID" \
  "$SOURCE_SHA"

write_checksums "$OUTPUT_DIR"

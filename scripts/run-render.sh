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
CONFIGURED_PREPARE_COMMAND="$(source_config_field prepareCommand)"
CHECK_COMMAND="$(source_config_field checkCommand)"
CRF="$(source_config_field crf)"
JOB_FORMAT="$(node - "$SOURCE_DIR/automation/current/job.json" <<'NODE'
const fs = require('node:fs');
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(String(job?.format || ''));
NODE
)"

PREPARE_COMMAND="$CONFIGURED_PREPARE_COMMAND"
FINAL_VALIDATION_COMMAND="npx eslint src && npx tsc --noEmit && npm run custom:contract:test"
if [ "$JOB_FORMAT" = "long" ]; then
  PREPARE_COMMAND="npm run long:prepare"
  # The source repository owns one canonical, aggregated long-form preflight.
  # Never duplicate individual schema/lint/audio checks in the worker: that is
  # how the old pipeline discovered one incompatibility per expensive revision.
  FINAL_VALIDATION_COMMAND="npm run long:preflight"
fi

FINAL_VIDEO="$OUTPUT_DIR/${OUTPUT_NAME}.mp4"
THUMBNAIL_FILE="$OUTPUT_DIR/thumbnail.png"
REMOTION_BIN="$SOURCE_DIR/node_modules/.bin/remotion"

REVIEW_FRAME_LIMIT="$(node - "$SOURCE_DIR/automation/current/job.json" "$SOURCE_DIR/automation/config.json" <<'NODE'
const fs = require('node:fs');
const [jobPath, configPath] = process.argv.slice(2);
const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const value = job.format === 'long' ? config?.longForm?.quality?.maximumFrames : config?.quality?.maximumFrames;
const maximumFrames = Number(value);
if (!Number.isInteger(maximumFrames) || maximumFrames < 3) throw new Error(`The ${job.format ?? 'short'} review-frame limit is invalid.`);
process.stdout.write(String(maximumFrames));
NODE
)"

node "$WORKER_ROOT/scripts/validate-private-render-contract.mjs" \
  "$SOURCE_DIR" render "$COMPOSITION_ID" "$THUMBNAIL_COMPOSITION_ID" "$CONFIGURED_PREPARE_COMMAND" "$CHECK_COMMAND"

# Reject malformed publishing metadata before dependency setup/rendering.
node "$WORKER_ROOT/scripts/validate-youtube-metadata.mjs" \
  "$SOURCE_DIR/automation/current/youtube.json" \
  "$JOB_ID"

install_private_dependencies "$INSTALL_COMMAND"
cd "$SOURCE_DIR"
bash -o pipefail -c "$PREPARE_COMMAND"

# Hard render boundary. All deterministic source/schema/audio/packaging/lint
# defects must be reported here before the first Remotion frame is rendered.
bash -o pipefail -c "$FINAL_VALIDATION_COMMAND"

if [ ! -x "$REMOTION_BIN" ]; then
  stage_fail "The Remotion CLI was not installed by the configured install command." 69
fi

"$REMOTION_BIN" render \
  "$ENTRY_POINT" "$COMPOSITION_ID" "$FINAL_VIDEO" \
  --codec=h264 --crf="$CRF" --log=error

if [ -n "$THUMBNAIL_COMPOSITION_ID" ]; then
  "$REMOTION_BIN" still \
    "$ENTRY_POINT" "$THUMBNAIL_COMPOSITION_ID" "$THUMBNAIL_FILE" \
    --frame=0 --log=error
fi

bash "$WORKER_ROOT/scripts/create-review-assets.sh" "$FINAL_VIDEO" "$OUTPUT_DIR" "$REVIEW_FRAME_LIMIT"

for artifact in automation/current/alignment.json automation/current/audio-runtime.json automation/current/composition.json; do
  if [ -s "$SOURCE_DIR/$artifact" ]; then cp "$SOURCE_DIR/$artifact" "$OUTPUT_DIR/$(basename "$artifact")"; fi
done

node - "$OUTPUT_DIR/status.json" "$JOB_ID" "$SOURCE_SHA" "$OUTPUT_NAME" "$THUMBNAIL_COMPOSITION_ID" <<'NODE'
const fs = require("node:fs");
const [outputFile, jobId, sourceSha, outputName, thumbnailCompositionId] = process.argv.slice(2);
fs.writeFileSync(outputFile, `${JSON.stringify({
  status: "complete", jobId, sourceSha, outputName,
  thumbnailCompositionId: thumbnailCompositionId || null,
  completedAt: new Date().toISOString(),
}, null, 2)}\n`);
NODE

node "$WORKER_ROOT/scripts/create-controller-handoff.mjs" \
  "$OUTPUT_DIR" "$SOURCE_DIR/automation/current/youtube.json" "$JOB_ID" "$SOURCE_SHA"

write_checksums "$OUTPUT_DIR"

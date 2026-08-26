#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: run-long-preview.sh <request.json> <private-source-dir> <output-dir>" >&2
  exit 64
fi

REQUEST_FILE="$1"
SOURCE_DIR="$2"
OUTPUT_DIR="$3"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$WORKER_ROOT/scripts/lib/stage-common.sh"
trap stage_cleanup EXIT
prepare_private_source_stage "Long-form complete preview"

ENTRY_POINT="$(source_config_field entryPoint)"
COMPOSITION_ID="$(source_config_field compositionId)"
THUMBNAIL_COMPOSITION_ID="$(source_config_field thumbnailCompositionId)"
INSTALL_COMMAND="$(source_config_field installCommand)"
CONFIGURED_PREPARE_COMMAND="$(source_config_field prepareCommand)"
CHECK_COMMAND="$(source_config_field checkCommand)"
PREPARE_COMMAND="npm run long:prepare"
PREVIEW_CRF=30
PREVIEW_SCALE="0.5"
REMOTION_BIN="$SOURCE_DIR/node_modules/.bin/remotion"
PREVIEW_VIDEO="$OUTPUT_DIR/review.mp4"

JOB_FORMAT="$(node - "$SOURCE_DIR/automation/current/job.json" <<'NODE'
const fs = require('node:fs');
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(String(job?.format || ''));
NODE
)"
if [ "$JOB_FORMAT" != "long" ]; then
  stage_fail "Long-form complete preview refuses non-long source (found ${JOB_FORMAT:-unknown})." 65
fi

REVIEW_FRAME_LIMIT="$(node - "$SOURCE_DIR/automation/current/job.json" "$SOURCE_DIR/automation/config.json" <<'NODE'
const fs = require('node:fs');
const [jobPath, configPath] = process.argv.slice(2);
const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const value = job.format === 'long' ? config?.longForm?.quality?.maximumFrames : config?.quality?.maximumFrames;
const maximumFrames = Number(value);
if (!Number.isInteger(maximumFrames) || maximumFrames < 3) throw new Error(`The ${job.format ?? 'unknown'} review-frame limit is invalid.`);
process.stdout.write(String(maximumFrames));
NODE
)"

node "$WORKER_ROOT/scripts/validate-private-render-contract.mjs" \
  "$SOURCE_DIR" long-preview "$COMPOSITION_ID" "$THUMBNAIL_COMPOSITION_ID" "$CONFIGURED_PREPARE_COMMAND" "$CHECK_COMMAND"
node "$WORKER_ROOT/scripts/validate-youtube-metadata.mjs" \
  "$SOURCE_DIR/automation/current/youtube.json" \
  "$JOB_ID"

install_private_dependencies "$INSTALL_COMMAND"
cd "$SOURCE_DIR"
bash -o pipefail -c "$PREPARE_COMMAND"
npx eslint src
npx tsc --noEmit
npm run long:contract:test

if [ ! -x "$REMOTION_BIN" ]; then
  stage_fail "The Remotion CLI was not installed by the configured install command." 69
fi

"$REMOTION_BIN" render \
  "$ENTRY_POINT" "$COMPOSITION_ID" "$PREVIEW_VIDEO" \
  --codec=h264 \
  --crf="$PREVIEW_CRF" \
  --scale="$PREVIEW_SCALE" \
  --log=error

# This package is intentionally non-canonical: it contains only the complete
# low-cost review video and chronological diagnostics. The full render owns
# final.mp4, thumbnail.png, publish.json, and the controller handoff.
TELIC_REUSE_SOURCE_AS_REVIEW=1 \
  bash "$WORKER_ROOT/scripts/create-review-assets.sh" \
    "$PREVIEW_VIDEO" "$OUTPUT_DIR" "$REVIEW_FRAME_LIMIT"

for artifact in automation/current/alignment.json automation/current/audio-runtime.json automation/current/composition.json; do
  if [ -s "$SOURCE_DIR/$artifact" ]; then cp "$SOURCE_DIR/$artifact" "$OUTPUT_DIR/$(basename "$artifact")"; fi
done

node - "$OUTPUT_DIR/status.json" "$JOB_ID" "$SOURCE_SHA" <<'NODE'
const fs = require('node:fs');
const [outputFile, jobId, sourceSha] = process.argv.slice(2);
fs.writeFileSync(outputFile, `${JSON.stringify({
  status: "long-preview-complete",
  jobId,
  sourceSha,
  canonical: false,
  completedAt: new Date().toISOString(),
}, null, 2)}\n`);
NODE

write_checksums "$OUTPUT_DIR"

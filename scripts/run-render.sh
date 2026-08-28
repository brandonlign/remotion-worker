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

MASTERING_PROFILE=""
CHANNEL_ID="$(node - "$SOURCE_DIR/automation/current/job.json" <<'NODE'
const fs = require('node:fs');
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(String(job?.channelId || ''));
NODE
)"
if [[ "$CHANNEL_ID" =~ ^[a-z0-9_-]+$ ]]; then
  MASTERING_PROFILE="$SOURCE_DIR/tools/telic-vnext/channels/$CHANNEL_ID/source-profile.json"
fi
HAS_MASTERING_POLICY="false"
if [ -s "$MASTERING_PROFILE" ]; then
  HAS_MASTERING_POLICY="$(node - "$MASTERING_PROFILE" <<'NODE'
const fs = require('node:fs');
const profile = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(profile?.audio?.mastering ? 'true' : 'false');
NODE
  )"
fi

PREPARE_COMMAND="$CONFIGURED_PREPARE_COMMAND"
if [ "$JOB_FORMAT" = "long" ]; then
  PREPARE_COMMAND="npm run long:prepare"
fi

FINAL_VIDEO="$OUTPUT_DIR/${OUTPUT_NAME}.mp4"
THUMBNAIL_FILE="$OUTPUT_DIR/thumbnail.png"
REMOTION_BIN="$SOURCE_DIR/node_modules/.bin/remotion"
FOCUSED_SOURCE_CHECK="npx eslint src && npx tsc --noEmit"
if [ "$JOB_FORMAT" = "long" ]; then
  FINAL_CONTRACT_COMMAND="npm run long:contract:test"
else
  FINAL_CONTRACT_COMMAND="npm run custom:contract:test"
fi

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

# Metadata is cheap and independent of rendered pixels. Reject malformed YouTube
# handoff data before dependency setup, asset preparation, or Remotion rendering so a
# missing chapter/schema field can never waste a full long-form render again.
node "$WORKER_ROOT/scripts/validate-youtube-metadata.mjs" \
  "$SOURCE_DIR/automation/current/youtube.json" \
  "$JOB_ID"

install_private_dependencies "$INSTALL_COMMAND"
cd "$SOURCE_DIR"
bash -o pipefail -c "$PREPARE_COMMAND"
bash -o pipefail -c "$FOCUSED_SOURCE_CHECK"
bash -o pipefail -c "$FINAL_CONTRACT_COMMAND"

if [ ! -x "$REMOTION_BIN" ]; then
  stage_fail "The Remotion CLI was not installed by the configured install command." 69
fi

"$REMOTION_BIN" render \
  "$ENTRY_POINT" "$COMPOSITION_ID" "$FINAL_VIDEO" \
  --codec=h264 --crf="$CRF" --log=error

if [ "$HAS_MASTERING_POLICY" = "true" ]; then
  MASTERED_VIDEO="$OUTPUT_DIR/.${OUTPUT_NAME}.mastered.mp4"
  node "$WORKER_ROOT/scripts/master-final-audio.mjs" \
    "$FINAL_VIDEO" "$MASTERED_VIDEO" "$MASTERING_PROFILE" "$OUTPUT_DIR/audio-mastering.json"
  mv -f "$MASTERED_VIDEO" "$FINAL_VIDEO"
fi

if [ -n "$THUMBNAIL_COMPOSITION_ID" ]; then
  "$REMOTION_BIN" still \
    "$ENTRY_POINT" "$THUMBNAIL_COMPOSITION_ID" "$THUMBNAIL_FILE" \
    --frame=0 --log=error
fi

# The full review video + chronological frames/contact sheet are the default
# review package. Exact semantic still extraction remains available through
# create-review-moments.mjs only when a reviewer has a concrete crop/readability/
# sync question; do not decode every full render again just because moments were
# declared in composition.json.
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

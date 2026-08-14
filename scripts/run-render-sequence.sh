#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: run-render-sequence.sh <request.json> <private-source-dir> <output-dir>" >&2
  exit 64
fi

REQUEST_FILE="$1"
SOURCE_DIR="$2"
OUTPUT_DIR="$3"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$WORKER_ROOT/scripts/lib/stage-common.sh"
trap stage_cleanup EXIT

if ! [[ "${SEQUENCE_INDEX:-}" =~ ^[0-9]+$ ]]; then
  stage_fail "SEQUENCE_INDEX is required for a long-form sequence preview." 64
fi

prepare_private_source_stage "Long-form sequence preview"
OUTPUT_ROOT="$OUTPUT_DIR"

ENTRY_POINT="$(source_config_field entryPoint)"
COMPOSITION_ID="$(source_config_field compositionId)"
INSTALL_COMMAND="$(source_config_field installCommand)"
PREPARE_COMMAND="$(source_config_field prepareCommand)"
CHECK_COMMAND="$(source_config_field checkCommand)"
PREVIEW_CHECK_COMMAND="npx eslint src && npx tsc --noEmit"
PREVIEW_CRF=28
PREVIEW_SCALE="0.6666666667"
REMOTION_BIN="$SOURCE_DIR/node_modules/.bin/remotion"
VISUAL_PLAN="$SOURCE_DIR/automation/current/visual-plan.json"

node "$WORKER_ROOT/scripts/validate-private-render-contract.mjs" \
  "$SOURCE_DIR" \
  render-sequence \
  "$COMPOSITION_ID" \
  "" \
  "$PREPARE_COMMAND" \
  "$CHECK_COMMAND"

cd "$SOURCE_DIR"
bash -o pipefail -c "$INSTALL_COMMAND"
if [ "$PREPARE_COMMAND" = "npm run long:prepare-window" ] \
  && [ "${GITHUB_ACTIONS:-}" = "true" ] \
  && [ "${GITHUB_WORKFLOW:-}" = "Render private Remotion source" ]; then
  # The sequence step in this workflow runs only after audio restore succeeds.
  # That restore already checked the frozen runtime and exact MP3 SHA-256.
  node scripts/autopilot/prepare-long-window.mjs
else
  # Keep the original integrity gate for direct/manual/legacy invocation.
  bash -o pipefail -c "$PREPARE_COMMAND"
fi
# Sequence previews need video-code safety, not the entire controller/installer
# regression suite. Keep ESLint over all src plus full TypeScript checking here;
# the Remotion render below is the final compilation/runtime check for this window.
bash -o pipefail -c "$PREVIEW_CHECK_COMMAND"

if [ ! -x "$REMOTION_BIN" ]; then
  stage_fail "The Remotion CLI was not installed by the configured install command." 69
fi
if [ ! -s "$VISUAL_PLAN" ]; then
  stage_fail "The private source has no visual-plan.json for sequence preview." 65
fi

RANGE_JSON="$(node "$WORKER_ROOT/scripts/sequence-preview.mjs" "$VISUAL_PLAN" "$SEQUENCE_INDEX")"
START_FRAME="$(node -e 'const x=JSON.parse(process.argv[1]); process.stdout.write(String(x.startFrame))' "$RANGE_JSON")"
RENDER_END_FRAME="$(node -e 'const x=JSON.parse(process.argv[1]); process.stdout.write(String(x.renderEndFrame))' "$RANGE_JSON")"
END_FRAME="$(node -e 'const x=JSON.parse(process.argv[1]); process.stdout.write(String(x.endFrame))' "$RANGE_JSON")"
PADDED_INDEX="$(printf '%02d' "$SEQUENCE_INDEX")"
OUTPUT_DIR="$OUTPUT_ROOT/sequence-$PADDED_INDEX"
# The sequence render is already the intentionally low-quality review asset.
# Render it directly to the canonical review filename instead of transcoding a
# second MP4 after Remotion finishes.
PREVIEW_VIDEO="$OUTPUT_DIR/review.mp4"
mkdir -p "$OUTPUT_DIR"

"$REMOTION_BIN" render \
  "$ENTRY_POINT" \
  "$COMPOSITION_ID" \
  "$PREVIEW_VIDEO" \
  --codec=h264 \
  --crf="$PREVIEW_CRF" \
  --scale="$PREVIEW_SCALE" \
  --frames="${START_FRAME}-${RENDER_END_FRAME}" \
  --log=error

# The workflow places a pinned full FFmpeg/FFprobe bundle on PATH for sequence
# review derivatives. Keep the rendered MP4 itself as the canonical review
# video and generate only metadata/stills from that full toolchain.
TELIC_REUSE_SOURCE_AS_REVIEW=1 \
  bash "$WORKER_ROOT/scripts/create-review-assets.sh" "$PREVIEW_VIDEO" "$OUTPUT_DIR"

node - "$OUTPUT_DIR/status.json" "$JOB_ID" "$SOURCE_SHA" "$SEQUENCE_INDEX" "$START_FRAME" "$END_FRAME" <<'NODE'
const fs = require("node:fs");
const [outputFile, jobId, sourceSha, sequenceIndex, startFrame, endFrame] = process.argv.slice(2);
fs.writeFileSync(outputFile, `${JSON.stringify({
  status: "sequence-preview-complete",
  jobId,
  sourceSha,
  sequenceIndex: Number(sequenceIndex),
  startFrame: Number(startFrame),
  endFrame: Number(endFrame),
  completedAt: new Date().toISOString(),
}, null, 2)}\n`);
NODE

write_checksums "$OUTPUT_DIR"

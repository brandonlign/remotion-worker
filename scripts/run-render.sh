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

if [ ! -f "$REQUEST_FILE" ]; then
  echo "Render request file does not exist." >&2
  exit 66
fi

mkdir -p "$OUTPUT_DIR"
SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

if [ ! -f "$SOURCE_DIR/remotion-worker.json" ]; then
  echo "The private source is missing remotion-worker.json." >&2
  exit 65
fi

if [ -z "${JOB_ID:-}" ] || [ -z "${SOURCE_SHA:-}" ]; then
  echo "JOB_ID and SOURCE_SHA are required." >&2
  exit 65
fi

ACTUAL_SHA="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
if [ "$ACTUAL_SHA" != "$SOURCE_SHA" ]; then
  echo "The checked-out private source does not match the requested commit." >&2
  exit 65
fi

NORMALIZED_CONFIG="$(mktemp)"
trap 'rm -f "$NORMALIZED_CONFIG"' EXIT
node "$WORKER_ROOT/scripts/validate-source-config.mjs" \
  "$SOURCE_DIR/remotion-worker.json" \
  "$NORMALIZED_CONFIG"

json_field() {
  node -e 'const fs=require("fs"); const value=JSON.parse(fs.readFileSync(process.argv[1],"utf8"))[process.argv[2]]; process.stdout.write(String(value));' "$NORMALIZED_CONFIG" "$1"
}

ENTRY_POINT="$(json_field entryPoint)"
COMPOSITION_ID="$(json_field compositionId)"
OUTPUT_NAME="$(json_field outputName)"
INSTALL_COMMAND="$(json_field installCommand)"
PREPARE_COMMAND="$(json_field prepareCommand)"
CHECK_COMMAND="$(json_field checkCommand)"
CRF="$(json_field crf)"
FINAL_VIDEO="$OUTPUT_DIR/${OUTPUT_NAME}.mp4"
REMOTION_BIN="$SOURCE_DIR/node_modules/.bin/remotion"

cd "$SOURCE_DIR"

bash -o pipefail -c "$INSTALL_COMMAND"
bash -o pipefail -c "$PREPARE_COMMAND"
bash -o pipefail -c "$CHECK_COMMAND"

if [ ! -x "$REMOTION_BIN" ]; then
  echo "The Remotion CLI was not installed by the configured install command." >&2
  exit 69
fi

"$REMOTION_BIN" render \
  "$ENTRY_POINT" \
  "$COMPOSITION_ID" \
  "$FINAL_VIDEO" \
  --codec=h264 \
  --crf="$CRF" \
  --log=error

bash "$WORKER_ROOT/scripts/create-review-assets.sh" "$FINAL_VIDEO" "$OUTPUT_DIR"

node - "$OUTPUT_DIR/status.json" "$JOB_ID" "$SOURCE_SHA" "$OUTPUT_NAME" <<'NODE'
const fs = require("node:fs");
const [outputFile, jobId, sourceSha, outputName] = process.argv.slice(2);
fs.writeFileSync(outputFile, `${JSON.stringify({
  status: "complete",
  jobId,
  sourceSha,
  outputName,
  completedAt: new Date().toISOString(),
}, null, 2)}\n`);
NODE

node "$WORKER_ROOT/scripts/create-controller-handoff.mjs" \
  "$OUTPUT_DIR" \
  "$SOURCE_DIR/automation/current/youtube.json" \
  "$JOB_ID" \
  "$SOURCE_SHA"

find "$OUTPUT_DIR" -type f ! -name checksums.txt -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > "$OUTPUT_DIR/checksums.txt"

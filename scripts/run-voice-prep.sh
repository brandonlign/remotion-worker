#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: run-voice-prep.sh <request.json> <private-source-dir> <output-dir>" >&2
  exit 64
fi

REQUEST_FILE="$1"
SOURCE_DIR="$2"
OUTPUT_DIR="$3"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -f "$REQUEST_FILE" ]; then
  echo "Voice preparation request file does not exist." >&2
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

INSTALL_COMMAND="$(node -e 'const fs=require("fs"); const c=JSON.parse(fs.readFileSync(process.argv[1],"utf8")); process.stdout.write(c.installCommand);' "$NORMALIZED_CONFIG")"

cd "$SOURCE_DIR"
bash -o pipefail -c "$INSTALL_COMMAND"
npm run audio:prepare

AUDIO_FILE="$SOURCE_DIR/public/automation/voiceover.mp3"
ALIGNMENT_FILE="$SOURCE_DIR/automation/current/alignment.json"
RUNTIME_FILE="$SOURCE_DIR/automation/current/audio-runtime.json"
NARRATION_FILE="$SOURCE_DIR/automation/current/narration.txt"

for required in "$AUDIO_FILE" "$ALIGNMENT_FILE" "$RUNTIME_FILE" "$NARRATION_FILE"; do
  if [ ! -s "$required" ]; then
    echo "Voice preparation did not produce a required private artifact." >&2
    exit 65
  fi
done

cp "$AUDIO_FILE" "$OUTPUT_DIR/voiceover.mp3"
cp "$ALIGNMENT_FILE" "$OUTPUT_DIR/alignment.json"
cp "$RUNTIME_FILE" "$OUTPUT_DIR/audio-runtime.json"
cp "$NARRATION_FILE" "$OUTPUT_DIR/narration.txt"

node - "$OUTPUT_DIR/status.json" "$JOB_ID" "$SOURCE_SHA" "$RUNTIME_FILE" <<'NODE'
const fs = require("node:fs");
const [outputFile, jobId, sourceSha, runtimeFile] = process.argv.slice(2);
const runtime = JSON.parse(fs.readFileSync(runtimeFile, "utf8"));
if (runtime.jobId !== jobId) throw new Error("Audio runtime job ID mismatch.");
if (runtime.scriptSourceSha !== sourceSha) throw new Error("Audio runtime source SHA mismatch.");
fs.writeFileSync(outputFile, `${JSON.stringify({
  status: "voice-ready",
  jobId,
  sourceSha,
  narrationSha256: runtime.narrationSha256,
  durationSeconds: runtime.durationSeconds,
  totalDurationInFrames: runtime.totalDurationInFrames,
  voiceProvider: runtime.voiceProvider,
  voiceName: runtime.voiceName ?? null,
  completedAt: new Date().toISOString(),
}, null, 2)}\n`);
NODE

find "$OUTPUT_DIR" -type f ! -name checksums.txt -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > "$OUTPUT_DIR/checksums.txt"

#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 4 ]; then
  echo "Usage: restore-existing-long-voice-prep.sh <private-source-dir> <job-id> <source-sha> <output-dir>" >&2
  exit 64
fi

SOURCE_DIR="$1"
JOB_ID="$2"
SOURCE_SHA="$3"
OUTPUT_DIR="$4"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$WORKER_ROOT/scripts/lib/rclone-common.sh"
source "$WORKER_ROOT/scripts/lib/channel-storage.sh"
STAGE_DIR="$(mktemp -d)"
NAMES_FILE="$(mktemp)"
trap 'rm -rf "$STAGE_DIR"; rm -f "$NAMES_FILE"; rclone_cleanup' EXIT

if [ ! -d "$SOURCE_DIR" ]; then
  echo "Private source directory does not exist." >&2
  exit 66
fi
if ! [[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Source SHA is invalid." >&2
  exit 64
fi
validate_job_id

FORMAT="$(node - "$SOURCE_DIR/automation/current/job.json" <<'NODE'
const fs = require('node:fs');
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(String(job?.format || ''));
NODE
)"
if [ "$FORMAT" != "long" ]; then
  exit 10
fi

NARRATION_FILE="$SOURCE_DIR/automation/current/narration.txt"
if [ ! -s "$NARRATION_FILE" ]; then
  exit 10
fi

prepare_rclone_config "The Drive credential is not configured."
VOICE_ROOT_PATH="$(render_root_for_job_id "$JOB_ID")/$JOB_ID"
printf '%s\n' 'voiceover.mp3' 'alignment.json' 'audio-runtime.json' > "$NAMES_FILE"

# Absence or mismatch is not a production failure: it simply means this exact
# source has no reusable voice package and normal generation should proceed.
if ! rclone copy "gdrive:$VOICE_ROOT_PATH" "$STAGE_DIR" \
  --config "$RCLONE_CONFIG_FILE" \
  --files-from "$NAMES_FILE" \
  --stats 0 \
  --log-level ERROR; then
  exit 10
fi

for required in voiceover.mp3 alignment.json audio-runtime.json; do
  if [ ! -s "$STAGE_DIR/$required" ]; then
    exit 10
  fi
done

if ! node "$WORKER_ROOT/scripts/verify-restored-audio.mjs" \
  --reusable-long-voice \
  "$STAGE_DIR/audio-runtime.json" \
  "$STAGE_DIR/alignment.json" \
  "$STAGE_DIR/voiceover.mp3" \
  "$NARRATION_FILE" \
  "$JOB_ID" \
  "$SOURCE_SHA" \
  >/dev/null; then
  exit 10
fi

mkdir -p "$SOURCE_DIR/public/automation" "$SOURCE_DIR/automation/current" "$OUTPUT_DIR"
cp "$STAGE_DIR/voiceover.mp3" "$SOURCE_DIR/public/automation/voiceover.mp3"
cp "$STAGE_DIR/alignment.json" "$SOURCE_DIR/automation/current/alignment.json"
cp "$STAGE_DIR/audio-runtime.json" "$SOURCE_DIR/automation/current/audio-runtime.json"
cp "$STAGE_DIR/voiceover.mp3" "$OUTPUT_DIR/voiceover.mp3"
cp "$STAGE_DIR/alignment.json" "$OUTPUT_DIR/alignment.json"
cp "$STAGE_DIR/audio-runtime.json" "$OUTPUT_DIR/audio-runtime.json"
cp "$NARRATION_FILE" "$OUTPUT_DIR/narration.txt"

node - "$OUTPUT_DIR/status.json" "$STAGE_DIR/audio-runtime.json" "$JOB_ID" "$SOURCE_SHA" <<'NODE'
const fs = require('node:fs');
const [outputFile, runtimeFile, jobId, sourceSha] = process.argv.slice(2);
const runtime = JSON.parse(fs.readFileSync(runtimeFile, 'utf8'));
if (runtime.jobId !== jobId || runtime.scriptSourceSha !== sourceSha) throw new Error('Reusable voice runtime identity changed after verification.');
fs.writeFileSync(outputFile, `${JSON.stringify({
  status: 'voice-ready',
  jobId,
  sourceSha,
  narrationSha256: runtime.narrationSha256,
  durationSeconds: runtime.durationSeconds,
  totalDurationInFrames: runtime.totalDurationInFrames,
  exactAlignment: runtime.exactAlignment,
  alignmentProvider: runtime.alignmentProvider,
  alignmentQuality: runtime.alignmentQuality ?? null,
  voiceProvider: runtime.voiceProvider,
  voiceName: runtime.voiceName ?? null,
  reusedFromPrivateDrive: true,
  completedAt: new Date().toISOString(),
}, null, 2)}\n`);
NODE

echo "Reused exact long-form voice package from private Drive for $JOB_ID."

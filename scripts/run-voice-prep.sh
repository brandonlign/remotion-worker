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
source "$WORKER_ROOT/scripts/lib/stage-common.sh"
trap stage_cleanup EXIT

if [ -z "${GEMINI_API_KEYS_JSON:-}" ] && [ -z "${GEMINI_API_KEY:-}" ]; then
  stage_fail "GEMINI_API_KEYS_JSON or GEMINI_API_KEY is required for private Gemini voice preparation."
fi

prepare_private_source_stage "Voice preparation"

INSTALL_COMMAND="$(source_config_field installCommand)"

WHISPERX_VERSION="3.8.6"
PYTHON_ABI="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
ALIGNER_MARKER_VALUE="$WHISPERX_VERSION-py$PYTHON_ABI"
ALIGNER_ROOT="${TELIC_ALIGNER_ROOT:-$HOME/.cache/telic-whisperx-$WHISPERX_VERSION}"
ALIGNER_VENV="$ALIGNER_ROOT/venv"
ALIGNER_MARKER="$ALIGNER_ROOT/version.txt"
if [ ! -x "$ALIGNER_VENV/bin/python" ] || [ ! -f "$ALIGNER_MARKER" ] || [ "$(cat "$ALIGNER_MARKER")" != "$ALIGNER_MARKER_VALUE" ]; then
  rm -rf "$ALIGNER_ROOT"
  mkdir -p "$ALIGNER_ROOT"
  python3 -m venv "$ALIGNER_VENV"
  "$ALIGNER_VENV/bin/python" -m pip install --disable-pip-version-check --no-input --upgrade pip
  "$ALIGNER_VENV/bin/python" -m pip install --disable-pip-version-check --no-input "whisperx==$WHISPERX_VERSION"
  printf '%s\n' "$ALIGNER_MARKER_VALUE" > "$ALIGNER_MARKER"
fi

"$ALIGNER_VENV/bin/python" - <<'PY'
from importlib.metadata import version
if version("whisperx") != "3.8.6":
    raise SystemExit("Pinned WhisperX version check failed.")
PY

export TELIC_ALIGNER_PYTHON="$ALIGNER_VENV/bin/python"
export TORCH_HOME="${TORCH_HOME:-$HOME/.cache/torch}"
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
export TELIC_ALIGN_MODEL_DIR="${TELIC_ALIGN_MODEL_DIR:-$TORCH_HOME/telic-align-models}"
mkdir -p "$TORCH_HOME" "$HF_HOME" "$TELIC_ALIGN_MODEL_DIR"

install_private_dependencies "$INSTALL_COMMAND"
cd "$SOURCE_DIR"
npm run voiceover:test
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

node - "$ALIGNMENT_FILE" "$RUNTIME_FILE" <<'NODE'
const fs = require("node:fs");
const [alignmentFile, runtimeFile] = process.argv.slice(2);
const alignment = JSON.parse(fs.readFileSync(alignmentFile, "utf8"));
const runtime = JSON.parse(fs.readFileSync(runtimeFile, "utf8"));
if (alignment.exactAlignment !== true || alignment.alignmentProvider !== "whisperx") {
  throw new Error("Private narration did not pass WhisperX forced alignment.");
}
if (runtime.exactAlignment !== true || runtime.alignmentProvider !== "whisperx") {
  throw new Error("Audio runtime does not contain exact WhisperX timing.");
}
NODE

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
  exactAlignment: runtime.exactAlignment,
  alignmentProvider: runtime.alignmentProvider,
  alignmentQuality: runtime.alignmentQuality ?? null,
  voiceProvider: runtime.voiceProvider,
  voiceName: runtime.voiceName ?? null,
  completedAt: new Date().toISOString(),
}, null, 2)}\n`);
NODE

write_checksums "$OUTPUT_DIR"

#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "Usage: download-drive-audio.sh <private-source-dir> <job-id> [render|long-preview|render-sequence]" >&2
  exit 64
fi

SOURCE_DIR="$1"
JOB_ID="$2"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUEST_FILE="$WORKER_ROOT/jobs/request.json"
REQUEST_MODE=""
if [ "$#" -eq 3 ]; then
  REQUEST_MODE="$3"
elif [ -s "$REQUEST_FILE" ]; then
  REQUEST_MODE="$(node - "$REQUEST_FILE" "$JOB_ID" <<'NODE'
const fs = require('node:fs');
const [requestFile, expectedJobId] = process.argv.slice(2);
try {
  const request = JSON.parse(fs.readFileSync(requestFile, 'utf8'));
  if (request.jobId === expectedJobId && ["render", "long-preview", "render-sequence"].includes(request.mode)) {
    process.stdout.write(request.mode);
  }
} catch {}
NODE
)"
fi
RESTORE_MODE="${REQUEST_MODE:-render}"

source "$WORKER_ROOT/scripts/lib/rclone-common.sh"
source "$WORKER_ROOT/scripts/lib/channel-storage.sh"
DRIVE_RUNTIME_FILE="$(mktemp)"
AUDIO_ROWS_FILE="$(mktemp)"
VOICE_NAMES_FILE="$(mktemp)"
VOICE_STAGE_DIR="$(mktemp -d)"
PRIVATE_AUDIO_STAGE_DIR="$(mktemp -d)"
trap 'rm -f "${DRIVE_RUNTIME_FILE}" "${AUDIO_ROWS_FILE}" "${VOICE_NAMES_FILE}"; rm -rf "${VOICE_STAGE_DIR}" "${PRIVATE_AUDIO_STAGE_DIR}"; rclone_cleanup' EXIT

case "$RESTORE_MODE" in
  render|long-preview|render-sequence) ;;
  *) rclone_fail "Unsupported audio restore mode: $RESTORE_MODE" 64 ;;
esac

if [ ! -d "$SOURCE_DIR" ]; then
  rclone_fail "Private source directory does not exist." 66
fi
validate_job_id
prepare_rclone_config "The Drive credential is not configured."

mkdir -p "$SOURCE_DIR/public/automation" "$SOURCE_DIR/automation/current"

# The durable voice package follows the same channel-owned render root as the
# final output. Never accept an arbitrary Drive locator from a public request.
VOICE_ROOT_PATH="$(render_root_for_job_id "$JOB_ID")/$JOB_ID"

AUDIO_FILE="$SOURCE_DIR/public/automation/voiceover.mp3"
ALIGNMENT_FILE="$SOURCE_DIR/automation/current/alignment.json"
SOURCE_RUNTIME_FILE="$SOURCE_DIR/automation/current/audio-runtime.json"

# Restore the immutable voice package with one provider copy instead of
# starting a separate rclone process for each file. Sequence previews need only
# the voiceover; complete previews and full renders also need the alignment/runtime pair.
printf '%s\n' 'voiceover.mp3' > "$VOICE_NAMES_FILE"
if [ "$RESTORE_MODE" = "render" ] || [ "$RESTORE_MODE" = "long-preview" ]; then
  printf '%s\n' 'alignment.json' 'audio-runtime.json' >> "$VOICE_NAMES_FILE"
fi
rclone copy "gdrive:$VOICE_ROOT_PATH" "$VOICE_STAGE_DIR" \
  --config "$RCLONE_CONFIG_FILE" \
  --files-from "$VOICE_NAMES_FILE" \
  --stats 0 \
  --log-level ERROR

cp "$VOICE_STAGE_DIR/voiceover.mp3" "$AUDIO_FILE"

if [ "$RESTORE_MODE" = "render-sequence" ]; then
  if [ ! -s "$AUDIO_FILE" ]; then
    rclone_fail "The prepared private voiceover is incomplete."
  fi
  node "$WORKER_ROOT/scripts/verify-restored-audio.mjs" \
    --committed-long \
    "$SOURCE_RUNTIME_FILE" \
    "$AUDIO_FILE" \
    "$JOB_ID" \
    >/dev/null
else
  cp "$VOICE_STAGE_DIR/alignment.json" "$ALIGNMENT_FILE"
  cp "$VOICE_STAGE_DIR/audio-runtime.json" "$DRIVE_RUNTIME_FILE"

  for required in "$AUDIO_FILE" "$ALIGNMENT_FILE" "$DRIVE_RUNTIME_FILE"; do
    if [ ! -s "$required" ]; then
      rclone_fail "The prepared private voice package is incomplete."
    fi
  done

  RESTORE_FORMAT="$(node "$WORKER_ROOT/scripts/verify-restored-audio.mjs" \
    "$SOURCE_RUNTIME_FILE" \
    "$DRIVE_RUNTIME_FILE" \
    "$AUDIO_FILE")"

  case "$RESTORE_FORMAT" in
    long)
      ;;
    short)
      cp "$DRIVE_RUNTIME_FILE" "$SOURCE_RUNTIME_FILE"
      ;;
    *)
      rclone_fail "Audio restore verifier returned an unsupported format: $RESTORE_FORMAT"
      ;;
  esac
fi

# Productions may request approved channel-owned music and SFX through the
# private audio-design.json. The private source validates the exact allowlist.
# This worker transports only those requested Drive files and never commits or
# logs proprietary media publicly.
AUDIO_REQUEST_FILE="$SOURCE_DIR/automation/current/audio-design.json"
if ! node "$WORKER_ROOT/scripts/read-private-music-request.mjs" "$AUDIO_REQUEST_FILE" > "$AUDIO_ROWS_FILE"; then
  rclone_fail "The private channel audio restore request could not be validated."
fi

RESTORED_PRIVATE_AUDIO_COUNT=0
if [ -s "$AUDIO_ROWS_FILE" ]; then
  # Most channel SFX live in one approved Drive folder. Verify each requested
  # provider ID from one folder listing, then copy all requested files from that
  # folder in one transfer. This preserves exact identity checks while avoiding
  # two Drive/rclone round trips per SFX cue.
  while IFS= read -r drive_folder_id; do
    [ -n "$drive_folder_id" ] || continue
    GROUP_ROWS_FILE="$(mktemp)"
    GROUP_LISTING_FILE="$(mktemp)"
    GROUP_NAMES_FILE="$(mktemp)"
    GROUP_STAGE_DIR="$PRIVATE_AUDIO_STAGE_DIR/$drive_folder_id"
    mkdir -p "$GROUP_STAGE_DIR"

    awk -F $'\t' -v folder="$drive_folder_id" '$1 == folder' "$AUDIO_ROWS_FILE" > "$GROUP_ROWS_FILE"
    set_drive_root "$drive_folder_id"
    rclone lsjson gdrive: \
      --config "$RCLONE_CONFIG_FILE" \
      --files-only \
      --max-depth 1 \
      --log-level ERROR > "$GROUP_LISTING_FILE"

    python3 - "$GROUP_ROWS_FILE" "$GROUP_LISTING_FILE" "$GROUP_NAMES_FILE" <<'PY'
import json
import sys

rows_path, listing_path, names_path = sys.argv[1:]
expected = {}
with open(rows_path, encoding="utf-8") as handle:
    for raw in handle:
        parts = raw.rstrip("\n").split("\t")
        if len(parts) != 4:
            raise SystemExit("The private channel audio restore request is incomplete.")
        _, drive_file_id, file_name, _ = parts
        prior = expected.get(file_name)
        if prior and prior != drive_file_id:
            raise SystemExit("Conflicting provider IDs were requested for one private audio filename.")
        expected[file_name] = drive_file_id

with open(listing_path, encoding="utf-8") as handle:
    listing = json.load(handle)
actual = {
    item.get("Name"): item.get("ID")
    for item in listing
    if isinstance(item, dict) and item.get("Name") and item.get("ID") and not item.get("IsDir")
}
for file_name, drive_file_id in expected.items():
    if actual.get(file_name) != drive_file_id:
        raise SystemExit("A selected private channel audio file failed provider identity verification.")

with open(names_path, "w", encoding="utf-8") as handle:
    for file_name in expected:
        handle.write(file_name + "\n")
PY

    rclone copy gdrive: "$GROUP_STAGE_DIR" \
      --config "$RCLONE_CONFIG_FILE" \
      --files-from "$GROUP_NAMES_FILE" \
      --stats 0 \
      --log-level ERROR

    while IFS=$'\t' read -r _ drive_file_id file_name asset_path; do
      if [ -z "$drive_file_id" ] || [ -z "$file_name" ] || [ -z "$asset_path" ]; then
        rclone_fail "The private channel audio restore request is incomplete."
      fi
      restored="$GROUP_STAGE_DIR/$file_name"
      if [ ! -s "$restored" ]; then
        rclone_fail "A selected private channel audio file was not restored."
      fi
      destination="$SOURCE_DIR/$asset_path"
      mkdir -p "$(dirname "$destination")"
      cp "$restored" "$destination"
      RESTORED_PRIVATE_AUDIO_COUNT=$((RESTORED_PRIVATE_AUDIO_COUNT + 1))
    done < "$GROUP_ROWS_FILE"

    rm -f "$GROUP_ROWS_FILE" "$GROUP_LISTING_FILE" "$GROUP_NAMES_FILE"
  done < <(cut -f1 "$AUDIO_ROWS_FILE" | sort -u)
fi

if [ "$RESTORED_PRIVATE_AUDIO_COUNT" -gt 0 ]; then
  echo "Restored $RESTORED_PRIVATE_AUDIO_COUNT private channel audio asset(s)."
fi

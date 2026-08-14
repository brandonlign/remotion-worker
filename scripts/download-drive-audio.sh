#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "Usage: download-drive-audio.sh <private-source-dir> <job-id> [render|render-sequence]" >&2
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
const fs = require("node:fs");
const [requestFile, expectedJobId] = process.argv.slice(2);
try {
  const request = JSON.parse(fs.readFileSync(requestFile, "utf8"));
  if (request.jobId === expectedJobId && ["render", "render-sequence"].includes(request.mode)) {
    process.stdout.write(request.mode);
  }
} catch {}
NODE
)"
fi
RESTORE_MODE="${REQUEST_MODE:-render}"

source "$WORKER_ROOT/scripts/lib/rclone-common.sh"
DRIVE_RUNTIME_FILE="$(mktemp)"
MUSIC_ROWS_FILE="$(mktemp)"
trap 'rm -f "${DRIVE_RUNTIME_FILE}" "${MUSIC_ROWS_FILE}"; rclone_cleanup' EXIT

case "$RESTORE_MODE" in
  render|render-sequence) ;;
  *) rclone_fail "Unsupported audio restore mode: $RESTORE_MODE" 64 ;;
esac

if [ ! -d "$SOURCE_DIR" ]; then
  rclone_fail "Private source directory does not exist." 66
fi
validate_job_id
prepare_rclone_config "The Drive credential is not configured."

mkdir -p "$SOURCE_DIR/public/automation" "$SOURCE_DIR/automation/current"

copy_voice_artifact() {
  local name="$1"
  local destination="$2"
  rclone copyto "gdrive:$JOB_ID/$name" "$destination" \
    --config "$RCLONE_CONFIG_FILE" \
    --stats 0 \
    --log-level ERROR
}

valid_drive_file_id() {
  [[ "$1" =~ ^[A-Za-z0-9_-]{10,}$ ]]
}

AUDIO_LOCATOR_DIR="${TELIC_AUDIO_LOCATOR_DIR:-}"
AUDIO_LOCATOR_FILE=""
if [ -n "$AUDIO_LOCATOR_DIR" ]; then
  AUDIO_LOCATOR_FILE="$AUDIO_LOCATOR_DIR/voiceover.id"
fi

read_cached_voiceover_id() {
  local value=""
  if [ -n "$AUDIO_LOCATOR_FILE" ] && [ -s "$AUDIO_LOCATOR_FILE" ]; then
    IFS= read -r value < "$AUDIO_LOCATOR_FILE" || true
    if valid_drive_file_id "$value"; then
      printf '%s' "$value"
      return 0
    fi
  fi
  return 1
}

write_cached_voiceover_id() {
  local value="$1"
  if [ -z "$AUDIO_LOCATOR_FILE" ] || ! valid_drive_file_id "$value"; then
    return 0
  fi
  mkdir -p "$AUDIO_LOCATOR_DIR"
  printf '%s\n' "$value" > "$AUDIO_LOCATOR_FILE"
  chmod 600 "$AUDIO_LOCATOR_FILE"
}

resolve_voiceover_id_from_path() {
  rclone lsjson "gdrive:$JOB_ID/voiceover.mp3" \
    --config "$RCLONE_CONFIG_FILE" \
    --stat \
    --files-only \
    --log-level ERROR | python3 -c '
import json, sys
item = json.load(sys.stdin)
if not isinstance(item, dict) or not item.get("ID") or item.get("IsDir"):
    raise SystemExit(65)
print(item["ID"])
'
}

copy_voiceover_by_id() {
  local drive_file_id="$1"
  local destination="$2"
  rclone backend copyid gdrive: "$drive_file_id" "$destination" \
    --config "$RCLONE_CONFIG_FILE" \
    --log-level ERROR \
    >/dev/null
}

AUDIO_FILE="$SOURCE_DIR/public/automation/voiceover.mp3"
ALIGNMENT_FILE="$SOURCE_DIR/automation/current/alignment.json"
SOURCE_RUNTIME_FILE="$SOURCE_DIR/automation/current/audio-runtime.json"

VOICEOVER_DRIVE_ID="$(read_cached_voiceover_id || true)"
if [ -n "$VOICEOVER_DRIVE_ID" ]; then
  # Fast path: the private Actions cache carries only the opaque provider ID.
  # copyid lets Drive fetch the exact file without resolving Telic-Renders and
  # the job path on every preview run.
  copy_voiceover_by_id "$VOICEOVER_DRIVE_ID" "$AUDIO_FILE"
else
  # Compatibility/fallback path for older jobs or the first run after this
  # optimization. It seeds the private locator cache for subsequent previews.
  use_telic_renders_root
  copy_voice_artifact voiceover.mp3 "$AUDIO_FILE"
  VOICEOVER_DRIVE_ID="$(resolve_voiceover_id_from_path)"
  write_cached_voiceover_id "$VOICEOVER_DRIVE_ID"
fi

if [ "$RESTORE_MODE" = "render-sequence" ]; then
  if [ ! -s "$AUDIO_FILE" ]; then
    rclone_fail "The prepared private voiceover is incomplete."
  fi
  # Sequence previews already have the frozen long-form runtime in private source.
  # Verify the downloaded MP3 directly against that committed SHA lock and job ID;
  # alignment.json and a duplicate Drive runtime are not needed to render a window.
  node "$WORKER_ROOT/scripts/verify-restored-audio.mjs" \
    --committed-long \
    "$SOURCE_RUNTIME_FILE" \
    "$AUDIO_FILE" \
    "$JOB_ID" \
    >/dev/null
else
  # Full renders still restore the complete timing package. If the voiceover used
  # the direct-ID fast path, resolve Telic-Renders only now for these extra files.
  if [ -n "$VOICEOVER_DRIVE_ID" ]; then
    use_telic_renders_root
  fi
  copy_voice_artifact alignment.json "$ALIGNMENT_FILE"
  copy_voice_artifact audio-runtime.json "$DRIVE_RUNTIME_FILE"

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
      # The committed private-source runtime remains authoritative. The verifier
      # already proved the Drive copy is semantically identical and the MP3 hash
      # matches it, so do not overwrite the frozen source manifest.
      ;;
    short)
      # Preserve the legacy Short behavior: timing is restored from the private
      # Drive package because Shorts do not use the committed long-form freeze.
      cp "$DRIVE_RUNTIME_FILE" "$SOURCE_RUNTIME_FILE"
      ;;
    *)
      rclone_fail "Audio restore verifier returned an unsupported format: $RESTORE_FORMAT"
      ;;
  esac
fi

# Quality-v2 productions may request one or more approved Telic music tracks in
# their private audio-design.json. The private source validates the exact
# library allowlist. This worker only transports the requested Drive files and
# never commits or logs the proprietary assets publicly.
MUSIC_REQUEST_FILE="$SOURCE_DIR/automation/current/audio-design.json"
if ! node "$WORKER_ROOT/scripts/read-private-music-request.mjs" "$MUSIC_REQUEST_FILE" > "$MUSIC_ROWS_FILE"; then
  rclone_fail "The private music restore request could not be validated."
fi
mapfile -t MUSIC_ROWS < "$MUSIC_ROWS_FILE"
RESTORED_MUSIC_COUNT=0
for row in "${MUSIC_ROWS[@]}"; do
  IFS=$'\t' read -r drive_folder_id drive_file_id file_name asset_path <<<"$row"
  if [ -z "$drive_folder_id" ] || [ -z "$drive_file_id" ] || [ -z "$file_name" ] || [ -z "$asset_path" ]; then
    rclone_fail "The private music restore request is incomplete."
  fi

  set_drive_root "$drive_folder_id"
  actual_id="$(rclone lsjson "gdrive:$file_name" \
    --config "$RCLONE_CONFIG_FILE" \
    --stat \
    --files-only \
    --log-level ERROR | python3 -c '
import json, sys
item = json.load(sys.stdin)
if not isinstance(item, dict) or not item.get("ID") or item.get("IsDir"):
    raise SystemExit(65)
print(item["ID"])
')"
  if [ "$actual_id" != "$drive_file_id" ]; then
    rclone_fail "The selected private Telic music file failed provider identity verification."
  fi

  destination="$SOURCE_DIR/$asset_path"
  mkdir -p "$(dirname "$destination")"
  rclone copyto "gdrive:$file_name" "$destination" \
    --config "$RCLONE_CONFIG_FILE" \
    --stats 0 \
    --log-level ERROR
  if [ ! -s "$destination" ]; then
    rclone_fail "A selected private Telic music file was not restored."
  fi
  RESTORED_MUSIC_COUNT=$((RESTORED_MUSIC_COUNT + 1))
done

if [ "$RESTORED_MUSIC_COUNT" -gt 0 ]; then
  echo "Restored $RESTORED_MUSIC_COUNT private Telic music asset(s)."
fi

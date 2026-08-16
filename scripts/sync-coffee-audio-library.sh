#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: sync-coffee-audio-library.sh <private-ingest-manifest>" >&2
  exit 64
fi

MANIFEST="$1"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$WORKER_ROOT/scripts/lib/rclone-common.sh"

if [ ! -s "$MANIFEST" ]; then
  rclone_fail "Coffee audio ingest manifest is missing." 66
fi
if ! command -v curl >/dev/null 2>&1 || ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  rclone_fail "Coffee audio ingest requires curl, ffmpeg, and ffprobe." 69
fi

prepare_rclone_config "The Drive credential is not configured."
TMP_DIR="$(mktemp -d)"
ROWS_FILE="$(mktemp)"
trap 'rm -rf "$TMP_DIR" "$ROWS_FILE"; rclone_cleanup' EXIT

node - "$MANIFEST" > "$ROWS_FILE" <<'NODE'
const fs = require('node:fs');
const manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
if (manifest.version !== 1 || manifest.channelId !== 'coffee') throw new Error('Invalid Coffee audio ingest manifest.');
const folders = manifest.destinationFolders ?? {};
for (const kind of ['music', 'sfx']) {
  if (typeof folders[kind] !== 'string' || !/^[A-Za-z0-9_-]{10,128}$/.test(folders[kind])) throw new Error(`Invalid ${kind} destination folder.`);
}
if (!Array.isArray(manifest.assets) || manifest.assets.length < 1 || manifest.assets.length > 40) throw new Error('Coffee audio ingest must contain 1 through 40 assets.');
const ids = new Set();
const names = new Set();
for (const asset of manifest.assets) {
  if (typeof asset.id !== 'string' || !/^[a-z0-9][a-z0-9-]{1,63}$/.test(asset.id)) throw new Error('Every Coffee audio asset needs a stable id.');
  if (ids.has(asset.id)) throw new Error(`Duplicate Coffee audio id: ${asset.id}`);
  ids.add(asset.id);
  if (!['music', 'sfx'].includes(asset.kind)) throw new Error(`Invalid asset kind for ${asset.id}.`);
  if (typeof asset.fileName !== 'string' || !/^[A-Za-z0-9_. -]{3,128}\.mp3$/i.test(asset.fileName)) throw new Error(`Invalid fileName for ${asset.id}.`);
  if (names.has(`${asset.kind}:${asset.fileName}`)) throw new Error(`Duplicate destination filename: ${asset.fileName}`);
  names.add(`${asset.kind}:${asset.fileName}`);

  const url = new URL(asset.sourceUrl);
  if (url.protocol !== 'https:') throw new Error(`Asset ${asset.id} must use HTTPS.`);
  const isMixkit = url.hostname === 'assets.mixkit.co';
  const isCommons = url.hostname === 'upload.wikimedia.org';
  if (!isMixkit && !isCommons) throw new Error(`Asset ${asset.id} uses an unapproved audio source host.`);

  if (typeof asset.sourcePage !== 'string' || !asset.sourcePage.startsWith('https://')) throw new Error(`Asset ${asset.id} needs a sourcePage.`);
  if (isMixkit) {
    if (!asset.sourcePage.startsWith('https://mixkit.co/')) throw new Error(`Mixkit asset ${asset.id} needs a Mixkit sourcePage.`);
    if (typeof asset.license !== 'string' || !asset.license.startsWith('Mixkit ')) throw new Error(`Mixkit asset ${asset.id} needs an explicit Mixkit license.`);
  } else {
    if (!asset.sourcePage.startsWith('https://commons.wikimedia.org/wiki/File:')) throw new Error(`Commons asset ${asset.id} needs its Wikimedia Commons file page.`);
    if (asset.license !== 'Public domain') throw new Error(`Commons asset ${asset.id} must be explicitly verified public domain.`);
    if (asset.kind !== 'sfx') throw new Error(`Commons assets are only approved for Coffee SFX.`);
  }

  if (asset.transcodeToMp3 !== true && asset.transcodeToMp3 !== false) throw new Error(`Asset ${asset.id} needs transcodeToMp3.`);
  const fields = [asset.kind, asset.id, folders[asset.kind], asset.fileName, asset.sourceUrl, asset.transcodeToMp3 ? '1' : '0'];
  if (fields.some((value) => String(value).includes('\t') || String(value).includes('\n'))) throw new Error(`Asset ${asset.id} contains unsafe control characters.`);
  process.stdout.write(fields.join('\t') + '\n');
}
NODE

SYNCED=0
REUSED=0
while IFS=$'\t' read -r kind asset_id folder_id file_name source_url force_transcode; do
  [ -n "$asset_id" ] || continue
  set_drive_root "$folder_id"

  existing="$(rclone lsjson "gdrive:$file_name" \
    --config "$RCLONE_CONFIG_FILE" \
    --stat \
    --files-only \
    --log-level ERROR 2>/dev/null || true)"
  if printf '%s' "$existing" | python3 -c 'import json,sys; raw=sys.stdin.read().strip(); item=json.loads(raw) if raw else {}; raise SystemExit(0 if isinstance(item,dict) and item.get("ID") and not item.get("IsDir") and int(item.get("Size") or 0)>0 else 1)'; then
    REUSED=$((REUSED + 1))
    echo "Verified existing Coffee ${kind} asset: ${asset_id}."
    continue
  fi

  source_file="$TMP_DIR/${asset_id}.source"
  output_file="$TMP_DIR/${asset_id}.mp3"
  curl --fail --location --silent --show-error --retry 3 --retry-all-errors --connect-timeout 20 --max-time 180 \
    --user-agent "Telic-Coffee-Audio-Ingest/1.0" \
    "$source_url" -o "$source_file"
  if [ ! -s "$source_file" ]; then
    rclone_fail "Approved Coffee audio source download was empty for ${asset_id}."
  fi

  source_codec="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$source_file" 2>/dev/null | head -n 1 || true)"
  if [ -z "$source_codec" ]; then
    rclone_fail "Approved Coffee audio source was not a readable audio file for ${asset_id}."
  fi

  if [ "$force_transcode" = "1" ] || [[ "$source_codec" != mp3* ]]; then
    ffmpeg -hide_banner -loglevel error -y -i "$source_file" -vn -codec:a libmp3lame -q:a 2 "$output_file"
  else
    cp "$source_file" "$output_file"
  fi

  if [ ! -s "$output_file" ] || [ "$(stat -c '%s' "$output_file")" -lt 1024 ]; then
    rclone_fail "Approved Coffee audio file was invalid after preparation for ${asset_id}."
  fi
  normalized_codec="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$output_file" 2>/dev/null | head -n 1 || true)"
  if [[ "$normalized_codec" != mp3* ]]; then
    rclone_fail "Approved Coffee audio asset ${asset_id} did not normalize to MP3-family audio."
  fi

  rclone copyto "$output_file" "gdrive:$file_name" \
    --config "$RCLONE_CONFIG_FILE" \
    --stats 0 \
    --log-level ERROR
  if ! rclone lsjson "gdrive:$file_name" \
    --config "$RCLONE_CONFIG_FILE" \
    --stat \
    --files-only \
    --log-level ERROR \
    | python3 -c 'import json,sys; item=json.load(sys.stdin); raise SystemExit(0 if isinstance(item,dict) and item.get("ID") and not item.get("IsDir") and int(item.get("Size") or 0)>0 else 65)'; then
    rclone_fail "Drive verification failed for approved Coffee audio asset ${asset_id}."
  fi

  SYNCED=$((SYNCED + 1))
  echo "Synced approved Coffee ${kind} asset: ${asset_id}."
done < "$ROWS_FILE"

echo "Coffee professional audio ingest completed: ${SYNCED} new assets synced, ${REUSED} existing assets verified."

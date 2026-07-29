#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: upload-drive.sh <result-dir> <job-id>" >&2
  exit 64
fi

RESULT_DIR="$1"
JOB_ID="$2"

if [ ! -d "$RESULT_DIR" ]; then
  echo "Result directory does not exist." >&2
  exit 66
fi

if [ -z "${RCLONE_CONFIG_B64:-}" ]; then
  echo "The Drive upload secret is not configured." >&2
  exit 65
fi

if ! [[ "$JOB_ID" =~ ^[a-z0-9][a-z0-9-]{5,63}$ ]]; then
  echo "Invalid job ID." >&2
  exit 65
fi

RCLONE_CONFIG_FILE="$(mktemp)"
TOKEN_INFO_FILE="$(mktemp)"
trap 'rm -f "$RCLONE_CONFIG_FILE" "$TOKEN_INFO_FILE"' EXIT

printf '%s' "$RCLONE_CONFIG_B64" | base64 --decode > "$RCLONE_CONFIG_FILE"
chmod 600 "$RCLONE_CONFIG_FILE"

if ! rclone listremotes --config "$RCLONE_CONFIG_FILE" | grep -qx 'gdrive:'; then
  echo "The rclone configuration must contain a remote named gdrive." >&2
  exit 65
fi

# Force authentication/refresh before checking the effective OAuth token scope.
rclone lsf gdrive:Telic-Renders \
  --dirs-only \
  --max-depth 1 \
  --config "$RCLONE_CONFIG_FILE" \
  --stats 0 \
  --log-level ERROR \
  >/dev/null

ACCESS_TOKEN="$(node - "$RCLONE_CONFIG_FILE" <<'NODE'
const fs = require('node:fs');
const config = fs.readFileSync(process.argv[2], 'utf8');
const section = config.match(/\[gdrive\]([\s\S]*?)(?:\n\[|$)/);
if (!section) process.exit(1);
const tokenLine = section[1].match(/^\s*token\s*=\s*(.+)$/m);
if (!tokenLine) process.exit(1);
const token = JSON.parse(tokenLine[1]);
if (typeof token.access_token !== 'string' || token.access_token.length < 20) process.exit(1);
process.stdout.write(token.access_token);
NODE
)"

curl --fail --silent --show-error --get \
  --data-urlencode "access_token=$ACCESS_TOKEN" \
  "https://oauth2.googleapis.com/tokeninfo" \
  > "$TOKEN_INFO_FILE"

node - "$TOKEN_INFO_FILE" <<'NODE'
const fs = require('node:fs');
const info = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const scopes = new Set(String(info.scope ?? '').split(/\s+/).filter(Boolean));
const driveFile = 'https://www.googleapis.com/auth/drive.file';
const fullDrive = 'https://www.googleapis.com/auth/drive';
if (!scopes.has(driveFile) || scopes.has(fullDrive)) {
  throw new Error('The effective Google token must use drive.file without full Drive access.');
}
NODE

printf 'Upload completed at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$RESULT_DIR/upload-complete.txt"

rclone copy \
  "$RESULT_DIR" \
  "gdrive:Telic-Renders/$JOB_ID" \
  --config "$RCLONE_CONFIG_FILE" \
  --transfers 4 \
  --checkers 8 \
  --stats 0 \
  --log-level ERROR

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
TOKENINFO_FILE="$(mktemp)"
trap 'rm -f "$RCLONE_CONFIG_FILE" "$TOKENINFO_FILE"' EXIT

printf '%s' "$RCLONE_CONFIG_B64" | base64 --decode > "$RCLONE_CONFIG_FILE"
chmod 600 "$RCLONE_CONFIG_FILE"

if ! rclone listremotes --config "$RCLONE_CONFIG_FILE" | grep -qx 'gdrive:'; then
  echo "The rclone configuration must contain a remote named gdrive." >&2
  exit 65
fi

RCLONE_SCOPE="$(awk '
  /^\[gdrive\]$/ { in_remote=1; next }
  /^\[/ { if (in_remote) exit }
  in_remote && /^[[:space:]]*scope[[:space:]]*=/ {
    sub(/^[^=]*=[[:space:]]*/, "", $0)
    sub(/[[:space:]]*$/, "", $0)
    print
    exit
  }
' "$RCLONE_CONFIG_FILE")"
NORMALIZED_SCOPE="$(printf '%s' "$RCLONE_SCOPE" | tr -d '[:space:]\"')"
SCOPE_CONFIRMED=0

case "$NORMALIZED_SCOPE" in
  drive.file|https://www.googleapis.com/auth/drive.file|drive.file,drive.metadata.readonly|drive.metadata.readonly,drive.file|https://www.googleapis.com/auth/drive.file,https://www.googleapis.com/auth/drive.metadata.readonly|https://www.googleapis.com/auth/drive.metadata.readonly,https://www.googleapis.com/auth/drive.file)
    SCOPE_CONFIRMED=1
    ;;
esac

if [ "$SCOPE_CONFIRMED" -ne 1 ]; then
  rclone lsf "gdrive:Telic-Renders" \
    --config "$RCLONE_CONFIG_FILE" \
    --max-depth 1 \
    --stats 0 \
    --log-level ERROR \
    >/dev/null

  TOKEN_JSON="$(awk '
    /^\[gdrive\]$/ { in_remote=1; next }
    /^\[/ { if (in_remote) exit }
    in_remote && /^[[:space:]]*token[[:space:]]*=/ {
      sub(/^[^=]*=[[:space:]]*/, "", $0)
      print
      exit
    }
  ' "$RCLONE_CONFIG_FILE")"

  ACCESS_TOKEN="$(printf '%s' "$TOKEN_JSON" | node -e '
    let input="";
    process.stdin.on("data", (chunk) => input += chunk);
    process.stdin.on("end", () => {
      try {
        const token = JSON.parse(input);
        if (typeof token.access_token !== "string" || token.access_token.length < 20) process.exit(1);
        process.stdout.write(token.access_token);
      } catch {
        process.exit(1);
      }
    });
  ')"

  printf 'access_token=%s' "$ACCESS_TOKEN" | curl --fail --silent --show-error \
    --header 'Content-Type: application/x-www-form-urlencoded' \
    --data-binary @- \
    https://oauth2.googleapis.com/tokeninfo \
    --output "$TOKENINFO_FILE"

  node - "$TOKENINFO_FILE" <<'NODE'
const fs = require('node:fs');
const tokenInfo = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const scopes = new Set(String(tokenInfo.scope ?? '').split(/\s+/).filter(Boolean));
const driveFile = 'https://www.googleapis.com/auth/drive.file';
const fullDrive = 'https://www.googleapis.com/auth/drive';
if (!scopes.has(driveFile) || scopes.has(fullDrive)) {
  process.exit(1);
}
NODE
fi

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

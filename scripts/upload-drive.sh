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
RCLONE_LOG_FILE="$(mktemp)"
trap 'rm -f "$RCLONE_CONFIG_FILE" "$RCLONE_LOG_FILE"' EXIT

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

if [[ ",$RCLONE_SCOPE," == *",drive.file,"* ]]; then
  :
elif [ "$RCLONE_SCOPE" = "drive" ] || [ -z "$RCLONE_SCOPE" ]; then
  echo "Temporary render warning: using the existing broader/default Drive scope." >&2
else
  echo "Unsupported gdrive scope: $RCLONE_SCOPE" >&2
  exit 65
fi

printf 'Upload completed at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$RESULT_DIR/upload-complete.txt"

set +e
rclone copy \
  "$RESULT_DIR" \
  "gdrive:Telic-Renders/$JOB_ID" \
  --config "$RCLONE_CONFIG_FILE" \
  --transfers 4 \
  --checkers 8 \
  --stats 0 \
  --log-level ERROR \
  --log-file "$RCLONE_LOG_FILE"
RCLONE_EXIT=$?
set -e

if [ "$RCLONE_EXIT" -ne 0 ]; then
  PARENT_STDERR="/proc/$PPID/fd/2"
  if [ -w "$PARENT_STDERR" ]; then
    {
      echo "::error::Sanitized private Drive upload diagnostic follows."
      grep -E 'ERROR|Failed|invalid_grant|unauthorized|forbidden|scope|quota|permission|access|token|root' "$RCLONE_LOG_FILE" \
        | tail -20 \
        | sed -E 's#https?://[^ ]+#[url-redacted]#g'
    } > "$PARENT_STDERR"
  fi
  exit "$RCLONE_EXIT"
fi

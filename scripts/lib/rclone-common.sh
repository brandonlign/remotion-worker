#!/usr/bin/env bash

RCLONE_CONFIG_FILE=""

rclone_cleanup() {
  if [ -n "$RCLONE_CONFIG_FILE" ]; then
    rm -f "$RCLONE_CONFIG_FILE"
  fi
}

rclone_fail() {
  local message="$1"
  local code="${2:-65}"
  echo "$message" >&2
  exit "$code"
}

validate_job_id() {
  if ! [[ "$JOB_ID" =~ ^[a-z0-9][a-z0-9-]{5,63}$ ]]; then
    rclone_fail "Invalid job ID."
  fi
}

prepare_rclone_config() {
  local missing_secret_message="$1"
  if [ -z "${RCLONE_CONFIG_B64:-}" ]; then
    rclone_fail "$missing_secret_message"
  fi

  RCLONE_CONFIG_FILE="$(mktemp)"
  if ! printf '%s' "$RCLONE_CONFIG_B64" | base64 --decode > "$RCLONE_CONFIG_FILE"; then
    rclone_fail "The Drive credential is not valid base64."
  fi
  chmod 600 "$RCLONE_CONFIG_FILE"

  if ! rclone listremotes --config "$RCLONE_CONFIG_FILE" | grep -qx 'gdrive:'; then
    rclone_fail "The rclone configuration must contain a remote named gdrive."
  fi
}

validate_drive_file_scope() {
  python3 - "$RCLONE_CONFIG_FILE" <<'PY'
import configparser
import re
import sys

config_path = sys.argv[1]
parser = configparser.RawConfigParser()
parser.read(config_path)
raw = parser.get("gdrive", "scope", fallback="").strip().strip("\"'")
tokens = {
    token
    for token in re.split(r"[\s,]+", raw.replace("\\,", ","))
    if token
}
normalized = {
    token.removeprefix("https://www.googleapis.com/auth/")
    for token in tokens
}
allowed = {"drive.file", "drive.readonly"}
if "drive.file" not in normalized or not normalized.issubset(allowed):
    print(
        "The gdrive remote must include drive.file and may only add the read-only drive.readonly scope; "
        f"configured scopes: {raw!r}",
        file=sys.stderr,
    )
    raise SystemExit(65)
PY
}

resolve_unique_folder_id() {
  local expected_name="$1"
  rclone lsjson gdrive: \
    --config "$RCLONE_CONFIG_FILE" \
    --dirs-only \
    --max-depth 1 \
    --log-level ERROR | \
    python3 -c '
import json
import sys

expected = sys.argv[1]
items = json.load(sys.stdin)
matches = [item for item in items if item.get("Name") == expected and item.get("IsDir")]
if len(matches) != 1:
    print(f"Expected exactly one Drive folder named {expected!r}; found {len(matches)}.", file=sys.stderr)
    raise SystemExit(65)
folder_id = matches[0].get("ID")
if not folder_id:
    print("The resolved Drive folder has no provider ID.", file=sys.stderr)
    raise SystemExit(65)
print(folder_id)
' "$expected_name"
}

set_drive_root() {
  local folder_id="$1"
  python3 - "$RCLONE_CONFIG_FILE" "$folder_id" <<'PY'
import configparser
import os
import sys

path, folder_id = sys.argv[1:]
parser = configparser.RawConfigParser()
parser.read(path)
if "gdrive" not in parser:
    raise SystemExit("The rclone configuration has no gdrive section.")
parser.set("gdrive", "root_folder_id", folder_id)
with open(path, "w", encoding="utf-8") as handle:
    parser.write(handle, space_around_delimiters=True)
os.chmod(path, 0o600)
PY
}

use_telic_renders_root() {
  local render_folder_id
  render_folder_id="$(resolve_unique_folder_id 'Telic-Renders')"
  set_drive_root "$render_folder_id"
}

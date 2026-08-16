#!/usr/bin/env bash

STAGE_TEMP_FILES=()

stage_cleanup() {
  if [ "${#STAGE_TEMP_FILES[@]}" -gt 0 ]; then
    rm -f "${STAGE_TEMP_FILES[@]}"
  fi
}

stage_fail() {
  local message="$1"
  local code="${2:-65}"
  echo "$message" >&2
  exit "$code"
}

prepare_private_source_stage() {
  local request_label="$1"

  if [ ! -f "$REQUEST_FILE" ]; then
    stage_fail "$request_label request file does not exist." 66
  fi
  if [ ! -d "$SOURCE_DIR" ]; then
    stage_fail "Private source directory does not exist." 66
  fi

  mkdir -p "$OUTPUT_DIR"
  SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
  OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

  if [ ! -f "$SOURCE_DIR/remotion-worker.json" ]; then
    stage_fail "The private source is missing remotion-worker.json."
  fi
  if [ -z "${JOB_ID:-}" ] || [ -z "${SOURCE_SHA:-}" ]; then
    stage_fail "JOB_ID and SOURCE_SHA are required."
  fi

  local actual_sha
  actual_sha="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
  if [ "$actual_sha" != "$SOURCE_SHA" ]; then
    stage_fail "The checked-out private source does not match the requested commit."
  fi

  NORMALIZED_CONFIG="$(mktemp)"
  STAGE_TEMP_FILES+=("$NORMALIZED_CONFIG")
  node "$WORKER_ROOT/scripts/validate-source-config.mjs" \
    "$SOURCE_DIR/remotion-worker.json" \
    "$NORMALIZED_CONFIG"
}

source_config_field() {
  node -e '
    const fs = require("node:fs");
    const config = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
    process.stdout.write(String(config[process.argv[2]]));
  ' "$NORMALIZED_CONFIG" "$1"
}

install_private_dependencies() {
  local install_command="$1"
  local lockfile="$SOURCE_DIR/package-lock.json"
  local node_modules="$SOURCE_DIR/node_modules"
  local marker="$node_modules/.telic-package-lock-sha256"

  if [ ! -f "$lockfile" ]; then
    stage_fail "The private source is missing package-lock.json; dependency reuse requires an exact lockfile." 65
  fi

  local lock_sha
  lock_sha="$(sha256sum "$lockfile" | awk '{print $1}')"
  local cached_sha=""
  if [ -f "$marker" ]; then
    cached_sha="$(tr -d '[:space:]' < "$marker")"
  fi

  if [ "$cached_sha" = "$lock_sha" ] && [ -x "$node_modules/.bin/remotion" ]; then
    echo "Reusing verified cached Node dependencies for package-lock $lock_sha."
    return 0
  fi

  if [ -d "$node_modules" ]; then
    echo "Cached Node dependencies are missing or stale; falling back to the configured clean install."
  fi
  (
    cd "$SOURCE_DIR"
    bash -o pipefail -c "$install_command"
  )

  if [ ! -x "$node_modules/.bin/remotion" ]; then
    stage_fail "The configured install command did not produce the Remotion CLI." 69
  fi
  printf '%s\n' "$lock_sha" > "$marker"
}

write_checksums() {
  local directory="$1"
  find "$directory" -type f ! -name checksums.txt -print0 \
    | sort -z \
    | xargs -0 -r sha256sum \
    > "$directory/checksums.txt"
}

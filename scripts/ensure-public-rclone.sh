#!/usr/bin/env bash
set -Eeuo pipefail

RCLONE_VERSION="1.75.0"
RCLONE_ROOT="${TELIC_RCLONE_ROOT:-$HOME/.cache/telic-tools/rclone-v$RCLONE_VERSION}"
RCLONE_BIN="$RCLONE_ROOT/rclone"

valid_cached_rclone() {
  [ -x "$RCLONE_BIN" ] && [ "$("$RCLONE_BIN" version 2>/dev/null | head -n 1)" = "rclone v$RCLONE_VERSION" ]
}

activate_cached_rclone() {
  export PATH="$RCLONE_ROOT:$PATH"
  if [ -n "${GITHUB_PATH:-}" ]; then
    printf '%s\n' "$RCLONE_ROOT" >> "$GITHUB_PATH"
  fi
}

download_pinned_rclone() (
  set -Eeuo pipefail
  command -v curl >/dev/null 2>&1 || exit 1
  command -v unzip >/dev/null 2>&1 || exit 1

  local_arch=""
  checksum=""
  case "$(uname -m)" in
    x86_64|amd64)
      local_arch="amd64"
      checksum="aa2804e08f48250e71009c727124b6341cd0288465804a9a09d14663cabafbaa"
      ;;
    aarch64|arm64)
      local_arch="arm64"
      checksum="d0ad88ba4c8e285b7c9efa591e0ab643280a91741e13c27f3a9c0957ccfa5203"
      ;;
    *)
      exit 1
      ;;
  esac

  archive="rclone-v${RCLONE_VERSION}-linux-${local_arch}.zip"
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "$temp_dir"' EXIT

  curl --fail --silent --show-error --location \
    "https://github.com/rclone/rclone/releases/download/v${RCLONE_VERSION}/${archive}" \
    --output "$temp_dir/$archive"

  printf '%s  %s\n' "$checksum" "$temp_dir/$archive" | sha256sum --check --status
  unzip -q "$temp_dir/$archive" -d "$temp_dir"
  extracted="$temp_dir/rclone-v${RCLONE_VERSION}-linux-${local_arch}/rclone"
  [ -x "$extracted" ]

  mkdir -p "$RCLONE_ROOT"
  install -m 0755 "$extracted" "$RCLONE_BIN"
  valid_cached_rclone
)

if valid_cached_rclone; then
  activate_cached_rclone
  echo "Using cached public rclone v$RCLONE_VERSION."
  return 0 2>/dev/null || exit 0
fi

rm -rf "$RCLONE_ROOT"
if download_pinned_rclone; then
  activate_cached_rclone
  echo "Installed checksum-verified public rclone v$RCLONE_VERSION."
  return 0 2>/dev/null || exit 0
fi

# Availability fallback only. Do not seed the version-pinned cache with an apt
# package whose version can vary with the runner image.
echo "Pinned rclone download was unavailable; falling back to the runner package manager."
sudo apt-get update -qq
sudo apt-get install -y -qq rclone
command -v rclone >/dev/null 2>&1

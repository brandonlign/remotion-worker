#!/usr/bin/env bash
set -Eeuo pipefail

# Window-review stills need a full FFmpeg build with fps/tile/split/scale.
# Pin an exact dated BtbN release plus exact archive names, and verify the
# downloaded archive against the checksum file published with that same release.
# The cache path is intentionally retained for compatibility with the existing
# workflow cache key. If the pinned download ever fails, use a bounded distro
# fallback rather than allowing a hosted runner to hang indefinitely.
FFMPEG_SERIES="8.1"
FFMPEG_RELEASE_TAG="autobuild-2026-08-18-15-03"
FFMPEG_CACHE_ROOT="${HOME}/.cache/telic-tools/ffmpeg-n8.1-btbn-20260813"
FFMPEG_BIN_DIR="$FFMPEG_CACHE_ROOT/bin"

case "$(uname -m)" in
  x86_64|amd64)
    FFMPEG_ARCHIVE_NAME="ffmpeg-n8.1.2-44-g7c533d0f86-linux64-gpl-8.1.tar.xz"
    ;;
  aarch64|arm64)
    FFMPEG_ARCHIVE_NAME="ffmpeg-n8.1.2-44-g7c533d0f86-linuxarm64-gpl-8.1.tar.xz"
    ;;
  *)
    FFMPEG_ARCHIVE_NAME=""
    ;;
esac

ffmpeg_has_required_filters() {
  local ffmpeg_bin="$1"
  [ -x "$ffmpeg_bin" ] || return 1
  local filters
  filters="$($ffmpeg_bin -hide_banner -filters 2>/dev/null)" || return 1
  for filter in fps tile split scale; do
    grep -Eq "[[:space:]]${filter}[[:space:]]" <<<"$filters" || return 1
  done
}

activate_cached_ffmpeg() {
  export PATH="$FFMPEG_BIN_DIR:$PATH"
  if [ -n "${GITHUB_PATH:-}" ]; then
    printf '%s\n' "$FFMPEG_BIN_DIR" >> "$GITHUB_PATH"
  fi
}

if [ -x "$FFMPEG_BIN_DIR/ffmpeg" ] \
  && [ -x "$FFMPEG_BIN_DIR/ffprobe" ] \
  && ffmpeg_has_required_filters "$FFMPEG_BIN_DIR/ffmpeg"; then
  activate_cached_ffmpeg
  echo "Using cached full FFmpeg ${FFMPEG_SERIES} preview tools."
  return 0 2>/dev/null || exit 0
fi

install_from_pinned_release() {
  [ -n "$FFMPEG_ARCHIVE_NAME" ] || return 1
  command -v curl >/dev/null 2>&1 || return 1
  command -v tar >/dev/null 2>&1 || return 1
  command -v sha256sum >/dev/null 2>&1 || return 1

  local temp_dir archive checksums extract_dir base_url expected_sha ffmpeg_src ffprobe_src
  temp_dir="$(mktemp -d)"
  archive="$temp_dir/$FFMPEG_ARCHIVE_NAME"
  checksums="$temp_dir/checksums.sha256"
  extract_dir="$temp_dir/extract"
  base_url="https://github.com/BtbN/FFmpeg-Builds/releases/download/$FFMPEG_RELEASE_TAG"
  mkdir -p "$extract_dir"

  if ! curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
    "$base_url/checksums.sha256" -o "$checksums"; then
    rm -rf "$temp_dir"
    return 1
  fi

  expected_sha="$(awk -v name="$FFMPEG_ARCHIVE_NAME" '$2 == name || $2 == "*" name {print $1; exit}' "$checksums")"
  if ! [[ "$expected_sha" =~ ^[0-9a-fA-F]{64}$ ]]; then
    rm -rf "$temp_dir"
    return 1
  fi

  if ! curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
    "$base_url/$FFMPEG_ARCHIVE_NAME" -o "$archive"; then
    rm -rf "$temp_dir"
    return 1
  fi

  if ! printf '%s  %s\n' "$expected_sha" "$archive" | sha256sum --check --status; then
    rm -rf "$temp_dir"
    return 1
  fi

  if ! tar -xJf "$archive" -C "$extract_dir"; then
    rm -rf "$temp_dir"
    return 1
  fi

  ffmpeg_src="$(find "$extract_dir" -type f -path '*/bin/ffmpeg' -print -quit)"
  ffprobe_src="$(find "$extract_dir" -type f -path '*/bin/ffprobe' -print -quit)"
  if [ -z "$ffmpeg_src" ] || [ -z "$ffprobe_src" ] || ! ffmpeg_has_required_filters "$ffmpeg_src"; then
    rm -rf "$temp_dir"
    return 1
  fi

  rm -rf "$FFMPEG_CACHE_ROOT"
  mkdir -p "$FFMPEG_BIN_DIR"
  install -m 0755 "$ffmpeg_src" "$FFMPEG_BIN_DIR/ffmpeg"
  install -m 0755 "$ffprobe_src" "$FFMPEG_BIN_DIR/ffprobe"
  rm -rf "$temp_dir"

  ffmpeg_has_required_filters "$FFMPEG_BIN_DIR/ffmpeg"
}

if install_from_pinned_release; then
  activate_cached_ffmpeg
  echo "Installed checksum-verified full FFmpeg ${FFMPEG_SERIES} preview tools."
  return 0 2>/dev/null || exit 0
fi

# Durable compatibility fallback. Keep it bounded so a transient apt mirror or
# package-manager issue fails the stage instead of wedging the worker indefinitely.
echo "Pinned FFmpeg bootstrap failed; falling back to the distro ffmpeg package." >&2
if ! timeout 180s sudo apt-get update -qq \
  || ! timeout 180s sudo apt-get install -y -qq ffmpeg; then
  echo "Timed out or failed while installing the distro ffmpeg fallback." >&2
  return 69 2>/dev/null || exit 69
fi
if ! command -v ffmpeg >/dev/null 2>&1 \
  || ! command -v ffprobe >/dev/null 2>&1 \
  || ! ffmpeg_has_required_filters "$(command -v ffmpeg)"; then
  echo "No compatible full FFmpeg installation is available." >&2
  return 69 2>/dev/null || exit 69
fi

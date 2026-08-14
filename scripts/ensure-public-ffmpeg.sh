#!/usr/bin/env bash
set -Eeuo pipefail

# Window-review stills need a full FFmpeg build with fps/tile/split/scale.
# Pin immutable GitHub release asset IDs plus their published SHA-256 digests;
# cache only these public binaries. If download or verification ever fails,
# fall back to the distro package rather than making rendering brittle.
FFMPEG_SERIES="8.1"
FFMPEG_CACHE_ROOT="${HOME}/.cache/telic-tools/ffmpeg-n8.1-btbn-20260813"
FFMPEG_BIN_DIR="$FFMPEG_CACHE_ROOT/bin"

case "$(uname -m)" in
  x86_64|amd64)
    FFMPEG_ASSET_ID="513287053"
    FFMPEG_ARCHIVE_SHA256="ae395e0425d3a494626d0cac8f75715aca6dd802762aedf0f2e295382d6d0ba4"
    ;;
  aarch64|arm64)
    FFMPEG_ASSET_ID="513287115"
    FFMPEG_ARCHIVE_SHA256="139dde8a333f0acb98e9c7acf6d0a48f3ed8203a9142f4d6e332e88e4572a7fa"
    ;;
  *)
    FFMPEG_ASSET_ID=""
    FFMPEG_ARCHIVE_SHA256=""
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

install_from_pinned_asset() {
  [ -n "$FFMPEG_ASSET_ID" ] || return 1
  command -v curl >/dev/null 2>&1 || return 1
  command -v tar >/dev/null 2>&1 || return 1
  command -v sha256sum >/dev/null 2>&1 || return 1

  local temp_dir archive extract_dir ffmpeg_src ffprobe_src
  temp_dir="$(mktemp -d)"
  archive="$temp_dir/ffmpeg.tar.xz"
  extract_dir="$temp_dir/extract"
  mkdir -p "$extract_dir"

  if ! curl --fail --location --silent --show-error \
    -H 'Accept: application/octet-stream' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    -H 'User-Agent: telic-remotion-worker' \
    "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/assets/$FFMPEG_ASSET_ID" \
    -o "$archive"; then
    rm -rf "$temp_dir"
    return 1
  fi

  if ! printf '%s  %s\n' "$FFMPEG_ARCHIVE_SHA256" "$archive" | sha256sum --check --status; then
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

if install_from_pinned_asset; then
  activate_cached_ffmpeg
  echo "Installed checksum-verified full FFmpeg ${FFMPEG_SERIES} preview tools."
  return 0 2>/dev/null || exit 0
fi

# Durable compatibility fallback. This is slower on a cold hosted runner, but
# preserves correctness if the pinned public asset ever becomes unavailable.
echo "Pinned FFmpeg bootstrap failed; falling back to the distro ffmpeg package." >&2
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg
if ! command -v ffmpeg >/dev/null 2>&1 \
  || ! command -v ffprobe >/dev/null 2>&1 \
  || ! ffmpeg_has_required_filters "$(command -v ffmpeg)"; then
  echo "No compatible full FFmpeg installation is available." >&2
  return 69 2>/dev/null || exit 69
fi

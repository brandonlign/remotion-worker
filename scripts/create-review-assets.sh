#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: create-review-assets.sh <video.mp4> <output-dir>" >&2
  exit 64
fi

VIDEO="$1"
OUTPUT_DIR="$2"
REMOTION_BIN="${TELIC_REMOTION_BIN:-}"
REUSE_SOURCE_AS_REVIEW="${TELIC_REUSE_SOURCE_AS_REVIEW:-0}"

if [ ! -s "$VIDEO" ]; then
  echo "Rendered video is missing or empty." >&2
  exit 66
fi

run_media_tool() {
  local tool="$1"
  shift
  case "$tool" in
    ffmpeg|ffprobe) ;;
    *)
      echo "Unsupported media tool: $tool" >&2
      return 64
      ;;
  esac

  if [ -n "$REMOTION_BIN" ] && [ -x "$REMOTION_BIN" ]; then
    "$REMOTION_BIN" "$tool" "$@"
  else
    "$tool" "$@"
  fi
}

mkdir -p "$OUTPUT_DIR/keyframes"

run_media_tool ffprobe \
  -v error \
  -show_format \
  -show_streams \
  -of json \
  "$VIDEO" \
  > "$OUTPUT_DIR/media-metadata.json"

if [ "$REUSE_SOURCE_AS_REVIEW" = "1" ]; then
  # render-sequence already produces a deliberately low-quality review video.
  # Require it to be the canonical review.mp4 so callers cannot accidentally
  # skip packaging while leaving no review video behind.
  if [ "$VIDEO" != "$OUTPUT_DIR/review.mp4" ]; then
    echo "TELIC_REUSE_SOURCE_AS_REVIEW requires the source video to be output-dir/review.mp4." >&2
    exit 64
  fi
else
  run_media_tool ffmpeg \
    -hide_banner \
    -loglevel error \
    -y \
    -i "$VIDEO" \
    -vf "scale=540:-2" \
    -c:v libx264 \
    -preset veryfast \
    -crf 28 \
    -c:a aac \
    -b:a 96k \
    -movflags +faststart \
    "$OUTPUT_DIR/review.mp4"
fi

# Decode the video only once for both still-image review products. Use explicit
# named filter options throughout this bundled-FFmpeg path; the runner's system
# FFmpeg accepted shorthand forms, but Remotion's bundled build rejected them.
run_media_tool ffmpeg \
  -hide_banner \
  -loglevel error \
  -y \
  -i "$VIDEO" \
  -filter_complex "[0:v]fps=fps=0.5,split=outputs=2[keyframes][sheet];[keyframes]scale=w=360:h=-2[keyframes_out];[sheet]scale=w=210:h=-2,tile=layout=5x4:padding=8:margin=8[sheet_out]" \
  -map "[keyframes_out]" \
  -q:v 3 \
  "$OUTPUT_DIR/keyframes/frame-%03d.jpg" \
  -map "[sheet_out]" \
  -frames:v 1 \
  -q:v 3 \
  "$OUTPUT_DIR/contact-sheet.jpg"

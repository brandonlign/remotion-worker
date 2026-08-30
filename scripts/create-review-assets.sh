#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "Usage: create-review-assets.sh <video.mp4> <output-dir> [maximum-review-frames]" >&2
  exit 64
fi

VIDEO="$1"
OUTPUT_DIR="$2"
MAXIMUM_REVIEW_FRAMES="${3:-0}"
REMOTION_BIN="${TELIC_REMOTION_BIN:-}"
REUSE_SOURCE_AS_REVIEW="${TELIC_REUSE_SOURCE_AS_REVIEW:-0}"

if ! [[ "$MAXIMUM_REVIEW_FRAMES" =~ ^[0-9]+$ ]]; then
  echo "maximum-review-frames must be a nonnegative integer." >&2
  exit 64
fi

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

if [ "$REUSE_SOURCE_AS_REVIEW" = "1" ] && [ "$VIDEO" != "$OUTPUT_DIR/review.mp4" ]; then
  echo "TELIC_REUSE_SOURCE_AS_REVIEW requires the source video to be output-dir/review.mp4." >&2
  exit 64
fi

# Sequence previews keep the established 0.5 fps cadence. Full renders pass
# the quality policy's maximumFrames so we never decode/write hundreds of
# review JPEGs only for the quality gate to discard most of them.
#
# The contact-sheet tile grid must hold EVERY sampled frame. tile= emits a new
# image once the grid fills, and the sheet is written with -frames:v 1, so a
# grid smaller than the sample count silently truncates the diagnostic to the
# first N frames and discards the rest of the video. QC treats this sheet as
# whole-video progression evidence, so the grid is derived from the real sample
# count instead of being hardcoded.
REVIEW_FPS="0.5"
REVIEW_TILE_LAYOUT="5x4"
REVIEW_PLAN="$(node - "$OUTPUT_DIR/media-metadata.json" "$MAXIMUM_REVIEW_FRAMES" <<'NODE'
const fs = require('node:fs');
const [metadataPath, maximumRaw] = process.argv.slice(2);
const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));
const maximumFrames = Number(maximumRaw);
const streams = Array.isArray(metadata.streams) ? metadata.streams : [];
const video = streams.find((stream) => stream.codec_type === 'video');
const duration = Number(metadata.format?.duration ?? video?.duration);
if (!Number.isFinite(duration) || duration <= 0) throw new Error('Review media duration is invalid.');

let fps = 0.5;
if (maximumFrames > 0) {
  if (!Number.isInteger(maximumFrames) || maximumFrames < 3) throw new Error('maximum-review-frames must be at least 3 when enabled.');
  fps = Math.min(0.5, Math.max(3, maximumFrames - 1) / duration);
}

// Mirror the ffmpeg fps filter: it emits a frame per 1/fps window across the
// stream, so ceil rather than floor to avoid a short-by-one grid.
const sampled = Math.max(1, Math.ceil(duration * fps));
const columns = Math.max(1, Math.ceil(Math.sqrt(sampled)));
const rows = Math.max(1, Math.ceil(sampled / columns));
process.stdout.write(`${fps.toFixed(8).replace(/0+$/, '').replace(/\.$/, '')} ${columns}x${rows}`);
NODE
)"
REVIEW_FPS="${REVIEW_PLAN%% *}"
REVIEW_TILE_LAYOUT="${REVIEW_PLAN##* }"

if [ -z "$REVIEW_FPS" ] || [ -z "$REVIEW_TILE_LAYOUT" ]; then
  echo "Failed to resolve the review sampling plan." >&2
  exit 65
fi

if [ "$REUSE_SOURCE_AS_REVIEW" = "1" ]; then
  # The sequence render is already the canonical low-resolution review MP4, so
  # decode it once only for chronological stills/contact-sheet derivatives.
  run_media_tool ffmpeg \
    -hide_banner \
    -loglevel error \
    -y \
    -i "$VIDEO" \
    -filter_complex "[0:v]fps=fps=${REVIEW_FPS},split=outputs=2[keyframes][sheet];[keyframes]scale=w=360:h=-2[keyframes_out];[sheet]scale=w=210:h=-2,tile=layout=${REVIEW_TILE_LAYOUT}:padding=8:margin=8[sheet_out]" \
    -map "[keyframes_out]" \
    -q:v 3 \
    "$OUTPUT_DIR/keyframes/frame-%03d.jpg" \
    -map "[sheet_out]" \
    -frames:v 1 \
    -q:v 3 \
    "$OUTPUT_DIR/contact-sheet.jpg"
else
  # Full renders previously decoded the final MP4 once for review.mp4 and again
  # for review stills. Split one decoded video stream three ways so the private
  # review MP4, chronological frames, and contact sheet are all produced in one
  # pass. Preserve the established review-video codec/audio settings exactly.
  run_media_tool ffmpeg \
    -hide_banner \
    -loglevel error \
    -y \
    -i "$VIDEO" \
    -filter_complex "[0:v]split=outputs=3[review][chron][sheet];[review]scale=w=540:h=-2[review_out];[chron]fps=fps=${REVIEW_FPS},scale=w=360:h=-2[keyframes_out];[sheet]fps=fps=${REVIEW_FPS},scale=w=210:h=-2,tile=layout=${REVIEW_TILE_LAYOUT}:padding=8:margin=8[sheet_out]" \
    -map "[review_out]" \
    -map "0:a?" \
    -c:v libx264 \
    -preset veryfast \
    -crf 28 \
    -c:a aac \
    -b:a 96k \
    -movflags +faststart \
    "$OUTPUT_DIR/review.mp4" \
    -map "[keyframes_out]" \
    -q:v 3 \
    "$OUTPUT_DIR/keyframes/frame-%03d.jpg" \
    -map "[sheet_out]" \
    -frames:v 1 \
    -q:v 3 \
    "$OUTPUT_DIR/contact-sheet.jpg"
fi

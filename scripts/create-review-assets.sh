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

# Sequence previews keep the established 0.5 fps cadence. Full renders pass
# the quality policy's maximumFrames so we never decode/write hundreds of
# review JPEGs only for the quality gate to discard most of them.
REVIEW_FPS="0.5"
if [ "$MAXIMUM_REVIEW_FRAMES" -gt 0 ]; then
  REVIEW_FPS="$(node - "$OUTPUT_DIR/media-metadata.json" "$MAXIMUM_REVIEW_FRAMES" <<'NODE'
const fs = require('node:fs');
const [metadataPath, maximumRaw] = process.argv.slice(2);
const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));
const maximumFrames = Number(maximumRaw);
const streams = Array.isArray(metadata.streams) ? metadata.streams : [];
const video = streams.find((stream) => stream.codec_type === 'video');
const duration = Number(metadata.format?.duration ?? video?.duration);
if (!Number.isFinite(duration) || duration <= 0) throw new Error('Review media duration is invalid.');
if (!Number.isInteger(maximumFrames) || maximumFrames < 3) throw new Error('maximum-review-frames must be at least 3 when enabled.');
const fps = Math.min(0.5, Math.max(3, maximumFrames - 1) / duration);
process.stdout.write(fps.toFixed(8).replace(/0+$/, '').replace(/\.$/, ''));
NODE
)"
fi

# Decode once for the chronological review frames and compact contact sheet.
# The configured cadence is capped for full renders but remains unchanged for
# sequence previews, where the short window itself is the review target.
run_media_tool ffmpeg \
  -hide_banner \
  -loglevel error \
  -y \
  -i "$VIDEO" \
  -filter_complex "[0:v]fps=fps=${REVIEW_FPS},split=outputs=2[keyframes][sheet];[keyframes]scale=w=360:h=-2[keyframes_out];[sheet]scale=w=210:h=-2,tile=layout=5x4:padding=8:margin=8[sheet_out]" \
  -map "[keyframes_out]" \
  -q:v 3 \
  "$OUTPUT_DIR/keyframes/frame-%03d.jpg" \
  -map "[sheet_out]" \
  -frames:v 1 \
  -q:v 3 \
  "$OUTPUT_DIR/contact-sheet.jpg"

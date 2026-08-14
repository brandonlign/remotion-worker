#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: create-review-assets.sh <video.mp4> <output-dir>" >&2
  exit 64
fi

VIDEO="$1"
OUTPUT_DIR="$2"

if [ ! -s "$VIDEO" ]; then
  echo "Rendered video is missing or empty." >&2
  exit 66
fi

mkdir -p "$OUTPUT_DIR/keyframes"

ffprobe \
  -v error \
  -show_format \
  -show_streams \
  -of json \
  "$VIDEO" \
  > "$OUTPUT_DIR/media-metadata.json"

ffmpeg \
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

# Decode the preview only once for both still-image review products. Sampling at
# one frame every two seconds is shared before splitting into the original
# keyframe and contact-sheet scales, preserving the existing review cadence and
# image quality while avoiding a redundant full-video decode.
ffmpeg \
  -hide_banner \
  -loglevel error \
  -y \
  -i "$VIDEO" \
  -filter_complex "[0:v]fps=1/2,split=2[keyframes][sheet];[keyframes]scale=360:-2[keyframes_out];[sheet]scale=210:-2,tile=5x4:padding=8:margin=8[sheet_out]" \
  -map "[keyframes_out]" \
  -q:v 3 \
  "$OUTPUT_DIR/keyframes/frame-%03d.jpg" \
  -map "[sheet_out]" \
  -frames:v 1 \
  -q:v 3 \
  "$OUTPUT_DIR/contact-sheet.jpg"

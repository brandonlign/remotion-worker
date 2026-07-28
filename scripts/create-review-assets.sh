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

ffmpeg \
  -hide_banner \
  -loglevel error \
  -y \
  -i "$VIDEO" \
  -vf "fps=1/2,scale=360:-2" \
  -q:v 3 \
  "$OUTPUT_DIR/keyframes/frame-%03d.jpg"

ffmpeg \
  -hide_banner \
  -loglevel error \
  -y \
  -i "$VIDEO" \
  -vf "fps=1/2,scale=270:-2,tile=4x4:padding=8:margin=8" \
  -frames:v 1 \
  -q:v 3 \
  "$OUTPUT_DIR/contact-sheet.jpg"

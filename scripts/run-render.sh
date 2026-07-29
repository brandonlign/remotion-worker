#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: run-render.sh <request.json> <private-source-dir> <output-dir>" >&2
  exit 64
fi

REQUEST_FILE="$1"
SOURCE_DIR="$2"
OUTPUT_DIR="$3"

if [ ! -f "$REQUEST_FILE" ] || [ ! -d "$SOURCE_DIR" ]; then
  echo "Drive probe inputs are missing." >&2
  exit 66
fi

mkdir -p "$OUTPUT_DIR"
printf 'Temporary private Drive upload probe.\n' > "$OUTPUT_DIR/drive-probe.txt"
printf '{"status":"drive-probe","jobId":"%s"}\n' "${JOB_ID:-unknown}" > "$OUTPUT_DIR/status.json"

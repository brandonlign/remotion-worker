#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: run-finalize.sh <finalize-request.json> <private-source-dir> <output-dir>" >&2
  exit 64
fi

REQUEST_FILE="$1"
SOURCE_DIR="$2"
OUTPUT_DIR="$3"
WORKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

read_request_field() {
  node - "$REQUEST_FILE" "$1" <<'NODE'
const fs = require("node:fs");
const [file, key] = process.argv.slice(2);
const request = JSON.parse(fs.readFileSync(file, "utf8"));
const value = request[key];
if (value === undefined || value === null || value === "") throw new Error(`Missing finalize request field: ${key}`);
process.stdout.write(String(value));
NODE
}

JOB_ID="$(read_request_field jobId)"
SOURCE_SHA="$(read_request_field sourceSha)"
RENDER_SOURCE_SHA="$(read_request_field renderSourceSha)"
REUSE_REVISION="$(read_request_field reuseRevision)"

if [ ! -d "$SOURCE_DIR" ] || [ ! -d "$OUTPUT_DIR" ]; then
  echo "Finalize source or restored render directory is missing." >&2
  exit 66
fi

node "$WORKER_ROOT/scripts/validate-youtube-metadata.mjs" \
  "$SOURCE_DIR/automation/current/youtube.json" \
  "$JOB_ID"

node - "$OUTPUT_DIR/status.json" "$SOURCE_DIR/automation/current/job.json" "$JOB_ID" "$SOURCE_SHA" "$RENDER_SOURCE_SHA" "$REUSE_REVISION" <<'NODE'
const fs = require("node:fs");
const path = require("node:path");
const [statusPath, jobPath, jobId, sourceSha, renderSourceSha, reuseRevision] = process.argv.slice(2);
const status = JSON.parse(fs.readFileSync(statusPath, "utf8"));
const job = JSON.parse(fs.readFileSync(jobPath, "utf8"));
if (status.status !== "complete" || status.jobId !== jobId || status.sourceSha !== renderSourceSha) {
  throw new Error("Restored render provenance does not match the finalize request.");
}
if (job.jobId && job.jobId !== jobId) throw new Error("Private job metadata does not match the finalize request.");
const renderedVideo = path.join(path.dirname(statusPath), `${status.outputName}.mp4`);
if (!fs.existsSync(renderedVideo) || fs.statSync(renderedVideo).size <= 0) throw new Error("Restored rendered video is missing.");
if (job.format === "long") {
  const thumbnail = path.join(path.dirname(statusPath), "thumbnail.png");
  if (!fs.existsSync(thumbnail) || fs.statSync(thumbnail).size <= 0) throw new Error("Restored long-form thumbnail is missing.");
}
const updated = {
  ...status,
  sourceSha,
  renderSourceSha,
  reusedRender: true,
  reusedFromRevision: Number(reuseRevision),
  finalizedAt: new Date().toISOString(),
};
fs.writeFileSync(statusPath, `${JSON.stringify(updated, null, 2)}\n`);
NODE

node "$WORKER_ROOT/scripts/create-controller-handoff.mjs" \
  "$OUTPUT_DIR" \
  "$SOURCE_DIR/automation/current/youtube.json" \
  "$JOB_ID" \
  "$SOURCE_SHA"

cat > "$OUTPUT_DIR/reuse.json" <<EOF
{
  "jobId": "$JOB_ID",
  "sourceSha": "$SOURCE_SHA",
  "renderSourceSha": "$RENDER_SOURCE_SHA",
  "reuseRevision": $REUSE_REVISION,
  "mode": "metadata-only-finalize"
}
EOF

rm -f "$OUTPUT_DIR/exit-code.txt"
printf '0\n' > "$OUTPUT_DIR/finalize-exit-code.txt"
echo "Finalized an existing rendered package with current metadata; no Remotion render was executed."

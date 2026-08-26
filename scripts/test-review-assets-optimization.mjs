#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";

const script = fs.readFileSync(new URL("./create-review-assets.sh", import.meta.url), "utf8");

assert.equal((script.match(/^  run_media_tool ffmpeg \\/gm) ?? []).length, 2, "the two mutually exclusive review paths should each use one ffmpeg invocation");
assert.equal((script.match(/^run_media_tool ffprobe \\/gm) ?? []).length, 1, "review packaging should use one ffprobe invocation");
assert.doesNotMatch(script, /^ffmpeg \\/m, "review packaging should keep the media-tool wrapper");
assert.doesNotMatch(script, /^ffprobe \\/m, "review packaging should keep the media-tool wrapper");
assert.match(script, /TELIC_REMOTION_BIN/);
assert.match(script, /TELIC_REUSE_SOURCE_AS_REVIEW/);
assert.match(script, /if \[ "\$REUSE_SOURCE_AS_REVIEW" = "1" \] && \[ "\$VIDEO" != "\$OUTPUT_DIR\/review\.mp4" \]/);
assert.match(script, /if \[ "\$REUSE_SOURCE_AS_REVIEW" = "1" \]; then/);
assert.match(script, /"\$REMOTION_BIN" "\$tool" "\$@"/);
assert.match(script, /"\$tool" "\$@"/);

// Full renders decode once and split that one decoded stream into the review
// MP4, chronological stills, and contact sheet while retaining review audio.
assert.match(script, /split=outputs=3\[review\]\[chron\]\[sheet\]/);
assert.match(script, /\[review\]scale=w=540:h=-2\[review_out\]/);
assert.match(script, /\[chron\]fps=fps=\$\{REVIEW_FPS\},scale=w=360:h=-2\[keyframes_out\]/);
assert.match(script, /\[sheet\]fps=fps=\$\{REVIEW_FPS\},scale=w=210:h=-2,tile=layout=5x4:padding=8:margin=8\[sheet_out\]/);
assert.match(script, /-map "\[review_out\]"/);
assert.match(script, /-map "0:a\?"/);
assert.match(script, /-preset veryfast/);
assert.match(script, /-crf 28/);
assert.match(script, /-b:a 96k/);
assert.match(script, /"\$OUTPUT_DIR\/review\.mp4" \\\n    -map "\[keyframes_out\]"/);

// Sequence previews retain their already-rendered review.mp4 and perform only
// the derivative-still decode.
assert.match(script, /fps=fps=\$\{REVIEW_FPS\},split=outputs=2\[keyframes\]\[sheet\]/);
assert.match(script, /\[keyframes\]scale=w=360:h=-2\[keyframes_out\]/);
assert.match(script, /\[sheet\]scale=w=210:h=-2,tile=layout=5x4:padding=8:margin=8\[sheet_out\]/);

// Sequence previews retain the established 0.5 fps cadence, while full renders
// can cap extraction to the maximum number of review frames the quality policy
// can actually consume.
assert.match(script, /MAXIMUM_REVIEW_FRAMES="\$\{3:-0\}"/);
assert.match(script, /REVIEW_FPS="0\.5"/);
assert.match(script, /maximumFrames - 1/);
assert.match(script, /Math\.min\(0\.5,/);
assert.match(script, /-map "\[keyframes_out\]"/);
assert.match(script, /keyframes\/frame-%03d\.jpg/);
assert.match(script, /-map "\[sheet_out\]"/);
assert.match(script, /-frames:v 1/);
assert.match(script, /contact-sheet\.jpg/);

const fullRender = fs.readFileSync(new URL("./run-render.sh", import.meta.url), "utf8");
assert.match(fullRender, /REVIEW_FRAME_LIMIT=/);
assert.match(fullRender, /config\?\.longForm\?\.quality\?\.maximumFrames/);
assert.match(fullRender, /config\?\.quality\?\.maximumFrames/);
assert.match(fullRender, /create-review-assets\.sh" "\$FINAL_VIDEO" "\$OUTPUT_DIR" "\$REVIEW_FRAME_LIMIT"/);
assert.doesNotMatch(fullRender, /node "\$WORKER_ROOT\/scripts\/create-review-moments\.mjs"/);
assert.match(fullRender, /Exact semantic still extraction remains available/);

const semanticMoments = fs.readFileSync(new URL("./create-review-moments.mjs", import.meta.url), "utf8");
assert.match(semanticMoments, /resolveReviewMoments/);
assert.match(semanticMoments, /Usage: create-review-moments\.mjs/);

const qualityGate = fs.readFileSync(new URL("./deterministic-quality-gate.mjs", import.meta.url), "utf8");
assert.match(qualityGate, /reviewFrameFps/);
assert.match(qualityGate, /Math\.min\(0\.5, Math\.max\(3, maximumFrames - 1\) \/ durationSeconds\)/);
assert.match(qualityGate, /timestampSeconds: Number\(\(\(frameNumber - 1\) \/ reviewFrameFps\)\.toFixed\(3\)\)/);
assert.doesNotMatch(qualityGate, /\(frameNumber - 1\) \* 2/);

const sequence = fs.readFileSync(new URL("./run-render-sequence.sh", import.meta.url), "utf8");
const longPreview = fs.readFileSync(new URL("./run-long-preview.sh", import.meta.url), "utf8");
assert.match(sequence, /PREVIEW_VIDEO="\$OUTPUT_DIR\/review\.mp4"/);
assert.doesNotMatch(sequence, /sequence-preview\.mp4/);
assert.match(sequence, /TELIC_REUSE_SOURCE_AS_REVIEW=1/);
assert.doesNotMatch(sequence, /TELIC_REMOTION_BIN=/, "sequence review derivatives must not use Remotion's minimal FFmpeg bundle");
assert.match(sequence, /create-review-assets\.sh/);
assert.match(longPreview, /PREVIEW_VIDEO="\$OUTPUT_DIR\/review\.mp4"/);
assert.match(longPreview, /PREVIEW_CRF=30/);
assert.match(longPreview, /PREVIEW_SCALE="0\.5"/);
assert.match(longPreview, /TELIC_REUSE_SOURCE_AS_REVIEW=1/);
assert.match(longPreview, /upload-preview-drive|canonical:false|canonical: false/);

const bootstrap = fs.readFileSync(new URL("./ensure-public-rclone.sh", import.meta.url), "utf8");
assert.match(bootstrap, /RCLONE_VERSION="1\.75\.0"/);
assert.match(bootstrap, /aa2804e08f48250e71009c727124b6341cd0288465804a9a09d14663cabafbaa/);
assert.match(bootstrap, /d0ad88ba4c8e285b7c9efa591e0ab643280a91741e13c27f3a9c0957ccfa5203/);
assert.match(bootstrap, /sha256sum --check --status/);
assert.match(bootstrap, /sudo apt-get install -y -qq rclone/);

const workflow = fs.readFileSync(new URL("../.github/workflows/render.yml", import.meta.url), "utf8");
assert.match(workflow, /name: Cache public rclone binary/);
assert.match(workflow, /key: telic-rclone-v1\.75\.0-\$\{\{ runner\.os \}\}-\$\{\{ runner\.arch \}\}/);
assert.match(workflow, /source scripts\/ensure-public-rclone\.sh/);
assert.match(workflow, /name: Cache public full FFmpeg tools/);
assert.match(workflow, /key: telic-ffmpeg-n8\.1-btbn-20260813-\$\{\{ runner\.os \}\}-\$\{\{ runner\.arch \}\}-py3/);
assert.match(workflow, /steps\.request\.outputs\.mode == 'voice-prep' \|\|\n          steps\.request\.outputs\.mode == 'render-sequence' \|\|\n          steps\.request\.outputs\.mode == 'long-preview' \|\|/);
assert.match(workflow, /steps\.request\.outputs\.mode == 'render' && steps\.render_dedupe\.outputs\.cache-hit != 'true'/);
assert.match(workflow, /if \[\[ "\$RENDER_MODE" == "voice-prep" \|\| "\$RENDER_MODE" == "render-sequence" \|\| "\$RENDER_MODE" == "long-preview" \|\| "\$RENDER_MODE" == "render" \]\]; then/);
assert.match(workflow, /source scripts\/ensure-public-ffmpeg\.sh/);
assert.doesNotMatch(workflow, /Remotion dependency after npm ci/);
assert.doesNotMatch(workflow, /packages\+=\(rclone\)/);

console.log("Review assets use one full-render decode, one complete long-form preview, semantic stills are targeted-only, and all render stages share the pinned public FFmpeg path.");

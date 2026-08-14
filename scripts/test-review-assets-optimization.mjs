#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";

const script = fs.readFileSync(new URL("./create-review-assets.sh", import.meta.url), "utf8");

const ffmpegInvocations = script.match(/^run_media_tool ffmpeg \\/gm) ?? [];
assert.equal(ffmpegInvocations.length, 2, "review packaging should use exactly two ffmpeg invocations: review MP4 + shared stills decode");
assert.equal((script.match(/^run_media_tool ffprobe \\/gm) ?? []).length, 1, "review packaging should use one ffprobe invocation");
assert.doesNotMatch(script, /^ffmpeg \\/m, "preview review packaging must not require system ffmpeg directly");
assert.doesNotMatch(script, /^ffprobe \\/m, "preview review packaging must not require system ffprobe directly");
assert.match(script, /TELIC_REMOTION_BIN/);
assert.match(script, /"\$REMOTION_BIN" "\$tool" "\$@"/);
assert.match(script, /"\$tool" "\$@"/);

assert.match(script, /-vf "scale=540:-2"/);
assert.match(script, /-preset veryfast/);
assert.match(script, /-crf 28/);
assert.match(script, /-b:a 96k/);

assert.match(script, /fps=1\/2,split=2\[keyframes\]\[sheet\]/);
assert.match(script, /\[keyframes\]scale=360:-2\[keyframes_out\]/);
assert.match(script, /\[sheet\]scale=210:-2,tile=5x4:padding=8:margin=8\[sheet_out\]/);
assert.match(script, /-map "\[keyframes_out\]"/);
assert.match(script, /keyframes\/frame-%03d\.jpg/);
assert.match(script, /-map "\[sheet_out\]"/);
assert.match(script, /-frames:v 1/);
assert.match(script, /contact-sheet\.jpg/);

const sequence = fs.readFileSync(new URL("./run-render-sequence.sh", import.meta.url), "utf8");
assert.match(sequence, /TELIC_REMOTION_BIN="\$REMOTION_BIN"/);
assert.match(sequence, /create-review-assets\.sh/);

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
assert.match(workflow, /RENDER_MODE" != "render-sequence"/);
assert.doesNotMatch(workflow, /packages\+=\(rclone\)/);

console.log("Review assets preserve outputs while render-sequence reuses pinned Remotion media tools and public rclone bootstrap.");

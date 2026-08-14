#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";

const script = fs.readFileSync(new URL("./create-review-assets.sh", import.meta.url), "utf8");

const ffmpegInvocations = script.match(/^ffmpeg \\/gm) ?? [];
assert.equal(ffmpegInvocations.length, 2, "review packaging should use exactly two ffmpeg invocations: review MP4 + shared stills decode");

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

console.log("Review asset generation shares one still-image decode while preserving outputs.");

#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import {MAX_SEQUENCE_INDEX, resolveSequencePreview} from "./sequence-preview.mjs";

const plan = {
  sequences: [
    {id: "one", startFrame: 0, endFrame: 300},
    {id: "two", startFrame: 280, endFrame: 650},
  ],
};

assert.deepEqual(resolveSequencePreview(plan, 0), {
  sequenceIndex: 0,
  startFrame: 0,
  endFrame: 300,
  renderEndFrame: 299,
  frameCount: 300,
});
assert.deepEqual(resolveSequencePreview(plan, 1), {
  sequenceIndex: 1,
  startFrame: 280,
  endFrame: 650,
  renderEndFrame: 649,
  frameCount: 370,
});
assert.equal(MAX_SEQUENCE_INDEX, 39);
assert.throws(() => resolveSequencePreview(plan, 2), /outside/);
assert.throws(() => resolveSequencePreview(plan, -1), /0 through 39/);
assert.throws(() => resolveSequencePreview(plan, 40), /0 through 39/);
assert.throws(() => resolveSequencePreview({sequences: [{startFrame: 5, endFrame: 5}]}, 0), /invalid frame range/);

const many = {sequences: Array.from({length: 40}, (_, index) => ({startFrame: index * 900, endFrame: (index + 1) * 900}))};
assert.equal(resolveSequencePreview(many, 39).sequenceIndex, 39);

const sequenceRender = fs.readFileSync(new URL("./run-render-sequence.sh", import.meta.url), "utf8");
const fullRender = fs.readFileSync(new URL("./run-render.sh", import.meta.url), "utf8");
assert.match(sequenceRender, /PREVIEW_CRF=28/);
assert.match(sequenceRender, /PREVIEW_SCALE="0\.6666666667"/);
assert.match(sequenceRender, /--crf="\$PREVIEW_CRF"/);
assert.match(sequenceRender, /--scale="\$PREVIEW_SCALE"/);
assert.doesNotMatch(fullRender, /PREVIEW_CRF|PREVIEW_SCALE/);

console.log("Dynamic long-form sequence preview range and quality tests passed.");

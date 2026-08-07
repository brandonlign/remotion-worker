#!/usr/bin/env node

import assert from "node:assert/strict";
import {resolveSequencePreview} from "./sequence-preview.mjs";

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
assert.throws(() => resolveSequencePreview(plan, 2), /outside/);
assert.throws(() => resolveSequencePreview(plan, -1), /0 through 13/);
assert.throws(() => resolveSequencePreview({sequences: [{startFrame: 5, endFrame: 5}]}, 0), /invalid frame range/);

console.log("Long-form sequence preview range tests passed.");

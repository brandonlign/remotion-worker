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
assert.match(sequenceRender, /PREVIEW_CHECK_COMMAND="npx eslint src && npx tsc --noEmit"/);
assert.match(sequenceRender, /bash -o pipefail -c "\$PREVIEW_CHECK_COMMAND"/);
assert.doesNotMatch(sequenceRender, /bash -o pipefail -c "\$CHECK_COMMAND"/);
assert.match(fullRender, /FOCUSED_SOURCE_CHECK="\$CHECK_COMMAND"/);
assert.match(fullRender, /bash -o pipefail -c "\$FOCUSED_SOURCE_CHECK"/);
assert.match(fullRender, /FINAL_CONTRACT_COMMAND="npm run long:contract:test"/);
assert.match(fullRender, /FINAL_CONTRACT_COMMAND="npm run custom:contract:test"/);
assert.doesNotMatch(fullRender, /bash -o pipefail -c "\$CHECK_COMMAND"/);
assert.doesNotMatch(fullRender, /PREVIEW_CRF|PREVIEW_SCALE|PREVIEW_CHECK_COMMAND/);

// The duplicate audio hash may be skipped only in the exact render workflow,
// where the sequence step is already gated on successful audio restoration.
assert.match(sequenceRender, /\$PREPARE_COMMAND" = "npm run long:prepare-window"/);
assert.match(sequenceRender, /\$\{GITHUB_ACTIONS:-\}" = "true"/);
assert.match(sequenceRender, /\$\{GITHUB_WORKFLOW:-\}" = "Render private Remotion source"/);
assert.match(sequenceRender, /node scripts\/autopilot\/prepare-long-window\.mjs/);
// Direct/manual/legacy invocation must retain the original prepare command,
// which includes the long-form voiceover integrity hash gate.
assert.match(sequenceRender, /bash -o pipefail -c "\$PREPARE_COMMAND"/);

console.log("Dynamic long-form sequence preview range, quality, focused-check, and audio-fast-path tests passed.");

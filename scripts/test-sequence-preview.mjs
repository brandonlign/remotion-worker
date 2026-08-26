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
const longPreview = fs.readFileSync(new URL("./run-long-preview.sh", import.meta.url), "utf8");
const fullRender = fs.readFileSync(new URL("./run-render.sh", import.meta.url), "utf8");
assert.match(sequenceRender, /PREVIEW_CRF=28/);
assert.match(sequenceRender, /PREVIEW_SCALE="0\.5"/);
assert.match(sequenceRender, /SEQUENCE_REVIEW_FRAME_LIMIT=20/);
assert.match(sequenceRender, /--crf="\$PREVIEW_CRF"/);
assert.match(sequenceRender, /--scale="\$PREVIEW_SCALE"/);
assert.match(sequenceRender, /create-review-assets\.sh" \\\n    "\$PREVIEW_VIDEO" "\$OUTPUT_DIR" "\$SEQUENCE_REVIEW_FRAME_LIMIT"/);
assert.match(sequenceRender, /PREVIEW_CHECK_COMMAND="npx eslint src && npx tsc --noEmit"/);
assert.match(sequenceRender, /bash -o pipefail -c "\$PREVIEW_CHECK_COMMAND"/);
assert.doesNotMatch(sequenceRender, /bash -o pipefail -c "\$CHECK_COMMAND"/);
assert.match(fullRender, /FOCUSED_SOURCE_CHECK="npx eslint src && npx tsc --noEmit"/);
assert.match(fullRender, /FINAL_CONTRACT_COMMAND="npm run long:contract:test"/);
assert.match(fullRender, /FINAL_CONTRACT_COMMAND="npm run custom:contract:test"/);
assert.doesNotMatch(fullRender, /bash -o pipefail -c "\$CHECK_COMMAND"/);
assert.doesNotMatch(fullRender, /PREVIEW_CRF|PREVIEW_SCALE|PREVIEW_CHECK_COMMAND/);

// Long sequence preparation is worker-owned. The private config is validated
// as one of the known-safe long commands, but it does not choose preview mode.
assert.match(sequenceRender, /CONFIGURED_PREPARE_COMMAND/);
assert.match(sequenceRender, /PREPARE_COMMAND="npm run long:prepare-window"/);
assert.match(sequenceRender, /\$\{GITHUB_ACTIONS:-\}" = "true"/);
assert.match(sequenceRender, /\$\{GITHUB_WORKFLOW:-\}" = "Render private Remotion source"/);
assert.match(sequenceRender, /node scripts\/autopilot\/prepare-long-window\.mjs/);
assert.match(sequenceRender, /bash -o pipefail -c "\$PREPARE_COMMAND"/);

// Complete long-form previews are the single visual gate before the full
// render. They render the assembled composition once at review quality and
// deliver only the non-canonical review package.
assert.match(longPreview, /PREVIEW_CRF=30/);
assert.match(longPreview, /PREVIEW_SCALE="0\.5"/);
assert.match(longPreview, /PREPARE_COMMAND="npm run long:prepare"/);
assert.match(longPreview, /npm run long:contract:test/);
assert.match(longPreview, /TELIC_REUSE_SOURCE_AS_REVIEW=1/);
assert.match(longPreview, /status: "long-preview-complete"/);
assert.doesNotMatch(longPreview, /run-render\.sh/);

console.log("Legacy sequence preview compatibility and single complete long-form preview contracts passed.");

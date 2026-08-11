#!/usr/bin/env node
import assert from "node:assert/strict";
import {validatePrivateRenderContract} from "./validate-private-render-contract.mjs";

const sequence = {
  mode: "render-sequence",
  jobFormat: "long",
  compositionId: "CustomLongForm",
  thumbnailCompositionId: "",
  prepareCommand: "npm run long:prepare-window",
  checkCommand: "npm run lint",
};
assert.equal(validatePrivateRenderContract(sequence), true);
assert.throws(() => validatePrivateRenderContract({...sequence, jobFormat: "short"}), /long-form source package/);
assert.throws(() => validatePrivateRenderContract({...sequence, compositionId: "AutoShort"}), /wrong composition/);
assert.throws(() => validatePrivateRenderContract({...sequence, prepareCommand: "npm run autopilot:prepare"}), /wrong prepare command/);
assert.throws(() => validatePrivateRenderContract({...sequence, checkCommand: "true"}), /wrong check command/);

const fullLong = {
  mode: "render",
  jobFormat: "long",
  compositionId: "CustomLongForm",
  thumbnailCompositionId: "LongFormThumbnail",
  prepareCommand: "npm run long:prepare",
  checkCommand: "npm run lint",
};
assert.equal(validatePrivateRenderContract(fullLong), true);
assert.throws(() => validatePrivateRenderContract({...fullLong, compositionId: "AutoShort"}), /wrong composition/);
assert.throws(() => validatePrivateRenderContract({...fullLong, thumbnailCompositionId: ""}), /wrong thumbnail composition/);
assert.throws(() => validatePrivateRenderContract({...fullLong, prepareCommand: "npm run long:prepare-window"}), /wrong prepare command/);

// Ordinary/legacy Short rendering keeps its existing source contract. The new
// validator only makes long-form requests fail closed.
assert.equal(validatePrivateRenderContract({
  mode: "render",
  jobFormat: "short",
  compositionId: "AutoShort",
  thumbnailCompositionId: "",
  prepareCommand: "npm run autopilot:prepare",
  checkCommand: "npm run lint",
}), true);

console.log("Private long-form render contract tests passed.");

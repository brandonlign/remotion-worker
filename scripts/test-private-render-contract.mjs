#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
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
// Long private source may be frozen while it still names either canonical long
// preparation command. The worker owns which one executes for each request mode.
assert.equal(validatePrivateRenderContract({...sequence, prepareCommand: "npm run long:prepare"}), true);
assert.throws(() => validatePrivateRenderContract({...sequence, jobFormat: "short"}), /long-form source package/);
assert.throws(() => validatePrivateRenderContract({...sequence, compositionId: "AutoShort"}), /wrong composition/);
assert.throws(() => validatePrivateRenderContract({...sequence, prepareCommand: "npm run autopilot:prepare"}), /unsupported prepare command/);
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
assert.equal(validatePrivateRenderContract({...fullLong, prepareCommand: "npm run long:prepare-window"}), true);
assert.throws(() => validatePrivateRenderContract({...fullLong, compositionId: "AutoShort"}), /wrong composition/);
assert.throws(() => validatePrivateRenderContract({...fullLong, thumbnailCompositionId: ""}), /wrong thumbnail composition/);
assert.throws(() => validatePrivateRenderContract({...fullLong, prepareCommand: "npm run autopilot:prepare"}), /unsupported prepare command/);

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

const sequenceScript = fs.readFileSync(new URL("./run-render-sequence.sh", import.meta.url), "utf8");
const finalScript = fs.readFileSync(new URL("./run-render.sh", import.meta.url), "utf8");
assert.match(sequenceScript, /PREPARE_COMMAND="npm run long:prepare-window"/);
assert.match(sequenceScript, /CONFIGURED_PREPARE_COMMAND/);
assert.match(finalScript, /if \[ "\$JOB_FORMAT" = "long" \]; then\n  PREPARE_COMMAND="npm run long:prepare"/);
assert.match(finalScript, /CONFIGURED_PREPARE_COMMAND/);

console.log("Private long-form worker-owned prepare contract tests passed.");

#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

const script = fs.readFileSync(new URL("./run-render.sh", import.meta.url), "utf8");

assert.match(script, /FOCUSED_SOURCE_CHECK="npx eslint src\/compositions\/CurrentCustomShort && npx tsc --noEmit .*CurrentCustomShort\/Composition\.tsx .*CurrentCustomShort\/qrEvidence\.ts .*CurrentCustomShort\/generated\.ts"/);
assert.match(script, /if \[ "\$PREPARE_COMMAND" = "npm run long:prepare" \]; then/);
assert.match(script, /FINAL_CONTRACT_COMMAND="npm run long:contract:test"/);
assert.match(script, /FINAL_CONTRACT_COMMAND="npm run custom:contract:test"/);
assert.match(script, /bash -o pipefail -c "\$FOCUSED_SOURCE_CHECK"/);
assert.match(script, /bash -o pipefail -c "\$FINAL_CONTRACT_COMMAND"/);
assert.doesNotMatch(
  script,
  /bash -o pipefail -c "\$CHECK_COMMAND"/,
  "final renders must not execute the generic infrastructure-heavy checkCommand",
);

// Preserve the actual render and output-quality path.
assert.match(script, /"\$REMOTION_BIN" render/);
assert.match(script, /--codec=h264/);
assert.match(script, /--crf="\$CRF"/);
assert.match(script, /create-review-assets\.sh/);

console.log("Final renders use focused format-aware checks while preserving render quality settings.");

#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

const script = fs.readFileSync(new URL("./run-render.sh", import.meta.url), "utf8");

assert.match(script, /FOCUSED_SOURCE_CHECK="npx eslint src && npx tsc --noEmit"/);
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

// Preserve the actual render and output-quality path while bounding review-only
// derivatives to the configured number the quality gate can consume.
assert.match(script, /"\$REMOTION_BIN" render/);
assert.match(script, /--codec=h264/);
assert.match(script, /--crf="\$CRF"/);
assert.match(script, /REVIEW_FRAME_LIMIT=/);
assert.match(script, /create-review-assets\.sh" "\$FINAL_VIDEO" "\$OUTPUT_DIR" "\$REVIEW_FRAME_LIMIT"/);

console.log("Final renders use focused format-aware checks and bounded review derivatives while preserving render quality settings.");

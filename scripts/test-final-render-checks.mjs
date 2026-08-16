#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

const script = fs.readFileSync(new URL("./run-render.sh", import.meta.url), "utf8");
const workflow = fs.readFileSync(new URL("../.github/workflows/render.yml", import.meta.url), "utf8");

assert.match(script, /FOCUSED_SOURCE_CHECK="npx eslint src && npx tsc --noEmit"/);
assert.match(script, /CONFIGURED_PREPARE_COMMAND/);
assert.match(script, /if \[ "\$JOB_FORMAT" = "long" \]; then\n  PREPARE_COMMAND="npm run long:prepare"/);
assert.match(script, /FINAL_CONTRACT_COMMAND="npm run long:contract:test"/);
assert.match(script, /FINAL_CONTRACT_COMMAND="npm run custom:contract:test"/);
assert.match(script, /bash -o pipefail -c "\$FOCUSED_SOURCE_CHECK"/);
assert.match(script, /bash -o pipefail -c "\$FINAL_CONTRACT_COMMAND"/);
assert.doesNotMatch(script, /bash -o pipefail -c "\$CHECK_COMMAND"/);

const metadataPreflight = script.indexOf('validate-youtube-metadata.mjs');
const install = script.indexOf('bash -o pipefail -c "$INSTALL_COMMAND"');
const render = script.indexOf('"$REMOTION_BIN" render');
assert.ok(metadataPreflight >= 0, "final render must validate YouTube metadata");
assert.ok(metadataPreflight < install, "metadata preflight must run before package install/asset preparation");
assert.ok(metadataPreflight < render, "metadata preflight must run before expensive Remotion rendering");

assert.match(script, /"\$REMOTION_BIN" render/);
assert.match(script, /--codec=h264/);
assert.match(script, /--crf="\$CRF"/);
assert.match(script, /REVIEW_FRAME_LIMIT=/);
assert.match(script, /create-review-assets\.sh" "\$FINAL_VIDEO" "\$OUTPUT_DIR" "\$REVIEW_FRAME_LIMIT"/);

const qualityGate = fs.readFileSync(new URL("./deterministic-quality-gate.mjs", import.meta.url), "utf8");
assert.match(qualityGate, /const mediaAnalysis = await runCapture\("ffmpeg"/);
assert.match(qualityGate, /blackdetect=.*freezedetect=/);
assert.match(qualityGate, /silencedetect=/);
assert.match(qualityGate, /extractDurations\(mediaAnalysis\.stderr, "black_duration"\)/);
assert.match(qualityGate, /extractDurations\(mediaAnalysis\.stderr, "silence_duration"\)/);
assert.match(qualityGate, /extractDurations\(mediaAnalysis\.stderr, "freeze_duration"\)/);
assert.doesNotMatch(qualityGate, /const \[black, silence, freeze\] = await Promise\.all/);

assert.match(workflow, /echo "ok=true" >> "\$GITHUB_OUTPUT"/);
assert.match(workflow, /steps\.audio_restore\.outputs\.ok == 'true'/);
assert.match(workflow, /steps\.render\.outputs\.ok == 'true'/);
assert.match(workflow, /steps\.quality\.outputs\.ok == 'true'/);
assert.match(workflow, /Deliver successful private package to Google Drive/);
assert.match(workflow, /Deliver failed-attempt diagnostics privately/);
assert.doesNotMatch(workflow, /steps\.(?:audio_restore|render|quality|sequence|voice)\.outputs\.exit_code == '0'/);

console.log("Final renders preflight metadata before expensive work and retain explicit success-only Drive authority.");

#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

const script = fs.readFileSync(new URL("./run-render.sh", import.meta.url), "utf8");
const sequenceScript = fs.readFileSync(new URL("./run-render-sequence.sh", import.meta.url), "utf8");
const voiceScript = fs.readFileSync(new URL("./run-voice-prep.sh", import.meta.url), "utf8");
const stageCommon = fs.readFileSync(new URL("./lib/stage-common.sh", import.meta.url), "utf8");
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
const dependencySetup = script.indexOf('install_private_dependencies "$INSTALL_COMMAND"');
const render = script.indexOf('"$REMOTION_BIN" render');
assert.ok(metadataPreflight >= 0, "final render must validate YouTube metadata");
assert.ok(dependencySetup >= 0, "final render must use the verified dependency setup helper");
assert.ok(metadataPreflight < dependencySetup, "metadata preflight must run before dependency setup/asset preparation");
assert.ok(metadataPreflight < render, "metadata preflight must run before expensive Remotion rendering");

assert.match(sequenceScript, /install_private_dependencies "\$INSTALL_COMMAND"/);
assert.match(voiceScript, /install_private_dependencies "\$INSTALL_COMMAND"/);
assert.match(stageCommon, /install_private_dependencies\(\)/);
assert.match(stageCommon, /\.telic-package-lock-sha256/);
assert.match(stageCommon, /sha256sum "\$lockfile"/);
assert.match(stageCommon, /cached_sha.*lock_sha/s);
assert.match(stageCommon, /\[ -x "\$node_modules\/\.bin\/remotion" \]/);
assert.match(stageCommon, /falling back to the configured clean install/);
assert.match(stageCommon, /bash -o pipefail -c "\$install_command"/);
assert.match(stageCommon, /GITHUB_WORKFLOW:-.*Render private Remotion source/s);
assert.match(stageCommon, /Deferring checksums to the workflow's final package pass/);
assert.match(workflow, /- name: Refresh private checksums/);
assert.match(workflow, /find "\$RUNNER_TEMP\/render-result" -type f ! -name checksums\.txt/);

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

assert.match(workflow, /Cache verified installed Node dependencies/);
assert.match(workflow, /path: private-source\/node_modules/);
assert.match(workflow, /telic-remotion-node-modules-v1-\$\{\{ runner\.os \}\}-\$\{\{ runner\.arch \}\}-node22-\$\{\{ hashFiles\('private-source\/package-lock\.json'\) \}\}/);
assert.match(workflow, /echo "ok=true" >> "\$GITHUB_OUTPUT"/);
assert.match(workflow, /steps\.audio_restore\.outputs\.ok == 'true'/);
assert.match(workflow, /steps\.render\.outputs\.ok == 'true'/);
assert.match(workflow, /steps\.quality\.outputs\.ok == 'true'/);
assert.match(workflow, /Deliver successful private package to Google Drive/);
assert.match(workflow, /Deliver failed-attempt diagnostics privately/);
assert.doesNotMatch(workflow, /steps\.(?:audio_restore|render|quality|sequence|voice)\.outputs\.exit_code == '0'/);

console.log("Final renders reuse only lockfile-verified cached dependencies, defer duplicate Actions checksum work, preflight metadata before expensive work, and retain explicit success-only Drive authority.");

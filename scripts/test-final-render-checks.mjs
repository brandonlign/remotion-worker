#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

const script = fs.readFileSync(new URL("./run-render.sh", import.meta.url), "utf8");
const sequenceScript = fs.readFileSync(new URL("./run-render-sequence.sh", import.meta.url), "utf8");
const voiceScript = fs.readFileSync(new URL("./run-voice-prep.sh", import.meta.url), "utf8");
const stageCommon = fs.readFileSync(new URL("./lib/stage-common.sh", import.meta.url), "utf8");
const workflow = fs.readFileSync(new URL("../.github/workflows/render.yml", import.meta.url), "utf8");

assert.match(script, /CONFIGURED_PREPARE_COMMAND/);
assert.match(script, /if \[ "\$JOB_FORMAT" = "long" \]; then\n  PREPARE_COMMAND="npm run long:prepare"/);
assert.match(script, /FINAL_VALIDATION_COMMAND="npx eslint src && npx tsc --noEmit && npm run custom:contract:test"/);
assert.match(script, /FINAL_VALIDATION_COMMAND="npm run long:preflight"/);
assert.match(script, /bash -o pipefail -c "\$FINAL_VALIDATION_COMMAND"/);
assert.doesNotMatch(script, /FOCUSED_SOURCE_CHECK=/);
assert.doesNotMatch(script, /FINAL_CONTRACT_COMMAND=/);
assert.doesNotMatch(script, /bash -o pipefail -c "\$CHECK_COMMAND"/);

const metadataPreflight = script.indexOf('validate-youtube-metadata.mjs');
const dependencySetup = script.indexOf('install_private_dependencies "$INSTALL_COMMAND"');
const deterministicBoundary = script.indexOf('bash -o pipefail -c "$FINAL_VALIDATION_COMMAND"');
const render = script.indexOf('"$REMOTION_BIN" render');
assert.ok(metadataPreflight >= 0, "final render must validate YouTube metadata");
assert.ok(dependencySetup >= 0, "final render must use the verified dependency setup helper");
assert.ok(deterministicBoundary >= 0, "final render must have one deterministic source-validation boundary");
assert.ok(metadataPreflight < dependencySetup, "metadata preflight must run before dependency setup/asset preparation");
assert.ok(metadataPreflight < render, "metadata preflight must run before expensive Remotion rendering");
assert.ok(deterministicBoundary < render, "all deterministic source validation must finish before expensive Remotion rendering");

assert.match(sequenceScript, /install_private_dependencies "\$INSTALL_COMMAND"/);
assert.doesNotMatch(voiceScript, /install_private_dependencies|INSTALL_COMMAND|node_modules/);
assert.match(voiceScript, /restore-existing-long-voice-prep\.sh/);
assert.match(voiceScript, /RCLONE_CONFIG_B64/);
assert.match(voiceScript, /npm run voiceover:test/);
assert.match(voiceScript, /npm run audio:prepare/);
const voiceReuse = voiceScript.indexOf('restore-existing-long-voice-prep.sh');
const voiceTests = voiceScript.indexOf('npm run voiceover:test');
const whisperSetup = voiceScript.indexOf('WHISPERX_VERSION="3.8.6"');
const audioPrepare = voiceScript.indexOf('npm run audio:prepare');
assert.ok(voiceReuse >= 0 && voiceReuse < voiceTests, "exact Drive reuse must be attempted before voice tests/generation");
assert.ok(voiceTests >= 0 && voiceTests < whisperSetup, "lightweight voice tests must fail before expensive WhisperX setup");
assert.ok(whisperSetup >= 0 && whisperSetup < audioPrepare, "alignment runtime must be ready before production audio preparation");

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

assert.match(workflow, /Restore verified installed Node dependencies/);
assert.match(workflow, /id: node_dependencies_cache/);
assert.match(workflow, /steps\.request\.outputs\.mode != 'voice-prep'/);
assert.match(workflow, /uses: actions\/cache\/restore@v4/);
assert.match(workflow, /path: private-source\/node_modules/);
assert.match(workflow, /telic-remotion-node-modules-v1-\$\{\{ runner\.os \}\}-\$\{\{ runner\.arch \}\}-node22-\$\{\{ hashFiles\('private-source\/package-lock\.json'\) \}\}/);
assert.match(workflow, /Save verified installed Node dependencies/);
assert.match(workflow, /steps\.node_dependencies_cache\.outputs\.cache-hit != 'true'/);
assert.match(workflow, /uses: actions\/cache\/save@v4/);
assert.match(workflow, /GEMINI_API_KEY: \$\{\{ secrets\.GEMINI_API_KEY \}\}\n          RCLONE_CONFIG_B64: \$\{\{ secrets\.RCLONE_CONFIG_B64 \}\}/);

// Public worker caches may contain public tools/dependencies and opaque success
// sentinels, never unreleased Telic/Coffee media.
assert.doesNotMatch(workflow, /voiceover_cache/);
assert.doesNotMatch(workflow, /telic-long-voice-v1/);
assert.doesNotMatch(workflow, /actions\/cache\/(?:restore|save)@v4[\s\S]{0,300}voiceover\.mp3/);

const dependencySave = workflow.indexOf('- name: Save verified installed Node dependencies');
const cleanup = workflow.indexOf('- name: Remove private source checkout');
assert.ok(dependencySave >= 0 && dependencySave < cleanup, "node_modules must be saved before private-source cleanup");

assert.match(workflow, /echo "ok=true" >> "\$GITHUB_OUTPUT"/);
assert.match(workflow, /steps\.audio_restore\.outputs\.ok == 'true'/);
assert.match(workflow, /steps\.render\.outputs\.ok == 'true'/);
assert.match(workflow, /steps\.quality\.outputs\.ok == 'true'/);
assert.match(workflow, /Deliver successful private package to Google Drive/);
assert.match(workflow, /Deliver failed-attempt diagnostics privately/);
assert.doesNotMatch(workflow, /steps\.(?:audio_restore|render|quality|sequence|voice)\.outputs\.exit_code == '0'/);

console.log("Final renders use one aggregated deterministic validation boundary before Remotion, reuse only public dependency/tool caches, keep private media out of public caches, and preserve success-only Drive authority.");

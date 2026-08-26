#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import {fileURLToPath} from "node:url";

const scriptPath = fileURLToPath(new URL("./run-voice-prep.sh", import.meta.url));
const script = fs.readFileSync(scriptPath, "utf8");
const sourceGate = script.indexOf("node scripts/autopilot/validate-long-source.mjs");
const sourceCheckout = script.indexOf('cd "$SOURCE_DIR"');
const voiceTests = script.indexOf("npm run voiceover:test");
const whisperSetup = script.indexOf('python3 -m venv "$ALIGNER_VENV"');
const credentialState = script.indexOf("GEMINI_CREDENTIAL_STATE_PATH");
const audioPrepare = script.indexOf("npm run audio:prepare");

assert.ok(sourceCheckout >= 0, "voice prep must enter the private source checkout");
assert.ok(sourceGate > sourceCheckout, "long-form source validation must run inside the private checkout");
assert.ok(sourceGate < voiceTests, "source validation must precede voice-tool tests");
assert.ok(voiceTests < whisperSetup, "voice-tool tests must precede WhisperX setup");
assert.ok(credentialState > voiceTests, "credential health must be initialized after unit tests");
assert.ok(credentialState < audioPrepare, "credential health must be available before audio generation");
assert.ok(sourceGate < whisperSetup, "source validation must precede expensive WhisperX setup");

console.log("Voice-prep ordering contract passed.");

#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {validateRuntimePolicy} from "./validate-runtime-policy.mjs";

const temp = await fs.mkdtemp(path.join(os.tmpdir(), "telic-runtime-policy-"));
try {
  const current = path.join(temp, "automation/current");
  const profileDir = path.join(temp, "tools/telic-vnext/channels/coffee");
  await fs.mkdir(current, {recursive: true});
  await fs.mkdir(profileDir, {recursive: true});
  await fs.writeFile(path.join(temp, "automation/config.json"), `${JSON.stringify({
    quality: {maximumFrames: 20, maximumDurationSeconds: 32},
    longForm: {minimumDurationSeconds: 240, quality: {maximumFrames: 48, maximumDurationSeconds: 600}},
  })}\n`);
  await fs.writeFile(path.join(current, "job.json"), `${JSON.stringify({jobId: "coffee-long-test-001", channelId: "coffee", format: "long"})}\n`);
  await fs.writeFile(path.join(profileDir, "source-profile.json"), `${JSON.stringify({
    long: {minimumDurationSeconds: 540, targetDurationSeconds: 660, maximumDurationSeconds: 720},
  })}\n`);
  await fs.writeFile(path.join(current, "audio-runtime.json"), `${JSON.stringify({jobId: "coffee-long-test-001", format: "long", durationSeconds: 643.99})}\n`);

  const valid = await validateRuntimePolicy(temp);
  assert.equal(valid.maximumDurationSeconds, 720);
  assert.equal(valid.policySource, "channel-source-profile");

  await fs.writeFile(path.join(current, "audio-runtime.json"), `${JSON.stringify({jobId: "coffee-long-test-001", format: "long", durationSeconds: 721})}\n`);
  await assert.rejects(validateRuntimePolicy(temp), /outside the channel policy 540-720s/);

  await fs.rm(profileDir, {recursive: true, force: true});
  await fs.writeFile(path.join(current, "audio-runtime.json"), `${JSON.stringify({jobId: "coffee-long-test-001", format: "long", durationSeconds: 601})}\n`);
  await assert.rejects(validateRuntimePolicy(temp), /outside the channel policy 240-600s/);

  console.log("Pre-render channel runtime validation tests passed.");
} finally {
  await fs.rm(temp, {recursive: true, force: true});
}

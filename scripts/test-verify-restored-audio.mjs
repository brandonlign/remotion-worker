#!/usr/bin/env node
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {verifyRestoredAudio} from "./verify-restored-audio.mjs";

const temp = await fs.mkdtemp(path.join(os.tmpdir(), "telic-restored-audio-"));
try {
  const sourceRuntimePath = path.join(temp, "source-runtime.json");
  const driveRuntimePath = path.join(temp, "drive-runtime.json");
  const audioPath = path.join(temp, "voiceover.mp3");
  const bytes = Buffer.from("locked voice binary");
  const hash = crypto.createHash("sha256").update(bytes).digest("hex");
  await fs.writeFile(audioPath, bytes);

  const runtime = {
    schemaVersion: 2,
    format: "long",
    jobId: "telic-long-test",
    scriptSourceSha: "1".repeat(40),
    narrationSha256: "2".repeat(64),
    voiceoverSha256: hash,
    fps: 30,
    totalDurationInFrames: 9000,
    beats: [{id: "beat-1", startFrame: 0, endFrame: 9000}],
  };
  // Different key ordering is semantically identical.
  await fs.writeFile(sourceRuntimePath, `${JSON.stringify(runtime, null, 2)}\n`);
  await fs.writeFile(driveRuntimePath, `${JSON.stringify({jobId: runtime.jobId, ...runtime}, null, 4)}\n`);
  const verified = await verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath});
  assert.equal(verified.format, "long");
  assert.equal(verified.voiceoverSha256, hash);

  await fs.writeFile(driveRuntimePath, `${JSON.stringify({...runtime, totalDurationInFrames: 9001}, null, 2)}\n`);
  await assert.rejects(
    verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}),
    /drifted from the committed frozen source runtime/,
  );

  await fs.writeFile(driveRuntimePath, `${JSON.stringify(runtime, null, 2)}\n`);
  await fs.writeFile(audioPath, Buffer.from("different voice bytes"));
  await assert.rejects(
    verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}),
    /does not match the committed runtime hash/,
  );

  const noHash = {...runtime};
  delete noHash.voiceoverSha256;
  await fs.writeFile(sourceRuntimePath, `${JSON.stringify(noHash, null, 2)}\n`);
  await fs.writeFile(driveRuntimePath, `${JSON.stringify(noHash, null, 2)}\n`);
  await assert.rejects(
    verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}),
    /no valid voiceoverSha256 lock/,
  );

  const shortDrive = {schemaVersion: 2, format: "short", jobId: "short"};
  await fs.writeFile(driveRuntimePath, `${JSON.stringify(shortDrive)}\n`);
  const shortResult = await verifyRestoredAudio({sourceRuntimePath: path.join(temp, "missing.json"), driveRuntimePath, audioPath});
  assert.equal(shortResult.format, "short");
  assert.deepEqual(shortResult.runtime, shortDrive);
} finally {
  await fs.rm(temp, {recursive: true, force: true});
}

console.log("Frozen long-form Drive audio restore tests passed.");

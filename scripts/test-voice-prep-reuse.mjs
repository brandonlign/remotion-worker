#!/usr/bin/env node
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {verifyReusableLongVoicePrep} from "./verify-restored-audio.mjs";

const temp = await fs.mkdtemp(path.join(os.tmpdir(), "telic-voice-reuse-"));
try {
  const narrationPath = path.join(temp, "narration.txt");
  const runtimePath = path.join(temp, "audio-runtime.json");
  const alignmentPath = path.join(temp, "alignment.json");
  const audioPath = path.join(temp, "voiceover.mp3");
  const narration = "An exact reusable narration.\n";
  const audio = Buffer.from("exact reusable voice bytes");
  const narrationSha256 = crypto.createHash("sha256").update(narration).digest("hex");
  const voiceoverSha256 = crypto.createHash("sha256").update(audio).digest("hex");
  const sourceSha = "a".repeat(40);
  const jobId = "coffee-long-reuse-test";

  const runtime = {
    schemaVersion: 2,
    format: "long",
    jobId,
    channelId: "coffee",
    scriptSourceSha: sourceSha,
    narrationSha256,
    voiceoverSha256,
    fps: 30,
    durationSeconds: 600,
    totalDurationInFrames: 18000,
    exactAlignment: true,
    alignmentProvider: "whisperx",
    voiceProvider: "gemini",
    voiceName: "Iapetus",
    voiceSegments: [],
    beats: [],
  };
  const alignment = {exactAlignment: true, alignmentProvider: "whisperx", voiceName: "Iapetus"};
  await fs.writeFile(narrationPath, narration);
  await fs.writeFile(audioPath, audio);
  await fs.writeFile(runtimePath, `${JSON.stringify(runtime)}\n`);
  await fs.writeFile(alignmentPath, `${JSON.stringify(alignment)}\n`);

  const valid = await verifyReusableLongVoicePrep({runtimePath, alignmentPath, audioPath, narrationPath, expectedJobId: jobId, expectedSourceSha: sourceSha});
  assert.equal(valid.format, "long");
  assert.equal(valid.voiceoverSha256, voiceoverSha256);

  await assert.rejects(
    verifyReusableLongVoicePrep({runtimePath, alignmentPath, audioPath, narrationPath, expectedJobId: jobId, expectedSourceSha: "b".repeat(40)}),
    /another source commit/,
  );

  await fs.writeFile(narrationPath, "Changed narration.\n");
  await assert.rejects(
    verifyReusableLongVoicePrep({runtimePath, alignmentPath, audioPath, narrationPath, expectedJobId: jobId, expectedSourceSha: sourceSha}),
    /current narration bytes/,
  );
  await fs.writeFile(narrationPath, narration);

  await fs.writeFile(audioPath, Buffer.from("wrong voice bytes"));
  await assert.rejects(
    verifyReusableLongVoicePrep({runtimePath, alignmentPath, audioPath, narrationPath, expectedJobId: jobId, expectedSourceSha: sourceSha}),
    /runtime hash/,
  );

  const restoreScript = await fs.readFile(new URL("./restore-existing-long-voice-prep.sh", import.meta.url), "utf8");
  assert.match(restoreScript, /render_root_for_job_id/);
  assert.match(restoreScript, /--reusable-long-voice/);
  assert.match(restoreScript, /exit 10/);
  assert.doesNotMatch(restoreScript, /Telic-Renders\//);
} finally {
  await fs.rm(temp, {recursive: true, force: true});
}

console.log("Exact private-Drive long voice-prep reuse verification tests passed.");

#!/usr/bin/env node
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {verifyCommittedLongAudio, verifyRestoredAudio} from "./verify-restored-audio.mjs";

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
    channelId: "telic",
    scriptSourceSha: "1".repeat(40),
    narrationSha256: "2".repeat(64),
    voiceoverSha256: hash,
    fps: 30,
    durationSeconds: 300,
    totalDurationInFrames: 9000,
    exactAlignment: true,
    alignmentProvider: "whisperx",
    alignmentQuality: {coreCharacterCoverage: 1, medianCharacterScore: 0.8},
    voiceProvider: "gemini",
    voiceName: "Schedar",
    voiceSegments: [{id: "voice-1", beatIds: ["beat-1"], startFrame: 0, endFrame: 9000}],
    beats: [{id: "beat-1", startFrame: 0, spokenEndFrame: 8970, endFrame: 9000, durationInFrames: 9000}],
  };
  await fs.writeFile(sourceRuntimePath, `${JSON.stringify(runtime, null, 2)}\n`);
  await fs.writeFile(driveRuntimePath, `${JSON.stringify({jobId: runtime.jobId, ...runtime}, null, 4)}\n`);
  const verified = await verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath});
  assert.equal(verified.format, "long");
  assert.equal(verified.voiceoverSha256, hash);

  await fs.writeFile(driveRuntimePath, `${JSON.stringify({
    ...runtime,
    beats: runtime.beats.map((beat) => ({...beat, purpose: "descriptive label", narration: "spoken text retained by voice prep"})),
  }, null, 2)}\n`);
  assert.equal((await verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath})).format, "long");

  const previewVerified = await verifyCommittedLongAudio({sourceRuntimePath, audioPath, expectedJobId: runtime.jobId});
  assert.equal(previewVerified.format, "long");
  assert.equal(previewVerified.voiceoverSha256, hash);
  await assert.rejects(
    verifyCommittedLongAudio({sourceRuntimePath, audioPath, expectedJobId: "different-job"}),
    /does not match the requested job ID/,
  );

  for (const drifted of [
    {...runtime, totalDurationInFrames: 9001},
    {...runtime, narrationSha256: "3".repeat(64)},
    {...runtime, beats: [{...runtime.beats[0], endFrame: 8999}]},
    {...runtime, voiceSegments: [{...runtime.voiceSegments[0], endFrame: 8999}]},
  ]) {
    await fs.writeFile(driveRuntimePath, `${JSON.stringify(drifted, null, 2)}\n`);
    await assert.rejects(
      verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}),
      /audio contract drifted from the committed frozen source timing\/identity/,
    );
  }

  const noDriveFormat = {...runtime};
  delete noDriveFormat.format;
  await fs.writeFile(driveRuntimePath, `${JSON.stringify(noDriveFormat, null, 2)}\n`);
  await assert.rejects(
    verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}),
    /attempted to downgrade a committed long-form runtime/,
  );
  await fs.writeFile(driveRuntimePath, `${JSON.stringify({...runtime, format: "short"}, null, 2)}\n`);
  await assert.rejects(
    verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}),
    /attempted to downgrade a committed long-form runtime/,
  );

  await fs.writeFile(driveRuntimePath, `${JSON.stringify(runtime, null, 2)}\n`);
  await fs.writeFile(audioPath, Buffer.from("different voice bytes"));
  await assert.rejects(verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}), /does not match the committed runtime hash/);
  await assert.rejects(verifyCommittedLongAudio({sourceRuntimePath, audioPath, expectedJobId: runtime.jobId}), /does not match the committed runtime hash/);

  await fs.writeFile(audioPath, bytes);
  const noHash = {...runtime};
  delete noHash.voiceoverSha256;
  await fs.writeFile(sourceRuntimePath, `${JSON.stringify(noHash, null, 2)}\n`);
  await fs.writeFile(driveRuntimePath, `${JSON.stringify(noHash, null, 2)}\n`);
  await assert.rejects(verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}), /no valid voiceoverSha256 lock/);

  await fs.rm(sourceRuntimePath, {force: true});
  await fs.writeFile(driveRuntimePath, `${JSON.stringify(runtime, null, 2)}\n`);
  await assert.rejects(verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}), /committed source has no authoritative long-form runtime/);

  const shortDrive = {schemaVersion: 2, format: "short", jobId: "short"};
  await fs.writeFile(driveRuntimePath, `${JSON.stringify(shortDrive)}\n`);
  const shortResult = await verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath});
  assert.equal(shortResult.format, "short");
  assert.deepEqual(shortResult.runtime, shortDrive);

  const restoreScript = await fs.readFile(new URL("./download-drive-audio.sh", import.meta.url), "utf8");
  assert.match(restoreScript, /REQUEST_FILE="\$WORKER_ROOT\/jobs\/request\.json"/);
  assert.match(restoreScript, /if \[ "\$RESTORE_MODE" = "render-sequence" \]; then/);
  assert.match(restoreScript, /RESTORE_MODE" = "long-preview"/);
  assert.match(restoreScript, /RESTORE_MODE" = "render" \] \|\|/);
  assert.match(restoreScript, /--committed-long/);
  assert.match(restoreScript, /source "\$WORKER_ROOT\/scripts\/lib\/channel-storage\.sh"/);
  assert.match(restoreScript, /VOICE_ROOT_PATH="\$\(render_root_for_job_id "\$JOB_ID"\)\/\$JOB_ID"/);
  assert.match(restoreScript, /rclone copy "gdrive:\$VOICE_ROOT_PATH" "\$VOICE_STAGE_DIR"/);
  assert.match(restoreScript, /--files-from "\$VOICE_NAMES_FILE"/);
  assert.match(restoreScript, /'alignment\.json' 'audio-runtime\.json'/);
  assert.doesNotMatch(restoreScript, /copy_voice_artifact/);
  assert.doesNotMatch(restoreScript, /VOICE_ROOT_PATH="Telic-Renders/);
  assert.doesNotMatch(restoreScript, /use_telic_renders_root/);
  assert.doesNotMatch(restoreScript, /TELIC_AUDIO_LOCATOR_DIR/);

  // Provider-ID copies are allowed only for private channel assets whose exact
  // tuple has first been validated against the immutable controller-authorized
  // source registry. Voice restoration remains path-rooted, and live Drive
  // listing/query ambiguity is not part of the trust decision.
  assert.match(restoreScript, /read-private-music-request\.mjs" \\\n  "\$AUDIO_REQUEST_FILE" "\$SOURCE_DIR"/);
  assert.match(restoreScript, /rclone backend copyid gdrive: "\$drive_file_id" "\$restored"/);
  assert.equal((restoreScript.match(/backend copyid/g) ?? []).length, 1);
  assert.doesNotMatch(restoreScript, /rclone backend query gdrive:/);
  assert.doesNotMatch(restoreScript, /rclone lsjson gdrive:/);
} finally {
  await fs.rm(temp, {recursive: true, force: true});
}

console.log("Semantic frozen long-form audio identity and restore tests passed.");

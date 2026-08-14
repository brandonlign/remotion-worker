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

  // Sequence previews do not need to download alignment.json or a duplicate
  // audio-runtime.json. The committed runtime plus exact MP3 hash and job ID are
  // sufficient to prove the restored voiceover is the frozen one.
  const previewVerified = await verifyCommittedLongAudio({
    sourceRuntimePath,
    audioPath,
    expectedJobId: runtime.jobId,
  });
  assert.equal(previewVerified.format, "long");
  assert.equal(previewVerified.voiceoverSha256, hash);
  await assert.rejects(
    verifyCommittedLongAudio({sourceRuntimePath, audioPath, expectedJobId: "different-job"}),
    /does not match the requested job ID/,
  );

  await fs.writeFile(driveRuntimePath, `${JSON.stringify({...runtime, totalDurationInFrames: 9001}, null, 2)}\n`);
  await assert.rejects(
    verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}),
    /drifted from the committed frozen source runtime/,
  );

  // Drive metadata may never downgrade an authoritative committed long runtime
  // into the legacy Short restore path by dropping or changing format.
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
  await assert.rejects(
    verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}),
    /does not match the committed runtime hash/,
  );
  await assert.rejects(
    verifyCommittedLongAudio({sourceRuntimePath, audioPath, expectedJobId: runtime.jobId}),
    /does not match the committed runtime hash/,
  );

  await fs.writeFile(audioPath, bytes);
  const noHash = {...runtime};
  delete noHash.voiceoverSha256;
  await fs.writeFile(sourceRuntimePath, `${JSON.stringify(noHash, null, 2)}\n`);
  await fs.writeFile(driveRuntimePath, `${JSON.stringify(noHash, null, 2)}\n`);
  await assert.rejects(
    verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}),
    /no valid voiceoverSha256 lock/,
  );

  // Conversely, a Drive long-form package must never be accepted when the
  // checked-out source has no authoritative long runtime.
  await fs.rm(sourceRuntimePath, {force: true});
  await fs.writeFile(driveRuntimePath, `${JSON.stringify(runtime, null, 2)}\n`);
  await assert.rejects(
    verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath}),
    /committed source has no authoritative long-form runtime/,
  );

  const shortDrive = {schemaVersion: 2, format: "short", jobId: "short"};
  await fs.writeFile(driveRuntimePath, `${JSON.stringify(shortDrive)}\n`);
  const shortResult = await verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath});
  assert.equal(shortResult.format, "short");
  assert.deepEqual(shortResult.runtime, shortDrive);

  const restoreScript = await fs.readFile(new URL("./download-drive-audio.sh", import.meta.url), "utf8");
  assert.match(restoreScript, /REQUEST_FILE="\$WORKER_ROOT\/jobs\/request\.json"/);
  assert.match(restoreScript, /if \[ "\$RESTORE_MODE" = "render-sequence" \]; then/);
  assert.match(restoreScript, /--committed-long/);
  assert.match(restoreScript, /copy_voice_artifact alignment\.json/);
  assert.match(restoreScript, /copy_voice_artifact audio-runtime\.json/);

  // The fast preview path must use an opaque private locator and Drive's ID
  // backend command, while retaining the path-based fallback for old jobs.
  assert.match(restoreScript, /TELIC_AUDIO_LOCATOR_DIR/);
  assert.match(restoreScript, /voiceover\.id/);
  assert.match(restoreScript, /rclone backend copyid gdrive:/);
  assert.match(restoreScript, /use_telic_renders_root/);
  assert.match(restoreScript, /resolve_voiceover_id_from_path/);

  const uploadScript = await fs.readFile(new URL("./upload-drive.sh", import.meta.url), "utf8");
  assert.match(uploadScript, /TELIC_AUDIO_LOCATOR_DIR/);
  assert.match(uploadScript, /voiceover_drive_id/);
  assert.match(uploadScript, /voiceover\.id/);
  assert.doesNotMatch(uploadScript, /echo .*voiceover_drive_id/);

  const workflow = await fs.readFile(new URL("../.github/workflows/render.yml", import.meta.url), "utf8");
  assert.match(workflow, /name: Cache private Drive audio locator/);
  assert.match(workflow, /key: telic-drive-audio-v1-\$\{\{ steps\.request\.outputs\.job_id \}\}/);
  assert.match(workflow, /TELIC_AUDIO_LOCATOR_DIR: \$\{\{ runner\.temp \}\}\/telic-drive-audio\/\$\{\{ steps\.request\.outputs\.job_id \}\}/);
} finally {
  await fs.rm(temp, {recursive: true, force: true});
}

console.log("Frozen long-form full and lightweight preview audio restore tests passed.");

#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {spawn} from "node:child_process";
import {fileURLToPath} from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const run = (command, args, {expectFailure = false} = {}) => new Promise((resolve, reject) => {
  const child = spawn(command, args, {cwd: ROOT, stdio: expectFailure ? "ignore" : "inherit"});
  child.once("error", reject);
  child.once("exit", (code) => {
    if (expectFailure ? code !== 0 : code === 0) return resolve();
    reject(new Error(`${command} exited with ${code}; expectFailure=${expectFailure}`));
  });
});

const writeRenderStatus = async ({output, jobId, sourceSha, outputName = "telic-autopilot"}) => {
  await fs.mkdir(output, {recursive: true});
  await fs.writeFile(path.join(output, `${outputName}.mp4`), "video-bytes", "utf8");
  await fs.writeFile(path.join(output, "status.json"), `${JSON.stringify({status: "complete", jobId, sourceSha, outputName}, null, 2)}\n`, "utf8");
};

const writeRequest = async ({file, jobId, sourceSha, issue = 123, revision = 7}) => {
  await fs.writeFile(file, `${JSON.stringify({
    jobId,
    sourceSha,
    sourceRepository: "brandonlign/remotion-video",
    sourceIssueNumber: issue,
    revision,
    mode: "render",
  }, null, 2)}\n`, "utf8");
};

const main = async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), "telic-handoff-"));
  try {
    const jobId = "telic-web-test-001";
    const sourceSha = "0123456789abcdef0123456789abcdef01234567";
    const request = path.join(temp, "request.json");
    await writeRequest({file: request, jobId, sourceSha});

    const shortOutput = path.join(temp, "short-output");
    const shortYoutube = path.join(temp, "short-youtube.json");
    await writeRenderStatus({output: shortOutput, jobId, sourceSha});
    await fs.writeFile(shortYoutube, `${JSON.stringify({
      version: 1,
      jobId,
      title: "Why QR Codes Survive Damage",
      description: "A test description.",
      tags: ["QR codes", "technology", "error correction"],
      categoryId: "28",
      defaultLanguage: "en",
      privacyStatus: "private",
      publishAt: "2026-08-05T22:00:00.000Z",
      madeForKids: false,
      containsSyntheticMedia: false,
      license: "youtube",
    }, null, 2)}\n`, "utf8");

    await run(process.execPath, ["scripts/create-controller-handoff.mjs", shortOutput, shortYoutube, request]);
    assert.equal(await fs.readFile(path.join(shortOutput, "final.mp4"), "utf8"), "video-bytes");
    const shortPublish = JSON.parse(await fs.readFile(path.join(shortOutput, "publish.json"), "utf8"));
    assert.equal(shortPublish.jobId, jobId);
    assert.equal(shortPublish.sourceSha, sourceSha);
    assert.equal(shortPublish.sourceRepository, "brandonlign/remotion-video");
    assert.equal(shortPublish.sourceIssueNumber, 123);
    assert.equal(shortPublish.revision, 7);

    const longDir = path.join(temp, "long-source");
    const longOutput = path.join(temp, "long-output");
    const longYoutube = path.join(longDir, "youtube.json");
    await fs.mkdir(longDir, {recursive: true});
    await writeRenderStatus({output: longOutput, jobId, sourceSha, outputName: "final"});
    await fs.writeFile(path.join(longDir, "audio-runtime.json"), `${JSON.stringify({format: "long", jobId, durationSeconds: 420}, null, 2)}\n`, "utf8");
    const validLong = {
      version: 2,
      format: "long",
      jobId,
      title: "The Hidden Constraint Behind a Familiar System",
      description: "A test long-form description.\n\n0:00 The result that does not fit\n1:30 The limit underneath it\n4:20 The decision that changes",
      chapters: [
        {startSeconds: 0, title: "The result that does not fit"},
        {startSeconds: 90, title: "The limit underneath it"},
        {startSeconds: 260, title: "The decision that changes"},
      ],
      tags: ["technology", "systems"],
      categoryId: "28",
      defaultLanguage: "en",
      privacyStatus: "private",
      publishAt: "2026-08-10T16:00:00.000Z",
      madeForKids: false,
      containsSyntheticMedia: false,
      license: "youtube",
    };
    await fs.writeFile(longYoutube, `${JSON.stringify(validLong, null, 2)}\n`, "utf8");
    await run(process.execPath, ["scripts/create-controller-handoff.mjs", longOutput, longYoutube, request]);
    const longPublish = JSON.parse(await fs.readFile(path.join(longOutput, "publish.json"), "utf8"));
    assert.match(longPublish.description, /0:00 The result that does not fit/);
    assert.match(longPublish.description, /4:20 The decision that changes/);
    assert.equal(longPublish.sourceIssueNumber, 123);

    const mismatchedRequest = path.join(temp, "mismatch-request.json");
    await writeRequest({file: mismatchedRequest, jobId, sourceSha: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"});
    await run(process.execPath, ["scripts/create-controller-handoff.mjs", longOutput, longYoutube, mismatchedRequest], {expectFailure: true});

    const invalidYoutube = path.join(longDir, "invalid-youtube.json");
    await fs.writeFile(invalidYoutube, `${JSON.stringify({...validLong, description: "No chapter lines here."}, null, 2)}\n`, "utf8");
    await run(process.execPath, ["scripts/create-controller-handoff.mjs", longOutput, invalidYoutube, request], {expectFailure: true});

    console.log("Source-bound controller handoff packaging tests passed.");
  } finally {
    await fs.rm(temp, {recursive: true, force: true});
  }
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});

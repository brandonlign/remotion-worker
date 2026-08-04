#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {spawn} from "node:child_process";
import {fileURLToPath} from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const run = (command, args) => new Promise((resolve, reject) => {
  const child = spawn(command, args, {cwd: ROOT, stdio: "inherit"});
  child.once("error", reject);
  child.once("exit", (code) => code === 0 ? resolve() : reject(new Error(`${command} exited with ${code}`)));
});

const main = async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), "telic-handoff-"));
  try {
    const output = path.join(temp, "output");
    const youtubePath = path.join(temp, "youtube.json");
    const jobId = "telic-web-test-001";
    const sourceSha = "0123456789abcdef0123456789abcdef01234567";
    await fs.mkdir(output, {recursive: true});
    await fs.writeFile(path.join(output, "telic-autopilot.mp4"), "video-bytes", "utf8");
    await fs.writeFile(path.join(output, "status.json"), `${JSON.stringify({
      status: "complete",
      jobId,
      sourceSha,
      outputName: "telic-autopilot",
    }, null, 2)}\n`, "utf8");
    await fs.writeFile(youtubePath, `${JSON.stringify({
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

    await run(process.execPath, [
      "scripts/create-controller-handoff.mjs",
      output,
      youtubePath,
      jobId,
      sourceSha,
    ]);

    assert.equal(await fs.readFile(path.join(output, "final.mp4"), "utf8"), "video-bytes");
    const publish = JSON.parse(await fs.readFile(path.join(output, "publish.json"), "utf8"));
    assert.deepEqual(publish, {
      jobId,
      title: "Why QR Codes Survive Damage",
      description: "A test description.",
      tags: ["QR codes", "technology", "error correction"],
      categoryId: "28",
      defaultLanguage: "en",
      madeForKids: false,
      containsSyntheticMedia: false,
      publishAt: "2026-08-05T22:00:00.000Z",
      sourceSha,
    });
    console.log("Studio controller handoff packaging test passed.");
  } finally {
    await fs.rm(temp, {recursive: true, force: true});
  }
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});

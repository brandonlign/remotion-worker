#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {spawn} from "node:child_process";
import {fileURLToPath} from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const run = (command, args, {expectFailure = false} = {}) => new Promise((resolve, reject) => {
  const child = spawn(command, args, {cwd: ROOT, stdio: "ignore"});
  child.once("error", reject);
  child.once("exit", (code) => {
    if (expectFailure ? code !== 0 : code === 0) return resolve();
    reject(new Error(`${command} exited with ${code}; expectFailure=${expectFailure}`));
  });
});

const writeTree = async (root, youtubeText, sourceText = "same source") => {
  await fs.mkdir(path.join(root, "automation/current"), {recursive: true});
  await fs.mkdir(path.join(root, "src"), {recursive: true});
  await fs.mkdir(path.join(root, ".agent/skills"), {recursive: true});
  await fs.writeFile(path.join(root, "automation/current/youtube.json"), youtubeText);
  await fs.writeFile(path.join(root, "src/index.ts"), sourceText);
  await fs.symlink("../../shared/mediabunny", path.join(root, ".agent/skills/mediabunny"));
};

const main = async () => {
  const workflow = await fs.readFile(path.join(ROOT, ".github/workflows/finalize.yml"), "utf8");
  assert.match(workflow, /jobs\/finalize-request\.json/);
  assert.match(workflow, /verify-metadata-only-reuse\.mjs/);
  assert.match(workflow, /download-drive-render\.sh/);
  assert.match(workflow, /run-finalize\.sh/);
  assert.doesNotMatch(workflow, /run-render\.sh/);
  assert.doesNotMatch(workflow, /REMOTION_BIN/);

  await run(process.execPath, ["scripts/validate-finalize-job.mjs", "jobs/finalize-request.example.json"]);

  const temp = await fs.mkdtemp(path.join(os.tmpdir(), "telic-finalize-reuse-"));
  try {
    const current = path.join(temp, "current");
    const rendered = path.join(temp, "rendered");
    await writeTree(current, '{"title":"new"}\n');
    await writeTree(rendered, '{"title":"old"}\n');
    const currentSha = "0123456789abcdef0123456789abcdef01234567";
    const renderSha = "fedcba9876543210fedcba9876543210fedcba98";

    await run(process.execPath, ["scripts/verify-metadata-only-reuse.mjs", current, rendered, currentSha, renderSha]);

    await fs.unlink(path.join(current, ".agent/skills/mediabunny"));
    await fs.symlink("../../shared/other-tool", path.join(current, ".agent/skills/mediabunny"));
    await run(process.execPath, ["scripts/verify-metadata-only-reuse.mjs", current, rendered, currentSha, renderSha], {expectFailure: true});
    await fs.unlink(path.join(current, ".agent/skills/mediabunny"));
    await fs.symlink("../../shared/mediabunny", path.join(current, ".agent/skills/mediabunny"));

    await fs.writeFile(path.join(current, "src/index.ts"), "changed pixels");
    await run(process.execPath, ["scripts/verify-metadata-only-reuse.mjs", current, rendered, currentSha, renderSha], {expectFailure: true});

    await fs.writeFile(path.join(current, "src/index.ts"), "same source");
    await fs.writeFile(path.join(rendered, "automation/current/youtube.json"), '{"title":"new"}\n');
    await run(process.execPath, ["scripts/verify-metadata-only-reuse.mjs", current, rendered, currentSha, currentSha]);

    const invalidRequest = path.join(temp, "invalid-finalize.json");
    await fs.writeFile(invalidRequest, `${JSON.stringify({
      jobId: "coffee-long-example-001",
      sourceSha: currentSha,
      renderSourceSha: renderSha,
      revision: 2,
      reuseRevision: 2,
    })}\n`);
    await run(process.execPath, ["scripts/validate-finalize-job.mjs", invalidRequest], {expectFailure: true});
  } finally {
    await fs.rm(temp, {recursive: true, force: true});
  }

  console.log("Metadata-only finalize reuse tests passed.");
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});

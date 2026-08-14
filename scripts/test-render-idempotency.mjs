#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const validator = path.join(root, "scripts/validate-job.mjs");
const temp = await fs.mkdtemp(path.join(os.tmpdir(), "telic-render-idempotency-"));

const run = async (request, name) => {
  const requestPath = path.join(temp, `${name}.json`);
  const outputPath = path.join(temp, `${name}-github-output.txt`);
  await fs.writeFile(requestPath, `${JSON.stringify(request)}\n`, "utf8");
  const result = spawnSync(process.execPath, [validator, requestPath], {
    encoding: "utf8",
    env: {...process.env, GITHUB_OUTPUT: outputPath},
  });
  return {result, output: result.status === 0 ? await fs.readFile(outputPath, "utf8") : ""};
};

try {
  const telic = await run({
    jobId: "telic-web-202608131318-0ed7a0",
    sourceSha: "26066aad9b3ba4911e3f739ffc0f4209d4d62ffa",
    revision: 2,
    mode: "render",
  }, "telic");
  assert.equal(telic.result.status, 0, telic.result.stderr);
  assert.match(telic.output, /^channel_id=telic$/m);
  assert.match(telic.output, /^revision=2$/m);
  assert.match(telic.output, /^mode=render$/m);
  assert.match(
    telic.output,
    /^request_key=telic-web-202608131318-0ed7a0-26066aad9b3ba4911e3f739ffc0f4209d4d62ffa-r2-render$/m,
  );

  const coffee = await run({
    jobId: "coffee-short-20260814-1800",
    sourceSha: "26066aad9b3ba4911e3f739ffc0f4209d4d62ffa",
    revision: 1,
    mode: "render",
  }, "coffee");
  assert.equal(coffee.result.status, 0, coffee.result.stderr);
  assert.match(coffee.output, /^channel_id=coffee$/m);

  const unknown = await run({
    jobId: "unknown-short-20260814-1800",
    sourceSha: "26066aad9b3ba4911e3f739ffc0f4209d4d62ffa",
    revision: 1,
    mode: "render",
  }, "unknown");
  assert.notEqual(unknown.result.status, 0);
  assert.match(unknown.result.stderr, /Unsupported channel prefix/);
} finally {
  await fs.rm(temp, {recursive: true, force: true});
}

console.log("Render idempotency and channel identity tests passed.");

#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temp = await fs.mkdtemp(path.join(os.tmpdir(), "telic-render-idempotency-"));
try {
  const requestPath = path.join(temp, "request.json");
  const outputPath = path.join(temp, "github-output.txt");
  const request = {
    jobId: "telic-web-202608131318-0ed7a0",
    sourceSha: "26066aad9b3ba4911e3f739ffc0f4209d4d62ffa",
    revision: 2,
    mode: "render",
  };
  await fs.writeFile(requestPath, `${JSON.stringify(request)}\n`, "utf8");
  const result = spawnSync(process.execPath, [path.join(root, "scripts/validate-job.mjs"), requestPath], {
    encoding: "utf8",
    env: {...process.env, GITHUB_OUTPUT: outputPath},
  });
  assert.equal(result.status, 0, result.stderr);
  const output = await fs.readFile(outputPath, "utf8");
  assert.match(output, /^revision=2$/m);
  assert.match(output, /^mode=render$/m);
  assert.match(
    output,
    /^request_key=telic-web-202608131318-0ed7a0-26066aad9b3ba4911e3f739ffc0f4209d4d62ffa-r2-render$/m,
  );
} finally {
  await fs.rm(temp, {recursive: true, force: true});
}

console.log("Render idempotency identity tests passed.");

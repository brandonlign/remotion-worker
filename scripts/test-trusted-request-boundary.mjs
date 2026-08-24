#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

const workflowPaths = [
  ".github/workflows/render.yml",
  ".github/workflows/finalize.yml",
  ".github/workflows/short-preview.yml",
];
for (const relative of workflowPaths) {
  const workflow = fs.readFileSync(new URL(`../${relative}`, import.meta.url), "utf8");
  assert.match(workflow, /workflow_run:/, `${relative} must run from the trusted workflow_run boundary`);
  assert.match(workflow, /workflows: \[Worker CI\]/, `${relative} must be gated by Worker CI`);
  assert.match(workflow, /ref: main/, `${relative} must execute the trusted main checkout`);
  assert.match(workflow, /prepare-trusted-request\.mjs/, `${relative} must validate and extract only its request payload`);
  assert.doesNotMatch(workflow, /github\.event\.pull_request\./, `${relative} must not execute directly in a PR context`);
  assert.doesNotMatch(workflow, /contents: write|pull-requests: write/, `${relative} must not request write permissions`);
}

const helper = fs.readFileSync(new URL("../scripts/prepare-trusted-request.mjs", import.meta.url), "utf8");
assert.match(helper, /git.*diff.*--name-only/s);
assert.match(helper, /git.*rev-list.*--parents/s);
assert.match(helper, /git.*show/s);
assert.match(helper, /JSON\.parse\(raw\)/);
assert.match(helper, /skipRender/);
assert.match(helper, /skipFinalize/);
assert.doesNotMatch(helper, /git.*checkout.*HEAD_SHA/s);

console.log("Trusted worker request boundary checks passed.");

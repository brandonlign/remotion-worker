#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

const workflow = fs.readFileSync(new URL("../.github/workflows/ci.yml", import.meta.url), "utf8");

assert.match(workflow, /Enforce request-only worker PR scope/);
assert.match(workflow, /startsWith\(github\.head_ref, 'render\/'\) \|\| startsWith\(github\.head_ref, 'preview\/'\)/);
assert.match(workflow, /preview\/\* PRs may change only jobs\/preview-request\.json/);
assert.match(workflow, /render\/\* PRs must never carry preview requests/);
assert.match(workflow, /jobs\/preview-request\.json jobId must exactly match preview\/<jobId>/);
assert.match(workflow, /jobs\/request\.json jobId must match render\/<jobId>/);
assert.match(workflow, /- name: Validate isolated worker request files/);
assert.match(workflow, /node scripts\/validate-preview-job\.mjs jobs\/preview-request\.json/);
assert.match(workflow, /node scripts\/validate-job\.mjs jobs\/request\.json/);
assert.match(workflow, /node scripts\/validate-finalize-job\.mjs jobs\/finalize-request\.json/);
assert.match(workflow, /!startsWith\(github\.head_ref, 'render\/'\) && !startsWith\(github\.head_ref, 'preview\/'\)/);

console.log("render and preview request PRs use separate lightweight isolation CI while reusable worker code retains full CI");

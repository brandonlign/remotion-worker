#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

const workflow = fs.readFileSync(new URL("../.github/workflows/ci.yml", import.meta.url), "utf8");

assert.match(workflow, /Enforce request-only render PR scope/);
assert.match(workflow, /render\/\* PRs are request-only/);
assert.match(workflow, /- name: Validate render request files\n        if: startsWith\(github\.head_ref, 'render\/'\)/);
assert.match(workflow, /node scripts\/validate-job\.mjs jobs\/request\.json/);
assert.match(workflow, /node scripts\/validate-finalize-job\.mjs jobs\/finalize-request\.json/);
assert.match(workflow, /- name: Validate worker files\n        if: \$\{\{ !startsWith\(github\.head_ref, 'render\/'\) \}\}\n        run: npm run check/);

console.log("render request PRs use lightweight schema/isolation CI while reusable worker code retains full CI");

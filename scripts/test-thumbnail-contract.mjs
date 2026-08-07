#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {spawnSync} from "node:child_process";

const root = path.resolve(new URL("..", import.meta.url).pathname);
const render = fs.readFileSync(path.join(root, "scripts/run-render.sh"), "utf8");
const gate = fs.readFileSync(path.join(root, "scripts/deterministic-quality-gate.mjs"), "utf8");
assert.match(render, /thumbnailCompositionId/);
assert.match(render, /remotion.*still|\"\$REMOTION_BIN\" still/s);
assert.match(render, /thumbnail\.png/);
assert.match(gate, /1920 by 1080/);
assert.match(gate, /50 MB desktop upload limit/);

const temp = fs.mkdtempSync(path.join(os.tmpdir(), "telic-thumbnail-config-"));
try {
  const input = path.join(temp, "input.json");
  const output = path.join(temp, "output.json");
  const base = {
    entryPoint: "src/index.ts",
    compositionId: "CustomLongForm",
    thumbnailCompositionId: "LongFormThumbnail",
    outputName: "final",
    installCommand: "npm ci",
    prepareCommand: "npm run long:prepare",
    checkCommand: "npm run lint",
    crf: 20,
  };
  fs.writeFileSync(input, JSON.stringify(base));
  let result = spawnSync(process.execPath, [path.join(root, "scripts/validate-source-config.mjs"), input, output], {encoding: "utf8"});
  assert.equal(result.status, 0, result.stderr);
  const normalized = JSON.parse(fs.readFileSync(output, "utf8"));
  assert.equal(normalized.thumbnailCompositionId, "LongFormThumbnail");

  fs.writeFileSync(input, JSON.stringify({...base, thumbnailCompositionId: "bad id!"}));
  result = spawnSync(process.execPath, [path.join(root, "scripts/validate-source-config.mjs"), input, output], {encoding: "utf8"});
  assert.notEqual(result.status, 0);

  delete base.thumbnailCompositionId;
  fs.writeFileSync(input, JSON.stringify(base));
  result = spawnSync(process.execPath, [path.join(root, "scripts/validate-source-config.mjs"), input, output], {encoding: "utf8"});
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(fs.readFileSync(output, "utf8")).thumbnailCompositionId, "");
} finally {
  fs.rmSync(temp, {recursive: true, force: true});
}

console.log("Long-form thumbnail worker contract tests passed.");

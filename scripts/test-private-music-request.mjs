#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";

const script = fileURLToPath(new URL("./read-private-music-request.mjs", import.meta.url));
const root = await fs.mkdtemp(path.join(os.tmpdir(), "music-request-"));
const input = path.join(root, "audio-design.json");
const run = () => spawnSync(process.execPath, [script, input], {encoding: "utf8"});

const music = {
  library: "telic-original-v1",
  driveFolderId: "folder_1234567890",
  driveFileId: "file_123456789012",
  fileName: "Private Track 01.mp3",
  assetPath: "public/assets/current/telic-music-01.mp3",
};
await fs.writeFile(input, JSON.stringify({qualityVersion: 2, music}));
let result = run();
assert.equal(result.status, 0, result.stderr);
assert.equal(result.stdout.trim().split("\t").length, 4);

await fs.writeFile(input, JSON.stringify({qualityVersion: 1, music}));
result = run();
assert.equal(result.status, 0, result.stderr);
assert.equal(result.stdout, "");

await fs.writeFile(input, JSON.stringify({qualityVersion: 2, music: {...music, assetPath: "../escape.mp3"}}));
result = run();
assert.notEqual(result.status, 0);
assert.match(result.stderr, /unsafe assetPath/);

await fs.rm(root, {recursive: true, force: true});
console.log("Private music restore request tests passed.");

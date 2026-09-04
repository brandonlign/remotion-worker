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
const run = (...extra) => spawnSync(process.execPath, [script, input, ...extra], {encoding: "utf8"});

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

const coffeeMusic = {
  ...music,
  library: "channel-library-v1",
  fileName: "Coffee Track 01.mp3",
  assetPath: "public/assets/current/coffee-music-01.mp3",
};
const coffeeSfx = {
  id: "cup-land",
  library: "channel-library-v1",
  librarySfxId: "cup-set-down",
  driveFolderId: "sfx_folder_123456789",
  driveFileId: "sfx_file_12345678901",
  fileName: "Cup Set Down.wav",
  assetPath: "public/assets/current/coffee-sfx-cup.wav",
};
await fs.writeFile(input, JSON.stringify({qualityVersion: 2, music: coffeeMusic, soundEffects: [coffeeSfx]}));
result = run();
assert.equal(result.status, 0, result.stderr);
assert.equal(result.stdout.trim().split("\n").length, 2);

await fs.writeFile(input, JSON.stringify({qualityVersion: 2, music: {...music, library: "unapproved-library"}}));
result = run();
assert.notEqual(result.status, 0);
assert.match(result.stderr, /approved library/);

await fs.writeFile(input, JSON.stringify({qualityVersion: 2, music: {...music, assetPath: "../escape.mp3"}}));
result = run();
assert.notEqual(result.status, 0);
assert.match(result.stderr, /unsafe assetPath/);

// A trusted private-source checkout supplies the immutable channel registry.
// Exact provider identity, filename, library, and destination must all match.
const sourceRoot = path.join(root, "source");
await fs.mkdir(path.join(sourceRoot, "automation", "current"), {recursive: true});
await fs.mkdir(path.join(sourceRoot, "tools", "telic-vnext", "channels", "coffee"), {recursive: true});
await fs.mkdir(path.join(sourceRoot, "tools", "telic-vnext", "universal"), {recursive: true});
await fs.writeFile(path.join(sourceRoot, "automation", "current", "job.json"), JSON.stringify({jobId: "coffee-long-test", channelId: "coffee"}));
await fs.writeFile(path.join(sourceRoot, "tools", "telic-vnext", "channels", "coffee", "source-profile.json"), JSON.stringify({
  audio: {libraryPath: "tools/telic-vnext/universal/audio-library.json"},
}));
await fs.writeFile(path.join(sourceRoot, "tools", "telic-vnext", "universal", "audio-library.json"), JSON.stringify({
  version: 1,
  library: "channel-library-v1",
  music: [coffeeMusic],
  sfx: [coffeeSfx],
}));

await fs.writeFile(input, JSON.stringify({qualityVersion: 2, music: coffeeMusic, soundEffects: [coffeeSfx]}));
result = run(sourceRoot);
assert.equal(result.status, 0, result.stderr);
assert.equal(result.stdout.trim().split("\n").length, 2);

await fs.writeFile(input, JSON.stringify({
  qualityVersion: 2,
  music: {...coffeeMusic, driveFileId: "different_file_123456789"},
}));
result = run(sourceRoot);
assert.notEqual(result.status, 0);
assert.match(result.stderr, /immutable source audio registry/);

await fs.rm(root, {recursive: true, force: true});
console.log("Private channel music/SFX restore request tests passed.");

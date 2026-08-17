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

const coffeeMusic = {
  ...music,
  library: "channel-library-v1",
  fileName: "Coffee Track 01.mp3",
  assetPath: "public/assets/current/coffee-music-01.mp3",
};
await fs.writeFile(input, JSON.stringify({qualityVersion: 2, music: coffeeMusic}));
result = run();
assert.equal(result.status, 0, result.stderr);
assert.equal(result.stdout.trim().split("\t").length, 4);

const coffeeSfx = {
  id: "cup-land",
  library: "channel-library-v1",
  librarySfxId: "cup-set-down",
  driveFolderId: "sfx_folder_123456789",
  driveFileId: "sfx_file_12345678901",
  fileName: "Cup Set Down.wav",
  assetPath: "public/assets/current/coffee-sfx-cup.wav",
};
await fs.writeFile(input, JSON.stringify({
  qualityVersion: 2,
  music: coffeeMusic,
  soundEffects: [
    {id: "opening-whoosh", assetPath: "public/assets/current/opening-whoosh.wav", frame: 0},
    coffeeSfx,
  ],
}));
result = run();
assert.equal(result.status, 0, result.stderr);
let rows = result.stdout.trim().split("\n");
assert.equal(rows.length, 2);
assert.equal(rows[1].split("\t").length, 4);
assert.match(rows[1], /Cup Set Down\.wav/);

// Coffee's channel-owned long-form audio design uses schemaVersion rather than
// Telic qualityVersion. It must still restore exact approved Drive identities.
await fs.writeFile(input, JSON.stringify({
  schemaVersion: 1,
  musicLibrarySelection: {...coffeeMusic, trackId: "coffee-track"},
  musicBeds: [coffeeMusic, coffeeMusic],
  soundEffects: [coffeeSfx],
}));
result = run();
assert.equal(result.status, 0, result.stderr);
rows = result.stdout.trim().split("\n");
assert.equal(rows.length, 2);
assert.match(rows[0], /Coffee Track 01\.mp3/);
assert.match(rows[1], /Cup Set Down\.wav/);

await fs.writeFile(input, JSON.stringify({qualityVersion: 1, music}));
result = run();
assert.equal(result.status, 0, result.stderr);
assert.equal(result.stdout, "");

await fs.writeFile(input, JSON.stringify({qualityVersion: 2, music: {...music, library: "unapproved-library"}}));
result = run();
assert.notEqual(result.status, 0);
assert.match(result.stderr, /approved channel-owned library/);

await fs.writeFile(input, JSON.stringify({qualityVersion: 2, music: {...music, assetPath: "../escape.mp3"}}));
result = run();
assert.notEqual(result.status, 0);
assert.match(result.stderr, /unsafe assetPath/);

await fs.writeFile(input, JSON.stringify({qualityVersion: 2, soundEffects: [{...coffeeSfx, library: "unapproved-library"}]}));
result = run();
assert.notEqual(result.status, 0);
assert.match(result.stderr, /approved channel-owned library/);

await fs.writeFile(input, JSON.stringify({qualityVersion: 2, soundEffects: [{...coffeeSfx, assetPath: "public/assets/current/coffee-sfx-cup.mp3"}]}));
result = run();
assert.notEqual(result.status, 0);
assert.match(result.stderr, /extension does not match/);

await fs.rm(root, {recursive: true, force: true});
console.log("Private channel music/SFX restore request tests passed.");

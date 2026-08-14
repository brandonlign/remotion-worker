#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const filePath = process.argv[2];
if (!filePath || !fs.existsSync(filePath)) process.exit(0);

const audioDesign = JSON.parse(fs.readFileSync(filePath, "utf8"));
if (audioDesign.qualityVersion !== 2) process.exit(0);

const candidates = Array.isArray(audioDesign.musicBeds)
  ? audioDesign.musicBeds
  : audioDesign.music
    ? [audioDesign.music]
    : [];

const ALLOWED_PRIVATE_LIBRARIES = new Set(["telic-original-v1", "channel-library-v1"]);
const rows = [];
const seen = new Set();
for (const music of candidates) {
  if (!ALLOWED_PRIVATE_LIBRARIES.has(music?.library)) {
    throw new Error("Private music request did not declare an approved channel-owned library.");
  }
  for (const [field, value] of [
    ["driveFolderId", music.driveFolderId],
    ["driveFileId", music.driveFileId],
  ]) {
    if (typeof value !== "string" || !/^[A-Za-z0-9_-]{10,128}$/.test(value)) {
      throw new Error(`Private music request has an invalid ${field}.`);
    }
  }
  if (typeof music.fileName !== "string" || !/^[A-Za-z0-9_. -]{3,128}\.mp3$/i.test(music.fileName)) {
    throw new Error("Private music request has an invalid fileName.");
  }
  if (
    typeof music.assetPath !== "string" ||
    !music.assetPath.startsWith("public/assets/current/") ||
    path.isAbsolute(music.assetPath) ||
    music.assetPath.split(/[\\/]/).includes("..")
  ) {
    throw new Error("Private music request has an unsafe assetPath.");
  }
  const key = `${music.driveFileId}\n${music.assetPath}`;
  if (seen.has(key)) continue;
  seen.add(key);
  rows.push([music.driveFolderId, music.driveFileId, music.fileName, music.assetPath].join("\t"));
}

process.stdout.write(rows.join("\n") + (rows.length ? "\n" : ""));

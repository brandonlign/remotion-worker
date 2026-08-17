#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const filePath = process.argv[2];
if (!filePath || !fs.existsSync(filePath)) process.exit(0);

const audioDesign = JSON.parse(fs.readFileSync(filePath, "utf8"));
const musicCandidates = Array.isArray(audioDesign.musicBeds)
  ? audioDesign.musicBeds
  : audioDesign.music
    ? [audioDesign.music]
    : [];
const sfxCandidates = Array.isArray(audioDesign.soundEffects)
  ? audioDesign.soundEffects.filter((cue) => cue?.library != null)
  : [];

// Telic quality-v2, channel-owned libraries, and the shared Universal SFX
// library all use the same private Drive transport contract. The public worker
// sees only provider identities and destination paths; it never commits or
// logs the private media itself.
const hasPrivateLibraryRequest =
  musicCandidates.some((item) => ["channel-library-v1", "telic-original-v1"].includes(item?.library)) ||
  sfxCandidates.some((item) => ["channel-library-v1", "universal-sfx-v1"].includes(item?.library)) ||
  audioDesign.musicLibrarySelection?.library === "channel-library-v1";
if (audioDesign.qualityVersion !== 2 && !hasPrivateLibraryRequest) process.exit(0);

const candidates = [
  ...musicCandidates.map((item) => ({kind: "music", item})),
  ...sfxCandidates.map((item) => ({kind: "sfx", item})),
];
const ALLOWED_PRIVATE_MUSIC_LIBRARIES = new Set(["telic-original-v1", "channel-library-v1"]);
const ALLOWED_PRIVATE_SFX_LIBRARIES = new Set(["channel-library-v1", "universal-sfx-v1"]);
const rows = [];
const seen = new Set();

for (const {kind, item} of candidates) {
  if (kind === "music") {
    if (!ALLOWED_PRIVATE_MUSIC_LIBRARIES.has(item?.library)) {
      throw new Error("Private music request did not declare an approved library.");
    }
  } else if (!ALLOWED_PRIVATE_SFX_LIBRARIES.has(item?.library)) {
    throw new Error("Private SFX request did not declare an approved channel or Universal SFX library.");
  }

  for (const [field, value] of [
    ["driveFolderId", item.driveFolderId],
    ["driveFileId", item.driveFileId],
  ]) {
    if (typeof value !== "string" || !/^[A-Za-z0-9_-]{10,128}$/.test(value)) {
      throw new Error(`Private ${kind} request has an invalid ${field}.`);
    }
  }

  const filePattern = kind === "music"
    ? /^[A-Za-z0-9_. -]{3,128}\.mp3$/i
    : /^[A-Za-z0-9_. -]{3,128}\.(?:wav|mp3)$/i;
  if (typeof item.fileName !== "string" || !filePattern.test(item.fileName)) {
    throw new Error(`Private ${kind} request has an invalid fileName.`);
  }
  if (
    typeof item.assetPath !== "string" ||
    !item.assetPath.startsWith("public/assets/current/") ||
    path.isAbsolute(item.assetPath) ||
    item.assetPath.split(/[\\/]/).includes("..")
  ) {
    throw new Error(`Private ${kind} request has an unsafe assetPath.`);
  }
  if (path.extname(item.assetPath).toLowerCase() !== path.extname(item.fileName).toLowerCase()) {
    throw new Error(`Private ${kind} request assetPath extension does not match fileName.`);
  }

  const key = `${item.driveFileId}\n${item.assetPath}`;
  if (seen.has(key)) continue;
  seen.add(key);
  rows.push([item.driveFolderId, item.driveFileId, item.fileName, item.assetPath].join("\t"));
}

process.stdout.write(rows.join("\n") + (rows.length ? "\n" : ""));

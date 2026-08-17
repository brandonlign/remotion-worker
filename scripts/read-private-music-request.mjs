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

// Telic quality-v2 and channel-owned audio plans both use the same private
// Drive transport contract. Preserve the old qualityVersion guard for legacy
// Telic packages, while allowing a channel-library-v1 plan (such as Coffee)
// to request only the exact provider-identified files it declares.
const hasChannelLibraryRequest =
  musicCandidates.some((item) => item?.library === "channel-library-v1") ||
  sfxCandidates.some((item) => item?.library === "channel-library-v1") ||
  audioDesign.musicLibrarySelection?.library === "channel-library-v1";
if (audioDesign.qualityVersion !== 2 && !hasChannelLibraryRequest) process.exit(0);

const candidates = [
  ...musicCandidates.map((item) => ({kind: "music", item})),
  ...sfxCandidates.map((item) => ({kind: "sfx", item})),
];
const ALLOWED_PRIVATE_MUSIC_LIBRARIES = new Set(["telic-original-v1", "channel-library-v1"]);
const rows = [];
const seen = new Set();

for (const {kind, item} of candidates) {
  if (kind === "music") {
    if (!ALLOWED_PRIVATE_MUSIC_LIBRARIES.has(item?.library)) {
      throw new Error("Private music request did not declare an approved channel-owned library.");
    }
  } else if (item?.library !== "channel-library-v1") {
    throw new Error("Private SFX request did not declare the approved channel-owned library.");
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

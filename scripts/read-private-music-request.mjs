#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const filePath = process.argv[2];
const sourceRootArg = process.argv[3];
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

let registered = null;
if (sourceRootArg) {
  const sourceRoot = path.resolve(sourceRootArg);
  const jobPath = path.join(sourceRoot, "automation", "current", "job.json");
  const job = JSON.parse(fs.readFileSync(jobPath, "utf8"));
  const channelId = String(job.channelId ?? job.jobId?.split("-")[0] ?? "").trim();
  if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(channelId)) {
    throw new Error("Private channel audio source has no valid channel identity.");
  }
  const profilePath = path.join(sourceRoot, "tools", "telic-vnext", "channels", channelId, "source-profile.json");
  const profile = JSON.parse(fs.readFileSync(profilePath, "utf8"));
  const relativeLibraryPath = profile.audio?.libraryPath ?? `tools/telic-vnext/channels/${channelId}/audio-library.json`;
  const libraryPath = path.resolve(sourceRoot, relativeLibraryPath);
  const rootPrefix = `${sourceRoot}${path.sep}`;
  if (libraryPath !== sourceRoot && !libraryPath.startsWith(rootPrefix)) {
    throw new Error("Private channel audio library path escapes the source checkout.");
  }
  const library = JSON.parse(fs.readFileSync(libraryPath, "utf8"));
  registered = new Set();
  for (const kind of ["music", "sfx"]) {
    for (const item of Array.isArray(library[kind]) ? library[kind] : []) {
      registered.add(JSON.stringify([
        kind,
        item.library,
        item.driveFolderId,
        item.driveFileId,
        item.fileName,
        item.assetPath,
      ]));
    }
  }
}

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

  if (registered) {
    const identity = JSON.stringify([
      kind,
      item.library,
      item.driveFolderId,
      item.driveFileId,
      item.fileName,
      item.assetPath,
    ]);
    if (!registered.has(identity)) {
      throw new Error(`Private ${kind} request is not present in the immutable source audio registry.`);
    }
  }

  const key = `${item.driveFileId}\n${item.assetPath}`;
  if (seen.has(key)) continue;
  seen.add(key);
  rows.push([item.driveFolderId, item.driveFileId, item.fileName, item.assetPath].join("\t"));
}

process.stdout.write(rows.join("\n") + (rows.length ? "\n" : ""));

#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const filePath = process.argv[2];
if (!filePath || !fs.existsSync(filePath)) process.exit(0);

const audioDesign = JSON.parse(fs.readFileSync(filePath, "utf8"));
const rows = [];
const seen = new Set();

const pushAsset = (asset, label, {requireQualityV2Library = false} = {}) => {
  if (requireQualityV2Library && asset?.library !== "telic-original-v1") {
    throw new Error("Private quality-v2 audio design did not request the Telic music library.");
  }
  for (const [field, value] of [
    ["driveFolderId", asset?.driveFolderId],
    ["driveFileId", asset?.driveFileId],
  ]) {
    if (typeof value !== "string" || !/^[A-Za-z0-9_-]{10,128}$/.test(value)) {
      throw new Error(`Private ${label} request has an invalid ${field}.`);
    }
  }
  if (typeof asset?.fileName !== "string" || !/^[A-Za-z0-9_. -]{3,128}\.(mp3|wav)$/i.test(asset.fileName)) {
    throw new Error(`Private ${label} request has an invalid fileName.`);
  }
  if (
    typeof asset?.assetPath !== "string" ||
    !asset.assetPath.startsWith("public/assets/current/") ||
    path.isAbsolute(asset.assetPath) ||
    asset.assetPath.split(/[\\/]/).includes("..")
  ) {
    throw new Error(`Private ${label} request has an unsafe assetPath.`);
  }
  const key = `${asset.driveFileId}\n${asset.assetPath}`;
  if (seen.has(key)) return;
  seen.add(key);
  rows.push([asset.driveFolderId, asset.driveFileId, asset.fileName, asset.assetPath].join("\t"));
};

if (audioDesign.qualityVersion === 2) {
  const candidates = Array.isArray(audioDesign.musicBeds)
    ? audioDesign.musicBeds
    : audioDesign.music
      ? [audioDesign.music]
      : [];
  for (const music of candidates) {
    pushAsset(music, "music", {requireQualityV2Library: true});
  }
} else if (audioDesign.registry === "config/telic-audio-library.json") {
  if (audioDesign.musicLibrarySelection) {
    pushAsset(audioDesign.musicLibrarySelection, "music");
  }
  for (const music of Array.isArray(audioDesign.musicBeds) ? audioDesign.musicBeds : []) {
    pushAsset(music, "music");
  }
  for (const effect of Array.isArray(audioDesign.soundEffects) ? audioDesign.soundEffects : []) {
    pushAsset(effect, "SFX");
  }
} else {
  process.exit(0);
}

process.stdout.write(rows.join("\n") + (rows.length ? "\n" : ""));

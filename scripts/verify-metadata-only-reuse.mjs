#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

const [currentDirArg, renderDirArg, currentSha, renderSha] = process.argv.slice(2);
if (!currentDirArg || !renderDirArg || !currentSha || !renderSha) {
  throw new Error("Usage: verify-metadata-only-reuse.mjs <current-source-dir> <render-source-dir> <current-sha> <render-sha>");
}
if (!/^[0-9a-f]{40}$/.test(currentSha) || !/^[0-9a-f]{40}$/.test(renderSha)) {
  throw new Error("Source SHAs must be complete lowercase commit SHAs.");
}

// An identical immutable Git commit is already the strongest possible source
// identity proof. Do not traverse the two working trees in this case: checkout
// implementation details (for example symlinks or generated filesystem entries)
// must not be able to turn exact-source media reuse into a false negative.
if (currentSha === renderSha) {
  console.log(`Verified exact-source render reuse at ${currentSha}.`);
  process.exit(0);
}

const YOUTUBE_PATH = "automation/current/youtube.json";
const CONFIG_PATH = "automation/config.json";
const ALLOWED_CHANGED_PATHS = new Set([YOUTUBE_PATH, CONFIG_PATH]);
const IGNORED_DIRS = new Set([".git", "node_modules"]);

const hashBytes = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");
const digestFile = async (file) => hashBytes(await fs.readFile(file));
const digestSymlink = async (file) => hashBytes(`symlink:${await fs.readlink(file)}`);
const clone = (value) => JSON.parse(JSON.stringify(value));

const verifyNonRenderingPolicyChange = async (currentRoot, renderRoot) => {
  const [currentConfig, renderConfig] = await Promise.all([
    fs.readFile(path.join(currentRoot, CONFIG_PATH), "utf8").then(JSON.parse),
    fs.readFile(path.join(renderRoot, CONFIG_PATH), "utf8").then(JSON.parse),
  ]);
  const currentMaximum = Number(currentConfig?.longForm?.maximumDurationSeconds);
  const renderMaximum = Number(renderConfig?.longForm?.maximumDurationSeconds);
  const currentQualityMaximum = Number(currentConfig?.longForm?.quality?.maximumDurationSeconds);
  const renderQualityMaximum = Number(renderConfig?.longForm?.quality?.maximumDurationSeconds);

  for (const [label, value] of [
    ["current long-form maximum duration", currentMaximum],
    ["render long-form maximum duration", renderMaximum],
    ["current long-form QC maximum duration", currentQualityMaximum],
    ["render long-form QC maximum duration", renderQualityMaximum],
  ]) {
    if (!Number.isFinite(value) || value <= 0) throw new Error(`Render reuse refused because ${label} is invalid.`);
  }
  if (currentMaximum < renderMaximum || currentQualityMaximum < renderQualityMaximum) {
    throw new Error("Render reuse refused because the long-form duration policy became stricter after rendering.");
  }
  if (currentQualityMaximum > currentMaximum) {
    throw new Error("Render reuse refused because the long-form QC maximum exceeds the production maximum.");
  }

  const normalizedCurrent = clone(currentConfig);
  normalizedCurrent.longForm.maximumDurationSeconds = renderMaximum;
  normalizedCurrent.longForm.quality.maximumDurationSeconds = renderQualityMaximum;
  if (JSON.stringify(normalizedCurrent) !== JSON.stringify(renderConfig)) {
    throw new Error("Render reuse refused because automation/config.json changed outside the non-rendering long-form duration policy.");
  }
};

const snapshot = async (root) => {
  const result = new Map();
  const visit = async (dir, relative = "") => {
    for (const entry of await fs.readdir(dir, {withFileTypes: true})) {
      if (entry.isDirectory() && IGNORED_DIRS.has(entry.name)) continue;
      const rel = relative ? `${relative}/${entry.name}` : entry.name;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await visit(full, rel);
      else if (entry.isFile()) result.set(rel, `file:${await digestFile(full)}`);
      else if (entry.isSymbolicLink()) result.set(rel, `symlink:${await digestSymlink(full)}`);
      else throw new Error(`Unsupported source entry while proving metadata-only reuse: ${rel}`);
    }
  };
  await visit(path.resolve(root));
  return result;
};

const currentRoot = path.resolve(currentDirArg);
const renderRoot = path.resolve(renderDirArg);
const current = await snapshot(currentRoot);
const rendered = await snapshot(renderRoot);
const changed = [...new Set([...current.keys(), ...rendered.keys()])]
  .filter((file) => current.get(file) !== rendered.get(file))
  .sort();
const unauthorized = changed.filter((file) => !ALLOWED_CHANGED_PATHS.has(file));

if (unauthorized.length > 0) {
  throw new Error(`Render reuse refused because non-metadata source changed: ${unauthorized.join(", ")}`);
}
if (changed.length === 0) {
  throw new Error("Different source SHAs have no observable metadata change; refusing ambiguous reuse.");
}
if (changed.includes(CONFIG_PATH)) {
  await verifyNonRenderingPolicyChange(currentRoot, renderRoot);
}

console.log(`Verified metadata/policy-only render reuse from ${renderSha} to ${currentSha}: ${changed.join(", ")}`);

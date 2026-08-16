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

const ALLOWED_CHANGED_PATHS = new Set(["automation/current/youtube.json"]);
const IGNORED_DIRS = new Set([".git", "node_modules"]);

const hashBytes = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");
const digestFile = async (file) => hashBytes(await fs.readFile(file));
const digestSymlink = async (file) => hashBytes(`symlink:${await fs.readlink(file)}`);

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

const current = await snapshot(currentDirArg);
const rendered = await snapshot(renderDirArg);
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

console.log(`Verified metadata-only render reuse from ${renderSha} to ${currentSha}: ${changed.join(", ")}`);

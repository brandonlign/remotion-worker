#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const file = process.argv[2];
if (!file) throw new Error("Usage: validate-controller-check.mjs <request.json>");

const request = JSON.parse(fs.readFileSync(file, "utf8"));
const allowed = new Set(["sourceSha", "revision"]);
for (const key of Object.keys(request)) {
  if (!allowed.has(key)) throw new Error(`Unsupported controller-check field: ${key}`);
}
if (typeof request.sourceSha !== "string" || !/^[0-9a-f]{40}$/.test(request.sourceSha)) {
  throw new Error("sourceSha must be a complete lowercase 40-character commit SHA.");
}
if (!Number.isInteger(request.revision) || request.revision < 1 || request.revision > 1000) {
  throw new Error("revision must be an integer from 1 through 1000.");
}

if (process.env.GITHUB_OUTPUT) {
  fs.appendFileSync(process.env.GITHUB_OUTPUT, `source_sha=${request.sourceSha}\nrevision=${request.revision}\n`);
}
console.log(`Validated ${path.basename(file)} for private controller installation.`);

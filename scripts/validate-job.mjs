#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const file = process.argv[2];
if (!file) {
  throw new Error("Usage: validate-job.mjs <request.json>");
}

const request = JSON.parse(fs.readFileSync(file, "utf8"));
const allowedKeys = new Set(["jobId", "sourceSha", "revision"]);
for (const key of Object.keys(request)) {
  if (!allowedKeys.has(key)) {
    throw new Error(`Unsupported request field: ${key}`);
  }
}

if (typeof request.jobId !== "string" || !/^[a-z0-9][a-z0-9-]{5,63}$/.test(request.jobId)) {
  throw new Error("jobId must be 6-64 lowercase letters, numbers, or hyphens.");
}

if (typeof request.sourceSha !== "string" || !/^[0-9a-f]{40}$/.test(request.sourceSha)) {
  throw new Error("sourceSha must be a complete lowercase 40-character commit SHA.");
}

if (!Number.isInteger(request.revision) || request.revision < 1 || request.revision > 1000) {
  throw new Error("revision must be an integer from 1 through 1000.");
}

const githubOutput = process.env.GITHUB_OUTPUT;
if (githubOutput) {
  fs.appendFileSync(
    githubOutput,
    `job_id=${request.jobId}\nsource_sha=${request.sourceSha}\nrevision=${request.revision}\n`,
  );
}

console.log(`Validated ${path.basename(file)}.`);

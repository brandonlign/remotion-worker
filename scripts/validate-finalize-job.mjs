#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const file = process.argv[2];
if (!file) throw new Error("Usage: validate-finalize-job.mjs <request.json>");

const request = JSON.parse(fs.readFileSync(file, "utf8"));
const allowedKeys = new Set(["jobId", "sourceSha", "renderSourceSha", "revision", "reuseRevision"]);
for (const key of Object.keys(request)) {
  if (!allowedKeys.has(key)) throw new Error(`Unsupported finalize request field: ${key}`);
}

if (typeof request.jobId !== "string" || !/^[a-z0-9][a-z0-9-]{5,63}$/.test(request.jobId)) {
  throw new Error("jobId must be 6-64 lowercase letters, numbers, or hyphens.");
}
const channelId = request.jobId.split("-", 1)[0];
if (!new Set(["telic", "coffee"]).has(channelId)) {
  throw new Error(`Unsupported channel prefix in jobId: ${channelId}`);
}

for (const field of ["sourceSha", "renderSourceSha"]) {
  if (typeof request[field] !== "string" || !/^[0-9a-f]{40}$/.test(request[field])) {
    throw new Error(`${field} must be a complete lowercase 40-character commit SHA.`);
  }
}
for (const field of ["revision", "reuseRevision"]) {
  if (!Number.isInteger(request[field]) || request[field] < 1 || request[field] > 1000) {
    throw new Error(`${field} must be an integer from 1 through 1000.`);
  }
}
if (request.reuseRevision >= request.revision) {
  throw new Error("reuseRevision must be older than the finalize revision.");
}

const requestKey = [
  request.jobId,
  request.sourceSha,
  request.renderSourceSha,
  `r${request.revision}`,
  `reuse-r${request.reuseRevision}`,
  "finalize",
].join("-");

if (process.env.GITHUB_OUTPUT) {
  fs.appendFileSync(process.env.GITHUB_OUTPUT,
    `job_id=${request.jobId}\nchannel_id=${channelId}\nsource_sha=${request.sourceSha}\nrender_source_sha=${request.renderSourceSha}\nrevision=${request.revision}\nreuse_revision=${request.reuseRevision}\nrequest_key=${requestKey}\n`);
}

console.log(`Validated ${path.basename(file)} for ${channelId} metadata-only finalization.`);

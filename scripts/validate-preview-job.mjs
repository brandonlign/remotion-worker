#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const file = process.argv[2];
if (!file) throw new Error("Usage: validate-preview-job.mjs <preview-request.json>");

const request = JSON.parse(fs.readFileSync(file, "utf8"));
const allowedKeys = new Set(["jobId", "sourceSha", "revision", "mode"]);
for (const key of Object.keys(request)) {
  if (!allowedKeys.has(key)) throw new Error(`Unsupported preview request field: ${key}`);
}

if (typeof request.jobId !== "string" || !/^[a-z0-9][a-z0-9-]{5,63}$/.test(request.jobId)) {
  throw new Error("jobId must be 6-64 lowercase letters, numbers, or hyphens.");
}
const channelId = request.jobId.split("-", 1)[0];
if (!new Set(["telic", "coffee"]).has(channelId)) {
  throw new Error(`Unsupported channel prefix in jobId: ${channelId}`);
}
if (typeof request.sourceSha !== "string" || !/^[0-9a-f]{40}$/.test(request.sourceSha)) {
  throw new Error("sourceSha must be a complete lowercase 40-character commit SHA.");
}
if (!Number.isInteger(request.revision) || request.revision < 1 || request.revision > 1000) {
  throw new Error("revision must be an integer from 1 through 1000.");
}
if (request.mode !== "short-preview") throw new Error("mode must be short-preview.");

const requestKey = [request.jobId, request.sourceSha, `p${request.revision}`].join("-");
const githubOutput = process.env.GITHUB_OUTPUT;
if (githubOutput) {
  fs.appendFileSync(
    githubOutput,
    `job_id=${request.jobId}\nchannel_id=${channelId}\nsource_sha=${request.sourceSha}\nrevision=${request.revision}\nrequest_key=${requestKey}\n`,
  );
}

console.log(`Validated ${path.basename(file)} for ${channelId} short QC preview.`);

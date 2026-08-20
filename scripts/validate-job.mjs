#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const file = process.argv[2];
if (!file) {
  throw new Error("Usage: validate-job.mjs <request.json>");
}

const request = JSON.parse(fs.readFileSync(file, "utf8"));
const allowedKeys = new Set([
  "jobId",
  "sourceSha",
  "sourceRepository",
  "sourceIssueNumber",
  "revision",
  "mode",
  "sequenceIndex",
]);
for (const key of Object.keys(request)) {
  if (!allowedKeys.has(key)) throw new Error(`Unsupported request field: ${key}`);
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
if (typeof request.sourceRepository !== "string" || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(request.sourceRepository)) {
  throw new Error("sourceRepository must be an explicit owner/name repository identity.");
}
if (!Number.isInteger(request.sourceIssueNumber) || request.sourceIssueNumber < 1 || request.sourceIssueNumber > 1_000_000_000) {
  throw new Error("sourceIssueNumber must be a positive GitHub issue number.");
}
const expectedRepository = String(process.env.EXPECTED_SOURCE_REPOSITORY ?? "brandonlign/remotion-video").trim();
if (request.sourceRepository !== expectedRepository) {
  throw new Error(`sourceRepository ${request.sourceRepository} does not match configured source repository ${expectedRepository}.`);
}

if (!Number.isInteger(request.revision) || request.revision < 1 || request.revision > 1000) {
  throw new Error("revision must be an integer from 1 through 1000.");
}

const mode = request.mode ?? "render";
if (!new Set(["voice-prep", "render-sequence", "render"]).has(mode)) {
  throw new Error("mode must be voice-prep, render-sequence, or render.");
}

let sequenceIndex = "";
if (mode === "render-sequence") {
  if (!Number.isInteger(request.sequenceIndex) || request.sequenceIndex < 0 || request.sequenceIndex > 39) {
    throw new Error("render-sequence requires sequenceIndex from 0 through 39.");
  }
  sequenceIndex = String(request.sequenceIndex);
} else if (request.sequenceIndex != null) {
  throw new Error("sequenceIndex is only valid for render-sequence requests.");
}

const requestKey = [
  request.jobId,
  request.sourceSha,
  `i${request.sourceIssueNumber}`,
  `r${request.revision}`,
  mode,
  sequenceIndex === "" ? null : `s${sequenceIndex}`,
].filter(Boolean).join("-");

const githubOutput = process.env.GITHUB_OUTPUT;
if (githubOutput) {
  fs.appendFileSync(
    githubOutput,
    [
      `job_id=${request.jobId}`,
      `channel_id=${channelId}`,
      `source_sha=${request.sourceSha}`,
      `source_repository=${request.sourceRepository}`,
      `source_issue_number=${request.sourceIssueNumber}`,
      `revision=${request.revision}`,
      `mode=${mode}`,
      `sequence_index=${sequenceIndex}`,
      `request_key=${requestKey}`,
      "",
    ].join("\n"),
  );
}

console.log(`Validated ${path.basename(file)} for ${channelId} in ${mode} mode with explicit source issue #${request.sourceIssueNumber}.`);

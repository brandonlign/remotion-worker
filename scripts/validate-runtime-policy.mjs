#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {fileURLToPath} from "node:url";
import {resolveQualityPolicy} from "./quality-policy.mjs";

const readJson = async (filePath) => JSON.parse(await fs.readFile(filePath, "utf8"));
const readOptionalJson = async (filePath) => {
  try { return await readJson(filePath); }
  catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
};

export const validateRuntimePolicy = async (sourceDirArg) => {
  const sourceDir = path.resolve(sourceDirArg);
  const [job, config, runtime] = await Promise.all([
    readJson(path.join(sourceDir, "automation/current/job.json")),
    readJson(path.join(sourceDir, "automation/config.json")),
    readJson(path.join(sourceDir, "automation/current/audio-runtime.json")),
  ]);
  const sourceProfile = job?.channelId
    ? await readOptionalJson(path.join(sourceDir, "tools", "telic-vnext", "channels", String(job.channelId), "source-profile.json"))
    : null;
  const policy = resolveQualityPolicy(job, config, sourceProfile);
  const durationSeconds = Number(runtime?.durationSeconds);

  if (runtime?.jobId !== job?.jobId) throw new Error("audio-runtime.json jobId does not match job.json.");
  if (runtime?.format && runtime.format !== job?.format) throw new Error("audio-runtime.json format does not match job.json.");
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) throw new Error("audio-runtime.json durationSeconds is invalid.");
  if (durationSeconds < policy.minimumDurationSeconds || durationSeconds > policy.maximumDurationSeconds) {
    throw new Error(`Locked ${policy.format} runtime ${durationSeconds.toFixed(3)}s is outside the channel policy ${policy.minimumDurationSeconds}-${policy.maximumDurationSeconds}s.`);
  }

  return {
    jobId: job.jobId,
    format: policy.format,
    durationSeconds,
    minimumDurationSeconds: policy.minimumDurationSeconds,
    maximumDurationSeconds: policy.maximumDurationSeconds,
    policySource: sourceProfile ? "channel-source-profile" : "legacy-config",
  };
};

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const sourceDir = process.argv[2];
  if (!sourceDir) throw new Error("Usage: validate-runtime-policy.mjs <private-source-dir>");
  validateRuntimePolicy(sourceDir)
    .then((result) => console.log(`Validated locked ${result.format} runtime ${result.durationSeconds.toFixed(3)}s against ${result.policySource} ${result.minimumDurationSeconds}-${result.maximumDurationSeconds}s.`))
    .catch((error) => {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    });
}

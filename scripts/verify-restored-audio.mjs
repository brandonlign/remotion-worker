#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";

const SHA256_PATTERN = /^[0-9a-f]{64}$/;

const readJson = async (filePath) => JSON.parse(await fs.readFile(filePath, "utf8"));
const readJsonOptional = async (filePath) => {
  try { return await readJson(filePath); }
  catch (error) { if (error?.code === "ENOENT") return null; throw error; }
};
const stable = (value) => {
  if (Array.isArray(value)) return value.map(stable);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, nested]) => [key, stable(nested)]));
};
const fingerprint = (value) => JSON.stringify(stable(value));
const sha256File = async (filePath) => crypto.createHash("sha256").update(await fs.readFile(filePath)).digest("hex");

const verifyLongAudio = async ({runtime, audioPath, expectedJobId = null}) => {
  if (runtime?.format !== "long") throw new Error("Committed source runtime is not long form.");
  if (expectedJobId && runtime.jobId !== expectedJobId) {
    throw new Error("Committed long-form audio runtime does not match the requested job ID.");
  }
  const expected = String(runtime.voiceoverSha256 ?? "").trim().toLowerCase();
  if (!SHA256_PATTERN.test(expected)) throw new Error("Committed long-form runtime has no valid voiceoverSha256 lock.");
  const actual = await sha256File(audioPath);
  if (actual !== expected) throw new Error("Restored long-form voiceover.mp3 does not match the committed runtime hash.");
  return {format: "long", runtime, voiceoverSha256: actual};
};

export const verifyCommittedLongAudio = async ({sourceRuntimePath, audioPath, expectedJobId}) => {
  const runtime = await readJson(sourceRuntimePath);
  return verifyLongAudio({runtime, audioPath, expectedJobId});
};

export const verifyRestoredAudio = async ({sourceRuntimePath, driveRuntimePath, audioPath}) => {
  const [sourceRuntime, driveRuntime] = await Promise.all([
    readJsonOptional(sourceRuntimePath),
    readJson(driveRuntimePath),
  ]);

  // The checked-out private source is authoritative for format. A committed
  // long-form runtime may never be downgraded into the legacy Short restore path
  // merely because the Drive copy is malformed or has lost its format field.
  if (sourceRuntime?.format === "long") {
    if (driveRuntime?.format !== "long") {
      throw new Error("Drive audio runtime attempted to downgrade a committed long-form runtime.");
    }
    if (sourceRuntime.jobId !== driveRuntime.jobId) throw new Error("Committed and Drive long-form audio runtimes have different job IDs.");
    if (fingerprint(sourceRuntime) !== fingerprint(driveRuntime)) {
      throw new Error("Drive long-form audio-runtime.json drifted from the committed frozen source runtime.");
    }
    return verifyLongAudio({runtime: sourceRuntime, audioPath});
  }

  if (driveRuntime?.format === "long") {
    throw new Error("Drive runtime is long form but the committed source has no authoritative long-form runtime.");
  }
  return {format: "short", runtime: driveRuntime};
};

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const args = process.argv.slice(2);
  if (args[0] === "--committed-long") {
    const [, sourceRuntimePath, audioPath, expectedJobId] = args;
    if (!sourceRuntimePath || !audioPath || !expectedJobId) {
      throw new Error("Usage: node scripts/verify-restored-audio.mjs --committed-long <source-runtime.json> <voiceover.mp3> <job-id>");
    }
    const result = await verifyCommittedLongAudio({sourceRuntimePath, audioPath, expectedJobId});
    process.stdout.write(`${result.format}\n`);
  } else {
    const [sourceRuntimePath, driveRuntimePath, audioPath] = args;
    if (!sourceRuntimePath || !driveRuntimePath || !audioPath) {
      throw new Error("Usage: node scripts/verify-restored-audio.mjs <source-runtime.json> <drive-runtime.json> <voiceover.mp3>");
    }
    const result = await verifyRestoredAudio({sourceRuntimePath, driveRuntimePath, audioPath});
    process.stdout.write(`${result.format}\n`);
  }
}

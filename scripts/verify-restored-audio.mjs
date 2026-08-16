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

const beatTiming = (beat) => ({
  id: beat?.id,
  startFrame: beat?.startFrame,
  spokenEndFrame: beat?.spokenEndFrame ?? null,
  endFrame: beat?.endFrame,
  durationInFrames: beat?.durationInFrames ?? null,
});

const voiceSegmentTiming = (segment) => ({
  id: segment?.id,
  beatIds: Array.isArray(segment?.beatIds) ? segment.beatIds : [],
  startFrame: segment?.startFrame,
  endFrame: segment?.endFrame,
});

// This is the durable binary/timing identity of a long-form voice package.
// Descriptive fields such as beat purpose/narration may be retained in the
// Drive voice-prep artifact and stripped from the later committed runtime; they
// do not change the waveform or exact alignment and must not invalidate it.
const longAudioContract = (runtime) => ({
  schemaVersion: runtime?.schemaVersion,
  format: runtime?.format,
  jobId: runtime?.jobId,
  channelId: runtime?.channelId ?? null,
  scriptSourceSha: runtime?.scriptSourceSha ?? null,
  narrationSha256: runtime?.narrationSha256 ?? null,
  voiceoverSha256: runtime?.voiceoverSha256 ?? null,
  fps: runtime?.fps,
  durationSeconds: runtime?.durationSeconds,
  totalDurationInFrames: runtime?.totalDurationInFrames,
  exactAlignment: runtime?.exactAlignment ?? null,
  alignmentProvider: runtime?.alignmentProvider ?? null,
  alignmentQuality: runtime?.alignmentQuality ?? null,
  voiceProvider: runtime?.voiceProvider ?? null,
  voiceName: runtime?.voiceName ?? null,
  voiceSegments: Array.isArray(runtime?.voiceSegments) ? runtime.voiceSegments.map(voiceSegmentTiming) : [],
  beats: Array.isArray(runtime?.beats) ? runtime.beats.map(beatTiming) : [],
});

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

  if (sourceRuntime?.format === "long") {
    if (driveRuntime?.format !== "long") {
      throw new Error("Drive audio runtime attempted to downgrade a committed long-form runtime.");
    }
    if (sourceRuntime.jobId !== driveRuntime.jobId) throw new Error("Committed and Drive long-form audio runtimes have different job IDs.");
    if (fingerprint(longAudioContract(sourceRuntime)) !== fingerprint(longAudioContract(driveRuntime))) {
      throw new Error("Drive long-form audio contract drifted from the committed frozen source timing/identity.");
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

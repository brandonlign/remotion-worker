#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {spawn} from "node:child_process";
import {resolveQualityPolicy} from "./quality-policy.mjs";

const readJson = async (filePath) => JSON.parse(await fs.readFile(filePath, "utf8"));

const runCapture = (command, args) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, args, {stdio: ["ignore", "pipe", "pipe"]});
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) return resolve({stdout, stderr});
      reject(new Error(signal ? `${command} ended with ${signal}.` : `${command} exited with code ${code}.`));
    });
  });

const extractDurations = (text, label) => {
  const expression = new RegExp(`${label}:([0-9.]+)`, "g");
  return [...text.matchAll(expression)].map((match) => Number(match[1])).filter((value) => Number.isFinite(value));
};

const listSampledFrames = async (keyframesDir, maximumFrames) => {
  const names = (await fs.readdir(keyframesDir)).filter((name) => /^frame-\d+\.jpg$/i.test(name)).sort((left, right) => left.localeCompare(right));
  if (names.length < 3) throw new Error("The review package has too few keyframes.");
  const count = Math.min(names.length, maximumFrames);
  const selectedIndexes = new Set();
  for (let index = 0; index < count; index += 1) selectedIndexes.add(Math.round((index * (names.length - 1)) / Math.max(1, count - 1)));
  return [...selectedIndexes].sort((a, b) => a - b).map((index) => {
    const name = names[index];
    const frameNumber = Number(name.match(/(\d+)/)?.[1]);
    return {name, frameNumber, timestampSeconds: Math.max(0, (frameNumber - 1) * 2)};
  });
};

const inspectLongThumbnail = async (resultDir, status) => {
  if (!status.thumbnailCompositionId) return {issue: "The long-form render did not declare a thumbnail composition.", metadata: null};
  const thumbnailPath = path.join(resultDir, "thumbnail.png");
  const stat = await fs.stat(thumbnailPath).catch(() => null);
  if (!stat?.isFile() || stat.size < 10_000) return {issue: "The long-form thumbnail artifact is missing or too small.", metadata: null};
  if (stat.size > 50 * 1024 * 1024) return {issue: "The long-form thumbnail exceeds YouTube's 50 MB desktop upload limit.", metadata: {sizeBytes: stat.size}};
  const probe = await runCapture("ffprobe", [
    "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", thumbnailPath,
  ]);
  const parsed = JSON.parse(probe.stdout || "{}");
  const stream = Array.isArray(parsed.streams) ? parsed.streams[0] : null;
  const width = Number(stream?.width);
  const height = Number(stream?.height);
  if (width !== 1920 || height !== 1080) return {issue: "The long-form thumbnail must be 1920 by 1080.", metadata: {sizeBytes: stat.size, width, height}};
  return {issue: null, metadata: {sizeBytes: stat.size, width, height}};
};

const main = async () => {
  const [resultArg, jobArg, configArg] = process.argv.slice(2);
  if (!resultArg || !jobArg || !configArg) throw new Error("Usage: deterministic-quality-gate.mjs <render-result-dir> <job.json> <config.json>");

  const resultDir = path.resolve(resultArg);
  const outputPath = path.join(resultDir, "quality-gate.json");
  const [status, job, config, metadata] = await Promise.all([
    readJson(path.join(resultDir, "status.json")),
    readJson(path.resolve(jobArg)),
    readJson(path.resolve(configArg)),
    readJson(path.join(resultDir, "media-metadata.json")),
  ]);
  const {format, quality, expectedWidth, expectedHeight, minimumDurationSeconds, maximumDurationSeconds, maximumFrames} = resolveQualityPolicy(job, config);

  const videoPath = path.join(resultDir, `${status.outputName}.mp4`);
  const stat = await fs.stat(videoPath);
  if (!stat.isFile() || stat.size < 100_000) throw new Error("The final rendered video is missing or too small.");

  const streams = Array.isArray(metadata.streams) ? metadata.streams : [];
  const videoStreams = streams.filter((stream) => stream.codec_type === "video");
  const audioStreams = streams.filter((stream) => stream.codec_type === "audio");
  const durationSeconds = Number(metadata.format?.duration ?? videoStreams[0]?.duration);
  const issues = [];

  if (videoStreams.length !== 1) issues.push("The final file must contain exactly one video stream.");
  if (audioStreams.length !== 1) issues.push("The final file must contain exactly one audio stream.");
  if (Number(videoStreams[0]?.width) !== expectedWidth || Number(videoStreams[0]?.height) !== expectedHeight) issues.push(`The final ${format} frame size is not ${expectedWidth} by ${expectedHeight}.`);
  if (!Number.isFinite(durationSeconds) || durationSeconds < minimumDurationSeconds || durationSeconds > maximumDurationSeconds) issues.push(`The final duration is outside the autonomous ${format} limits.`);

  const [black, silence, freeze] = await Promise.all([
    runCapture("ffmpeg", ["-hide_banner", "-loglevel", "info", "-i", videoPath, "-vf", `blackdetect=d=${quality.maximumBlackSeconds}:pic_th=0.98:pix_th=0.10`, "-an", "-f", "null", "-"]),
    runCapture("ffmpeg", ["-hide_banner", "-loglevel", "info", "-i", videoPath, "-af", `silencedetect=n=-45dB:d=${quality.maximumSilenceSeconds}`, "-vn", "-f", "null", "-"]),
    runCapture("ffmpeg", ["-hide_banner", "-loglevel", "info", "-i", videoPath, "-vf", `freezedetect=n=-50dB:d=${quality.maximumFreezeSeconds}`, "-an", "-f", "null", "-"]),
  ]);

  const blackDurations = extractDurations(black.stderr, "black_duration");
  const silenceDurations = extractDurations(silence.stderr, "silence_duration");
  const freezeDurations = extractDurations(freeze.stderr, "freeze_duration");
  if (blackDurations.some((value) => value >= quality.maximumBlackSeconds)) issues.push("The final video contains an extended black segment.");
  if (silenceDurations.some((value) => value >= quality.maximumSilenceSeconds)) issues.push("The final video contains an extended silent segment.");
  if (freezeDurations.some((value) => value >= quality.maximumFreezeSeconds)) issues.push("The final video contains an extended frozen segment.");

  let thumbnail = null;
  if (format === "long") {
    const inspected = await inspectLongThumbnail(resultDir, status);
    thumbnail = inspected.metadata;
    if (inspected.issue) issues.push(inspected.issue);
  }

  const sampledFrames = await listSampledFrames(path.join(resultDir, "keyframes"), maximumFrames);
  const passed = issues.length === 0;
  const report = {
    version: 4,
    jobId: job.jobId,
    format,
    styleMode: job.styleMode ?? config.styleMode ?? "pragma",
    status: passed ? "deterministic-passed" : "failed",
    reviewMode: "chatgpt-web-required",
    visualReviewRequired: true,
    completedAt: new Date().toISOString(),
    media: {
      sizeBytes: stat.size,
      durationSeconds,
      width: Number(videoStreams[0]?.width ?? 0),
      height: Number(videoStreams[0]?.height ?? 0),
      videoStreams: videoStreams.length,
      audioStreams: audioStreams.length,
      maximumBlackDurationSeconds: Math.max(0, ...blackDurations),
      maximumSilenceDurationSeconds: Math.max(0, ...silenceDurations),
      maximumFreezeDurationSeconds: Math.max(0, ...freezeDurations),
    },
    thumbnail,
    sampledFrames,
    deterministicIssues: issues,
  };
  await fs.writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, {mode: 0o600});

  if (!passed) {
    console.error(`The deterministic ${format} quality gate rejected the render.`);
    process.exitCode = 1;
    return;
  }
  console.log(`Deterministic ${format} media QC passed; private visual review is required in ChatGPT web.`);
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});

#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {spawn} from "node:child_process";
import {fileURLToPath} from "node:url";

const finite = (value, label) => {
  const number = Number(value);
  if (!Number.isFinite(number)) throw new Error(`${label} must be a finite number.`);
  return number;
};

export const normalizeMasteringPolicy = (input) => {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Audio mastering policy is missing or invalid.");
  const policy = {
    targetIntegratedLufs: finite(input.targetIntegratedLufs, "targetIntegratedLufs"),
    targetLoudnessRangeLu: finite(input.targetLoudnessRangeLu, "targetLoudnessRangeLu"),
    targetTruePeakDbtp: finite(input.targetTruePeakDbtp, "targetTruePeakDbtp"),
    integratedToleranceLufs: finite(input.integratedToleranceLufs, "integratedToleranceLufs"),
    truePeakToleranceDbtp: finite(input.truePeakToleranceDbtp, "truePeakToleranceDbtp"),
  };
  if (policy.targetIntegratedLufs < -40 || policy.targetIntegratedLufs > -5) throw new Error("targetIntegratedLufs is outside the supported mastering range.");
  if (policy.targetLoudnessRangeLu <= 0 || policy.targetLoudnessRangeLu > 50) throw new Error("targetLoudnessRangeLu is outside the supported mastering range.");
  if (policy.targetTruePeakDbtp > 0 || policy.targetTruePeakDbtp < -20) throw new Error("targetTruePeakDbtp is outside the supported mastering range.");
  if (policy.integratedToleranceLufs <= 0 || policy.integratedToleranceLufs > 5) throw new Error("integratedToleranceLufs is outside the supported mastering range.");
  if (policy.truePeakToleranceDbtp <= 0 || policy.truePeakToleranceDbtp > 5) throw new Error("truePeakToleranceDbtp is outside the supported mastering range.");
  return Object.freeze(policy);
};

export const resolveMasteringPolicy = (sourceProfile) => {
  const raw = sourceProfile?.audio?.mastering;
  return raw == null ? null : normalizeMasteringPolicy(raw);
};

export const parseLoudnormStats = (text) => {
  const end = text.lastIndexOf("}");
  const start = text.lastIndexOf("{", end);
  if (start < 0 || end <= start) throw new Error("FFmpeg loudnorm did not return its measurement JSON.");
  let parsed;
  try {
    parsed = JSON.parse(text.slice(start, end + 1));
  } catch (error) {
    throw new Error(`FFmpeg loudnorm returned invalid measurement JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  for (const field of ["input_i", "input_tp", "input_lra", "input_thresh", "target_offset"]) {
    if (!Number.isFinite(Number(parsed[field]))) throw new Error(`FFmpeg loudnorm measurement is missing a finite ${field}.`);
  }
  return parsed;
};

const runProcess = (command, args) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, args, {stdio: ["ignore", "pipe", "pipe"]});
    let stdout = "";
    let stderr = "";
    let settled = false;
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", (error) => {
      if (settled) return;
      settled = true;
      reject(error);
    });
    child.once("exit", (code, signal) => {
      if (settled) return;
      settled = true;
      if (code === 0) return resolve({stdout, stderr});
      const detail = stderr.trim().split("\n").slice(-8).join(" ");
      reject(new Error(signal ? `${command} ended with ${signal}. ${detail}` : `${command} exited with code ${code}. ${detail}`.trim()));
    });
  });

const loudnormFilter = (policy, measured = null) => {
  const fields = [
    `I=${policy.targetIntegratedLufs}`,
    `LRA=${policy.targetLoudnessRangeLu}`,
    `TP=${policy.targetTruePeakDbtp}`,
  ];
  if (measured) {
    fields.push(
      `measured_I=${measured.input_i}`,
      `measured_LRA=${measured.input_lra}`,
      `measured_TP=${measured.input_tp}`,
      `measured_thresh=${measured.input_thresh}`,
      `offset=${measured.target_offset}`,
      "linear=true",
    );
  }
  fields.push("print_format=json");
  return `loudnorm=${fields.join(":")}`;
};

const measurementFromStats = (stats, prefix) => ({
  integratedLufs: finite(stats[`${prefix}_i`], `${prefix}_i`),
  truePeakDbtp: finite(stats[`${prefix}_tp`], `${prefix}_tp`),
  loudnessRangeLu: finite(stats[`${prefix}_lra`], `${prefix}_lra`),
});

export const measureAudioLoudness = async (videoPath, policyInput, {runner = runProcess} = {}) => {
  const policy = normalizeMasteringPolicy(policyInput);
  const result = await runner("ffmpeg", [
    "-hide_banner", "-loglevel", "info", "-nostats",
    "-i", videoPath,
    "-map", "0:a:0", "-vn",
    "-af", loudnormFilter(policy),
    "-f", "null", "-",
  ]);
  const stats = parseLoudnormStats(result.stderr);
  return {
    ...measurementFromStats(stats, "input"),
    thresholdLufs: finite(stats.input_thresh, "input_thresh"),
    targetOffsetLufs: finite(stats.target_offset, "target_offset"),
  };
};

export const audioLoudnessIssues = ({measurement, policy: policyInput}) => {
  const policy = normalizeMasteringPolicy(policyInput);
  const issues = [];
  if (Math.abs(measurement.integratedLufs - policy.targetIntegratedLufs) > policy.integratedToleranceLufs) {
    issues.push(`Integrated loudness ${measurement.integratedLufs.toFixed(2)} LUFS is outside the ${policy.targetIntegratedLufs.toFixed(2)} ± ${policy.integratedToleranceLufs.toFixed(2)} LUFS target.`);
  }
  if (measurement.truePeakDbtp > policy.targetTruePeakDbtp + policy.truePeakToleranceDbtp) {
    issues.push(`True peak ${measurement.truePeakDbtp.toFixed(2)} dBTP exceeds the ${policy.targetTruePeakDbtp.toFixed(2)} dBTP ceiling.`);
  }
  return issues;
};

export const masterVideoAudio = async ({inputPath, outputPath, policy: policyInput, reportPath = null, runner = runProcess}) => {
  const policy = normalizeMasteringPolicy(policyInput);
  if (path.resolve(inputPath) === path.resolve(outputPath)) throw new Error("The mastered output must be separate from the rendered input.");

  const firstPass = await runner("ffmpeg", [
    "-hide_banner", "-loglevel", "info", "-nostats",
    "-i", inputPath,
    "-map", "0:a:0", "-vn",
    "-af", loudnormFilter(policy),
    "-f", "null", "-",
  ]);
  const measured = parseLoudnormStats(firstPass.stderr);
  const inputMeasurement = measurementFromStats(measured, "input");

  const secondPass = await runner("ffmpeg", [
    "-y", "-hide_banner", "-loglevel", "info", "-nostats",
    "-i", inputPath,
    "-map", "0:v:0", "-map", "0:a:0", "-map_metadata", "0", "-map_chapters", "0",
    "-af", loudnormFilter(policy, measured),
    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
    outputPath,
  ]);
  const masteredStats = parseLoudnormStats(secondPass.stderr);
  const outputMeasurement = measurementFromStats(masteredStats, "output");
  const issues = audioLoudnessIssues({measurement: outputMeasurement, policy});
  const report = {
    version: 1,
    status: issues.length ? "failed" : "passed",
    completedAt: new Date().toISOString(),
    policy,
    input: inputMeasurement,
    output: outputMeasurement,
    deterministicIssues: issues,
  };
  if (reportPath) {
    await fs.mkdir(path.dirname(reportPath), {recursive: true});
    await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, {mode: 0o600});
  }
  if (issues.length) throw new Error(`Final audio mastering failed: ${issues.join(" ")}`);
  const outputStat = await fs.stat(outputPath).catch(() => null);
  if (!outputStat?.isFile() || outputStat.size < 100_000) throw new Error("Final audio mastering did not produce a usable output video.");
  return report;
};

const main = async () => {
  const [inputPath, outputPath, profilePath, reportPath] = process.argv.slice(2);
  if (!inputPath || !outputPath || !profilePath) throw new Error("Usage: master-final-audio.mjs <input-video> <output-video> <source-profile.json> [report.json]");
  const profile = JSON.parse(await fs.readFile(profilePath, "utf8"));
  const policy = resolveMasteringPolicy(profile);
  if (!policy) throw new Error("The source profile does not declare audio.mastering policy.");
  const report = await masterVideoAudio({inputPath, outputPath, policy, reportPath});
  console.log(`Final audio mastering passed: ${report.output.integratedLufs.toFixed(2)} LUFS, ${report.output.truePeakDbtp.toFixed(2)} dBTP.`);
};

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}

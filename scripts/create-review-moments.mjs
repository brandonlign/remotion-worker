#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {spawn} from "node:child_process";
import {fileURLToPath} from "node:url";

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{1,63}$/;

export const resolveReviewMoments = (composition) => {
  const moments = composition?.reviewMoments;
  if (moments == null) return [];
  if (!Array.isArray(moments) || moments.length < 3 || moments.length > 16) {
    throw new Error("Semantic review moments must contain three to sixteen entries.");
  }
  const fps = Number(composition?.fps);
  const duration = Number(composition?.durationInFrames);
  if (!Number.isFinite(fps) || fps <= 0 || !Number.isInteger(duration) || duration <= 0) {
    throw new Error("Composition fps/duration are invalid for semantic review moments.");
  }

  const ids = new Set();
  return moments.map((moment, index) => {
    if (!moment || typeof moment !== "object") throw new Error(`Review moment ${index + 1} is invalid.`);
    if (typeof moment.id !== "string" || !ID_PATTERN.test(moment.id)) {
      throw new Error(`Review moment ${index + 1} has an invalid id.`);
    }
    if (ids.has(moment.id)) throw new Error(`Duplicate review moment id: ${moment.id}`);
    ids.add(moment.id);
    if (!Number.isInteger(moment.frame) || moment.frame < 0 || moment.frame >= duration) {
      throw new Error(`Review moment ${moment.id} has an invalid frame.`);
    }
    if (typeof moment.expectation !== "string" || moment.expectation.trim().length < 12) {
      throw new Error(`Review moment ${moment.id} needs a specific expectation.`);
    }
    return {
      id: moment.id,
      frame: moment.frame,
      timestampSeconds: moment.frame / fps,
      expectation: moment.expectation.trim(),
    };
  });
};

const run = (command, args) => new Promise((resolve, reject) => {
  const child = spawn(command, args, {stdio: ["ignore", "ignore", "pipe"]});
  let stderr = "";
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  child.once("error", reject);
  child.once("exit", (code, signal) => {
    if (code === 0) return resolve();
    reject(new Error(signal ? `${command} ended with ${signal}.` : `${command} exited with ${code}: ${stderr.slice(-600)}`));
  });
});

const renderMoments = async (videoPath, compositionPath, outputDir) => {
  const composition = JSON.parse(await fs.readFile(compositionPath, "utf8"));
  const moments = resolveReviewMoments(composition);
  if (moments.length === 0) {
    console.log("No semantic review moments declared; preserving legacy review behavior.");
    return;
  }

  await fs.mkdir(outputDir, {recursive: true});
  const report = [];
  for (let index = 0; index < moments.length; index += 1) {
    const moment = moments[index];
    const file = `${String(index + 1).padStart(2, "0")}-${moment.id}.jpg`;
    const outputPath = path.join(outputDir, file);
    await run("ffmpeg", [
      "-hide_banner",
      "-loglevel", "error",
      "-y",
      "-ss", moment.timestampSeconds.toFixed(6),
      "-i", videoPath,
      "-frames:v", "1",
      "-vf", "scale=540:-2",
      "-q:v", "2",
      outputPath,
    ]);
    const stat = await fs.stat(outputPath);
    if (!stat.isFile() || stat.size < 2_000) throw new Error(`Review moment image is missing or too small: ${file}`);
    report.push({...moment, file, sizeBytes: stat.size});
  }

  await fs.writeFile(
    path.join(outputDir, "review-moments.json"),
    `${JSON.stringify({version: 1, moments: report}, null, 2)}\n`,
    {mode: 0o600},
  );
  console.log(`Rendered ${report.length} private semantic review moments.`);
};

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const [videoArg, compositionArg, outputArg] = process.argv.slice(2);
  if (!videoArg || !compositionArg || !outputArg) {
    throw new Error("Usage: create-review-moments.mjs <video.mp4> <composition.json> <output-dir>");
  }
  renderMoments(path.resolve(videoArg), path.resolve(compositionArg), path.resolve(outputArg)).catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}

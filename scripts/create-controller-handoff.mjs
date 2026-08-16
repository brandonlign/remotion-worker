#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {validateYoutubeMetadata} from "./validate-youtube-metadata.mjs";

const [outputDirArg, youtubePathArg, expectedJobId, expectedSourceSha] = process.argv.slice(2);
const fail = (message) => { throw new Error(message); };

const readJson = async (filePath) => {
  const raw = await fs.readFile(filePath, "utf8");
  try { return JSON.parse(raw); }
  catch (error) { fail(`${filePath} is not valid JSON: ${error.message}`); }
};

const text = (value, name, maximum) => {
  if (typeof value !== "string" || !value.trim()) fail(`${name} is required.`);
  const normalized = value.trim();
  if (normalized.length > maximum) fail(`${name} exceeds ${maximum} characters.`);
  return normalized;
};

const main = async () => {
  if (!outputDirArg || !youtubePathArg || !expectedJobId || !expectedSourceSha) {
    fail("Usage: create-controller-handoff.mjs <render-output-dir> <youtube.json> <job-id> <source-sha>");
  }
  if (!/^[0-9a-f]{40}$/.test(expectedSourceSha)) fail("The expected source SHA is invalid.");

  const outputDir = path.resolve(outputDirArg);
  const youtubePath = path.resolve(youtubePathArg);
  const status = await readJson(path.join(outputDir, "status.json"));
  const youtube = await readJson(youtubePath);

  if (status.status !== "complete") fail("The render status is not complete.");
  if (status.jobId !== expectedJobId) fail("The render status job ID does not match the request.");
  if (status.sourceSha !== expectedSourceSha) fail("The render status source SHA does not match the request.");
  const metadata = await validateYoutubeMetadata({youtube, youtubePath, expectedJobId});

  const renderedVideo = path.join(outputDir, `${text(status.outputName, "status.outputName", 120)}.mp4`);
  const finalVideo = path.join(outputDir, "final.mp4");
  await fs.access(renderedVideo);
  if (renderedVideo !== finalVideo) await fs.copyFile(renderedVideo, finalVideo);

  const publish = {...metadata, jobId: expectedJobId, sourceSha: expectedSourceSha};
  await fs.writeFile(path.join(outputDir, "publish.json"), `${JSON.stringify(publish, null, 2)}\n`, "utf8");
  console.log(`Prepared final.mp4 and publish.json for Studio controller job ${expectedJobId}.`);
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});

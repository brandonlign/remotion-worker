#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const [outputDirArg, youtubePathArg, expectedJobId, expectedSourceSha] = process.argv.slice(2);

const fail = (message) => {
  throw new Error(message);
};

const readJson = async (filePath) => {
  const text = await fs.readFile(filePath, "utf8");
  try {
    return JSON.parse(text);
  } catch (error) {
    fail(`${filePath} is not valid JSON: ${error.message}`);
  }
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
  if (youtube.jobId !== expectedJobId) fail("youtube.json jobId does not match the request.");

  const renderedVideo = path.join(outputDir, `${text(status.outputName, "status.outputName", 120)}.mp4`);
  const finalVideo = path.join(outputDir, "final.mp4");
  await fs.access(renderedVideo);
  if (renderedVideo !== finalVideo) await fs.copyFile(renderedVideo, finalVideo);

  const tags = Array.isArray(youtube.tags)
    ? [...new Set(youtube.tags.map((tag) => String(tag).trim()).filter(Boolean))]
    : [];
  if (tags.join(",").length > 500) fail("The combined YouTube tags exceed 500 characters.");

  const categoryId = String(youtube.categoryId ?? "28").trim();
  if (!/^\d+$/.test(categoryId)) fail("youtube.json categoryId must be numeric.");
  if (typeof youtube.madeForKids !== "boolean") fail("youtube.json madeForKids must be boolean.");
  if (typeof youtube.publishAt !== "string" || !Number.isFinite(Date.parse(youtube.publishAt))) {
    fail("youtube.json publishAt must be an ISO date-time.");
  }

  const publish = {
    jobId: expectedJobId,
    title: text(youtube.title, "youtube.json title", 100),
    description: typeof youtube.description === "string" ? youtube.description.trim() : "",
    tags,
    categoryId,
    defaultLanguage: text(youtube.defaultLanguage ?? "en", "youtube.json defaultLanguage", 20),
    madeForKids: youtube.madeForKids,
    containsSyntheticMedia: youtube.containsSyntheticMedia === true,
    publishAt: new Date(youtube.publishAt).toISOString(),
    sourceSha: expectedSourceSha,
  };
  if (publish.description.length > 5000) fail("youtube.json description exceeds 5000 characters.");

  await fs.writeFile(path.join(outputDir, "publish.json"), `${JSON.stringify(publish, null, 2)}\n`, "utf8");
  console.log(`Prepared final.mp4 and publish.json for Studio controller job ${expectedJobId}.`);
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});

#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {fileURLToPath} from "node:url";

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

const chapterTimestampVariants = (startSeconds) => {
  const total = Number(startSeconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const secondText = String(seconds).padStart(2, "0");
  if (hours > 0) {
    const minuteText = String(minutes).padStart(2, "0");
    return [...new Set([
      `${hours}:${minuteText}:${secondText}`,
      `${String(hours).padStart(2, "0")}:${minuteText}:${secondText}`,
    ])];
  }
  return [...new Set([
    `${minutes}:${secondText}`,
    `${String(minutes).padStart(2, "0")}:${secondText}`,
  ])];
};

const validateLongChapters = async ({youtube, youtubePath, expectedJobId}) => {
  if (youtube.format !== "long") return;
  if (!Array.isArray(youtube.chapters) || youtube.chapters.length < 3 || youtube.chapters.length > 10) {
    fail("Long-form youtube.json needs 3 through 10 manual chapters.");
  }

  const runtimePath = path.join(path.dirname(youtubePath), "audio-runtime.json");
  const runtime = await readJson(runtimePath);
  if (runtime.format !== "long" || runtime.jobId !== expectedJobId) fail("Long-form audio-runtime.json does not match the handoff job.");
  const durationSeconds = Number(runtime.durationSeconds);
  if (!Number.isFinite(durationSeconds) || durationSeconds < 30) fail("Long-form audio runtime is invalid.");

  const description = typeof youtube.description === "string" ? youtube.description : "";
  let previous = -10;
  let lastDescriptionIndex = -1;
  for (const [index, chapter] of youtube.chapters.entries()) {
    const startSeconds = Number(chapter?.startSeconds);
    if (!Number.isInteger(startSeconds) || startSeconds < 0) fail(`Long-form chapter ${index + 1} needs a nonnegative integer startSeconds.`);
    if (index === 0 && startSeconds !== 0) fail("The first long-form chapter must start at 00:00.");
    if (startSeconds - previous < 10) fail("Long-form chapter starts must be ascending with at least 10 seconds between chapters.");
    const title = text(chapter?.title, `youtube.json chapters.${index + 1}.title`, 100);
    const lines = chapterTimestampVariants(startSeconds).map((timestamp) => `${timestamp} ${title}`);
    const matches = lines
      .map((line) => ({line, index: description.indexOf(line, lastDescriptionIndex + 1)}))
      .filter((match) => match.index >= 0)
      .sort((a, b) => a.index - b.index);
    if (matches.length === 0) fail(`Long-form description is missing chapter line: ${lines[0]}`);
    previous = startSeconds;
    lastDescriptionIndex = matches[0].index;
  }
  if (previous > Math.floor(durationSeconds) - 10) fail("The final long-form chapter must leave at least 10 seconds before the video ends.");
};

export const validateYoutubeMetadata = async ({youtube, youtubePath, expectedJobId}) => {
  if (youtube.jobId !== expectedJobId) fail("youtube.json jobId does not match the request.");
  const title = text(youtube.title, "youtube.json title", 100);
  const description = typeof youtube.description === "string" ? youtube.description.trim() : "";
  if (description.length > 5000) fail("youtube.json description exceeds 5000 characters.");

  const tags = Array.isArray(youtube.tags)
    ? [...new Set(youtube.tags.map((tag) => String(tag).trim()).filter(Boolean))]
    : [];
  if (tags.join(",").length > 500) fail("The combined YouTube tags exceed 500 characters.");

  const categoryId = String(youtube.categoryId ?? "28").trim();
  if (!/^\d+$/.test(categoryId)) fail("youtube.json categoryId must be numeric.");
  if (typeof youtube.madeForKids !== "boolean") fail("youtube.json madeForKids must be boolean.");
  if (typeof youtube.publishAt !== "string" || !Number.isFinite(Date.parse(youtube.publishAt))) fail("youtube.json publishAt must be an ISO date-time.");
  const defaultLanguage = text(youtube.defaultLanguage ?? "en", "youtube.json defaultLanguage", 20);

  await validateLongChapters({youtube, youtubePath, expectedJobId});
  return {
    title,
    description,
    tags,
    categoryId,
    defaultLanguage,
    madeForKids: youtube.madeForKids,
    containsSyntheticMedia: youtube.containsSyntheticMedia === true,
    publishAt: new Date(youtube.publishAt).toISOString(),
  };
};

export const validateYoutubeMetadataFile = async ({youtubePath, expectedJobId}) => {
  const resolved = path.resolve(youtubePath);
  const youtube = await readJson(resolved);
  return validateYoutubeMetadata({youtube, youtubePath: resolved, expectedJobId});
};

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const [youtubePath, expectedJobId] = process.argv.slice(2);
  if (!youtubePath || !expectedJobId) fail("Usage: validate-youtube-metadata.mjs <youtube.json> <job-id>");
  validateYoutubeMetadataFile({youtubePath, expectedJobId})
    .then(() => console.log(`Validated YouTube metadata before render for ${expectedJobId}.`))
    .catch((error) => { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1; });
}

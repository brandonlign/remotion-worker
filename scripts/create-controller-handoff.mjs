#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {validateYoutubeMetadata} from "./validate-youtube-metadata.mjs";

const [outputDirArg, youtubePathArg, requestPathArg] = process.argv.slice(2);
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
  if (!outputDirArg || !youtubePathArg || !requestPathArg) {
    fail("Usage: create-controller-handoff.mjs <render-output-dir> <youtube.json> <request.json>");
  }

  const outputDir = path.resolve(outputDirArg);
  const youtubePath = path.resolve(youtubePathArg);
  const requestPath = path.resolve(requestPathArg);
  const status = await readJson(path.join(outputDir, "status.json"));
  const youtube = await readJson(youtubePath);
  const request = await readJson(requestPath);

  const expectedJobId = text(request.jobId, "request.jobId", 64);
  const expectedSourceSha = text(request.sourceSha, "request.sourceSha", 40).toLowerCase();
  if (!/^[0-9a-f]{40}$/.test(expectedSourceSha)) fail("The request source SHA is invalid.");
  const sourceRepository = text(request.sourceRepository, "request.sourceRepository", 160);
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(sourceRepository)) fail("The request source repository is invalid.");
  const sourceIssueNumber = Number(request.sourceIssueNumber);
  const revision = Number(request.revision);
  if (!Number.isInteger(sourceIssueNumber) || sourceIssueNumber < 1) fail("The request source issue number is invalid.");
  if (!Number.isInteger(revision) || revision < 1 || revision > 1000) fail("The request revision is invalid.");
  if (request.mode !== "render") fail("Controller publish handoff may only be created from a full render request.");

  if (status.status !== "complete") fail("The render status is not complete.");
  if (status.jobId !== expectedJobId) fail("The render status job ID does not match the request.");
  if (status.sourceSha !== expectedSourceSha) fail("The render status source SHA does not match the request.");
  const metadata = await validateYoutubeMetadata({youtube, youtubePath, expectedJobId});

  const renderedVideo = path.join(outputDir, `${text(status.outputName, "status.outputName", 120)}.mp4`);
  const finalVideo = path.join(outputDir, "final.mp4");
  await fs.access(renderedVideo);
  if (renderedVideo !== finalVideo) await fs.copyFile(renderedVideo, finalVideo);

  const publish = {
    ...metadata,
    jobId: expectedJobId,
    sourceSha: expectedSourceSha,
    sourceRepository,
    sourceIssueNumber,
    revision,
  };
  await fs.writeFile(path.join(outputDir, "publish.json"), `${JSON.stringify(publish, null, 2)}\n`, "utf8");
  console.log(`Prepared final.mp4 and source-bound publish.json for ${expectedJobId} issue #${sourceIssueNumber}.`);
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});

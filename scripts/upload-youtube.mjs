#!/usr/bin/env node

import fs from "node:fs/promises";
import { createReadStream } from "node:fs";
import path from "node:path";
import process from "node:process";

const TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token";
const YOUTUBE_API = "https://www.googleapis.com/youtube/v3";
const YOUTUBE_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos";
const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

const safeJson = async (response) => {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text.slice(0, 1000) };
  }
};

const fetchWithRetry = async (url, options, attempts = 3) => {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, { ...options, signal: AbortSignal.timeout(180_000) });
      if (response.ok || (response.status < 500 && response.status !== 429)) return response;
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    if (attempt < attempts) await sleep(Math.min(30_000, 2_000 * 2 ** (attempt - 1)));
  }
  throw lastError ?? new Error("Request failed.");
};

const requireSecret = (name) => {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
};

const validateMetadata = (metadata) => {
  if (metadata?.version !== 1) throw new Error("YouTube metadata version must be 1.");
  if (typeof metadata.jobId !== "string" || !/^[a-z0-9-]{6,64}$/.test(metadata.jobId)) {
    throw new Error("YouTube metadata jobId is invalid.");
  }
  if (typeof metadata.title !== "string" || metadata.title.length < 1 || metadata.title.length > 100) {
    throw new Error("YouTube title must be 1-100 characters.");
  }
  if (typeof metadata.description !== "string" || metadata.description.length > 5000) {
    throw new Error("YouTube description must be at most 5000 characters.");
  }
  if (!Array.isArray(metadata.tags) || metadata.tags.some((tag) => typeof tag !== "string" || tag.length > 500)) {
    throw new Error("YouTube tags are invalid.");
  }
  if (typeof metadata.categoryId !== "string" || !/^\d+$/.test(metadata.categoryId)) {
    throw new Error("YouTube categoryId is invalid.");
  }
  if (metadata.privacyStatus !== "private") {
    throw new Error("Scheduled YouTube uploads must begin with privacyStatus=private.");
  }
  const publishAt = Date.parse(metadata.publishAt);
  if (!Number.isFinite(publishAt) || publishAt <= Date.now() + 5 * 60_000) {
    throw new Error("YouTube publishAt must be at least five minutes in the future.");
  }
  if (typeof metadata.madeForKids !== "boolean") throw new Error("YouTube madeForKids must be boolean.");
  if (!['youtube', 'creativeCommon'].includes(metadata.license)) throw new Error("YouTube license is invalid.");
  return metadata;
};

const refreshAccessToken = async ({ clientId, clientSecret, refreshToken }) => {
  const body = new URLSearchParams({
    client_id: clientId,
    client_secret: clientSecret,
    refresh_token: refreshToken,
    grant_type: "refresh_token",
  });
  const response = await fetchWithRetry(TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const payload = await safeJson(response);
  if (!response.ok || typeof payload.access_token !== "string") {
    throw new Error(`Google OAuth refresh failed with HTTP ${response.status}: ${JSON.stringify(payload).slice(0, 900)}`);
  }
  return payload.access_token;
};

const initializeUpload = async ({ accessToken, metadata, videoSize }) => {
  const endpoint = new URL(YOUTUBE_UPLOAD);
  endpoint.searchParams.set("uploadType", "resumable");
  endpoint.searchParams.set("part", "snippet,status");
  endpoint.searchParams.set("notifySubscribers", "false");
  const resource = {
    snippet: {
      title: metadata.title,
      description: metadata.description,
      tags: metadata.tags,
      categoryId: metadata.categoryId,
      defaultLanguage: metadata.defaultLanguage || "en",
    },
    status: {
      privacyStatus: "private",
      publishAt: metadata.publishAt,
      selfDeclaredMadeForKids: metadata.madeForKids,
      license: metadata.license,
      embeddable: true,
      publicStatsViewable: true,
    },
  };
  const response = await fetchWithRetry(endpoint, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json; charset=UTF-8",
      "X-Upload-Content-Length": String(videoSize),
      "X-Upload-Content-Type": "video/mp4",
    },
    body: JSON.stringify(resource),
  });
  const payload = await safeJson(response);
  if (!response.ok) {
    throw new Error(`YouTube upload initialization failed with HTTP ${response.status}: ${JSON.stringify(payload).slice(0, 1000)}`);
  }
  const location = response.headers.get("location");
  if (!location) throw new Error("YouTube did not return a resumable upload URL.");
  return location;
};

const uploadVideo = async ({ accessToken, uploadUrl, videoPath, videoSize }) => {
  const response = await fetch(uploadUrl, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "video/mp4",
      "Content-Length": String(videoSize),
    },
    body: createReadStream(videoPath),
    duplex: "half",
    signal: AbortSignal.timeout(45 * 60_000),
  });
  const payload = await safeJson(response);
  if (!response.ok || typeof payload.id !== "string") {
    throw new Error(`YouTube media upload failed with HTTP ${response.status}: ${JSON.stringify(payload).slice(0, 1000)}`);
  }
  return payload.id;
};

const pollProcessing = async ({ accessToken, videoId }) => {
  const deadline = Date.now() + 30 * 60_000;
  while (Date.now() < deadline) {
    const endpoint = new URL(`${YOUTUBE_API}/videos`);
    endpoint.searchParams.set("part", "status,processingDetails");
    endpoint.searchParams.set("id", videoId);
    const response = await fetchWithRetry(endpoint, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(`YouTube status check failed with HTTP ${response.status}: ${JSON.stringify(payload).slice(0, 1000)}`);
    }
    const video = payload.items?.[0];
    if (!video) throw new Error("YouTube status response did not contain the uploaded video.");
    const processingStatus = video.processingDetails?.processingStatus ?? "unknown";
    if (processingStatus === "succeeded") return video;
    if (processingStatus === "failed" || processingStatus === "terminated") {
      throw new Error(`YouTube processing ended with ${processingStatus}.`);
    }
    console.log(`YouTube is processing video ${videoId}.`);
    await sleep(20_000);
  }
  throw new Error(`Timed out waiting for YouTube processing for video ${videoId}.`);
};

const main = async () => {
  const [videoArg, metadataArg, outputArg] = process.argv.slice(2);
  if (!videoArg || !metadataArg || !outputArg) {
    throw new Error("Usage: upload-youtube.mjs <video.mp4> <metadata.json> <status-output.json>");
  }
  if (process.env.AUTOPUBLISH_ENABLED !== "1") {
    throw new Error("AUTOPUBLISH_ENABLED must be set to 1 for unattended publication.");
  }

  const videoPath = path.resolve(videoArg);
  const metadataPath = path.resolve(metadataArg);
  const outputPath = path.resolve(outputArg);
  const [metadataRaw, stat] = await Promise.all([fs.readFile(metadataPath, "utf8"), fs.stat(videoPath)]);
  if (!stat.isFile() || stat.size < 100_000) throw new Error("Rendered video is missing or unexpectedly small.");
  const metadata = validateMetadata(JSON.parse(metadataRaw));

  const credentials = {
    clientId: requireSecret("YOUTUBE_CLIENT_ID"),
    clientSecret: requireSecret("YOUTUBE_CLIENT_SECRET"),
    refreshToken: requireSecret("YOUTUBE_REFRESH_TOKEN"),
  };
  const accessToken = await refreshAccessToken(credentials);

  let videoId = null;
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const uploadUrl = await initializeUpload({ accessToken, metadata, videoSize: stat.size });
      videoId = await uploadVideo({ accessToken, uploadUrl, videoPath, videoSize: stat.size });
      break;
    } catch (error) {
      lastError = error;
      if (attempt < 3) {
        console.warn(`YouTube upload attempt ${attempt} failed; starting a fresh resumable session.`);
        await sleep(5_000 * attempt);
      }
    }
  }
  if (!videoId) throw lastError ?? new Error("YouTube upload failed.");

  const video = await pollProcessing({ accessToken, videoId });
  const result = {
    status: "scheduled",
    jobId: metadata.jobId,
    videoId,
    watchUrl: `https://www.youtube.com/watch?v=${videoId}`,
    publishAt: metadata.publishAt,
    privacyStatus: video.status?.privacyStatus ?? "private",
    uploadStatus: video.status?.uploadStatus ?? null,
    processingStatus: video.processingDetails?.processingStatus ?? "succeeded",
    completedAt: new Date().toISOString(),
  };
  await fs.writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, { mode: 0o600 });
  console.log(`YouTube accepted and processed video ${videoId}; scheduled for ${metadata.publishAt}.`);
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});

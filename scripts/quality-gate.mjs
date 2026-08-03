#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { spawn } from "node:child_process";

const RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses";

const readJson = async (filePath) => JSON.parse(await fs.readFile(filePath, "utf8"));

const runCapture = (command, args) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) {
        resolve({ stdout, stderr });
        return;
      }
      reject(new Error(signal ? `${command} ended with ${signal}.` : `${command} exited with code ${code}.`));
    });
  });

const extractDurations = (text, label) => {
  const expression = new RegExp(`${label}:([0-9.]+)`, "g");
  return [...text.matchAll(expression)]
    .map((match) => Number(match[1]))
    .filter((value) => Number.isFinite(value));
};

const getOutputText = (payload) => {
  const chunks = [];
  for (const item of payload.output ?? []) {
    if (item.type !== "message") continue;
    for (const content of item.content ?? []) {
      if (content.type === "refusal") throw new Error("The quality model refused the review.");
      if (content.type === "output_text" && typeof content.text === "string") chunks.push(content.text);
    }
  }
  if (chunks.length === 0) throw new Error("The quality model returned no structured output.");
  return chunks.join("\n").trim();
};

const reviewSchema = {
  type: "object",
  additionalProperties: false,
  required: ["pass", "summary", "scores", "issues"],
  properties: {
    pass: { type: "boolean" },
    summary: { type: "string" },
    scores: {
      type: "object",
      additionalProperties: false,
      required: [
        "hookClarity",
        "mechanismClarity",
        "specificity",
        "pacing",
        "readability",
        "continuity",
        "ending",
      ],
      properties: {
        hookClarity: { type: "integer" },
        mechanismClarity: { type: "integer" },
        specificity: { type: "integer" },
        pacing: { type: "integer" },
        readability: { type: "integer" },
        continuity: { type: "integer" },
        ending: { type: "integer" },
      },
    },
    issues: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["severity", "frameNumber", "timestampSeconds", "description"],
        properties: {
          severity: { type: "string", enum: ["blocking", "warning"] },
          frameNumber: { type: "integer" },
          timestampSeconds: { type: "number" },
          description: { type: "string" },
        },
      },
    },
  },
};

const validateReview = (review) => {
  if (!review || typeof review !== "object" || typeof review.pass !== "boolean") {
    throw new Error("The quality review has an invalid shape.");
  }
  const scoreNames = [
    "hookClarity",
    "mechanismClarity",
    "specificity",
    "pacing",
    "readability",
    "continuity",
    "ending",
  ];
  for (const name of scoreNames) {
    const value = review.scores?.[name];
    if (!Number.isInteger(value) || value < 1 || value > 5) {
      throw new Error(`The quality review score ${name} is invalid.`);
    }
  }
  if (!Array.isArray(review.issues)) throw new Error("The quality review issues are invalid.");
  return review;
};

const callVisualReview = async ({ apiKey, model, reasoningEffort, prompt, job, frames }) => {
  const content = [
    {
      type: "input_text",
      text: `${prompt}\n\nPRIVATE PRODUCTION JOB\n${JSON.stringify({
        jobId: job.jobId,
        topic: job.topic,
        centralQuestion: job.centralQuestion,
        mechanism: job.mechanism,
        consequence: job.consequence,
        title: job.title,
        narration: job.narration,
        beats: job.beats.map((beat) => ({
          id: beat.id,
          purpose: beat.purpose,
          narration: beat.narration,
          visual: beat.visual,
        })),
      })}\n\nThe images below are chronological samples. Each image is preceded by its approximate timestamp.`,
    },
  ];

  for (const frame of frames) {
    const bytes = await fs.readFile(frame.path);
    content.push({
      type: "input_text",
      text: `Frame ${frame.frameNumber}, approximately ${frame.timestampSeconds.toFixed(1)} seconds.`,
    });
    content.push({
      type: "input_image",
      image_url: `data:image/jpeg;base64,${bytes.toString("base64")}`,
      detail: "low",
    });
  }

  const response = await fetch(RESPONSES_ENDPOINT, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model,
      reasoning: { effort: reasoningEffort },
      input: [{ role: "user", content }],
      text: {
        format: {
          type: "json_schema",
          name: "telic_final_quality_gate",
          strict: true,
          schema: reviewSchema,
        },
      },
      max_output_tokens: 4_000,
      store: false,
    }),
    signal: AbortSignal.timeout(600_000),
  });

  const raw = await response.text();
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    throw new Error(`The quality API returned invalid JSON with HTTP ${response.status}.`);
  }
  if (!response.ok) {
    const code = payload?.error?.code ?? payload?.error?.type ?? "unknown";
    throw new Error(`The quality API failed with HTTP ${response.status} (${String(code).slice(0, 80)}).`);
  }
  if (payload.status !== "completed") {
    const reason = payload.incomplete_details?.reason ?? payload.status;
    throw new Error(`The quality API ended with status ${String(reason).slice(0, 80)}.`);
  }
  return validateReview(JSON.parse(getOutputText(payload)));
};

const sampleFrames = async (keyframesDir, maximumFrames) => {
  const names = (await fs.readdir(keyframesDir))
    .filter((name) => /^frame-\d+\.jpg$/i.test(name))
    .sort((left, right) => left.localeCompare(right));
  if (names.length < 3) throw new Error("The final review package has too few keyframes.");

  const count = Math.min(names.length, maximumFrames);
  const selectedIndexes = new Set();
  for (let index = 0; index < count; index += 1) {
    selectedIndexes.add(Math.round((index * (names.length - 1)) / Math.max(1, count - 1)));
  }
  return [...selectedIndexes].sort((a, b) => a - b).map((index) => {
    const name = names[index];
    const frameNumber = Number(name.match(/(\d+)/)?.[1]);
    return {
      frameNumber,
      timestampSeconds: Math.max(0, (frameNumber - 1) * 2),
      path: path.join(keyframesDir, name),
    };
  });
};

const main = async () => {
  const [resultArg, jobArg, configArg, promptArg] = process.argv.slice(2);
  if (!resultArg || !jobArg || !configArg || !promptArg) {
    throw new Error("Usage: quality-gate.mjs <render-result-dir> <job.json> <config.json> <prompt.txt>");
  }

  const resultDir = path.resolve(resultArg);
  const outputPath = path.join(resultDir, "quality-gate.json");
  const [status, job, config, prompt, metadata] = await Promise.all([
    readJson(path.join(resultDir, "status.json")),
    readJson(path.resolve(jobArg)),
    readJson(path.resolve(configArg)),
    fs.readFile(path.resolve(promptArg), "utf8"),
    readJson(path.join(resultDir, "media-metadata.json")),
  ]);
  const quality = config.quality;
  if (!quality || typeof quality !== "object") throw new Error("The private config has no quality policy.");

  const videoPath = path.join(resultDir, `${status.outputName}.mp4`);
  const stat = await fs.stat(videoPath);
  if (!stat.isFile() || stat.size < 100_000) throw new Error("The final rendered video is missing or too small.");

  const streams = Array.isArray(metadata.streams) ? metadata.streams : [];
  const videoStreams = streams.filter((stream) => stream.codec_type === "video");
  const audioStreams = streams.filter((stream) => stream.codec_type === "audio");
  const durationSeconds = Number(metadata.format?.duration ?? videoStreams[0]?.duration);
  const deterministicIssues = [];

  if (videoStreams.length !== 1) deterministicIssues.push("The final file must contain exactly one video stream.");
  if (audioStreams.length !== 1) deterministicIssues.push("The final file must contain exactly one audio stream.");
  if (Number(videoStreams[0]?.width) !== 1080 || Number(videoStreams[0]?.height) !== 1920) {
    deterministicIssues.push("The final frame size is not 1080 by 1920.");
  }
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 10 || durationSeconds > quality.maximumDurationSeconds) {
    deterministicIssues.push("The final duration is outside the autonomous Short limit.");
  }

  const [black, silence, freeze] = await Promise.all([
    runCapture("ffmpeg", [
      "-hide_banner", "-loglevel", "info", "-i", videoPath,
      "-vf", `blackdetect=d=${quality.maximumBlackSeconds}:pix_th=0.98`,
      "-an", "-f", "null", "-",
    ]),
    runCapture("ffmpeg", [
      "-hide_banner", "-loglevel", "info", "-i", videoPath,
      "-af", `silencedetect=n=-45dB:d=${quality.maximumSilenceSeconds}`,
      "-vn", "-f", "null", "-",
    ]),
    runCapture("ffmpeg", [
      "-hide_banner", "-loglevel", "info", "-i", videoPath,
      "-vf", `freezedetect=n=-50dB:d=${quality.maximumFreezeSeconds}`,
      "-an", "-f", "null", "-",
    ]),
  ]);

  const blackDurations = extractDurations(black.stderr, "black_duration");
  const silenceDurations = extractDurations(silence.stderr, "silence_duration");
  const freezeDurations = extractDurations(freeze.stderr, "freeze_duration");
  if (blackDurations.some((value) => value >= quality.maximumBlackSeconds)) {
    deterministicIssues.push("The final video contains an extended black segment.");
  }
  if (silenceDurations.some((value) => value >= quality.maximumSilenceSeconds)) {
    deterministicIssues.push("The final video contains an extended silent segment.");
  }
  if (freezeDurations.some((value) => value >= quality.maximumFreezeSeconds)) {
    deterministicIssues.push("The final video contains an extended frozen segment.");
  }

  const frames = await sampleFrames(path.join(resultDir, "keyframes"), quality.maximumFrames);
  const apiKey = process.env.OPENAI_API_KEY?.trim();
  if (!apiKey) throw new Error("OPENAI_API_KEY is required for the autonomous final quality gate.");
  const review = await callVisualReview({
    apiKey,
    model: process.env.OPENAI_QC_MODEL?.trim() || quality.model,
    reasoningEffort: quality.reasoningEffort,
    prompt,
    job,
    frames,
  });

  const thresholdFailures = [];
  if (review.scores.hookClarity < quality.minimumHookClarity) thresholdFailures.push("hook clarity");
  if (review.scores.mechanismClarity < quality.minimumMechanismClarity) thresholdFailures.push("mechanism clarity");
  if (review.scores.readability < quality.minimumReadability) thresholdFailures.push("readability");
  if (review.scores.specificity < quality.minimumSpecificity) thresholdFailures.push("specificity");
  const blockingReviewIssues = review.issues.filter((issue) => issue.severity === "blocking");
  const passed =
    deterministicIssues.length === 0 &&
    thresholdFailures.length === 0 &&
    blockingReviewIssues.length === 0 &&
    review.pass;

  const report = {
    version: 1,
    jobId: job.jobId,
    status: passed ? "passed" : "failed",
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
    sampledFrames: frames.map(({ frameNumber, timestampSeconds }) => ({ frameNumber, timestampSeconds })),
    deterministicIssues,
    thresholdFailures,
    review,
  };
  await fs.writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });

  if (!passed) {
    console.error("The autonomous final quality gate rejected the render.");
    process.exitCode = 1;
    return;
  }
  console.log("The autonomous final quality gate passed.");
};

main().catch(async (error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});

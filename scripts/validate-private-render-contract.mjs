#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const fail = (message) => {
  const error = new Error(message);
  error.code = "TELIC_PRIVATE_RENDER_CONTRACT";
  throw error;
};

export const validatePrivateRenderContract = ({
  mode,
  jobFormat,
  compositionId,
  thumbnailCompositionId = "",
  prepareCommand,
  checkCommand,
}) => {
  if (mode === "render-sequence") {
    if (jobFormat !== "long") fail("Sequence preview requires a private long-form source package.");
    if (compositionId !== "CustomLongForm") fail("Private long-form sequence source selected the wrong composition.");
    if (prepareCommand !== "npm run long:prepare-window") fail("Private long-form sequence source selected the wrong prepare command.");
    if (checkCommand !== "npm run lint") fail("Private long-form sequence source selected the wrong check command.");
    return true;
  }

  if (mode === "render" && jobFormat === "long") {
    if (compositionId !== "CustomLongForm") fail("Private long-form final source selected the wrong composition.");
    if (thumbnailCompositionId !== "LongFormThumbnail") fail("Private long-form final source selected the wrong thumbnail composition.");
    if (prepareCommand !== "npm run long:prepare") fail("Private long-form final source selected the wrong prepare command.");
    if (checkCommand !== "npm run lint") fail("Private long-form final source selected the wrong check command.");
  }
  return true;
};

export const readPrivateJobFormat = (sourceDir) => {
  const jobPath = path.join(sourceDir, "automation/current/job.json");
  let job;
  try {
    job = JSON.parse(fs.readFileSync(jobPath, "utf8"));
  } catch (error) {
    fail(`Private render source has no readable job identity: ${error instanceof Error ? error.message : String(error)}`);
  }
  return typeof job?.format === "string" ? job.format : "";
};

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const [sourceDir, mode, compositionId, thumbnailCompositionId = "", prepareCommand = "", checkCommand = ""] = process.argv.slice(2);
  if (!sourceDir || !mode || !compositionId) {
    throw new Error("Usage: node validate-private-render-contract.mjs <private-source-dir> <mode> <composition-id> <thumbnail-composition-id> <prepare-command> <check-command>");
  }
  validatePrivateRenderContract({
    mode,
    jobFormat: readPrivateJobFormat(path.resolve(sourceDir)),
    compositionId,
    thumbnailCompositionId,
    prepareCommand,
    checkCommand,
  });
}

#!/usr/bin/env node
import { existsSync, readFileSync } from "node:fs";

const [buildPath, uploadPath] = process.argv.slice(2);
const readSafe = (path) =>
  path && existsSync(path) ? readFileSync(path, "utf8") : "";

const build = readSafe(buildPath);
const upload = readSafe(uploadPath);

const buildMarkers = [
  ["Prepared all Popcorn private and sourced assets", "ASSETS_PREPARED"],
  ["Prepared Popcorn narration with the approved", "CTA_PREPARED"],
  ["Popcorn base voiceover verified", "BASE_AUDIO_VERIFIED"],
  ["Full Popcorn audit passed", "FULL_AUDIT_PASSED"],
  ["npm run lint", "LINT_STARTED"],
  ["Rendering composition", "RENDER_STARTED"],
  ["Render completed", "RENDER_COMPLETED"],
];

const completed = buildMarkers
  .filter(([needle]) => build.includes(needle))
  .map(([, label]) => label);

const classifyBuild = () => {
  if (!build) return "BUILD_LOG_MISSING";
  if (build.includes("ELEVENLABS_API_KEYS_JSON")) return "CTA_KEY_CONFIGURATION";
  if (build.includes("Could not generate the approved Popcorn CTA")) return "CTA_PROVIDER_FAILURE";
  if (build.includes("Combined narration duration")) return "CTA_DURATION_FAILURE";
  if (build.includes("ffmpeg failed")) return "CTA_AUDIO_ASSEMBLY_FAILURE";
  if (build.includes("Parsing error") || build.includes("SyntaxError")) return "SOURCE_SYNTAX_FAILURE";
  if (build.includes("error TS")) return "TYPESCRIPT_FAILURE";
  if (build.includes("Full Popcorn audit") || build.includes("feedback revision lost")) return "POPCORN_AUDIT_FAILURE";
  if (build.includes("npm ERR!")) return "NPM_FAILURE";
  if (build.includes("command not found")) return "MISSING_BUILD_TOOL";
  if (build.includes("Private render package complete")) return "SUCCESS";
  return "BUILD_FAILURE_UNCLASSIFIED";
};

const classifyUpload = () => {
  if (!upload) return "UPLOAD_LOG_MISSING";
  if (upload.includes("invalid_grant") || upload.includes("token has been expired")) return "DRIVE_AUTH_EXPIRED";
  if (upload.includes("insufficientPermissions") || upload.includes("insufficient permissions")) return "DRIVE_PERMISSION_FAILURE";
  if (upload.includes("storageQuotaExceeded") || upload.includes("quota")) return "DRIVE_QUOTA_FAILURE";
  if (upload.includes("directory not found") || upload.includes("not found")) return "DRIVE_ROOT_NOT_FOUND";
  if (upload.includes("Failed to create file system")) return "DRIVE_REMOTE_INIT_FAILURE";
  if (upload.includes("couldn't list directory")) return "DRIVE_LIST_FAILURE";
  if (upload.includes("Failed to copy")) return "DRIVE_COPY_FAILURE";
  if (upload.includes("Transferred:")) return "SUCCESS";
  return "UPLOAD_FAILURE_UNCLASSIFIED";
};

console.log(`PRIVATE_BUILD_CLASS=${classifyBuild()}`);
console.log(`PRIVATE_BUILD_COMPLETED=${completed.join(",") || "NONE"}`);
console.log(`PRIVATE_UPLOAD_CLASS=${classifyUpload()}`);

#!/usr/bin/env node
import { existsSync, readFileSync } from "node:fs";

const [buildPath, uploadPath, exitCodeValue] = process.argv.slice(2);
const readSafe = (path) =>
  path && existsSync(path) ? readFileSync(path, "utf8") : "";

const build = readSafe(buildPath);
const upload = readSafe(uploadPath);
const buildLower = build.toLowerCase();
const uploadLower = upload.toLowerCase();
const exitCode = Number(exitCodeValue);

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
const preparedAssetCount = (build.match(/Prepared Popcorn asset:/g) ?? []).length;

const classifyBuild = () => {
  if (exitCode === 0) return "SUCCESS";
  if (!build) return "BUILD_LOG_MISSING";
  if (build.includes("RCLONE_CONFIG_B64 is required")) return "SOURCE_DRIVE_SECRET_MISSING";
  if (
    buildLower.includes("failed to create file system") ||
    buildLower.includes("couldn't find root directory id") ||
    buildLower.includes("failed to initialize file system")
  ) return "SOURCE_DRIVE_INIT_FAILURE";
  if (buildLower.includes("couldn't list directory") || buildLower.includes("error listing")) {
    return "SOURCE_DRIVE_LIST_FAILURE";
  }
  if (buildLower.includes("failed to copy") || buildLower.includes("copy failed")) {
    return "SOURCE_DRIVE_COPY_FAILURE";
  }
  if (buildLower.includes("invalid_grant") || buildLower.includes("token has been expired")) {
    return "SOURCE_DRIVE_AUTH_EXPIRED";
  }
  if (buildLower.includes("insufficient permissions") || buildLower.includes("insufficientpermissions")) {
    return "SOURCE_DRIVE_PERMISSION_FAILURE";
  }
  if (buildLower.includes("curl: (")) return "PUBLIC_ASSET_DOWNLOAD_FAILURE";
  if (buildLower.includes("not valid media") || buildLower.includes("failed validation after preparation")) {
    return "MEDIA_VALIDATION_FAILURE";
  }
  if (buildLower.includes("size mismatch") || buildLower.includes("checksum mismatch")) {
    return "BASE_AUDIO_INTEGRITY_FAILURE";
  }
  if (build.includes("ELEVENLABS_API_KEYS_JSON is not valid JSON")) {
    return "CTA_KEYS_JSON_INVALID";
  }
  if (build.includes("ELEVENLABS_API_KEYS_JSON must be a JSON array")) {
    return "CTA_KEYS_JSON_NOT_ARRAY";
  }
  if (build.includes("An authorized ElevenLabs key is required")) {
    return "CTA_KEY_MISSING";
  }
  if (build.includes("Could not generate the approved Popcorn CTA")) return "CTA_PROVIDER_FAILURE";
  if (build.includes("Combined narration duration")) return "CTA_DURATION_FAILURE";
  if (buildLower.includes("ffmpeg failed")) return "CTA_AUDIO_ASSEMBLY_FAILURE";
  if (build.includes("Parsing error") || build.includes("SyntaxError")) return "SOURCE_SYNTAX_FAILURE";
  if (build.includes("error TS")) return "TYPESCRIPT_FAILURE";
  if (build.includes("feedback revision lost")) return "POPCORN_AUDIT_FAILURE";
  if (buildLower.includes("cannot find module")) return "DEPENDENCY_RESOLUTION_FAILURE";
  if (buildLower.includes("enospc") || buildLower.includes("no space left")) return "RUNNER_DISK_FAILURE";
  if (buildLower.includes("npm err!") || buildLower.includes("npm error")) return "NPM_FAILURE";
  if (buildLower.includes("command not found")) return "MISSING_BUILD_TOOL";
  return "BUILD_FAILURE_UNCLASSIFIED";
};

const classifyUpload = () => {
  if (!upload) return "UPLOAD_LOG_MISSING";
  if (uploadLower.includes("invalid_grant") || uploadLower.includes("token has been expired")) {
    return "DRIVE_AUTH_EXPIRED";
  }
  if (uploadLower.includes("insufficientpermissions") || uploadLower.includes("insufficient permissions")) {
    return "DRIVE_PERMISSION_FAILURE";
  }
  if (uploadLower.includes("storagequotaexceeded") || uploadLower.includes("quota exceeded")) {
    return "DRIVE_QUOTA_FAILURE";
  }
  if (uploadLower.includes("least-privilege drive.file scope")) {
    return "DRIVE_SCOPE_POLICY_MISMATCH";
  }
  if (
    uploadLower.includes("directory not found") ||
    uploadLower.includes("couldn't find root directory id") ||
    uploadLower.includes("root folder id")
  ) return "DRIVE_ROOT_NOT_FOUND";
  if (
    uploadLower.includes("failed to create file system") ||
    uploadLower.includes("failed to initialize file system")
  ) return "DRIVE_REMOTE_INIT_FAILURE";
  if (uploadLower.includes("couldn't list directory") || uploadLower.includes("error listing")) {
    return "DRIVE_LIST_FAILURE";
  }
  if (uploadLower.includes("failed to copy") || uploadLower.includes("copy failed")) {
    return "DRIVE_COPY_FAILURE";
  }
  if (uploadLower.includes("base64") && uploadLower.includes("invalid")) {
    return "DRIVE_SECRET_DECODE_FAILURE";
  }
  if (uploadLower.includes("didn't find section") || uploadLower.includes("no gdrive section")) {
    return "DRIVE_CONFIG_FAILURE";
  }
  if (uploadLower.includes("403")) return "DRIVE_HTTP_403";
  if (uploadLower.includes("401")) return "DRIVE_HTTP_401";
  if (uploadLower.includes("transferred:")) return "SUCCESS";
  if (upload.trim() === "") return "SUCCESS";
  return "UPLOAD_FAILURE_UNCLASSIFIED";
};

const keywordFlags = [
  ["rclone", buildLower.includes("rclone")],
  ["curl", buildLower.includes("curl")],
  ["ffmpeg", buildLower.includes("ffmpeg")],
  ["voiceover", buildLower.includes("voiceover")],
  ["elevenlabs", buildLower.includes("elevenlabs")],
  ["audit", buildLower.includes("audit")],
  ["lint", buildLower.includes("lint")],
  ["render", buildLower.includes("render")],
]
  .filter(([, present]) => present)
  .map(([name]) => name)
  .join(",");

console.log(`PRIVATE_BUILD_CLASS=${classifyBuild()}`);
console.log(`PRIVATE_BUILD_COMPLETED=${completed.join(",") || "NONE"}`);
console.log(`PRIVATE_BUILD_PREPARED_ASSETS=${preparedAssetCount}`);
console.log(`PRIVATE_BUILD_KEYWORDS=${keywordFlags || "NONE"}`);
console.log(`PRIVATE_UPLOAD_CLASS=${classifyUpload()}`);
console.log(`PRIVATE_UPLOAD_LOG_BYTES=${Buffer.byteLength(upload)}`);

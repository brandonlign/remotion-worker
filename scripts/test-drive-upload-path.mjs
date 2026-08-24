#!/usr/bin/env node
import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";

const upload = fs.readFileSync(new URL("./upload-drive.sh", import.meta.url), "utf8");
const previewUpload = fs.readFileSync(new URL("./upload-preview-drive.sh", import.meta.url), "utf8");
const rcloneCommon = fs.readFileSync(new URL("./lib/rclone-common.sh", import.meta.url), "utf8");
const restore = fs.readFileSync(new URL("./download-drive-audio.sh", import.meta.url), "utf8");
const routing = fs.readFileSync(new URL("./lib/channel-storage.sh", import.meta.url), "utf8");
const validator = fs.readFileSync(new URL("./validate-job.mjs", import.meta.url), "utf8");

assert.match(routing, /telic\)[\s\S]*'YouTube\/Telic\/Telic-Renders'/);
assert.match(routing, /coffee\)[\s\S]*'YouTube\/Coffee\/Renders'/);
assert.match(routing, /Unsupported render channel/);
assert.match(upload, /RENDER_ROOT_PATH="\$\(render_root_for_job_id "\$JOB_ID"\)"/);
assert.match(upload, /JOB_TARGET_PATH="\$RENDER_ROOT_PATH\/\$JOB_ID"/);
assert.match(upload, /DELIVERY_KIND="\$\{3:-success\}"/);
assert.match(upload, /TARGET_PATH="\$JOB_TARGET_PATH\/diagnostics\/revision-\$REVISION"/);
assert.match(upload, /rm -f "\$RESULT_DIR\/upload-complete\.txt"/);
assert.match(upload, /Only a successful requested stage may write the canonical completion marker/);
assert.match(upload, /rclone lsjson "gdrive:\$RENDER_ROOT_PATH"/);
assert.match(upload, /--dirs-only/);
assert.match(upload, /--max-depth 1/);
assert.match(upload, /if \[ "\$DUPLICATE_JOB_FOLDERS" -gt 1 \]; then/);
assert.match(upload, /Multiple render folders already exist for this job ID/);
assert.match(upload, /"gdrive:\$TARGET_PATH"/);
assert.match(upload, /validate_drive_file_scope/);
assert.match(previewUpload, /validate_drive_file_scope/);
assert.match(rcloneCommon, /must use exactly the drive\.file OAuth scope/);
assert.doesNotMatch(upload, /auth\/drive["']/);
assert.doesNotMatch(previewUpload, /auth\/drive["']/);
assert.match(restore, /VOICE_ROOT_PATH="\$\(render_root_for_job_id "\$JOB_ID"\)\/\$JOB_ID"/);
assert.match(validator, /supportedChannels = new Set\(\["telic", "coffee"\]\)/);
assert.match(validator, /channel_id=\$\{channelId\}/);

// Public request data must not be able to provide an arbitrary Drive path.
assert.doesNotMatch(validator, /driveRoot|renderRoot|folderId/i);
assert.doesNotMatch(upload, /use_telic_renders_root/);
assert.doesNotMatch(upload, /resolve_unique_folder_id/);
assert.doesNotMatch(upload, /rclone lsjson gdrive: \\/);

const scopeRoot = fs.mkdtempSync(path.join(os.tmpdir(), "drive-scope-"));
const commonPath = fileURLToPath(new URL("./lib/rclone-common.sh", import.meta.url));
const runScopeCheck = (scope) => {
  const configPath = path.join(scopeRoot, "rclone.conf");
  fs.writeFileSync(configPath, `[gdrive]\nscope = ${scope}\n`);
  return spawnSync(
    "bash",
    ["-c", 'source "$1"; RCLONE_CONFIG_FILE="$2"; validate_drive_file_scope', "scope-test", commonPath, configPath],
    {encoding: "utf8"},
  );
};

assert.equal(runScopeCheck("drive.file").status, 0);
assert.equal(runScopeCheck("https://www.googleapis.com/auth/drive.file").status, 0);
assert.notEqual(runScopeCheck("drive").status, 0);
assert.notEqual(runScopeCheck("https://www.googleapis.com/auth/drive").status, 0);
assert.notEqual(runScopeCheck("drive.file https://www.googleapis.com/auth/drive.metadata.readonly").status, 0);
fs.rmSync(scopeRoot, {recursive: true, force: true});

console.log("Drive success delivery is canonical while failed diagnostics stay isolated by revision.");

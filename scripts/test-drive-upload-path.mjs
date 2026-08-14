#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";

const upload = fs.readFileSync(new URL("./upload-drive.sh", import.meta.url), "utf8");
const restore = fs.readFileSync(new URL("./download-drive-audio.sh", import.meta.url), "utf8");
const routing = fs.readFileSync(new URL("./lib/channel-storage.sh", import.meta.url), "utf8");
const validator = fs.readFileSync(new URL("./validate-job.mjs", import.meta.url), "utf8");

assert.match(routing, /telic\)[\s\S]*'YouTube\/Telic\/Telic-Renders'/);
assert.match(routing, /coffee\)[\s\S]*'YouTube\/Coffee\/Renders'/);
assert.match(routing, /Unsupported render channel/);
assert.match(upload, /RENDER_ROOT_PATH="\$\(render_root_for_job_id "\$JOB_ID"\)"/);
assert.match(upload, /JOB_TARGET_PATH="\$RENDER_ROOT_PATH\/\$JOB_ID"/);
assert.match(upload, /rclone lsjson "gdrive:\$RENDER_ROOT_PATH"/);
assert.match(upload, /--dirs-only/);
assert.match(upload, /--max-depth 1/);
assert.match(upload, /if \[ "\$DUPLICATE_JOB_FOLDERS" -gt 1 \]; then/);
assert.match(upload, /Multiple render folders already exist for this job ID/);
assert.match(upload, /"gdrive:\$JOB_TARGET_PATH"/);
assert.match(restore, /VOICE_ROOT_PATH="\$\(render_root_for_job_id "\$JOB_ID"\)\/\$JOB_ID"/);
assert.match(validator, /supportedChannels = new Set\(\["telic", "coffee"\]\)/);
assert.match(validator, /channel_id=\$\{channelId\}/);

// Public request data must not be able to provide an arbitrary Drive path.
assert.doesNotMatch(validator, /driveRoot|renderRoot|folderId/i);
assert.doesNotMatch(upload, /use_telic_renders_root/);
assert.doesNotMatch(upload, /resolve_unique_folder_id/);
assert.doesNotMatch(upload, /rclone lsjson gdrive: \\/);

console.log("Drive delivery and audio restore route by validated job channel without accepting public Drive locators.");

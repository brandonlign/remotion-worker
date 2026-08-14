#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";

const upload = fs.readFileSync(new URL("./upload-drive.sh", import.meta.url), "utf8");

assert.match(upload, /RENDER_ROOT_PATH="Telic-Renders"/);
assert.match(upload, /JOB_TARGET_PATH="\$RENDER_ROOT_PATH\/\$JOB_ID"/);
assert.match(upload, /rclone lsjson "gdrive:\$RENDER_ROOT_PATH"/);
assert.match(upload, /--dirs-only/);
assert.match(upload, /--max-depth 1/);
assert.match(upload, /if \[ "\$DUPLICATE_JOB_FOLDERS" -gt 1 \]; then/);
assert.match(upload, /Multiple render folders already exist for this job ID/);
assert.match(upload, /"gdrive:\$JOB_TARGET_PATH"/);

// Delivery must not scan the Drive root just to rediscover Telic-Renders.
assert.doesNotMatch(upload, /use_telic_renders_root/);
assert.doesNotMatch(upload, /resolve_unique_folder_id/);
assert.doesNotMatch(upload, /rclone lsjson gdrive: \\/);

console.log("Drive delivery uses the stable Telic-Renders path directly while preserving duplicate-job-folder protection.");

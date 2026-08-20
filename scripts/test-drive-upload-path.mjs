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
assert.match(restore, /VOICE_ROOT_PATH="\$\(render_root_for_job_id "\$JOB_ID"\)\/\$JOB_ID"/);
assert.match(validator, /new Set\(\["telic", "coffee"\]\)\.has\(channelId\)/);
assert.match(validator, /channel_id=\$\{channelId\}/);
assert.match(validator, /Full render requests require explicit sourceRepository and sourceIssueNumber authority/);
assert.match(validator, /source_repository=\$\{request\.sourceRepository \?\? ""\}/);
assert.match(validator, /source_issue_number=\$\{request\.sourceIssueNumber \?\? ""\}/);

// Public request data must not be able to provide an arbitrary Drive path.
assert.doesNotMatch(validator, /driveRoot|renderRoot|folderId/i);
assert.doesNotMatch(upload, /use_telic_renders_root/);
assert.doesNotMatch(upload, /resolve_unique_folder_id/);
assert.doesNotMatch(upload, /rclone lsjson gdrive: \\/);

console.log("Drive success delivery is canonical while failed diagnostics stay isolated by revision and full renders require explicit source authority.");

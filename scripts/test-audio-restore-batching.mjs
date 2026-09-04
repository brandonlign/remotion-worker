#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("./download-drive-audio.sh", import.meta.url), "utf8");

assert.match(source, /rclone copy "gdrive:\$VOICE_ROOT_PATH" "\$VOICE_STAGE_DIR"/);
assert.match(source, /--files-from "\$VOICE_NAMES_FILE"/);
assert.match(source, /--committed-long/);
assert.doesNotMatch(source, /CACHED_LONG_VOICE/);
assert.doesNotMatch(source, /Reused SHA-verified cached long-form voiceover/);
assert.doesNotMatch(source, /copy_voice_artifact/);

assert.match(source, /cut -f1 "\$AUDIO_ROWS_FILE" \| sort -u/);
assert.match(source, /rclone lsjson gdrive:/);
assert.match(source, /A selected private channel audio file failed provider identity verification/);
assert.match(source, /rclone backend copyid gdrive: "\$drive_file_id" "\$restored"/);
assert.match(source, /\(item\.get\("Name"\), item\.get\("ID"\)\)/);
assert.doesNotMatch(source, /rclone copy gdrive: "\$GROUP_STAGE_DIR"/);
assert.doesNotMatch(source, /--files-from "\$GROUP_NAMES_FILE"/);
assert.doesNotMatch(source, /rclone copyto "gdrive:\$file_name"/);

console.log("private audio restore batches folder verification and copies exact Drive provider IDs");

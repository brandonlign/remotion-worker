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

assert.match(source, /read-private-music-request\.mjs" \\\n  "\$AUDIO_REQUEST_FILE" "\$SOURCE_DIR"/);
assert.match(source, /rclone backend copyid gdrive: "\$drive_file_id" "\$restored"/);
assert.doesNotMatch(source, /rclone backend query gdrive:/);
assert.doesNotMatch(source, /rclone lsjson gdrive:/);
assert.doesNotMatch(source, /set_drive_root "\$drive_folder_id"/);
assert.doesNotMatch(source, /rclone copy gdrive: "\$GROUP_STAGE_DIR"/);
assert.doesNotMatch(source, /rclone copyto "gdrive:\$file_name"/);

console.log("private audio restore uses immutable source registry authority plus provider-ID copy");

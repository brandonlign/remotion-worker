#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("./download-drive-audio.sh", import.meta.url), "utf8");

assert.match(source, /CACHED_LONG_VOICE=false/);
assert.match(source, /verify-restored-audio\.mjs" \\\n    --committed-long/);
assert.match(source, /Reused SHA-verified cached long-form voiceover/);
assert.match(source, /else\n    rm -f "\$AUDIO_FILE"/);
assert.match(source, /if \[ "\$CACHED_LONG_VOICE" != "true" \]; then\n  printf '%s\\n' 'voiceover\.mp3'/);
assert.match(source, /if \[ -s "\$VOICE_NAMES_FILE" \]; then\n  rclone copy "gdrive:\$VOICE_ROOT_PATH" "\$VOICE_STAGE_DIR"/);
assert.match(source, /if \[ "\$CACHED_LONG_VOICE" != "true" \]; then\n  cp "\$VOICE_STAGE_DIR\/voiceover\.mp3" "\$AUDIO_FILE"/);

assert.match(source, /rclone copy "gdrive:\$VOICE_ROOT_PATH" "\$VOICE_STAGE_DIR"/);
assert.match(source, /--files-from "\$VOICE_NAMES_FILE"/);
assert.doesNotMatch(source, /copy_voice_artifact/);

assert.match(source, /cut -f1 "\$AUDIO_ROWS_FILE" \| sort -u/);
assert.match(source, /rclone lsjson gdrive:/);
assert.match(source, /A selected private channel audio file failed provider identity verification/);
assert.match(source, /rclone copy gdrive: "\$GROUP_STAGE_DIR"/);
assert.match(source, /--files-from "\$GROUP_NAMES_FILE"/);
assert.doesNotMatch(source, /rclone copyto "gdrive:\$file_name"/);

console.log("private audio restore batching and SHA-verified long voice cache fallback contracts passed");

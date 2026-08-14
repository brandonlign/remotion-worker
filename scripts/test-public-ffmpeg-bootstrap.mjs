#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";

const script = fs.readFileSync(new URL("./ensure-public-ffmpeg.sh", import.meta.url), "utf8");

assert.match(script, /FFMPEG_SERIES="8\.1"/);
assert.match(script, /ffmpeg-n8\.1-btbn-20260813/);

// Immutable BtbN GitHub release asset IDs and their published SHA-256 digests.
assert.match(script, /FFMPEG_ASSET_ID="513287053"/);
assert.match(script, /ae395e0425d3a494626d0cac8f75715aca6dd802762aedf0f2e295382d6d0ba4/);
assert.match(script, /FFMPEG_ASSET_ID="513287115"/);
assert.match(script, /139dde8a333f0acb98e9c7acf6d0a48f3ed8203a9142f4d6e332e88e4572a7fa/);
assert.match(script, /releases\/assets\/\$FFMPEG_ASSET_ID/);
assert.doesNotMatch(script, /releases\/download\/latest/);
assert.match(script, /Accept: application\/octet-stream/);
assert.match(script, /sha256sum --check --status/);

// A cached/downloaded binary is accepted only if the exact review filters exist.
for (const filter of ["fps", "tile", "split", "scale"]) {
  assert.match(script, new RegExp(`for filter in fps tile split scale`));
}
assert.match(script, /ffmpeg_has_required_filters/);
assert.match(script, /find "\$extract_dir" -type f -path '\*\/bin\/ffmpeg'/);
assert.match(script, /find "\$extract_dir" -type f -path '\*\/bin\/ffprobe'/);
assert.match(script, /GITHUB_PATH/);

// Public binary failure must degrade to the existing reliable distro path.
assert.match(script, /sudo apt-get update -qq/);
assert.match(script, /sudo apt-get install -y -qq ffmpeg/);
assert.match(script, /No compatible full FFmpeg installation is available/);

console.log("Pinned full FFmpeg preview bootstrap is immutable, checksum-verified, filter-verified, cached, and has an apt fallback.");

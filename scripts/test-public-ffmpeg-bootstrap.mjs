#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";

const script = fs.readFileSync(new URL("./ensure-public-ffmpeg.sh", import.meta.url), "utf8");

assert.match(script, /FFMPEG_SERIES="8\.1"/);
assert.match(script, /FFMPEG_RELEASE_TAG="autobuild-2026-08-18-15-03"/);
assert.match(script, /ffmpeg-n8\.1-btbn-20260813/);

// Pin an exact dated BtbN release/archive and verify it against that release's
// published checksum manifest instead of relying on deletable release asset IDs.
assert.match(script, /ffmpeg-n8\.1\.2-44-g7c533d0f86-linux64-gpl-8\.1\.tar\.xz/);
assert.match(script, /ffmpeg-n8\.1\.2-44-g7c533d0f86-linuxarm64-gpl-8\.1\.tar\.xz/);
assert.match(script, /releases\/download\/\$FFMPEG_RELEASE_TAG/);
assert.doesNotMatch(script, /releases\/assets\/\$FFMPEG_ASSET_ID/);
assert.doesNotMatch(script, /releases\/download\/latest/);
assert.match(script, /checksums\.sha256/);
assert.match(script, /sha256sum --check --status/);

// A cached/downloaded binary is accepted only if the exact review filters exist.
for (const filter of ["fps", "tile", "split", "scale"]) {
  assert.match(script, new RegExp(`for filter in fps tile split scale`));
}
assert.match(script, /ffmpeg_has_required_filters/);
assert.match(script, /find "\$extract_dir" -type f -path '\*\/bin\/ffmpeg'/);
assert.match(script, /find "\$extract_dir" -type f -path '\*\/bin\/ffprobe'/);
assert.match(script, /GITHUB_PATH/);

// Public binary failure must degrade to a bounded distro path rather than hang.
assert.match(script, /timeout 180s sudo apt-get update -qq/);
assert.match(script, /timeout 180s sudo apt-get install -y -qq ffmpeg/);
assert.match(script, /Timed out or failed while installing the distro ffmpeg fallback/);
assert.match(script, /No compatible full FFmpeg installation is available/);

console.log("Pinned full FFmpeg preview bootstrap uses a dated release, published checksum verification, filter verification, caching, and a bounded apt fallback.");

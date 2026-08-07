#!/usr/bin/env node
import assert from "node:assert/strict";
import {resolveQualityPolicy} from "./quality-policy.mjs";

const config = {
  quality: {
    maximumFrames: 20,
    maximumDurationSeconds: 32,
    maximumBlackSeconds: 0.5,
    maximumSilenceSeconds: 2,
    maximumFreezeSeconds: 2.5,
  },
  longForm: {
    minimumDurationSeconds: 240,
    quality: {
      maximumFrames: 48,
      maximumDurationSeconds: 600,
      maximumBlackSeconds: 1.5,
      maximumSilenceSeconds: 3.5,
      maximumFreezeSeconds: 6,
    },
  },
};

assert.deepEqual(
  resolveQualityPolicy({format: "short"}, config),
  {
    format: "short",
    quality: config.quality,
    expectedWidth: 1080,
    expectedHeight: 1920,
    minimumDurationSeconds: 10,
    maximumDurationSeconds: 32,
    maximumFrames: 20,
  },
);
assert.deepEqual(
  resolveQualityPolicy({format: "long"}, config),
  {
    format: "long",
    quality: config.longForm.quality,
    expectedWidth: 1920,
    expectedHeight: 1080,
    minimumDurationSeconds: 240,
    maximumDurationSeconds: 600,
    maximumFrames: 48,
  },
);
assert.equal(resolveQualityPolicy({}, config).format, "short");
assert.throws(() => resolveQualityPolicy({format: "vertical-long"}, config), /Unsupported Telic format/);
assert.throws(() => resolveQualityPolicy({format: "long"}, {quality: config.quality}), /no long quality policy/);

console.log("Worker format-aware quality policy tests passed.");

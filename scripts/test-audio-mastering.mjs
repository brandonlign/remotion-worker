#!/usr/bin/env node

import assert from "node:assert/strict";
import {
  audioLoudnessIssues,
  normalizeMasteringPolicy,
  parseLoudnormStats,
  resolveMasteringPolicy,
} from "./master-final-audio.mjs";

const policy = {
  targetIntegratedLufs: -16,
  targetLoudnessRangeLu: 7,
  targetTruePeakDbtp: -1.5,
  integratedToleranceLufs: 0.5,
  truePeakToleranceDbtp: 0.2,
};

assert.deepEqual(resolveMasteringPolicy({audio: {mastering: policy}}), policy);
assert.equal(resolveMasteringPolicy({audio: {}}), null);
assert.throws(() => normalizeMasteringPolicy({...policy, targetTruePeakDbtp: 1}), /targetTruePeakDbtp/);
assert.throws(() => normalizeMasteringPolicy({...policy, integratedToleranceLufs: 0}), /integratedToleranceLufs/);

const stats = parseLoudnormStats(`
  [Parsed_loudnorm_0] measured
  {"input_i":"-18.40","input_tp":"-2.10","input_lra":"4.20","input_thresh":"-28.90","output_i":"-16.00","output_tp":"-1.50","output_lra":"4.20","target_offset":"2.40"}
`);
assert.equal(stats.input_i, "-18.40");
assert.equal(stats.output_tp, "-1.50");
assert.throws(() => parseLoudnormStats("no measurement"), /measurement JSON/);

assert.deepEqual(audioLoudnessIssues({
  policy,
  measurement: {integratedLufs: -16.4, truePeakDbtp: -1.6, loudnessRangeLu: 4.2},
}), []);
const issues = audioLoudnessIssues({
  policy,
  measurement: {integratedLufs: -14.9, truePeakDbtp: -1.1, loudnessRangeLu: 4.2},
});
assert.equal(issues.length, 2);
assert.match(issues[0], /Integrated loudness/);
assert.match(issues[1], /True peak/);

console.log("Audio mastering policy and loudnorm parsing tests passed.");

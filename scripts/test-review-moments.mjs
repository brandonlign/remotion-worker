#!/usr/bin/env node

import assert from "node:assert/strict";
import {buildBatchExtractionPlan, resolveReviewMoments} from "./create-review-moments.mjs";

const composition = {
  fps: 30,
  durationInFrames: 300,
  reviewMoments: [
    {id: "opening-land", frame: 18, expectation: "The opening camera move has landed on the subject."},
    {id: "mechanism-land", frame: 150, expectation: "The moving object is exactly inside its intended target."},
    {id: "payoff", frame: 270, expectation: "The final visual is readable and free of overlap."},
  ],
};

const moments = resolveReviewMoments(composition);
assert.equal(moments.length, 3);
assert.equal(moments[0].timestampSeconds, 0.6);
assert.equal(moments[1].timestampSeconds, 5);
assert.deepEqual(resolveReviewMoments({fps: 30, durationInFrames: 300}), []);

const batch = buildBatchExtractionPlan(moments);
assert.deepEqual(batch.frames, [18, 150, 270]);
assert.equal(batch.filter, "select='eq(n\\,18)+eq(n\\,150)+eq(n\\,270)',scale=540:-2");

const duplicateFrameBatch = buildBatchExtractionPlan([
  moments[2],
  {...moments[0], id: "opening-copy"},
  moments[0],
]);
assert.deepEqual(duplicateFrameBatch.frames, [18, 270]);
assert.equal(duplicateFrameBatch.filter, "select='eq(n\\,18)+eq(n\\,270)',scale=540:-2");
assert.deepEqual(buildBatchExtractionPlan([]), {frames: [], filter: null});

assert.throws(
  () => resolveReviewMoments({...composition, reviewMoments: composition.reviewMoments.slice(0, 2)}),
  /three to eight/,
);
assert.throws(
  () => resolveReviewMoments({...composition, reviewMoments: [composition.reviewMoments[0], composition.reviewMoments[0], composition.reviewMoments[2]]}),
  /Duplicate review moment id/,
);
assert.throws(
  () => resolveReviewMoments({...composition, reviewMoments: [{...composition.reviewMoments[0], frame: 999}, composition.reviewMoments[1], composition.reviewMoments[2]]}),
  /invalid frame/,
);
assert.throws(
  () => buildBatchExtractionPlan([{frame: -1}]),
  /nonnegative integer frames/,
);

console.log("Semantic review moment tests passed.");

#!/usr/bin/env node

import assert from "node:assert/strict";
import {resolveReviewMoments} from "./create-review-moments.mjs";

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

const frozenTwelve = {
  ...composition,
  durationInFrames: 720,
  reviewMoments: Array.from({length: 12}, (_, index) => ({
    frame: index * 50,
    sequenceId: `sequence-${(index % 4) + 1}`,
    expectation: `Frozen semantic review expectation ${index + 1} remains exact.`,
  })),
};
const frozenTwelveMoments = resolveReviewMoments(frozenTwelve);
assert.equal(frozenTwelveMoments.length, 12);
assert.equal(frozenTwelveMoments[0].id, "sequence-1-0");
assert.equal(frozenTwelveMoments[1].id, "sequence-2-50");

assert.throws(
  () => resolveReviewMoments({...composition, reviewMoments: composition.reviewMoments.slice(0, 2)}),
  /three to sixteen/,
);
assert.throws(
  () => resolveReviewMoments({...composition, reviewMoments: [composition.reviewMoments[0], composition.reviewMoments[0], composition.reviewMoments[2]]}),
  /Duplicate review moment id/,
);
assert.throws(
  () => resolveReviewMoments({...composition, reviewMoments: [{...composition.reviewMoments[0], frame: 999}, composition.reviewMoments[1], composition.reviewMoments[2]]}),
  /invalid frame/,
);

console.log("Semantic review moment tests passed.");

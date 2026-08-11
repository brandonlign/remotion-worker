#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

export const MAX_SEQUENCE_INDEX = 39;

export const resolveSequencePreview = (visualPlan, sequenceIndex) => {
  if (!Number.isInteger(sequenceIndex) || sequenceIndex < 0 || sequenceIndex > MAX_SEQUENCE_INDEX) {
    throw new Error(`sequenceIndex must be an integer from 0 through ${MAX_SEQUENCE_INDEX}.`);
  }
  if (!Array.isArray(visualPlan?.sequences) || visualPlan.sequences.length === 0) {
    throw new Error("visual-plan.json has no long-form sequences.");
  }
  if (sequenceIndex >= visualPlan.sequences.length) {
    throw new Error(`sequenceIndex ${sequenceIndex} is outside the ${visualPlan.sequences.length}-sequence visual plan.`);
  }
  const sequence = visualPlan.sequences[sequenceIndex];
  const startFrame = Number(sequence?.startFrame);
  const endFrame = Number(sequence?.endFrame);
  if (!Number.isInteger(startFrame) || !Number.isInteger(endFrame) || startFrame < 0 || endFrame <= startFrame) {
    throw new Error(`Sequence ${sequenceIndex} has an invalid frame range.`);
  }
  return {
    sequenceIndex,
    startFrame,
    endFrame,
    // Remotion's frame range is inclusive while Telic visual-plan endFrame is exclusive.
    renderEndFrame: endFrame - 1,
    frameCount: endFrame - startFrame,
  };
};

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const [visualPlanPath, rawIndex] = process.argv.slice(2);
  if (!visualPlanPath || rawIndex == null) {
    throw new Error("Usage: node scripts/sequence-preview.mjs <visual-plan.json> <sequence-index>");
  }
  const visualPlan = JSON.parse(fs.readFileSync(path.resolve(visualPlanPath), "utf8"));
  console.log(JSON.stringify(resolveSequencePreview(visualPlan, Number(rawIndex))));
}

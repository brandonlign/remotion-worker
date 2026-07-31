#!/usr/bin/env node

import fs from "node:fs";

const [logPath, phasePath] = process.argv.slice(2);
if (!logPath || !phasePath) {
  console.error("Usage: summarize-private-check.mjs <private-log> <phase-file>");
  process.exit(64);
}

const allowedPhases = new Set([
  "source-validation",
  "install",
  "prepare",
  "check",
  "render",
  "review-assets",
  "metadata",
  "complete",
]);

let phase = "unknown";
try {
  const candidate = fs.readFileSync(phasePath, "utf8").trim().split(/\r?\n/, 1)[0];
  if (allowedPhases.has(candidate)) {
    phase = candidate;
  }
} catch {
  // Keep the non-sensitive fallback.
}

console.log(`Private render failed during phase: ${phase}.`);
if (phase !== "check") {
  process.exit(0);
}

let log = "";
try {
  log = fs.readFileSync(logPath, "utf8");
} catch {
  console.log("Safe check summary unavailable.");
  process.exit(0);
}

const totals = log.match(/(?:✖|x)\s+(\d+)\s+problems?\s+\((\d+)\s+errors?,\s+(\d+)\s+warnings?\)/i);
const rules = new Set();
for (const line of log.split(/\r?\n/)) {
  const match = line.match(/\s((?:@[a-z0-9_-]+\/)?[a-z0-9_-]+\/[a-z0-9_-]+)\s*$/i);
  if (match) {
    rules.add(match[1]);
  }
}

const totalText = totals
  ? `${totals[2]} error(s), ${totals[3]} warning(s)`
  : "problem totals unavailable";
const ruleText = rules.size > 0 ? [...rules].sort().join(", ") : "rule IDs unavailable";
console.log(`Safe check summary: ${totalText}; rules: ${ruleText}.`);

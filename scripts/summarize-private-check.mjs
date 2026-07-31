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
  log = fs.readFileSync(logPath, "utf8").replace(/\u001b\[[0-9;]*m/g, "");
} catch {
  console.log("Safe check summary unavailable.");
  process.exit(0);
}

const totals = log.match(/(?:✖|x)\s+(\d+)\s+problems?\s+\((\d+)\s+errors?,\s+(\d+)\s+warnings?\)/i);
const details = [];
for (const line of log.split(/\r?\n/)) {
  const match = line.match(/^\s*(\d+):(\d+)\s+(error|warning)\s+.*?\s{2,}(\S+)\s*$/i);
  if (match) {
    details.push(`${match[1]}:${match[2]}:${match[4]}`);
    continue;
  }
  const parserMatch = line.match(/^\s*(\d+):(\d+)\s+(error|warning)\s+Parsing error:/i);
  if (parserMatch) {
    details.push(`${parserMatch[1]}:${parserMatch[2]}:parsing-error`);
  }
}

const totalText = totals
  ? `${totals[2]} error(s), ${totals[3]} warning(s)`
  : "problem totals unavailable";
const detailText = details.length > 0 ? [...new Set(details)].join(", ") : "locations unavailable";
console.log(`Safe check summary: ${totalText}; locations and rules: ${detailText}.`);

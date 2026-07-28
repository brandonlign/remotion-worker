#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const inputFile = process.argv[2];
const outputFile = process.argv[3];
if (!inputFile || !outputFile) {
  throw new Error("Usage: validate-source-config.mjs <input.json> <normalized-output.json>");
}

const config = JSON.parse(fs.readFileSync(inputFile, "utf8"));
const allowedKeys = new Set([
  "entryPoint",
  "compositionId",
  "outputName",
  "installCommand",
  "checkCommand",
  "crf",
]);
for (const key of Object.keys(config)) {
  if (!allowedKeys.has(key)) {
    throw new Error(`Unsupported source config field: ${key}`);
  }
}

const safeRelativePath = (value, name) => {
  if (typeof value !== "string" || value.length < 1 || value.length > 240) {
    throw new Error(`${name} must be a non-empty relative path.`);
  }
  if (path.isAbsolute(value) || value.split(/[\\/]/).includes("..")) {
    throw new Error(`${name} must stay inside the private source checkout.`);
  }
  return value;
};

const safeCommand = (value, name, fallback) => {
  const command = value ?? fallback;
  if (typeof command !== "string" || command.length < 1 || command.length > 500) {
    throw new Error(`${name} must be a non-empty command under 500 characters.`);
  }
  if (command.includes("\n") || command.includes("\r")) {
    throw new Error(`${name} must be one line.`);
  }
  return command;
};

if (typeof config.compositionId !== "string" || !/^[A-Za-z0-9_-]{1,100}$/.test(config.compositionId)) {
  throw new Error("compositionId contains unsupported characters.");
}

if (typeof config.outputName !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(config.outputName)) {
  throw new Error("outputName contains unsupported characters.");
}

const crf = config.crf ?? 23;
if (!Number.isInteger(crf) || crf < 1 || crf > 51) {
  throw new Error("crf must be an integer from 1 through 51.");
}

const normalized = {
  entryPoint: safeRelativePath(config.entryPoint, "entryPoint"),
  compositionId: config.compositionId,
  outputName: config.outputName,
  installCommand: safeCommand(config.installCommand, "installCommand", "npm ci --no-audit --no-fund"),
  checkCommand: safeCommand(config.checkCommand, "checkCommand", "npm run lint"),
  crf,
};

fs.writeFileSync(outputFile, `${JSON.stringify(normalized, null, 2)}\n`, { mode: 0o600 });
console.log("Validated private source configuration.");

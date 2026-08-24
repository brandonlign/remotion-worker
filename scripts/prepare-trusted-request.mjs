#!/usr/bin/env node

import fs from "node:fs";
import {execFileSync} from "node:child_process";

const kind = String(process.env.WORKFLOW_KIND ?? "").trim();
const headSha = String(process.env.HEAD_SHA ?? "").trim();
const baseSha = String(process.env.BASE_SHA ?? "").trim();
const headRef = String(process.env.HEAD_REF ?? "").trim();
const requestPath = kind === "preview"
  ? "jobs/preview-request.json"
  : kind === "finalize"
    ? "jobs/finalize-request.json"
    : "jobs/request.json";

if (!["render", "finalize", "preview"].includes(kind)) throw new Error("WORKFLOW_KIND must be render, finalize, or preview.");
if (!/^[0-9a-f]{40}$/i.test(headSha) || !/^[0-9a-f]{40}$/i.test(baseSha)) {
  throw new Error("Trusted worker request preparation requires complete base and head commit SHAs.");
}
const expectedPrefix = kind === "preview" ? "preview/" : "render/";
if (!headRef.startsWith(expectedPrefix) || headRef.length <= expectedPrefix.length) {
  throw new Error(`${kind} worker requests require a ${expectedPrefix}<jobId> branch.`);
}

execFileSync("git", ["fetch", "--no-tags", "origin", baseSha, headSha], {stdio: "inherit"});
const changed = execFileSync("git", ["diff", "--name-only", baseSha, headSha], {encoding: "utf8"})
  .split(/\r?\n/)
  .map((value) => value.trim())
  .filter(Boolean);
const allowed = kind === "preview"
  ? new Set([requestPath])
  : new Set(["jobs/request.json", "jobs/finalize-request.json"]);
if (changed.length === 0 || changed.some((file) => !allowed.has(file))) {
  throw new Error(`${headRef} may change only the trusted ${[...allowed].join(" and ")} request path(s); changed: ${changed.join(", ") || "none"}.`);
}

const parent = execFileSync("git", ["rev-list", "--parents", "-n", "1", headSha], {encoding: "utf8"})
  .trim()
  .split(/\s+/)[1];
if (!/^[0-9a-f]{40}$/i.test(parent ?? "")) throw new Error("Trusted worker request preparation could not resolve the PR head parent.");
const latestChanged = execFileSync("git", ["diff", "--name-only", parent, headSha], {encoding: "utf8"})
  .split(/\r?\n/)
  .map((value) => value.trim())
  .filter(Boolean);
const skipFinalize = kind === "finalize" && !latestChanged.includes("jobs/finalize-request.json");
// A finalize-only commit can still have the original jobs/request.json in the
// cumulative PR diff. Keep the render workflow green but inert for that run;
// the finalize workflow is the only secret-bearing path that should execute.
const skipRender = kind === "render" && latestChanged.includes("jobs/finalize-request.json");
const skip = skipRender || skipFinalize;

if (!skip && !changed.includes(requestPath)) {
  throw new Error(`${kind} workflow requires the current ${requestPath} in the trusted request diff; changed: ${changed.join(", ") || "none"}.`);
}

if (!skip) {
  const raw = execFileSync("git", ["show", `${headSha}:${requestPath}`], {encoding: "utf8"});
  JSON.parse(raw);
  fs.mkdirSync("jobs", {recursive: true});
  fs.writeFileSync(requestPath, raw, {encoding: "utf8", mode: 0o600});
}

if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `request_path=${requestPath}\nhead_sha=${headSha}\nskip=${skip ? "true" : "false"}\n`);
console.log(skip
  ? `No ${kind} request was changed by the triggering commit; trusted workflow is inert.`
  : `Prepared trusted ${kind} request from ${headSha}; no PR-controlled worker code was checked out or executed.`);

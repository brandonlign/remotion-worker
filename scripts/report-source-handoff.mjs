#!/usr/bin/env node
import fs from 'node:fs/promises';

const [requestPath, workflowKind = 'render'] = process.argv.slice(2);
if (!requestPath) throw new Error('Usage: report-source-handoff.mjs <request.json> [render|finalize]');

const request = JSON.parse(await fs.readFile(requestPath, 'utf8'));
const jobId = String(request.jobId ?? '').trim();
const sourceSha = String(request.sourceSha ?? '').trim();
const revision = Number(request.revision);
const mode = workflowKind === 'finalize' ? 'finalize' : String(request.mode ?? '').trim();
if (!jobId || !/^[0-9a-f]{40}$/i.test(sourceSha) || !Number.isInteger(revision) || revision < 1) {
  throw new Error('Request is missing a valid jobId/sourceSha/revision.');
}
if (workflowKind === 'render' && mode !== 'render') {
  console.log(`Skipping source handoff for worker mode ${mode}.`);
  process.exit(0);
}

const sourceRepository = String(process.env.SOURCE_REPOSITORY ?? '').trim();
const token = String(process.env.SOURCE_REPO_TOKEN ?? '').trim();
const runId = String(process.env.WORKER_RUN_ID ?? process.env.GITHUB_RUN_ID ?? '').trim();
const runUrl = String(process.env.WORKER_RUN_URL ?? '').trim();
const workerSha = String(process.env.WORKER_HEAD_SHA ?? process.env.GITHUB_SHA ?? '').trim();
if (!/^[^/]+\/[^/]+$/.test(sourceRepository) || !token) throw new Error('SOURCE_REPOSITORY/SOURCE_REPO_TOKEN are required.');

const api = async (url, options = {}) => {
  const response = await fetch(url, {
    ...options,
    headers: {
      accept: 'application/vnd.github+json',
      authorization: `Bearer ${token}`,
      'x-github-api-version': '2022-11-28',
      'user-agent': 'telic-worker-handoff',
      ...(options.headers ?? {}),
    },
    signal: AbortSignal.timeout(30_000),
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) throw new Error(`GitHub API ${response.status}: ${payload?.message ?? text}`);
  return payload;
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let issue = null;
for (let attempt = 0; attempt < 4 && !issue; attempt += 1) {
  const q = encodeURIComponent(`repo:${sourceRepository} is:issue in:title "${jobId}"`);
  const result = await api(`https://api.github.com/search/issues?q=${q}&per_page=20`);
  const matches = (result.items ?? []).filter((item) => String(item.title ?? '').includes(jobId));
  issue = matches.find((item) => item.state === 'open') ?? matches[0] ?? null;
  if (!issue && attempt < 3) await sleep(2_000 * (attempt + 1));
}
if (!issue) throw new Error(`Could not resolve source coordination issue for ${jobId}.`);

const handoff = {
  schemaVersion: 1,
  jobId,
  sourceSha,
  revision,
  mode,
  status: 'drive_delivered',
  deterministicQc: 'passed_or_deduped_from_passed_identity',
  workerRepository: process.env.GITHUB_REPOSITORY ?? null,
  workerHeadSha: workerSha || null,
  workflowRunId: runId || null,
  workflowRunUrl: runUrl || null,
};
const body = `TELIC_WORKER_RESULT\n${JSON.stringify(handoff)}`;

const comments = await api(`https://api.github.com/repos/${sourceRepository}/issues/${issue.number}/comments?per_page=100`);
const duplicate = comments.some((comment) => {
  const text = String(comment.body ?? '');
  if (!text.startsWith('TELIC_WORKER_RESULT\n')) return false;
  try {
    const existing = JSON.parse(text.split(/\r?\n/, 2)[1]);
    return existing.jobId === jobId && existing.sourceSha === sourceSha && Number(existing.revision) === revision && existing.status === 'drive_delivered';
  } catch { return false; }
});
if (duplicate) {
  console.log(`Source handoff already recorded for ${jobId} ${sourceSha}:r${revision}.`);
  process.exit(0);
}

await api(`https://api.github.com/repos/${sourceRepository}/issues/${issue.number}/comments`, {
  method: 'POST',
  headers: {'content-type': 'application/json'},
  body: JSON.stringify({body}),
});
console.log(`Recorded authoritative worker handoff on source issue #${issue.number}.`);

#!/usr/bin/env node

const [jobId, sourceSha, revisionRaw, status, mode, workerPrRaw, workerCommit] = process.argv.slice(2);
const revision = Number(revisionRaw);
const workerPr = Number(workerPrRaw);

if (typeof jobId !== 'string' || !/^[a-z0-9][a-z0-9-]{5,63}$/.test(jobId)) throw new Error('Invalid jobId.');
if (!/^[0-9a-f]{40}$/.test(String(sourceSha ?? ''))) throw new Error('Invalid sourceSha.');
if (!Number.isInteger(revision) || revision < 1 || revision > 1000) throw new Error('Invalid revision.');
if (!new Set(['rendering', 'drive_verified', 'invalidated']).has(status)) throw new Error('Invalid render authority status.');
if (!new Set(['render', 'render-sequence', 'voice-prep']).has(mode)) throw new Error('Invalid worker mode.');
if (!Number.isInteger(workerPr) || workerPr < 1) throw new Error('Invalid worker PR number.');
if (!/^[0-9a-f]{40}$/.test(String(workerCommit ?? ''))) throw new Error('Invalid worker commit SHA.');

const authority = {
  jobId,
  sourceSha,
  revision,
  key: `${sourceSha}:r${revision}`,
  status,
  mode,
  workerPr,
  workerCommit,
};

process.stdout.write(`TELIC_RENDER_AUTHORITY: ${JSON.stringify(authority)}\n`);

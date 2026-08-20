#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SHA = '0123456789abcdef0123456789abcdef01234567';

const runValidate = (file, {expectFailure = false, outputFile} = {}) => new Promise((resolve, reject) => {
  const child = spawn(process.execPath, ['scripts/validate-job.mjs', file], {
    cwd: ROOT,
    env: {...process.env, ...(outputFile ? {GITHUB_OUTPUT: outputFile} : {})},
    stdio: 'ignore',
  });
  child.once('error', reject);
  child.once('exit', (code) => {
    if (expectFailure ? code !== 0 : code === 0) resolve();
    else reject(new Error(`validate-job exited ${code}; expectFailure=${expectFailure}`));
  });
});

const main = async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'worker-authority-'));
  try {
    const write = async (name, value) => {
      const file = path.join(dir, name);
      await fs.writeFile(file, `${JSON.stringify(value, null, 2)}\n`);
      return file;
    };

    await runValidate(await write('missing.json', {jobId: 'telic-render-test-001', sourceSha: SHA, revision: 1, mode: 'render'}), {expectFailure: true});
    await runValidate(await write('voice.json', {jobId: 'coffee-voice-test-001', sourceSha: SHA, revision: 1, mode: 'voice-prep'}));
    await runValidate(await write('wrong-repo.json', {
      jobId: 'telic-render-test-002', sourceSha: SHA, sourceRepository: 'someone/else', sourceIssueNumber: 12, revision: 1, mode: 'render',
    }), {expectFailure: true});

    const output = path.join(dir, 'github-output.txt');
    const valid = await write('valid.json', {
      jobId: 'coffee-render-test-001',
      sourceSha: SHA,
      sourceRepository: 'brandonlign/remotion-video',
      sourceIssueNumber: 387,
      revision: 4,
      mode: 'render',
    });
    await runValidate(valid, {outputFile: output});
    const text = await fs.readFile(output, 'utf8');
    assert.match(text, /source_repository=brandonlign\/remotion-video/);
    assert.match(text, /source_issue_number=387/);
    assert.match(text, /request_key=coffee-render-test-001-.*i387-r4-render/);

    console.log('Explicit worker render-authority tests passed.');
  } finally {
    await fs.rm(dir, {recursive: true, force: true});
  }
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});

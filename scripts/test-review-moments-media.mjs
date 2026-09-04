#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawnSync, execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';

if (spawnSync('ffmpeg', ['-version'], {stdio: 'ignore'}).status !== 0) {
  console.log('Skipping review-moment media test: FFmpeg is unavailable.');
} else {
  const exec = promisify(execFile);
  const root = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), 'review-moment-media-')));
  const script = fileURLToPath(new URL('./create-review-moments.mjs', import.meta.url));
  const video = path.join(root, 'source.mp4');
  const composition = path.join(root, 'composition.json');
  const moment = (id, frame) => ({id, frame, expectation: 'The exact requested frame must be preserved.'});
  const run = (output) => exec(process.execPath, [script, video, composition, path.join(root, output)]);
  try {
    await exec('ffmpeg', ['-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
      'testsrc2=size=320x180:rate=30:duration=2', '-c:v', 'libx264', '-preset', 'ultrafast', video]);
    for (const frames of [[17, 0, 17, 8], [59, 0, 17]]) {
      const output = `frames-${frames[0]}`;
      const moments = frames.map((frame, i) => moment(`target-${i}`, frame));
      await fs.writeFile(composition, JSON.stringify({fps: 30, durationInFrames: 60, reviewMoments: moments}));
      await run(output);
      const report = JSON.parse(await fs.readFile(path.join(root, output, 'review-moments.json'), 'utf8'));
      assert.deepEqual(report.moments.map(({frame}) => frame), frames);
      for (const entry of report.moments) {
        const reference = path.join(root, `reference-${entry.frame}.jpg`);
        await exec('ffmpeg', ['-y', '-hide_banner', '-loglevel', 'error', '-i', video,
          '-vf', `select=eq(n\\,${entry.frame}),scale=540:-2`, '-fps_mode', 'vfr', '-q:v', '2', reference]);
        assert.deepEqual(await fs.readFile(path.join(root, output, entry.file)), await fs.readFile(reference));
      }
    }
    await fs.writeFile(composition, JSON.stringify({fps: 30, durationInFrames: 100, reviewMoments: [moment('start', 0), moment('middle', 17), moment('missing', 90)]}));
    await assert.rejects(run('missing'), /did not produce frame 90/);
    await assert.rejects(fs.access(path.join(root, 'missing', 'review-moments.json')));
    assert.ok(!(await fs.readdir(path.join(root, 'missing'))).some((name) => name.startsWith('.batch-')));
    console.log('Exact review frames, duplicates, final-frame boundaries, and missing-frame rejection passed with FFmpeg.');
  } finally {
    await fs.rm(root, {recursive: true, force: true});
  }
}

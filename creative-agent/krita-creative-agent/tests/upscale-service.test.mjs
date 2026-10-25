// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The upscale service shares one job between requests for the same output (live, 2026-10-25: one companion started three
// sharpening workers on the same goal at once, and they fought for the CPU). No files are written.
import test from 'node:test';
import assert from 'node:assert/strict';
import { upscaleService } from '../src/upscale/index.ts';

const reply = { ms: 1, load_ms: 0, peak_mb: 1, provider: 'cpu', tiles: 1, ms_per_tile: 1, full: { width: 4, height: 4 }, reference: { width: 4, height: 4, path: '/x.ref.png', bytes: 1 }, compare: { width: 1, height: 1, crop: [0, 0, 1] } };
function fakeSpawn() {
  const spawned = [];
  const spawn = () => {
    let release; const done = new Promise(resolve => { release = resolve; });
    const link = { killed: false, run: async (_request, onProgress) => { onProgress(1, 2); await done; return reply; }, kill() { link.killed = true; } };
    spawned.push({ link, release });
    return link;
  };
  return { spawned, spawn };
}
const input = path => ({ rgba: new Uint8Array(64), width: 4, height: 4, outputs: { full: path, reference: path + '.r', compare: path + '.c' }, max_pixels: 100, max_bytes: 100 });

test('two services asked for the same output at once run one worker; both get its result and progress', async () => {
  const { spawned, spawn } = fakeSpawn();
  const a = upscaleService({ modelDir: async () => '/m', spawn }), b = upscaleService({ modelDir: async () => '/m', spawn });
  const seen = [];
  const first = a.upscale(input('/chat/goal-sharpen/abc.x4.png'), { onProgress: (d, t) => seen.push(['a', d, t]) });
  const second = b.upscale(input('/chat/goal-sharpen/abc.x4.png'), { onProgress: (d, t) => seen.push(['b', d, t]) });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(spawned.length, 1, 'one worker');
  spawned[0].release();
  assert.deepEqual(await first, reply); assert.deepEqual(await second, reply);
  assert.ok(seen.some(s => s[0] === 'b'), 'the joined request sees progress too');
  const third = a.upscale(input('/chat/goal-sharpen/abc.x4.png'));
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(spawned.length, 2, 'a later request runs again'); spawned[1].release(); await third;
});

test('a joined request that stops leaves the job running for the other; the last one stopping kills it', async () => {
  const { spawned, spawn } = fakeSpawn();
  const service = upscaleService({ modelDir: async () => '/m', spawn });
  const one = new AbortController(), two = new AbortController();
  const p1 = service.upscale(input('/chat/g.x4.png'), { signal: one.signal }), p2 = service.upscale(input('/chat/g.x4.png'), { signal: two.signal });
  await new Promise(resolve => setTimeout(resolve, 10));
  one.abort();
  await assert.rejects(p1, /stopped/i);
  assert.equal(spawned[0].link.killed, false, 'still wanted by the other');
  two.abort();
  await assert.rejects(p2, /stopped/i);
  assert.equal(spawned[0].link.killed, true);
});

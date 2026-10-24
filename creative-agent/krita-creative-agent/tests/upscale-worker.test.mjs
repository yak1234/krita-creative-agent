// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The sharpening worker (src/upscale/core.ts, worker.ts, index.ts) with a nearest-neighbour fake for the model
// (fixtures/fake-upscale-runtime.mjs): providers in order and the CPU check of an accelerator, the three files it writes,
// progress per tile, a real child process, a Stop that kills it, and plain messages for failures. Temporary folders only.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { upscaleCore, upscaleProviders } from '../src/upscale/core.ts';
import { upscaleService, forkUpscaler, upscaleFailure, UpscaleError } from '../src/upscale/index.ts';
import { decodePlane } from '../src/shapes/png.ts';
import { fakeUpscaler } from './fixtures/fake-upscale-runtime.mjs';

const FAKE = fileURLToPath(new URL('./fixtures/fake-upscale-runtime.mjs', import.meta.url));
const W = 150, H = 100;
function goal() {
  const rgba = new Uint8Array(W * H * 4);
  for (let i = 0; i < W * H; i++) { rgba[i * 4] = (i * 7) & 255; rgba[i * 4 + 1] = (i >> 3) & 255; rgba[i * 4 + 2] = 90; rgba[i * 4 + 3] = 255; }
  return rgba;
}
async function folder(t) {
  const dir = await mkdtemp(join(tmpdir(), 'upscale-worker-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}
const outputs = dir => ({ full: join(dir, 'full.png'), reference: join(dir, 'reference.png'), compare: join(dir, 'compare.png') });
const request = (dir, extra = {}) => ({ op: 'upscale', rgba: goal(), width: W, height: H, outputs: outputs(dir), max_pixels: 60000, ...extra });

test('providers: Core ML first on a Mac, CUDA on Linux, DirectML on Windows, the CPU last everywhere', () => {
  assert.deepEqual(upscaleProviders('darwin'), ['coreml', 'cpu']);
  assert.deepEqual(upscaleProviders('linux'), ['cuda', 'cpu']);
  assert.deepEqual(upscaleProviders('win32'), ['dml', 'cpu']);
});

test('the worker sharpens tile by tile and writes the 4x picture, the reference-size copy and the side-by-side', async t => {
  const dir = await folder(t), runtime = fakeUpscaler(), core = upscaleCore(runtime, { modelDir: '/m', platform: 'darwin', memory: () => 321 });
  const progress = [];
  const reply = await core.handle(request(dir), (done, total) => progress.push([done, total]));
  assert.equal(reply.provider, 'coreml');
  assert.deepEqual(reply.full, { width: 600, height: 400 });
  assert.equal(reply.tiles, 2 * 1);
  assert.deepEqual(progress, [[1, 2], [2, 2]]);
  assert.ok(reply.reference.width * reply.reference.height <= 60000 && Math.abs(reply.reference.width / reply.reference.height - 1.5) < 0.01);
  assert.equal(reply.peak_mb, 321);
  const full = decodePlane(await readFile(outputs(dir).full));
  assert.deepEqual([full.width, full.height], [600, 400]);
  const rgba = goal();
  for (const [x, y] of [[0, 0], [599, 399], [313, 201]]) assert.equal(full.data[y * 600 + x], rgba[(Math.floor(y / 4) * W + Math.floor(x / 4)) * 4], `${x},${y}`);
  const compare = decodePlane(await readFile(outputs(dir).compare));
  assert.deepEqual([compare.width, compare.height], [reply.compare.width, reply.compare.height]);
  assert.equal(runtime.counts.run.cpu, 1, 'the accelerator’s first tile is checked once against the CPU');
  assert.equal(reply.reference.path, outputs(dir).reference, 'reduced: its own file');
  const whole = await core.handle(request(dir, { max_pixels: 1e9, max_bytes: 1e9 }));
  assert.deepEqual([whole.reference.width, whole.reference.height, whole.reference.path], [600, 400, outputs(dir).full], 'read whole: the 4x file is the reference');
  const tight = await core.handle(request(dir, { max_pixels: 1e9, max_bytes: Math.floor(whole.reference.bytes / 2) }));
  assert.ok(tight.reference.width < 600 && tight.reference.bytes <= whole.reference.bytes / 2, 'shrunk until the file fits');
});

test('an accelerator that fails to load, disagrees with the CPU or stops half-way leaves the job to the CPU', async t => {
  const dir = await folder(t);
  const failing = fakeUpscaler({ fail: 'coreml' });
  assert.equal((await upscaleCore(failing, { modelDir: '/m', platform: 'darwin' }).handle(request(dir))).provider, 'cpu');
  const off = fakeUpscaler({ off: 'coreml' });
  const checked = await upscaleCore(off, { modelDir: '/m', platform: 'darwin' }).handle(request(dir, { max_pixels: 1e9 }));
  assert.equal(checked.provider, 'cpu');
  const full = decodePlane(await readFile(outputs(dir).full));
  assert.equal(full.data[0], goal()[0], 'the disagreeing tile is not used');
  const stops = fakeUpscaler({ broken: { provider: 'coreml', after: 2 } });
  assert.equal((await upscaleCore(stops, { modelDir: '/m', platform: 'darwin' }).handle(request(dir))).provider, 'cpu');
  const none = fakeUpscaler({ fail: 'cpu' });
  await assert.rejects(upscaleCore(none, { modelDir: '/m', platform: 'linux-other' }).handle(request(dir)), error => error.code === 'load_failed');
  await assert.rejects(upscaleCore(fakeUpscaler(), { modelDir: '/m' }).handle({ ...request(dir), width: 3 }), /Invalid goal pixels/);
  await assert.rejects(upscaleCore(fakeUpscaler(), { modelDir: '/m' }).handle({ ...request(dir), width: 2000, height: 1001, rgba: new Uint8Array(2000 * 1001 * 4) }),
    error => error.code === 'invalid' && /too large to sharpen/.test(error.message), 'input pixels are capped');
});

test('a real child process sharpens, reports progress and exits; a Stop kills it at once', async t => {
  const dir = await folder(t);
  const service = upscaleService({ modelDir: async () => '/m', spawn: modelDir => forkUpscaler(modelDir, { runtimeModule: FAKE }) });
  const progress = [];
  const reply = await service.upscale({ ...request(dir), op: undefined }, { onProgress: (done, total) => progress.push(done / total) });
  assert.deepEqual(reply.full, { width: 600, height: 400 });
  assert.ok(reply.peak_mb > 10, 'the child measures its own memory: ' + reply.peak_mb);
  assert.deepEqual(progress, [0.5, 1]);

  process.env.FAKE_UPSCALE_DELAY = '400';
  t.after(() => { delete process.env.FAKE_UPSCALE_DELAY; });
  const slow = upscaleService({ modelDir: async () => '/m', spawn: modelDir => forkUpscaler(modelDir, { runtimeModule: FAKE }) });
  const controller = new AbortController(), started = Date.now();
  const running = slow.upscale(request(await folder(t), { width: 400, height: 300, rgba: new Uint8Array(400 * 300 * 4) }), { signal: controller.signal, onProgress: () => controller.abort() });
  await assert.rejects(running, error => error instanceof UpscaleError && error.code === 'cancelled');
  assert.ok(Date.now() - started < 3000, 'stopped without waiting for the remaining tiles');
});

test('failures are plain: killed outright or out of memory says so, a model that does not load is a model error', () => {
  assert.equal(upscaleFailure({ signal: 'SIGKILL' }).code, 'out_of_memory');
  assert.match(upscaleFailure({ message: 'std::bad_alloc' }).message, /ran out of memory/);
  assert.equal(upscaleFailure({ code: 'load_failed', message: 'The sharpening model could not be loaded (cpu: x).' }).code, 'model');
  assert.match(upscaleFailure({ message: 'boom.\nstack' }).message, /^Sharpening failed: boom\.$/);
});

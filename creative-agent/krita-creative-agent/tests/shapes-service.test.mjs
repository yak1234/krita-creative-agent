// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Element shapes, the worker and the service (src/shapes/core.ts, worker.ts, index.ts) with a fake runtime
// (tests/fixtures/fake-shape-runtime.mjs): a reference is studied once, each shape is its mask's bounds, score and a
// cropped 8-bit PNG, a repeat prompt is answered from the chat folder's cache without the model, a failure is retried
// once with a fresh worker and then reported plainly, the providers go CUDA (Linux), DirectML (Windows), CPU, and the
// worker is a real child process that exits when idle. Files go to a temporary folder that is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { shapeService, forkWorker, ShapeError } from '../src/shapes/index.ts';
import { workerCore, providerOrder } from '../src/shapes/core.ts';
import { squareRgb } from '../src/shapes/image.ts';
import { decodePng } from './fixtures/png-rgba.ts';
import { fakeRuntime } from './fixtures/fake-shape-runtime.mjs';

const MODEL = { name: 'sam2.1-hiera-base-plus', revision: 'r1' };
const W = 512, H = 256;
const pixels = () => new Uint8Array(W * H * 4).fill(200);
const square = () => squareRgb(pixels(), W, H);
const FAKE = fileURLToPath(new URL('./fixtures/fake-shape-runtime.mjs', import.meta.url));

/** The worker's core in this process, behind the same link the child process gives: `fail(message, n)` makes call n die. */
function inProcess(runtime, { fail, reply } = {}) {
  const spawned = [], messages = [];
  const spawn = modelDir => {
    const core = workerCore(runtime, { modelDir, platform: 'darwin' }), listeners = [];
    let calls = 0;
    const link = {
      modelDir, core, closed: false,
      async call(message) {
        if (link.closed) throw new Error('The shape worker has stopped.');
        messages.push(message);
        const failure = fail?.(message, ++calls, spawned.length);
        if (failure) { link.closed = true; for (const listener of listeners) listener(failure); throw Object.assign(new Error(failure.message ?? 'The shape worker stopped.'), failure); }
        const answer = await core.handle(message);
        return reply ? reply(message, answer) : answer;
      },
      close() { link.closed = true; },
      onExit(listener) { listeners.push(listener); },
      listeners,
    };
    spawned.push(link);
    return link;
  };
  return { spawn, spawned, messages };
}

async function folder(t) {
  const dir = await mkdtemp(join(tmpdir(), 'shapes-test-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}

test('the providers go CUDA on Linux, DirectML on Windows, then the CPU; the CPU alone on a Mac', () => {
  assert.deepEqual(providerOrder('linux'), ['cuda', 'cpu']);
  assert.deepEqual(providerOrder('win32'), ['dml', 'cpu']);
  assert.deepEqual(providerOrder('darwin'), ['cpu']);
});

test('the worker core loads the first provider that works and records it; a shape before a study is refused', async () => {
  const runtime = fakeRuntime({ fail: 'cuda' }), core = workerCore(runtime, { modelDir: '/m', platform: 'linux' });
  await assert.rejects(core.handle({ op: 'shape', image_id: 'a', prompt: { box: [0, 0, 10, 10] } }), error => error.code === 'not_studied');
  const studied = await core.handle({ op: 'study', image_id: 'a', width: W, height: H, square: square() });
  assert.equal(studied.provider, 'cpu');
  assert.ok(studied.ms >= 0 && studied.peak_mb > 0);
  const again = await core.handle({ op: 'study', image_id: 'a', width: W, height: H, square: square() });
  assert.equal(runtime.counts.encode, 1, 'a reference is studied once while the worker lives');
  assert.equal(runtime.counts.decode, 1, 'a study warms the decoder up, so the first shape is as quick as the rest');
  assert.equal(again.studied, false);
});

test('a box gives the shape inside it: bounds, score, a cropped 8-bit PNG, the model, its revision and the timings', async t => {
  const dir = await folder(t), runtime = fakeRuntime(), timings = [];
  const { spawn } = inProcess(runtime);
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn, onTiming: entry => timings.push(entry) });
  t.after(() => service.close());
  const study = await service.study('hash-a', pixels(), W, H);
  assert.equal(study.provider, 'cpu');
  // 1024/16 = 64-unit cells (32 px across, 16 px down here); the box holds the centres of cells 3..12 across and 4..12 down.
  const shape = await service.shape('hash-a', { box: [100, 60, 312, 140] });
  assert.equal(shape.model, 'sam2.1-hiera-base-plus'); assert.equal(shape.revision, 'r1');
  assert.ok(Math.abs(shape.score - 0.93) < 1e-6);
  assert.equal(shape.provider, 'cpu'); assert.equal(shape.cached, false);
  assert.ok(shape.ms >= 0 && shape.peak_mb > 0);
  const [x, y, w, h] = shape.bounds;
  assert.ok(x >= 96 && x <= 116 && y >= 56 && y <= 76 && x + w >= 396 && x + w <= 420 && y + h >= 196 && y + h <= 212, String(shape.bounds));
  assert.ok(shape.mask_path.startsWith(dir));
  const mask = decodePng(await readFile(shape.mask_path));
  assert.equal(mask.width, w); assert.equal(mask.height, h);
  const at = (px, py) => mask.data[(py * w + px) * 4];
  assert.equal(at(w >> 1, h >> 1), 255, 'inside is 255');
  assert.ok([0, w - 1].every(px => Array.from({ length: h }, (_, py) => at(px, py)).includes(255)), 'cropped: the first and last columns hold the shape');
  assert.ok([0, h - 1].every(py => Array.from({ length: w }, (_, px) => at(px, py)).includes(255)), 'cropped: the first and last rows hold the shape');
  assert.deepEqual(timings.map(entry => entry.kind), ['study', 'shape']);
  for (const entry of timings) for (const key of ['ms', 'peak_mb', 'provider']) assert.ok(key in entry, key);
  assert.equal(timings[1].image_id, 'hash-a');
});

test('points include and exclude', async t => {
  const dir = await folder(t), { spawn } = inProcess(fakeRuntime());
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn });
  t.after(() => service.close());
  await service.study('hash-a', pixels(), W, H);
  const one = await service.shape('hash-a', { points: [[256, 128, 1]] });
  const [x, , w] = one.bounds;
  assert.ok(x > 180 && x + w < 330, String(one.bounds));
  await assert.rejects(service.shape('hash-a', { points: [[256, 128, 0]] }), /No shape/);
});

test('a repeat prompt never runs the model again, even in a later service, without studying', async t => {
  const dir = await folder(t), runtime = fakeRuntime(), { spawn, spawned } = inProcess(runtime), timings = [];
  let asked = 0;
  const modelDir = async () => { asked++; return '/model'; };
  const first = shapeService({ modelDir, cacheDir: () => dir, model: MODEL, spawn });
  await first.study('hash-a', pixels(), W, H);
  const shape = await first.shape('hash-a', { box: [100, 60, 312, 140] });
  const repeat = await first.shape('hash-a', { box: [100, 60, 312, 140] });
  assert.equal(runtime.counts.decode, 2, 'the warm-up and the one shape');
  assert.equal(repeat.cached, true); assert.deepEqual(repeat.bounds, shape.bounds); assert.equal(repeat.mask_path, shape.mask_path);
  await first.close();
  const later = shapeService({ modelDir, cacheDir: () => dir, model: MODEL, spawn, onTiming: entry => timings.push(entry) });
  const cached = await later.shape('hash-a', { box: [100, 60, 312, 140] });
  assert.equal(cached.cached, true); assert.equal(cached.provider, 'cache'); assert.ok(Math.abs(cached.score - 0.93) < 1e-6);
  assert.equal(runtime.counts.decode, 2); assert.equal(spawned.length, 1); assert.equal(asked, 1, 'a cached shape needs no model');
  assert.equal(timings[0].cached, true);
  await later.close();
  // Another revision of the model, or another reference, is another key.
  const other = shapeService({ modelDir, cacheDir: () => dir, model: { ...MODEL, revision: 'r2' }, spawn });
  await other.study('hash-a', pixels(), W, H);
  assert.equal((await other.shape('hash-a', { box: [100, 60, 312, 140] })).cached, false);
  await other.close();
  const files = await readdir(dir);
  assert.equal(files.filter(f => f.endsWith('.png')).length, 2); assert.equal(files.filter(f => f.endsWith('.json')).length, 2);
});

test('a worker that stopped is replaced once: the reference is studied again in the fresh worker and the shape found', async t => {
  const dir = await folder(t), runtime = fakeRuntime(), timings = [];
  const { spawn, spawned } = inProcess(runtime, { fail: (message, _n, workers) => message.op === 'shape' && workers === 1 ? { code: null, signal: 'SIGSEGV' } : null });
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn, onTiming: entry => timings.push(entry) });
  t.after(() => service.close());
  await service.study('hash-a', pixels(), W, H);
  const shape = await service.shape('hash-a', { box: [100, 60, 312, 140] });
  assert.equal(spawned.length, 2);
  assert.ok(spawned.every(link => link.modelDir === '/model'), 'the same model, never another');
  assert.equal(runtime.counts.encode, 2);
  assert.equal(shape.attempt, 2);
  assert.deepEqual(timings.map(entry => entry.kind), ['study', 'study', 'shape']);
});

test('a second failure is a plain message for the panel: memory, or what actually went wrong', async t => {
  const dir = await folder(t);
  const memory = inProcess(fakeRuntime(), { fail: message => message.op === 'study' ? { code: null, signal: 'SIGKILL' } : null });
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn: memory.spawn });
  await assert.rejects(service.study('hash-a', pixels(), W, H), error => error instanceof ShapeError && error.code === 'out_of_memory'
    && error.message === 'Finding shapes ran out of memory. Close some apps and try again.');
  assert.equal(memory.spawned.length, 1, 'out of memory is not retried: another 1.6 GB under memory pressure could get Krita killed');
  await service.close();
  const allocation = inProcess(fakeRuntime(), { fail: () => ({ message: 'onnxruntime: std::bad_alloc' }) });
  const second = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn: allocation.spawn });
  await assert.rejects(second.study('hash-a', pixels(), W, H), error => error.code === 'out_of_memory');
  assert.equal(allocation.spawned.length, 1);
  await second.close();
  const broken = inProcess(fakeRuntime(), { fail: () => ({ message: 'Load model failed: protobuf parsing failed', code: 1 }) });
  const third = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn: broken.spawn });
  await assert.rejects(third.study('hash-a', pixels(), W, H), error => error.code === 'failed' && /^Finding shapes failed/.test(error.message)
    && /protobuf parsing failed/.test(error.message));
  assert.equal(broken.spawned.length, 2, 'any other failure is retried once');
  await third.close();
  // A prompt outside the reference is the caller's mistake: refused at once, nothing retried.
  const fine = inProcess(fakeRuntime());
  const fourth = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn: fine.spawn });
  await fourth.study('hash-a', pixels(), W, H);
  await assert.rejects(fourth.shape('hash-a', { box: [500, 0, 100, 10] }), error => error.code === 'invalid' && /inside the reference/.test(error.message));
  await assert.rejects(fourth.shape('hash-b', { box: [0, 0, 10, 10] }), error => error.code === 'not_studied');
  assert.equal(fine.spawned.length, 1);
  await fourth.close();
});

test('a worker that exited when idle is started again and studies the reference again', async t => {
  const dir = await folder(t), runtime = fakeRuntime(), { spawn, spawned } = inProcess(runtime);
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn });
  t.after(() => service.close());
  await service.study('hash-a', pixels(), W, H);
  spawned[0].close(); for (const listener of spawned[0].listeners) listener({ code: 0, signal: null });   // as the idle child does
  const shape = await service.shape('hash-a', { box: [100, 60, 312, 140] });
  assert.equal(spawned.length, 2); assert.equal(runtime.counts.encode, 2); assert.equal(shape.attempt, 1);
});

test('the worker is a real child process: it studies, finds shapes, measures its own memory and exits when idle', async t => {
  const dir = await folder(t);
  let exited = null;
  const spawn = modelDir => {
    const link = forkWorker(modelDir, { idleMs: 400, runtimeModule: FAKE });
    link.onExit(info => { exited = info; });
    return link;
  };
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn });
  t.after(() => service.close());
  const study = await service.study('hash-a', pixels(), W, H);
  assert.equal(study.provider, 'cpu');
  assert.ok(study.peak_mb > 10, 'the child process measures its own peak memory: ' + study.peak_mb);
  const shape = await service.shape('hash-a', { box: [100, 60, 312, 140] });
  assert.ok(Math.abs(shape.score - 0.93) < 1e-6);
  assert.equal(decodePng(await readFile(shape.mask_path)).width, shape.bounds[2]);
  const started = Date.now();
  while (!exited && Date.now() - started < 5000) await new Promise(resolve => setTimeout(resolve, 50));
  assert.ok(exited, 'the worker is gone when idle (retired by the service just before it would exit by itself), so its memory is freed');
  const again = await service.shape('hash-a', { box: [10, 10, 100, 100] });
  assert.equal(again.cached, false, 'a new prompt starts a new worker and studies again from the kept pixels');
});

test('study bookkeeping: A, B, C, A, D then a shape of A needs no second worker', async t => {
  const dir = await folder(t), runtime = fakeRuntime(), { spawn, spawned } = inProcess(runtime);
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn });
  t.after(() => service.close());
  for (const id of ['A', 'B', 'C', 'A', 'D']) await service.study(id, pixels(), W, H);
  await service.shape('A', { box: [100, 60, 312, 140] });
  assert.equal(spawned.length, 1);
  assert.equal(runtime.counts.encode, 4, 'A studied once: the repeat only refreshed it');
});

test('a worker that forgot a study is asked to study it again, in the same worker and without a retry', async t => {
  const dir = await folder(t), runtime = fakeRuntime(), timings = [], { spawn, spawned } = inProcess(runtime);
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn, onTiming: e => timings.push(e) });
  t.after(() => service.close());
  await service.study('A', pixels(), W, H);
  await spawned[0].core.handle({ op: 'forget', image_id: 'A' });        // the worker lost it; the service does not know
  const shape = await service.shape('A', { box: [100, 60, 312, 140] });
  assert.equal(spawned.length, 1); assert.equal(spawned[0].closed, false); assert.equal(shape.attempt, 1);
  assert.equal(runtime.counts.encode, 2);
});

test('forget drops a reference from the service and from the worker', async t => {
  const dir = await folder(t), runtime = fakeRuntime(), { spawn, messages } = inProcess(runtime);
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn });
  t.after(() => service.close());
  await service.study('A', pixels(), W, H);
  await service.forget('A');
  assert.deepEqual(messages.at(-1), { op: 'forget', image_id: 'A' });
  await assert.rejects(service.shape('A', { box: [100, 60, 312, 140] }), error => error.code === 'not_studied');
  await service.forget('never-studied');                                // harmless, and starts no worker
});

test('the service keeps a 1024 square of each reference, not its full-size pixels, and up to four of them', async t => {
  const dir = await folder(t), runtime = fakeRuntime(), { spawn, messages, spawned } = inProcess(runtime);
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn });
  t.after(() => service.close());
  for (const id of ['A', 'B', 'C', 'D']) await service.study(id, pixels(), W, H);
  const study = messages.find(m => m.op === 'study');
  assert.equal(study.square.length, 1024 * 1024 * 3); assert.equal(study.pixels, undefined);
  assert.equal(study.width, W); assert.equal(study.height, H);
  spawned[0].close(); for (const listener of spawned[0].listeners) listener({ code: 0, signal: null });
  for (const id of ['A', 'B', 'C', 'D']) await service.shape(id, { box: [100, 60, 312, 140] });   // all four studied again
  assert.equal(spawned.length, 2);
});

test('an idle exit racing a request is not a failure, and the service retires an idle worker itself', async t => {
  const dir = await folder(t), runtime = fakeRuntime();
  const { spawn, spawned } = inProcess(runtime, { fail: (message, n, workers) => workers === 1 && message.op === 'shape' ? { code: 0, signal: null } : null });
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn, idleMs: 300 });
  t.after(() => service.close());
  await service.study('A', pixels(), W, H);
  const shape = await service.shape('A', { box: [100, 60, 312, 140] });
  assert.equal(shape.attempt, 1, 'an exit with code 0 is the idle exit: not counted as a failed attempt');
  assert.equal(spawned.length, 2);
  await new Promise(resolve => setTimeout(resolve, 400));
  assert.equal(spawned[1].closed, true, 'retired before its own idle exit could race the next request');
});

test('a worker reply whose mask does not fit its bounds is refused', async t => {
  const dir = await folder(t), { spawn } = inProcess(fakeRuntime(), { reply: (message, answer) => message.op === 'shape' ? { ...answer, mask: new Uint8Array(3) } : answer });
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn });
  t.after(() => service.close());
  await service.study('A', pixels(), W, H);
  await assert.rejects(service.shape('A', { box: [100, 60, 312, 140] }), error => error instanceof ShapeError && error.code === 'failed');
});

test('a cached entry finds its mask by its key, never by a path stored in it', async t => {
  const dir = await folder(t), { spawn } = inProcess(fakeRuntime());
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn });
  t.after(() => service.close());
  await service.study('A', pixels(), W, H);
  const shape = await service.shape('A', { box: [100, 60, 312, 140] });
  const { writeFile } = await import('node:fs/promises');
  const json = shape.mask_path.replace(/\.png$/, '.json'), entry = JSON.parse(await readFile(json, 'utf8'));
  await writeFile(json, JSON.stringify({ ...entry, mask: '../../elsewhere.png' }));
  assert.equal((await service.shape('A', { box: [100, 60, 312, 140] })).mask_path, shape.mask_path);
});

test('close does not wait for a request in flight: it is cancelled', async t => {
  const dir = await folder(t);
  const link = { call: () => new Promise(() => {}), close() { link.closed = true; }, onExit() {} };
  const service = shapeService({ modelDir: async () => '/model', cacheDir: () => dir, model: MODEL, spawn: () => link });
  const studying = service.study('A', pixels(), W, H);
  await new Promise(resolve => setTimeout(resolve, 20));
  await service.close();
  assert.equal(link.closed, true);
  await assert.rejects(studying, error => error.code === 'cancelled');
});

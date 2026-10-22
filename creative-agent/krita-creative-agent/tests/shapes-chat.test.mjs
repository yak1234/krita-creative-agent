// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Element shapes in a chat (src/shapes/chat.ts): before the first download the panel is told the model's size and waits
// for the artist's OK (shapes_model_needed; the panel answers with the shapes_model command), the chat records the model
// and revision it uses and keeps them, shapes are cached in the chat folder, and every study and shape logs
// {ms, peak_mb, provider} to the diagnostics and as a shape_timing event (which the test driver's report collects).
// With a fake runtime and a fake download; files go to a temporary folder that is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, truncate, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chatShapes } from '../src/shapes/chat.ts';
import { workerCore } from '../src/shapes/core.ts';
import { SHAPES_MODEL, modelDirectory } from '../src/shapes/model.ts';
import { fakeRuntime } from './fixtures/fake-shape-runtime.mjs';

const W = 64, H = 32, pixels = () => new Uint8Array(W * H * 4).fill(90);

function spawnInProcess(runtime) {
  return modelDir => {
    const core = workerCore(runtime, { modelDir, platform: 'darwin' });
    return { modelDir, call: message => core.handle(message), close() {}, onExit() {} };
  };
}

async function setup(t, { ready = false, download } = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'shapes-chat-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const events = [], records = [], downloads = [];
  const runtime = {
    config: { data_dir: join(dir, 'data'), output: join(dir, 'data') },
    study: { id: 'chat-1', directory: join(dir, 'chat-1') }, persisted: 0,
    emit: event => events.push(event), diagnostics: { record: event => records.push(event) },
    async persist() { this.persisted++; },
  };
  const directory = modelDirectory(runtime.config.data_dir);
  if (ready) await markReady(directory);
  const fake = fakeRuntime(), spawned = [];
  const shapes = chatShapes(runtime, {
    spawn: dirName => { spawned.push(dirName); return spawnInProcess(fake)(dirName); },
    download: download ?? (async ({ directory: into, onProgress }) => { downloads.push(into); onProgress?.(10, 100); onProgress?.(100, 100); await markReady(into); }),
  });
  t.after(() => shapes.close());
  return { runtime, shapes, events, records, downloads, spawned, directory, fake };
}

async function markReady(directory) {
  await mkdir(directory, { recursive: true });
  for (const file of SHAPES_MODEL.files) { await writeFile(join(directory, file.name), ''); await truncate(join(directory, file.name), file.size); }   // sparse: no disk used
  await writeFile(join(directory, 'verified.json'), JSON.stringify({ revision: SHAPES_MODEL.revision, files: Object.fromEntries(SHAPES_MODEL.files.map(f => [f.name, f.sha256])) }));
}
const tick = () => new Promise(resolve => setTimeout(resolve, 10));

test('the first shape asks the artist before downloading the model, with its size, and goes on after the OK', async t => {
  const { runtime, shapes, events, downloads, spawned, directory } = await setup(t);
  const studied = shapes.study('ref-hash', pixels(), W, H);
  await tick();
  const asked = events.filter(e => e.type === 'shapes_model_needed');
  assert.equal(asked.length, 1);
  assert.equal(asked[0].model, 'sam2.1-hiera-base-plus'); assert.equal(asked[0].revision, SHAPES_MODEL.revision);
  assert.ok(asked[0].size_mb >= 320 && asked[0].size_mb <= 340);
  assert.match(asked[0].message, /328 MB/);
  assert.equal(downloads.length, 0, 'nothing is downloaded before the OK');
  const second = shapes.study('ref-hash-2', pixels(), W, H);       // a second call meanwhile waits for the same answer
  await tick();
  assert.equal(events.filter(e => e.type === 'shapes_model_needed').length, 1);
  shapes.answer('accept');
  await studied; await second;
  assert.deepEqual(downloads, [directory]);
  assert.ok(events.some(e => e.type === 'status' && /Downloading the shape model/.test(e.message)));
  assert.ok(events.some(e => e.type === 'shapes_model_ready'));
  assert.deepEqual(spawned, [directory]);
  assert.deepEqual(runtime.study.shapes_model, { model: 'sam2.1-hiera-base-plus', revision: SHAPES_MODEL.revision });
  assert.ok(runtime.persisted >= 1, 'the chat records the model and revision it uses');
});

test('a decline lasts for the chat: every waiting call gets it, later calls fail at once, until the artist allows shapes again', async t => {
  const { shapes, events, runtime } = await setup(t);
  const first = shapes.study('ref-hash', pixels(), W, H), second = shapes.study('ref-hash-2', pixels(), W, H);
  await tick(); shapes.answer('decline');
  for (const call of [first, second]) await assert.rejects(call, error => error.code === 'declined' && /download/.test(error.message));
  assert.equal(runtime.study.shapes_model, undefined, 'a chat records a model only once it used it');
  assert.equal(runtime.study.shapes_declined, true); assert.ok(runtime.persisted >= 1, 'the decline is kept with the chat');
  assert.equal(shapes.answer('accept'), false, 'nothing waits for an answer now');
  await assert.rejects(shapes.study('ref-hash', pixels(), W, H), error => error.code === 'declined');
  assert.equal(events.filter(e => e.type === 'shapes_model_needed').length, 1, 'not asked again in this chat');
  assert.equal(shapes.answer('enable'), true);                       // the panel's "Ask again"
  assert.equal(runtime.study.shapes_declined, undefined);
  const again = shapes.study('ref-hash', pixels(), W, H);
  await tick();
  assert.equal(events.filter(e => e.type === 'shapes_model_needed').length, 2);
  shapes.answer('accept'); await again;
});

test('Stop cancels a pending download question; the next shape asks again', async t => {
  const { shapes, events } = await setup(t);
  const waiting = shapes.study('ref-hash', pixels(), W, H);
  await tick(); shapes.stop();
  await assert.rejects(waiting, error => error.code === 'cancelled');
  const again = shapes.study('ref-hash', pixels(), W, H);
  await tick();
  assert.equal(events.filter(e => e.type === 'shapes_model_needed').length, 2);
  shapes.answer('accept'); await again;
});

test('close during a download does not wait for it: the download is aborted and the call cancelled', async t => {
  let signal = null;
  const { shapes } = await setup(t, { download: async options => { signal = options.signal; await new Promise(() => {}); } });
  const waiting = shapes.study('ref-hash', pixels(), W, H);
  await tick(); shapes.answer('accept'); await tick();
  const started = Date.now();
  await shapes.close();
  assert.ok(Date.now() - started < 200, 'close returned at once');
  assert.equal(signal?.aborted, true, 'the download gets the abort');
  await assert.rejects(waiting, error => error.code === 'cancelled');
});

test('a model the worker cannot load is checked again: its verified record is removed and the files fetched as needed', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'shapes-chat-')); t.after(() => rm(dir, { recursive: true, force: true }));
  const events = [], downloads = [];
  const runtime = { config: { data_dir: dir }, study: { id: 'c', directory: join(dir, 'c') }, emit: e => events.push(e), async persist() {} };
  const directory = modelDirectory(dir); await markReady(directory);
  const core = workerCore(fakeRuntime(), { modelDir: directory, platform: 'darwin' });
  let workers = 0, verifiedAtRetry = null;
  const shapes = chatShapes(runtime, {
    spawn: () => { workers++; const n = workers; return { call: async m => {
      if (n === 1) throw Object.assign(new Error('The shape model could not be loaded (cpu: protobuf parsing failed).'), { code: 'load_failed' });
      return core.handle(m); }, close() {}, onExit() {} }; },
    download: async ({ directory: into }) => { downloads.push(into); verifiedAtRetry = existsSync(join(into, 'verified.json')); await markReady(into); },
  });
  t.after(() => shapes.close());
  await shapes.study('ref', pixels(), W, H);
  assert.equal(workers, 2); assert.deepEqual(downloads, [directory]);
  assert.equal(verifiedAtRetry, false, 'the damaged model is checked file by file again');
  assert.equal(events.filter(e => e.type === 'shapes_model_needed').length, 0, 'the artist agreed to this model already');
});

test('a ready model is used at once; a failed download is a plain error and nothing else is tried', async t => {
  const ready = await setup(t, { ready: true });
  await ready.shapes.study('ref-hash', pixels(), W, H);
  assert.equal(ready.events.filter(e => e.type === 'shapes_model_needed').length, 0);
  const broken = await setup(t, { download: async () => { throw Object.assign(new Error('vision_encoder.onnx does not match its pinned checksum: refused and removed.'), { code: 'checksum' }); } });
  const studied = broken.shapes.study('ref-hash', pixels(), W, H);
  await tick(); broken.shapes.answer('accept');
  await assert.rejects(studied, error => error.code === 'model' && /checksum/.test(error.message) && /shape model/.test(error.message));
  assert.equal(broken.spawned.length, 0);
});

test('a chat keeps the model it started with: another revision recorded on the chat is refused, not swapped', async t => {
  const { runtime, shapes } = await setup(t, { ready: true });
  runtime.study.shapes_model = { model: 'sam2.1-hiera-base-plus', revision: 'an-older-revision' };
  await assert.rejects(shapes.study('ref-hash', pixels(), W, H), error => error.code === 'model' && /an-older-revision/.test(error.message));
});

test('every study and shape logs its time, peak memory and provider to the diagnostics and as an event', async t => {
  const { shapes, events, records, runtime } = await setup(t, { ready: true });
  await shapes.study('ref-hash', pixels(), W, H);
  const shape = await shapes.shape('ref-hash', { box: [8, 4, 40, 20] });
  assert.ok(shape.mask_path.startsWith(join(runtime.study.directory, 'shapes')), 'cached in the chat folder');
  await shapes.shape('ref-hash', { box: [8, 4, 40, 20] });
  const logged = records.filter(r => r.type === 'shape_timing');
  assert.deepEqual(logged.map(r => [r.kind, !!r.cached]), [['study', false], ['shape', false], ['shape', true]]);
  for (const entry of logged) {
    assert.equal(typeof entry.ms, 'number'); assert.equal(typeof entry.peak_mb, 'number'); assert.equal(typeof entry.provider, 'string');
    assert.equal(entry.model, 'sam2.1-hiera-base-plus'); assert.equal(entry.chat_id, 'chat-1');
  }
  assert.deepEqual(events.filter(e => e.type === 'shape_timing').map(e => e.kind), ['study', 'shape', 'shape']);
});

test('shapes need an open chat', async t => {
  const { runtime, shapes } = await setup(t, { ready: true });
  runtime.study = undefined;
  await assert.rejects(shapes.study('ref-hash', pixels(), W, H), /chat/);
});

test('the studio carries the chat’s shapes, the panel’s answer reaches them, and a chat’s end stops the worker', async () => {
  const { readFile } = await import('node:fs/promises');
  const { StudioRuntime } = await import('../src/studio.mjs');
  const runtime = new StudioRuntime({ config: { output: '/tmp/creative-store-placeholder' }, emit: () => {} });
  try {
    for (const method of ['study', 'shape', 'close', 'answer']) assert.equal(typeof runtime.shapes[method], 'function', method);
    assert.equal(runtime.shapes.answer('accept'), false, 'nothing waits for an answer');
  } finally { runtime.dispose(); }
  const main = await readFile(new URL('../src/main.mjs', import.meta.url), 'utf8');
  assert.match(main, /case 'shapes_model':/);
  assert.match(main, /\['accept', 'enable'\]\.includes\(command\.action\) \? command\.action : 'decline'/);
  const studio = await readFile(new URL('../src/studio.mjs', import.meta.url), 'utf8');
  assert.match(studio.slice(studio.indexOf('async _end()')), /this\.shapes\?\.close\(\)/);
  assert.match(studio.slice(studio.indexOf('async _end()')), /this\.shapeStudies = undefined; this\.canvasPixels = null;/,
    'the chat’s studies (use.ts) go with its worker');
  let stopped = 0;
  const other = new StudioRuntime({ config: { output: '/tmp/creative-store-placeholder' }, emit: () => {}, shapes: { stop: () => stopped++, close: async () => {} } });
  try { other.stop(); } finally { other.dispose(); }
  assert.equal(stopped, 1, 'the panel’s Stop reaches the shapes (a pending download question or download)');
});

// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Element shapes end to end with the real service code path (chat.ts, index.ts, core.ts; only ONNX Runtime is the fake
// of tests/fixtures/fake-shape-runtime.mjs): a guide traced from a shape on a reference, a pass painted inside a shape
// on the painting and a protection proposed from a shape, then the shape timings the chat emitted read by the test
// driver's companion as its state's shape_timings. The plugin and the companion process are fakes. Files go to a
// temporary folder that is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { mkdtemp, mkdir, rm, truncate, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { guideTools } from '../src/guide-tool.ts';
import { paintingTools } from '../src/tools.mjs';
import { mapReferencePoint } from '../src/reference-generator.mjs';
import { chatShapes } from '../src/shapes/chat.ts';
import { workerCore } from '../src/shapes/core.ts';
import { SHAPES_MODEL, modelDirectory } from '../src/shapes/model.ts';
import { TestCompanion } from '../src/test-companion.ts';
import { fakeRuntime } from './fixtures/fake-shape-runtime.mjs';
import { fakeTraceEdges } from './fixtures/fake-trace-edges.mjs';

function grey(width, height, dark) {
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const v = dark(x, y) ? 50 : 210, i = (y * width + x) * 4;
    data[i] = data[i + 1] = data[i + 2] = v; data[i + 3] = 255;
  }
  return { width, height, data };
}

async function markReady(directory) {
  await mkdir(directory, { recursive: true });
  for (const file of SHAPES_MODEL.files) { await writeFile(join(directory, file.name), ''); await truncate(join(directory, file.name), file.size); }
  await writeFile(join(directory, 'verified.json'), JSON.stringify({ revision: SHAPES_MODEL.revision, files: Object.fromEntries(SHAPES_MODEL.files.map(f => [f.name, f.sha256])) }));
}

test('a guide, a pass and a protection from shapes through the real service, and their timings in the driver state', async t => {
  const folder = await mkdtemp(join(tmpdir(), 'shapes-e2e-'));
  t.after(() => rm(folder, { recursive: true, force: true }));
  const data = join(folder, 'data'), chat = join(folder, 'chat');
  await mkdir(join(chat, '.previews'), { recursive: true });
  await markReady(modelDirectory(data));
  const view = join(chat, '.previews', 'view-1.png');
  await writeFile(view, 'the canvas view');
  const events = [], records = [], calls = [], ort = fakeRuntime();
  const reference = grey(400, 600, (x, y) => x >= 100 && x < 300 && y >= 40);             // a dark tower
  const canvas = grey(1000, 500, (x, y) => Math.hypot(x - 150, y - 120) <= 40);         // a dark moon on the view
  const runtime = {
    config: { data_dir: data }, forkTools: true, faulted: false, calls,
    study: { id: 'chat-1', directory: chat, references: [{ id: 'goal', width: 400, height: 600 }] },
    decisionObservation: { width: 2000, height: 1000, image_path: view, image_width: 1000, image_height: 500 },
    emit: event => events.push(event), diagnostics: { record: event => records.push(event) }, async persist() {},
    async callNative(operation, params, id) {
      calls.push({ operation, params, id });
      if (operation === 'trace_reference') return { sha256: params.sha256, width: 1000, height: 500, rgba_base64: Buffer.from(canvas.data).toString('base64') };
      return { status: 'ok', layer_id: 'L' + calls.length };
    },
  };
  runtime.shapes = chatShapes(runtime, { spawn: modelDir => {
    const core = workerCore(ort, { modelDir, platform: 'darwin' });
    return { call: message => core.handle(message), close() {}, onExit() {} };
  } });
  t.after(() => runtime.shapes.close());

  // A guide from a shape on the reference.
  const guides = guideTools(runtime, {
    execute: operation => async (id, params) => { calls.push({ operation, params }); return { content: [{ type: 'text', text: '{"status":"ok"}' }], details: { status: 'ok' } }; },
    mapPoint: mapReferencePoint, referencePixels: async () => reference, traceEdges: fakeTraceEdges(() => [400, 600]) });
  const guide = await guides.find(x => x.name === 'draw_guide').execute('g1',
    { element: 'Tower', from_reference: { reference_id: 'goal', shape: { box: [90, 30, 220, 570] }, target: [100, 100, 440, 1140] } });
  assert.match(guide.content.map(p => p.text ?? '').join(' '), /"shape":\{"score":0\.93/);
  assert.ok(calls.some(c => c.operation === 'draw_guide' && c.params.strokes.length > 0), 'guide lines reach the plugin');

  // A pass inside a shape on the painting, and a protection proposed from one.
  const tools = paintingTools(runtime);
  await tools.find(x => x.name === 'paint_pass').execute('p1', { name: 'Moon glow', preset: 'b) Basic-1',
    strokes: [{ start: [250, 230], segments: [[260, 230, 290, 240, 330, 250]], size: 30, opacity: 1, flow: 1, color: '#f0e8c0' }],
    inside_shape: { box: [200, 140, 200, 200] } });
  const pass = calls.find(c => c.operation === 'paint_pass');
  assert.ok(pass.params.inside_shape.mask_path.startsWith(join(chat, '.shapes')));
  await tools.find(x => x.name === 'propose_protection').execute('pr1', { name: 'Moon', shape: { box: [200, 140, 200, 200] } });
  assert.ok(calls.find(c => c.operation === 'propose_protection').params.area[0].element_shape);

  // Two images, two studies, three shapes: all through the worker core, with the cache in the chat folder.
  assert.equal(ort.counts.encode, 2);
  const timings = events.filter(e => e.type === 'shape_timing');
  assert.deepEqual(timings.map(e => e.kind), ['study', 'shape', 'study', 'shape', 'shape']);
  assert.ok(timings.every(e => e.provider === 'cpu' || e.provider === 'cache'));
  assert.equal(records.filter(r => r.type === 'shape_timing').length, 5, 'and in the diagnostics');

  // The test driver's companion reads them from the companion's events, as its state's shape_timings.
  const child = new EventEmitter();
  child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
  child.kill = () => child.emit('exit', 0);
  child.stdin.on('data', chunk => { for (const line of String(chunk).split('\n').filter(Boolean)) {
    const command = JSON.parse(line);
    if (command.type === 'start') { child.stdout.write(JSON.stringify({ type: 'study', id: 'chat-1' }) + '\n'); child.stdout.write(JSON.stringify({ type: 'busy', busy: true }) + '\n'); }
    if (command.type === 'shutdown') setImmediate(() => child.emit('exit', 0));
  } });
  setImmediate(() => child.stdout.write(JSON.stringify({ type: 'ready' }) + '\n'));
  const base = { node: 'node', companion: '/c/src/main.mjs', data_dir: data, project_root: folder, bridge_url: 'http://127.0.0.1:1', build_id: 'b' };
  const bridge = async (action, params = {}) => action === 'creative' && params.operation === 'health' ? { build: { build_id: 'b' }, session_active: false } : { status: 'ok' };
  const driven = new TestCompanion(base, join(folder, 'run'), { bridge, spawn: () => child, quietMs: 20 });
  await driven.start({ prompt: 'Trace the tower.', width: 800, height: 600 });
  for (const event of timings) child.stdout.write(JSON.stringify(event) + '\n');
  child.stdout.write(JSON.stringify({ type: 'busy', busy: false }) + '\n');
  const state = await driven.waitIdle(2000);
  assert.deepEqual(state.shape_timings.map(e => e.kind), ['study', 'shape', 'study', 'shape', 'shape']);
  assert.ok(state.shape_timings.every(e => typeof e.ms === 'number' && typeof e.peak_mb === 'number' && e.provider));
  await driven.end();
});

// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Guides from a reference (draw_guide from_reference; sharper-guides goals 2 and 3). The plugin traces at full
// resolution (trace_edges; its geometry is tested in tests/test_edge_trace.py); here: the caps grow with the element's
// size on the canvas, the companion asks the plugin with the right crop, scale and shapes, finds the big shapes once for
// a block-in, says so when it falls back to the brightness split, and maps the lines onto the target. Images are made
// in memory; files go to a temporary folder that is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, truncate, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { traceCaps, findBigShapes, labelMap, BIG_SHAPES, SHAPE_GRID } from '../src/guide-trace.ts';
import { guideTools, traceSide, GUIDE_LINES } from '../src/guide-tool.ts';
import { mapReferencePoint } from '../src/reference-generator.mjs';
import { traceReferencePixels, traceReferenceEdges, TRACE_REFERENCE_MB } from '../src/reference-tool.mjs';
import { decodePlane, encodePlane } from '../src/shapes/png.ts';
import { ShapeError } from '../src/shapes/index.ts';
import { chatShapes } from '../src/shapes/chat.ts';
import { SHAPES_MODEL, modelDirectory } from '../src/shapes/model.ts';

const grey = (width, height) => ({ width, height, data: new Uint8Array(width * height * 4) });
const strokeLines = strokes => strokes.map(s => [s.start, ...s.segments.map(seg => seg.slice(4))]);

/** A guide runtime and tools whose plugin trace is a fake: it records each request and answers `reply(request)`. */
function setup({ references = [{ id: 'goal', width: 1200, height: 900 }], shapes, declined = false, reply, pixels = grey(1200, 900) } = {}) {
  const calls = [], traces = [], decodes = [];
  const runtime = { study: { references, ...(declined ? { shapes_declined: true } : {}) }, decisionObservation: { width: 2400, height: 1800 },
    ...(shapes ? { shapes } : {}), emit() {} };
  const tools = guideTools(runtime, {
    execute: operation => async (id, params) => { calls.push({ operation, params }); return { content: [{ type: 'text', text: '{"status":"ok"}' }], details: { status: 'ok' } }; },
    mapPoint: mapReferencePoint,
    referencePixels: async (id, side) => { decodes.push(side); return pixels; },
    traceEdges: async request => { traces.push(request); return { silhouette: request.labels ? 'shapes' : 'brightness', ms: 120, width: 1200, height: 900,
      original_width: 1200, original_height: 900, ...(reply ? reply(request) : { lines: [{ kind: 'outline', points: [[100, 100], [500, 100], [500, 400]] },
        { kind: 'structure', points: [[200, 200], [200, 300]] }, { kind: 'light', points: [[50, 50], [60, 60]] }] }) }; },
  });
  return { runtime, calls, traces, decodes, draw: tools.find(t => t.name === 'draw_guide') };
}
const text = result => result.content.map(part => part.text ?? '').join(' ');

/** A fake shape service: a point in a rectangle of `rects` (image pixels) gets that rectangle, else nothing. */
function rectShapes(folder, rects, { score = 0.9 } = {}) {
  const prompts = [], studies = [];
  let count = 0;
  return { prompts, studies, service: {
    async study(key) { studies.push(key); return { ms: 1, peak_mb: 1, provider: 'cpu' }; },
    async shape(key, prompt) {
      prompts.push(prompt);
      const [x, y] = prompt.points?.[0] ?? [prompt.box[0] + prompt.box[2] / 2, prompt.box[1] + prompt.box[3] / 2];
      const hit = rects.find(([rx, ry, rw, rh]) => x >= rx && y >= ry && x < rx + rw && y < ry + rh);
      if (!hit) throw new ShapeError('empty', 'No shape was found there.');
      const [, , w, h] = hit, mask_path = join(folder, `s-${++count}.png`);
      await writeFile(mask_path, encodePlane({ width: w, height: h, data: new Uint8Array(w * h).fill(255) }));
      return { bounds: hit, score, mask_path, model: 'm', revision: 'r', ms: 5, peak_mb: 1, provider: 'cpu' };
    },
    async forget() {}, async close() {},
  } };
}
async function scratch(t) {
  const folder = await mkdtemp(join(tmpdir(), 'guide-trace-'));
  t.after(() => rm(folder, { recursive: true, force: true }));
  return folder;
}

test('the caps grow with the element’s size on the canvas, within draw_guide’s own limit', () => {
  assert.equal(traceCaps([0, 0, 200, 200], 'simple'), 8, 'a moon keeps the old cap');
  assert.equal(traceCaps([0, 0, 200, 200], 'medium'), 24);
  const city = traceCaps([0, 0, 3000, 2000], 'simple'), cityMedium = traceCaps([0, 0, 3000, 2000], 'medium');
  assert.ok(city > 30 && cityMedium > 2 * city, `a whole cityscape gets more (${city}, ${cityMedium})`);
  assert.ok(traceCaps([0, 0, 100000, 100000], 'medium') <= GUIDE_LINES - 16, 'never past what one call draws, with room for lights');
  for (let side = 100; side < 8000; side *= 1.5)
    assert.ok(traceCaps([0, 0, side, side], 'simple') <= traceCaps([0, 0, side * 1.5, side * 1.5], 'simple'), 'monotonic');
});

test('without the shapes model the plugin traces by brightness, and the result says so', async () => {
  const { calls, traces, decodes, draw } = setup();
  const result = await draw.execute('g1', { element: 'City', from_reference: { reference_id: 'goal', source: [0, 0, 1200, 900], target: [0, 0, 2400, 1800], lights: true } });
  assert.deepEqual(traces[0], { reference_id: 'goal', source: [0, 0, 1200, 900], scale: 2, detail: 'simple', lights: true,
    max_lines: traceCaps([0, 0, 2400, 1800], 'simple'), size: [1200, 900] });
  assert.deepEqual(decodes, [], 'no decode for shapes that cannot be found');
  const strokes = calls[0].params.strokes;
  assert.deepEqual(strokes.map(s => s.weight), ['contour', 'construction', 'light'], 'outlines contour, inner structure thin, lights warm');
  assert.deepEqual(strokeLines(strokes)[0], [[200, 200], [1000, 200], [1000, 800]], 'mapped onto the target (scale 2)');
  assert.match(text(result), /"silhouette":"brightness"/);
  assert.match(text(result), /shapes model[^.]*not available/i, 'no silent fallback');
  assert.equal(result.details.trace.ms, 120);
});

test('a declined shapes model is not asked again: brightness, and the result says why', async t => {
  const folder = await scratch(t);
  const shapes = rectShapes(folder, [[0, 0, 1200, 400]]);
  const { traces, draw } = setup({ shapes: shapes.service, declined: true });
  const result = await draw.execute('g1', { element: 'City', from_reference: { reference_id: 'goal', target: [0, 0, 2400, 1800] } });
  assert.equal(shapes.prompts.length, 0);
  assert.equal(traces[0].labels, undefined);
  assert.match(text(result), /not allowed the shapes model/i);
});

test('a block-in finds the big shapes once and sends them as labels; a figure stays on top of its mass', async t => {
  const folder = await scratch(t);
  // Sky, a building mass, a figure in front of it (image pixels of the 1200 x 900 decode).
  const sky = [0, 0, 1200, 400], mass = [100, 400, 900, 500], figure = [500, 600, 100, 250];
  const shapes = rectShapes(folder, [figure, sky, mass]);
  const { traces, draw, decodes } = setup({ shapes: shapes.service });
  const result = await draw.execute('g1', { element: 'City', from_reference: { reference_id: 'goal', target: [0, 0, 2400, 1800], detail: 'medium' } });
  assert.equal(shapes.studies.length, 1, 'studied once');
  assert.ok(shapes.prompts.length < SHAPE_GRID * SHAPE_GRID, `points inside a shape found already are skipped (${shapes.prompts.length})`);
  assert.ok(shapes.prompts.every(p => p.points?.length === 1 && p.points[0][2] === 1), 'one point on each');
  assert.equal(decodes.length, 1);
  const labels = traces[0].labels;
  assert.deepEqual([labels.bounds, labels.space, labels.inside], [[0, 0, 1200, 900], [1200, 900], false]);
  const plane = decodePlane(Buffer.from(labels.png_base64, 'base64'));
  const at = (x, y) => plane.data[y * plane.width + x];
  assert.ok(at(550, 700) && at(550, 700) !== at(200, 600) && at(200, 600) && at(600, 100) && at(600, 100) !== at(200, 600),
    'the sky, the mass and the figure each have their own id, the figure on top of the mass');
  assert.equal(at(1100, 600), 0, 'outside every shape: none');
  assert.match(text(result), /"silhouette":"shapes"/);
  assert.match(text(result), /"shapes":3/);
  // A second block-in of the same reference asks the shapes model nothing new.
  const asked = shapes.prompts.length;
  await draw.execute('g2', { element: 'City', from_reference: { reference_id: 'goal', target: [0, 0, 2400, 1800] } });
  assert.equal(shapes.prompts.length, asked, 'found once');
});

test('the shapes model failing falls back to brightness, saying why', async () => {
  const failing = { async study() { throw new ShapeError('out_of_memory', 'Finding shapes ran out of memory. Close some apps and try again.'); },
    async shape() { throw new Error('unreachable'); }, async forget() {}, async close() {} };
  const { traces, draw } = setup({ shapes: failing });
  const result = await draw.execute('g1', { element: 'City', from_reference: { reference_id: 'goal', target: [0, 0, 2400, 1800] } });
  assert.equal(traces[0].labels, undefined);
  assert.match(text(result), /ran out of memory/);
  assert.match(text(result), /"silhouette":"brightness"/);
});

test('findBigShapes keeps confident, new, big-enough shapes inside the crop, at most BIG_SHAPES', async t => {
  const folder = await scratch(t);
  const tiny = [10, 10, 4, 4], whole = [0, 0, 1000, 1000];
  const many = Array.from({ length: 64 }, (_, i) => [(i % 8) * 125, Math.floor(i / 8) * 125, 125, 125]);
  const host = { shapes: rectShapes(folder, [tiny, ...many]).service };
  const found = await findBigShapes(host, 'k', grey(1000, 1000), [0, 0, 1000, 1000]);
  assert.equal(found.length, BIG_SHAPES);
  const none = await findBigShapes({ shapes: rectShapes(folder, [whole]).service }, 'k2', grey(1000, 1000), [0, 0, 1000, 1000]);
  assert.deepEqual(none, [], 'a shape filling the whole crop is no shape');
  const unsure = await findBigShapes({ shapes: rectShapes(folder, [[0, 0, 500, 1000]], { score: 0.3 }).service }, 'k3', grey(1000, 1000), [0, 0, 1000, 1000]);
  assert.deepEqual(unsure, [], 'uncertain shapes are not outlined');
  const map = labelMap([{ bounds: [0, 0, 10, 10], data: new Uint8Array(100).fill(255) }, { bounds: [5, 5, 2, 2], data: new Uint8Array(4).fill(255) }], [0, 0, 20, 20], 20, 20);
  const plane = decodePlane(Buffer.from(map.png_base64, 'base64'));
  assert.deepEqual([plane.data[0], plane.data[5 * 20 + 5], plane.data[15 * 20 + 15]], [1, 2, 0], 'the smaller shape on top');
});

test('a pointed element traces inside its shape only, from a crop around it', async t => {
  const folder = await scratch(t);
  const tower = [400, 100, 200, 700];
  const shapes = rectShapes(folder, [tower]);
  const { traces, calls, draw } = setup({ shapes: shapes.service,
    reply: () => ({ lines: [{ kind: 'outline', points: [[400, 800], [400, 100], [600, 100], [600, 800]] }] }) });
  const result = await draw.execute('g1', { element: 'Tower', from_reference: { reference_id: 'goal', shape: { box: [380, 80, 240, 740] }, target: [100, 100, 480, 1480] } });
  const request = traces[0];
  assert.equal(request.labels.inside, true);
  assert.deepEqual(request.labels.space, [1200, 900]);
  const [x, y, w, h] = request.source;
  assert.ok(x <= 400 && y <= 100 && x + w >= 600 && y + h >= 800 && x >= 370 && x + w <= 630, `a crop round the shape (${request.source})`);
  assert.equal(request.scale, 2, 'the box maps at scale 2');
  const map = mapReferencePoint([380, 80, 240, 740], [100, 100, 480, 1480]);
  assert.deepEqual(strokeLines(calls[0].params.strokes)[0], [[400, 800], [400, 100], [600, 100], [600, 800]].map(([px, py]) => map(px, py)));
  assert.match(text(result), /"shape":\{"score":0\.9/);
  assert.match(text(result), /"silhouette":"shapes"/);
});

test('the traced lines leave room for the painter’s own lines and perspective', async () => {
  const { traces, draw } = setup();
  await draw.execute('g1', { element: 'City', from_reference: { reference_id: 'goal', target: [0, 0, 2400, 1800], detail: 'medium', lights: true },
    lines: Array.from({ length: 60 }, (_, i) => ({ points: [[i, 0], [i, 10]] })), perspective: { eye_level_y: 900, vanishing_points: [[1200, 900]], rays: 24 } });
  assert.ok(traces[0].max_lines + 8 + 60 + 25 <= GUIDE_LINES, `max_lines ${traces[0].max_lines}`);
});

test('the source and the lines are in the listed pixels: the plugin is told the listed size', async () => {
  // Listed at 600 x 450 (the file may be larger): the plugin maps the source from the listed size and answers in it.
  const { calls, traces, draw } = setup({ references: [{ id: 'goal', width: 600, height: 450 }],
    reply: () => ({ original_width: 1200, original_height: 900, lines: [{ kind: 'outline', points: [[100, 50], [500, 400]] }] }) });
  await draw.execute('g1', { element: 'City', from_reference: { reference_id: 'goal', source: [100, 50, 400, 300], target: [0, 0, 400, 300] } });
  assert.deepEqual([traces[0].source, traces[0].size], [[100, 50, 400, 300], [600, 450]]);
  assert.deepEqual(strokeLines(calls[0].params.strokes)[0], [[0, 0], [400, 350]], 'not rescaled by the file’s own size');
});

test('the scale the plugin gets stays in its range', async () => {
  const { traces, draw } = setup({ reply: () => ({ lines: [{ kind: 'outline', points: [[0, 0], [1, 1]] }] }) });
  await draw.execute('g1', { element: 'Speck', from_reference: { reference_id: 'goal', source: [0, 0, 4, 3], target: [0, 0, 2400, 1800] } });
  await draw.execute('g2', { element: 'Tiny', from_reference: { reference_id: 'goal', source: [0, 0, 1200, 900], target: [0, 0, 4, 3] } });
  assert.deepEqual(traces.map(t => t.scale), [100, 0.01]);
});

test('a call with no room left for traced lines is refused before anything runs', async t => {
  const folder = await scratch(t);
  const shapes = rectShapes(folder, [[0, 0, 1200, 400]]);
  const { traces, draw, calls } = setup({ shapes: shapes.service });
  // 128 - 100 own lines - 25 perspective = 3: not enough for one line and the lights.
  await assert.rejects(draw.execute('g1', { element: 'City', from_reference: { reference_id: 'goal', target: [0, 0, 2400, 1800], lights: true },
    lines: Array.from({ length: 100 }, (_, i) => ({ points: [[i, 0], [i, 10]] })), perspective: { eye_level_y: 900, vanishing_points: [[1200, 900]], rays: 24 } }),
  /room|own draw_guide call/);
  assert.deepEqual([traces.length, shapes.prompts.length, shapes.studies.length, calls.length], [0, 0, 0, 0]);
});

test('a plain block-in never asks for the shapes model download: brightness, and how to enable it', async t => {
  const folder = await scratch(t);
  const data = join(folder, 'data'), events = [];
  const chat = { config: { data_dir: data }, study: { id: 'c', directory: folder }, emit: event => events.push(event), async persist() {} };
  const shapes = chatShapes(chat, { spawn: () => { throw new Error('no worker in this test'); } });
  t.after(() => shapes.close());
  assert.equal(await shapes.ready(), false, 'the model is not downloaded');
  const { traces, draw } = setup({ shapes });
  const result = await draw.execute('g1', { element: 'City', from_reference: { reference_id: 'goal', target: [0, 0, 2400, 1800] } });
  assert.equal(traces[0].labels, undefined);
  assert.ok(!events.some(e => e.type === 'shapes_model_needed'), 'no download question from a block-in');
  assert.match(text(result), /shapes model[^.]*would sharpen/i);
  assert.match(text(result), /shape/);
  // Once downloaded (and not declined), the same block-in uses it.
  const directory = modelDirectory(data);
  await mkdir(directory, { recursive: true });
  for (const file of SHAPES_MODEL.files) { await writeFile(join(directory, file.name), ''); await truncate(join(directory, file.name), file.size); }
  await writeFile(join(directory, 'verified.json'), JSON.stringify({ revision: SHAPES_MODEL.revision, files: Object.fromEntries(SHAPES_MODEL.files.map(f => [f.name, f.sha256])) }));
  assert.equal(await shapes.ready(), true);
  chat.study.shapes_declined = true;
  assert.equal(await shapes.ready(), false, 'declined is not ready');
});

test('Stop during a block-in stops the shapes and the trace', async t => {
  const folder = await scratch(t);
  const cancelled = { async study() { throw new ShapeError('cancelled', 'Finding shapes was stopped.'); }, async shape() {}, async forget() {}, async close() {} };
  const stopped = setup({ shapes: cancelled });
  await assert.rejects(stopped.draw.execute('g1', { element: 'City', from_reference: { reference_id: 'goal', target: [0, 0, 2400, 1800] } }), /stopped/);
  assert.equal(stopped.traces.length, 0, 'a cancelled shapes model is no fallback');
  // The tool's signal is checked between the grid's prompts.
  const controller = new AbortController(), shapes = rectShapes(folder, [[0, 0, 100, 100]]);
  const original = shapes.service.shape;
  shapes.service.shape = async (...args) => { controller.abort(); return original(...args); };
  const { traces, draw } = setup({ shapes: shapes.service });
  await assert.rejects(draw.execute('g2', { element: 'City', from_reference: { reference_id: 'goal', target: [0, 0, 2400, 1800] } }, controller.signal), /abort/i);
  assert.equal(shapes.prompts.length, 1, 'no prompt after Stop');
  assert.equal(traces.length, 0);
  await assert.rejects(findBigShapes({ shapes: rectShapes(folder, []).service }, 'k', grey(100, 100), [0, 0, 100, 100], undefined, AbortSignal.abort()), /abort/i);
});

test('refusals reach nothing', async () => {
  const { draw, calls, runtime } = setup();
  for (const [from_reference, message] of [
    [{ reference_id: 'goal', source: [0, 0, 1200, 900], target: [0, 0, 400, 400] }, /matching aspect ratios/],
    [{ reference_id: 'goal', source: [300, 0, 1000, 900], target: [0, 0, 1000, 900] }, /Source crop must fit the reference/],
    [{ reference_id: 'missing', target: [0, 0, 400, 600] }, /Unknown reference ID/]])
    await assert.rejects(draw.execute('bad', { element: 'City', from_reference }), message, JSON.stringify(from_reference));
  const empty = setup({ reply: () => ({ lines: [] }) });
  await assert.rejects(empty.draw.execute('e', { element: 'City', from_reference: { reference_id: 'goal', target: [0, 0, 1200, 900] } }), /No clear outline/);
  delete runtime.decisionObservation;
  await assert.rejects(draw.execute('blind', { element: 'City', from_reference: { reference_id: 'goal', target: [0, 0, 1200, 900] } }), /look at the canvas/i);
  assert.equal(calls.length, 0);
  assert.equal(traceSide(1600, 1067, [0, 0, 1600, 1067]), 1440, 'the shapes decode: about 1440 on the long side');
  assert.equal(traceSide(800, 600, [0, 0, 800, 600]), 800, 'never larger than the reference');
});

test('traceReferenceEdges sends the reference to the plugin’s trace_edges; traceReferencePixels decodes once per size', async t => {
  const folder = await scratch(t);
  const path = join(folder, 'goal.png');
  await writeFile(path, 'not really a png');
  const native = [];
  const runtime = { study: { directory: folder, references: [{ id: 'goal', path, width: 4800, height: 3200 }] },
    async callNative(operation, params) {
      native.push({ operation, params });
      if (operation === 'trace_edges') return { status: 'ok', lines: [], silhouette: 'none', ms: 1, width: 2449, height: 1633, original_width: 4800, original_height: 3200 };
      return { status: 'ok', sha256: params.sha256, width: 1440, height: 960, rgba_base64: Buffer.alloc(1440 * 960 * 4).toString('base64') };
    } };
  const reply = await traceReferenceEdges(runtime, { reference_id: 'goal', source: [0, 0, 4800, 3200], scale: 0.5, detail: 'simple', max_lines: 30, lights: false });
  assert.equal(reply.original_width, 4800);
  assert.equal(native[0].operation, 'trace_edges');
  assert.deepEqual(Object.keys(native[0].params).sort(), ['detail', 'image_base64', 'lights', 'max_lines', 'scale', 'sha256', 'source']);
  assert.equal(Buffer.from(native[0].params.image_base64, 'base64').toString(), 'not really a png');
  await traceReferencePixels(runtime, 'goal', 1440); await traceReferencePixels(runtime, 'goal', 1440);
  assert.equal(native.filter(c => c.operation === 'trace_reference').length, 1, 'the shapes decode is cached for the chat');
  await truncate(path, (TRACE_REFERENCE_MB + 1) * 1024 * 1024);
  await assert.rejects(traceReferenceEdges(runtime, { reference_id: 'goal', source: [0, 0, 1, 1], scale: 1, detail: 'simple', max_lines: 8, lights: false }), /too large to trace a guide from/);
  await assert.rejects(traceReferenceEdges(runtime, { reference_id: 'nope', source: [0, 0, 1, 1], scale: 1, detail: 'simple', max_lines: 8, lights: false }), /attached reference/);
});

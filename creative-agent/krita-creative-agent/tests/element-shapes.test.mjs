// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Element shapes in use (element-shapes 1.4-1.6): a fake shape service returns synthetic shapes; draw_guide traces
// only the element inside a cluttered box, paint_pass and paint_batch paint inside a shape on the painting, and
// propose_protection proposes a shape. Mask files go to a temporary folder that each test removes.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { guideTools } from '../src/guide-tool.ts';
import { paintingTools } from '../src/tools.mjs';
import { mapReferencePoint } from '../src/reference-generator.mjs';
import { decodePlane, encodePlane } from '../src/shapes/png.ts';
import { LOW_SCORE, findShape, pruneShapes, scalePrompt, SHAPE_STUDIES, CANVAS_SHAPES } from '../src/shapes/use.ts';
import { EMPTY_SHAPE, KEPT_REFERENCES } from '../src/shapes/index.ts';
import { KEPT_STUDIES } from '../src/shapes/core.ts';
import { prunePreviews } from '../src/previews.mjs';
import { fakeTraceEdges } from './fixtures/fake-trace-edges.mjs';
import { readdir } from 'node:fs/promises';

const TOWER = [[100, 600], [100, 400], [140, 400], [140, 250], [175, 250], [175, 150], [190, 150], [200, 40], [210, 150], [225, 150],
  [225, 250], [260, 250], [260, 400], [300, 400], [300, 600]];
const BUILDING = [[20, 300], [90, 300], [90, 600], [20, 600]];                        // clutter left of the tower
const BLOCK = [[320, 330], [390, 330], [390, 600], [320, 600]];                       // clutter right of it
const CLOUD = { x: 330, y: 110, r: 40 };                                              // a dark cloud above right
function inside(x, y, polygon) {
  let hit = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i], [xj, yj] = polygon[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}
const cluttered = (x, y) => inside(x, y, TOWER) || inside(x, y, BUILDING) || inside(x, y, BLOCK) || Math.hypot(x - CLOUD.x, y - CLOUD.y) <= CLOUD.r;
function image(width, height, dark, scale = 1) {
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const v = dark((x + 0.5) / scale, (y + 0.5) / scale) ? 50 : 210, i = (y * width + x) * 4;
    data[i] = data[i + 1] = data[i + 2] = v; data[i + 3] = 255;
  }
  return { width, height, data };
}
const segment = (p, a, b) => {
  const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy, t = l ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l)) : 0;
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
};
const distance = (p, ring) => Math.min(...ring.map((q, i) => segment(p, ring[(i + ring.length - 1) % ring.length], q)));
function along(points, step = 2) {
  const out = [];
  for (let i = 1; i < points.length; i++) {
    const [a, b] = [points[i - 1], points[i]], n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / step));
    for (let k = 0; k <= n; k++) out.push([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n]);
  }
  return out;
}
const strokeLines = strokes => strokes.map(s => [s.start, ...s.segments.map(seg => seg.slice(4))]);

/** A shape service that answers every prompt with `answer(key, prompt)`: {bounds, inside(x,y) in image pixels, score}. */
function fakeShapes(folder, answer) {
  const studies = [], shapes = [], forgotten = [];
  let count = 0;
  return { studies, shapes, forgotten, service: {
    forget(key) { forgotten.push(key); },
    async study(key, rgba, width, height) { studies.push({ key, width, height, bytes: rgba.length }); return { ms: 1300, peak_mb: 1600, provider: 'cpu' }; },
    async shape(key, prompt) {
      shapes.push({ key, prompt });
      const { bounds, within, score } = answer(key, prompt);
      const [x, y, w, h] = bounds, data = new Uint8Array(w * h);
      for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) data[j * w + i] = within(x + i + 0.5, y + j + 0.5) ? 255 : 0;
      const mask_path = join(folder, `shape-${++count}.png`);
      await writeFile(mask_path, encodePlane({ width: w, height: h, data }));
      return { bounds, score, mask_path, model: 'sam2.1-hiera-base-plus', revision: 'bab1859', ms: 12, peak_mb: 1600, provider: 'cpu' };
    },
    async close() {},
  } };
}
async function scratch(t) {
  const folder = await mkdtemp(join(tmpdir(), 'element-shapes-'));
  t.after(() => rm(folder, { recursive: true, force: true }));
  return folder;
}

/** The reference decodes to 400 x 600 (the tower and its clutter), listed at `listed`; the shape is the tower's. */
function guideSetup(folder, { listed = [400, 600], score = 0.93 } = {}) {
  const calls = [], events = [], sides = [], traces = [];
  const pixels = image(400, 600, cluttered);
  const shapes = fakeShapes(folder, () => ({ bounds: [100, 40, 200, 560], within: (x, y) => inside(x, y, TOWER), score }));
  const runtime = { study: { references: [{ id: 'goal', width: listed[0], height: listed[1] }] }, decisionObservation: { width: 2000, height: 2000 },
    shapes: shapes.service, emit: event => events.push(event) };
  const tools = guideTools(runtime, {
    execute: operation => async (id, params) => { calls.push({ operation, params }); return { content: [{ type: 'text', text: '{"status":"ok"}' }], details: { status: 'ok' } }; },
    mapPoint: mapReferencePoint, referencePixels: async (id, side) => { sides.push(side); return pixels; },
    traceEdges: fakeTraceEdges(() => listed, traces) });
  return { calls, events, shapes, sides, runtime, traces, draw: tools.find(t => t.name === 'draw_guide') };
}

test('a tower inside a cluttered box: lines on the tower only, none on the clutter, mapped onto the target', async t => {
  const folder = await scratch(t);
  const { calls, shapes, draw, events, traces } = guideSetup(folder);
  const box = [10, 30, 385, 570], target = [100, 100, 770, 1140];             // scale 2
  const result = await draw.execute('g1', { element: 'Tower', from_reference: { reference_id: 'goal', shape: { box }, target, detail: 'medium' } });
  const map = mapReferencePoint(box, target), back = ([x, y]) => [(x - 100) / 2 + 10, (y - 100) / 2 + 30];
  const lines = strokeLines(calls[0].params.strokes).map(line => line.map(back));
  assert.ok(lines.length >= 1, 'the tower is outlined');
  for (const line of lines) for (const p of along(line)) {
    assert.ok(inside(...p, TOWER) || distance(p, TOWER) <= 4, `${p.map(Math.round)} lies on or in the tower`);
    for (const clutter of [BUILDING, BLOCK]) assert.ok(distance(p, clutter) > 8 || inside(...p, TOWER), 'never on the clutter');
    assert.ok(Math.abs(Math.hypot(p[0] - CLOUD.x, p[1] - CLOUD.y) - CLOUD.r) > 8, 'never on the cloud');
  }
  const outline = along(TOWER, 3), covered = outline.filter(p => lines.some(line => along(line).some(q => Math.hypot(q[0] - p[0], q[1] - p[1]) <= 4)));
  assert.ok(covered.length / outline.length >= 0.85, `the outline is covered (${covered.length}/${outline.length})`);
  // The mapping is the reference tools': the tower's corners land where mapReferencePoint puts them.
  const mapped = strokeLines(calls[0].params.strokes).flatMap(line => along(line));
  for (const corner of [[100, 400], [140, 250], [260, 250], [300, 400]]) {
    const at = map(...corner);
    assert.ok(mapped.some(p => Math.hypot(p[0] - at[0], p[1] - at[1]) <= 8), `the corner ${corner} lands on the target`);
  }
  assert.ok(Object.keys(calls[0].params).every(key => ['element', 'strokes'].includes(key)), 'only lines reach the plugin');
  assert.deepEqual(shapes.shapes[0].prompt, { box }, 'the prompt in the decoded reference’s pixels');
  const text = result.content.map(part => part.text ?? '').join(' ');
  assert.match(text, /"shape":\{"score":0\.93/, 'the score is in the result');
  assert.doesNotMatch(text, /uncertain/);
  assert.equal(result.details.shape.score, 0.93);
  assert.ok(events.some(e => /shape/.test(e.message) && !/mask/i.test(e.message)), 'the panel says "shape"');
  // The same box without a shape (and no shapes for a block-in here: the service finds the tower wherever it is
  // pointed, which is one shape) is traced without the element's own: the shape is what keeps the clutter out.
  assert.equal(traces[0].labels.inside, true, 'the plugin traces inside the shape only');
  await draw.execute('g0', { element: 'Tower', from_reference: { reference_id: 'goal', source: box, target, detail: 'medium' } });
  assert.notEqual(traces[1].labels?.inside, true, 'a box alone is not one element');
  // Studied once per reference and content; each prompt is its own shape.
  await draw.execute('g2', { element: 'Tower', from_reference: { reference_id: 'goal', shape: { points: [[200, 300, 1], [50, 450, 0]] }, target: [0, 0, 800, 1200] } });
  assert.equal(shapes.studies.length, 1, 'the reference is studied once');
  const asked = shapes.shapes.filter(s => s.prompt.points?.length !== 1);     // the block-in's grid points are one each
  assert.equal(asked.length, 2);
  assert.deepEqual(asked[1].prompt, { points: [[200, 300, 1], [50, 450, 0]] });
});

test('a low score is reported so the painter can prompt again', async t => {
  const folder = await scratch(t);
  const { draw } = guideSetup(folder, { score: 0.42 });
  const result = await draw.execute('g1', { element: 'Tower', from_reference: { reference_id: 'goal', shape: { box: [10, 30, 385, 570] }, target: [0, 0, 385, 570] } });
  const text = result.content.map(part => part.text ?? '').join(' ');
  assert.match(text, /uncertain \(score 0\.42 < 0\.6\)/);
  assert.match(text, /tighter box|points/);
  assert.equal(LOW_SCORE, 0.6);
});

test('a reference decoded smaller gets its prompt scaled down and its lines scaled back', async t => {
  const folder = await scratch(t);
  const { calls, shapes, draw } = guideSetup(folder, { listed: [800, 1200] });
  await draw.execute('g1', { element: 'Tower', from_reference: { reference_id: 'goal', shape: { box: [20, 60, 770, 1140] }, target: [0, 0, 770, 1140] } });
  assert.deepEqual(shapes.shapes[0].prompt, { box: [10, 30, 385, 570] }, 'reference pixels to the decode’s');
  const lines = strokeLines(calls[0].params.strokes).map(line => line.map(([x, y]) => [x + 20, y + 60]));   // target = source, offset
  const big = TOWER.map(([x, y]) => [2 * x, 2 * y]);
  for (const line of lines) for (const p of along(line, 4)) assert.ok(inside(...p, big) || distance(p, big) <= 8, `${p.map(Math.round)} on the tower at full size`);
});

test('shape refusals: bad prompts, and no shape service', async t => {
  const folder = await scratch(t);
  const { draw, calls } = guideSetup(folder);
  for (const [shape, message] of [[{ box: [0, 0, 0, 10] }, /width and a height/], [{ points: [[1, 1, 0]] }, /label 1/], [{ points: [[1, 1, 2]] }, /label/]])
    await assert.rejects(draw.execute('bad', { element: 'Tower', from_reference: { reference_id: 'goal', shape, target: [0, 0, 400, 600] } }), message);
  const runtime = { study: { references: [{ id: 'goal', width: 400, height: 600 }] }, decisionObservation: { width: 900, height: 900 }, emit() {} };
  const bare = guideTools(runtime, { execute: () => async () => ({ content: [], details: {} }), mapPoint: mapReferencePoint, referencePixels: async () => image(400, 600, cluttered),
    traceEdges: fakeTraceEdges(() => [400, 600]) });
  await assert.rejects(bare.find(t => t.name === 'draw_guide').execute('x', { element: 'Tower', from_reference: { reference_id: 'goal', shape: { box: [10, 30, 385, 570] }, target: [0, 0, 385, 570] } }), /not available/);
  assert.equal(calls.length, 0);
});

/** A painting runtime whose canvas view is 1000 x 500 for a 2000 x 1000 canvas; the plugin is a fake. */
async function canvasSetup(t, { score = 0.95, scoreFor = null, observation = {}, decoded = [1000, 500], forkTools = true } = {}) {
  const folder = await scratch(t);
  await mkdir(join(folder, '.previews'));
  const view = join(folder, '.previews', 'view-1.png');
  await writeFile(view, 'the canvas view');
  const calls = [], events = [];
  // The moon on the view: a disc at (150, 120) radius 20, so bounds [130,100,40,40] in view pixels.
  const shapes = fakeShapes(folder, (key, prompt) => ({ bounds: [130, 100, 40, 40], within: (x, y) => Math.hypot(x - 150, y - 120) <= 20,
    score: scoreFor ? scoreFor(prompt) : score }));
  const runtime = { calls, faulted: false, forkTools, study: { directory: folder, references: [] }, shapes: shapes.service, emit: e => events.push(e),
    decisionObservation: { width: 2000, height: 1000, image_path: view, image_width: 1000, image_height: 500, ...observation },
    async callNative(operation, params, id) {
      calls.push({ operation, params, id });
      if (operation === 'trace_reference') return { sha256: params.sha256, width: decoded[0], height: decoded[1], rgba_base64: Buffer.alloc(decoded[0] * decoded[1] * 4).toString('base64') };
      return { status: 'ok', layer_id: 'L' + calls.length };
    } };
  return { folder, view, runtime, calls, events, shapes, tools: paintingTools(runtime) };
}
const STROKE = { start: [250, 230], segments: [[260, 230, 290, 240, 330, 250]], size: 30, opacity: 1, flow: 1, color: '#f0e8c0' };
const PASS = { name: 'Moon glow', preset: 'b) Basic-1', strokes: [STROKE] };

test('paint_pass inside a shape on the painting sends the plugin the shape at canvas resolution', async t => {
  const { folder, calls, shapes, tools, events } = await canvasSetup(t);
  const result = await tools.find(x => x.name === 'paint_pass').execute('p1', { ...PASS, inside_shape: { box: [250, 190, 100, 100] } });
  assert.deepEqual(shapes.shapes[0].prompt, { box: [125, 95, 50, 50] }, 'canvas pixels to the view’s');
  const pass = calls.find(c => c.operation === 'paint_pass');
  assert.deepEqual(pass.params.inside_shape.bounds, [260, 200, 80, 80], 'the view’s bounds on the canvas');
  assert.ok(pass.params.inside_shape.mask_path.startsWith(join(folder, '.shapes')), 'the file is in the chat folder');
  const plane = decodePlane(await readFile(pass.params.inside_shape.mask_path));
  assert.deepEqual([plane.width, plane.height], [80, 80]);
  assert.equal(plane.data[40 * 80 + 40], 255, 'inside the moon');
  assert.equal(plane.data[0], 0, 'outside the disc');
  assert.equal(pass.params.strokes, PASS.strokes);
  assert.ok(!('box' in pass.params.inside_shape), 'the prompt never reaches the plugin');
  assert.match(result.content.map(p => p.text ?? '').join(' '), /"shape":\{"score":0\.95/);
  assert.ok(events.some(e => /inside the shape/.test(e.message)));
  // The same canvas is studied once.
  await tools.find(x => x.name === 'paint_pass').execute('p2', { ...PASS, inside_shape: { points: [[300, 240, 1]] } });
  assert.equal(shapes.studies.length, 1);
  assert.equal(calls.filter(c => c.operation === 'trace_reference').length, 1, 'the view is decoded once');
  // Without a shape nothing changes.
  await tools.find(x => x.name === 'paint_pass').execute('p3', PASS);
  assert.ok(!('inside_shape' in calls.at(-1).params));
});

test('a pass inside an uncertain shape is refused before anything paints; paint_batch takes inside_shape too', async t => {
  const low = await canvasSetup(t, { score: 0.4 });
  await assert.rejects(low.tools.find(x => x.name === 'paint_pass').execute('p1', { ...PASS, inside_shape: { box: [250, 190, 100, 100] } }),
    /uncertain \(score 0\.4 < 0\.6\)[^]*Nothing was painted/);
  assert.equal(low.calls.filter(c => c.operation === 'paint_pass').length, 0);
  const { calls, tools } = await canvasSetup(t);
  const batch = tools.find(x => x.name === 'paint_batch');
  const done = await batch.execute('b1', { actions: [{ tool: 'paint_pass', arguments: { ...PASS, inside_shape: { box: [250, 190, 100, 100] } } },
    { tool: 'paint_pass', arguments: PASS }] });
  const passes = calls.filter(c => c.operation === 'paint_pass');
  assert.equal(passes.length, 2);
  assert.deepEqual(passes[0].params.inside_shape.bounds, [260, 200, 80, 80]);
  assert.ok(!('inside_shape' in passes[1].params), 'the shape limits its own action only');
  assert.match(done.content[0].text, /"status":"ok"/);
});

test('propose_protection may carry a shape; the artist still keeps or discards it', async t => {
  const { calls, tools } = await canvasSetup(t);
  const propose = tools.find(x => x.name === 'propose_protection');
  const result = await propose.execute('pr1', { name: 'Moon', shape: { box: [250, 190, 100, 100] } });
  const sent = calls.find(c => c.operation === 'propose_protection');
  assert.equal(sent.params.name, 'Moon');
  assert.equal(sent.params.area.length, 1);
  assert.deepEqual(sent.params.area[0].element_shape.bounds, [260, 200, 80, 80]);
  assert.ok(!('shape' in sent.params), 'the plugin gets the shape as a selection step');
  assert.match(result.content.map(p => p.text ?? '').join(' '), /"shape":\{"score":0\.95/);
  assert.match(propose.description, /shape/);
  await assert.rejects(propose.execute('pr2', { name: 'Moon' }), /area or shape/);
  await assert.rejects(propose.execute('pr3', { name: 'Moon', shape: { box: [0, 0, 10, 10] }, area: [{ shape: 'rectangle', bounds: [0, 0, 2, 2] }] }), /area or shape/);
  // An area as before reaches the plugin unchanged.
  await propose.execute('pr4', { name: 'Car', area: [{ shape: 'rectangle', bounds: [0, 0, 2, 2] }] });
  assert.deepEqual(calls.at(-1).params, { name: 'Car', area: [{ shape: 'rectangle', bounds: [0, 0, 2, 2] }] });
});

test('propose_protection refuses magic-wand seeds and colour ranges before the plugin; the reply says proposed', async t => {
  // Protection is made from the objects (the artist, 2026-10-23): the painter seeded a sky and protected the inverse,
  // and the sky-coloured towers counted as sky. The plugin refuses too (saved selections built from seeds included).
  const { calls, tools } = await canvasSetup(t);
  const propose = tools.find(x => x.name === 'propose_protection');
  const before = calls.length;
  for (const area of [[{ seed: [10, 10], tolerance: 40 }, { invert: true }], [{ color: '#203040' }],
    [{ shape: 'rectangle', bounds: [0, 0, 20, 20] }, { color: '#203040', mode: 'subtract' }]])
    await assert.rejects(propose.execute('pc', { name: 'Buildings', area }),
      /Protection is made from the objects themselves: use shape \(one box around each object\) or polygons around them, not a colour selection\./);
  assert.equal(calls.length, before, 'nothing reached the plugin');
  assert.doesNotMatch(propose.description, /colour range|seed|magic wand/i);
  assert.match(propose.description, /Proposed and shown in red; the artist keeps or discards it\. Until then you keep out of it\./);
  assert.match(propose.description, /shape/);
});

test('mask files: filtered rows and colour masks decode; written masks round-trip', async () => {
  const { deflateSync, crc32 } = await import('node:zlib');
  const chunk = (kind, body) => { const head = Buffer.alloc(8); head.writeUInt32BE(body.length); head.write(kind, 4, 'latin1');
    const tail = Buffer.alloc(4); tail.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), body]))); return Buffer.concat([head, body, tail]); };
  const png = (w, h, colour, raw) => { const header = Buffer.alloc(13); header.writeUInt32BE(w); header.writeUInt32BE(h, 4); header[8] = 8; header[9] = colour;
    return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header), chunk('IDAT', deflateSync(Buffer.from(raw))), chunk('IEND', Buffer.alloc(0))]); };
  // Grey 3 x 2: row 1 Sub-filtered (10, 20, 30), row 2 Up-filtered (+5 each).
  assert.deepEqual([...decodePlane(png(3, 2, 0, [1, 10, 10, 10, 2, 5, 5, 5])).data], [10, 20, 30, 15, 25, 35]);
  // Grey and alpha: the value times alpha.
  assert.deepEqual([...decodePlane(png(2, 1, 4, [0, 255, 255, 255, 0])).data], [255, 0]);
  // Paeth on RGB: the first channel.
  assert.deepEqual([...decodePlane(png(2, 1, 2, [4, 200, 1, 1, 0, 0, 0])).data], [200, 200]);
  const data = Uint8Array.from({ length: 35 }, (_, i) => i * 7 % 256);
  assert.deepEqual(decodePlane(encodePlane({ width: 7, height: 5, data })), { width: 7, height: 5, data });
  assert.throws(() => decodePlane(Buffer.from('not a png')), /not a PNG/);
});

test('C1: a shape on a region observation maps through the region’s offset and scale', async t => {
  const { calls, shapes, tools } = await canvasSetup(t, { observation: { region: [1000, 500, 800, 400] } });
  const pass = tools.find(x => x.name === 'paint_pass');
  await pass.execute('r1', { ...PASS, inside_shape: { box: [1100, 580, 80, 80] } });
  assert.deepEqual(shapes.shapes[0].prompt, { box: [125, 100, 100, 100] }, '(canvas - region) x 1000/800');
  const sent = calls.find(c => c.operation === 'paint_pass').params.inside_shape;
  assert.deepEqual(sent.bounds, [1104, 580, 32, 32], 'region + view / 1.25');
  for (const box of [[100, 100, 50, 50], [1700, 800, 200, 50]])
    await assert.rejects(pass.execute('r2', { ...PASS, inside_shape: { box } }), /outside the region you last looked at/);
  await assert.rejects(pass.execute('r3', { ...PASS, inside_shape: { points: [[1100, 600, 1], [10, 10, 0]] } }), /outside the region/);
  const odd = await canvasSetup(t, { decoded: [900, 500] });
  await assert.rejects(odd.tools.find(x => x.name === 'paint_pass').execute('r4', { ...PASS, inside_shape: { box: [250, 190, 100, 100] } }), /decoded at 900 x 500/);
  assert.equal(odd.calls.filter(c => c.operation === 'paint_pass').length, 0);
});

test('I1: a batch finds every shape on the same view before anything paints, and refuses up front', async t => {
  const low = await canvasSetup(t, { scoreFor: prompt => prompt.box[0] > 200 ? 0.3 : 0.95 });
  const batch = low.tools.find(x => x.name === 'paint_batch');
  await assert.rejects(batch.execute('b1', { actions: [
    { tool: 'paint_pass', arguments: { ...PASS, inside_shape: { box: [250, 190, 100, 100] } } },
    { tool: 'paint_pass', arguments: { ...PASS, inside_shape: { box: [600, 190, 100, 100] } } }] }), /Action 2[^]*uncertain[^]*Nothing was painted/);
  assert.equal(low.calls.filter(c => c.operation === 'paint_pass').length, 0, 'the first action did not paint');
  for (const extra of [{ region: [0, 0, 500, 500] }, { selection: 'Sky' }]) {
    const { tools, calls, shapes } = await canvasSetup(t);
    await assert.rejects(tools.find(x => x.name === 'paint_batch').execute('b2', { actions: [{ tool: 'paint_pass', arguments: PASS },
      { tool: 'paint_pass', arguments: { ...PASS, ...extra, inside_shape: { box: [250, 190, 100, 100] } } }] }), /one limit/);
    await assert.rejects(tools.find(x => x.name === 'paint_pass').execute('p2', { ...PASS, ...extra, inside_shape: { box: [250, 190, 100, 100] } }), /one limit/);
    assert.deepEqual([calls.length, shapes.studies.length], [0, 0], 'refused before the canvas is read or the worker asked');
  }
  const stock = await canvasSetup(t, { forkTools: false });
  await assert.rejects(stock.tools.find(x => x.name === 'paint_pass').execute('s1', { ...PASS, inside_shape: { box: [250, 190, 100, 100] } }), /our Krita/);
  assert.equal(stock.shapes.studies.length, 0);
  // Every shape comes from the view seen before the batch, though the first pass changes the canvas.
  const { tools, calls, runtime, folder } = await canvasSetup(t);
  const later = join(folder, '.previews', 'view-2.png');
  await writeFile(later, 'the canvas after the first pass');
  const call = runtime.callNative;
  runtime.callNative = async (operation, params, id) => {
    const answer = await call(operation, params, id);
    if (operation === 'paint_pass') runtime.decisionObservation = { ...runtime.decisionObservation, image_path: later };
    return answer;
  };
  await tools.find(x => x.name === 'paint_batch').execute('b3', { actions: [
    { tool: 'paint_pass', arguments: { ...PASS, inside_shape: { box: [250, 190, 100, 100] } } },
    { tool: 'paint_pass', arguments: { ...PASS, inside_shape: { box: [260, 200, 100, 100] } } }] });
  assert.equal(calls.filter(c => c.operation === 'trace_reference').length, 1, 'one view for the whole batch');
  assert.equal(calls.filter(c => c.operation === 'paint_pass').length, 2);
});

test('minor 4: the raw score is compared, not the rounded one', async t => {
  const { tools, calls } = await canvasSetup(t, { score: 0.596 });
  await assert.rejects(tools.find(x => x.name === 'paint_pass').execute('p', { ...PASS, inside_shape: { box: [250, 190, 100, 100] } }), /uncertain/);
  assert.equal(calls.filter(c => c.operation === 'paint_pass').length, 0);
});

/** A service whose worker forgets its studies when it restarts (as a short-lived worker does): shape() then answers
 * not_studied, as src/shapes/index.ts does. */
function forgetfulShapes(folder) {
  const known = new Set(), studies = [];
  let count = 0;
  return { known, studies, service: {
    async study(key) { known.add(key); studies.push(key); return { ms: 1, peak_mb: 1, provider: 'cpu' }; },
    async shape(key) {
      if (!known.has(key)) throw Object.assign(new Error('Study this reference before finding its shapes.'), { code: 'not_studied' });
      const mask_path = join(folder, `f-${++count}.png`);
      await writeFile(mask_path, encodePlane({ width: 2, height: 2, data: new Uint8Array([255, 255, 255, 255]) }));
      return { bounds: [1, 1, 2, 2], score: 0.9, mask_path, model: 'm', revision: 'r', ms: 1, peak_mb: 1, provider: 'cpu' };
    },
    async forget(key) { known.delete(key); },
    async close() {} } };
}
const tiny = { width: 4, height: 4, data: new Uint8Array(64) };

test('I2: a study the service forgot (not_studied) is studied again and the shape retried once; any other failure propagates', async t => {
  const folder = await scratch(t);
  const fake = forgetfulShapes(folder), host = { shapes: fake.service };
  await findShape(host, 'canvas:a', tiny, { box: [0, 0, 4, 4] });
  fake.known.clear();                                                 // the service lost it
  const found = await findShape(host, 'canvas:a', tiny, { box: [0, 0, 4, 4] });
  assert.deepEqual(found.bounds, [1, 1, 2, 2]);
  assert.equal(fake.studies.length, 2, 'studied again once');
  fake.service.shape = async () => { throw Object.assign(new Error('Finding shapes ran out of memory. Close some apps and try again.'), { code: 'out_of_memory' }); };
  await assert.rejects(findShape(host, 'canvas:a', tiny, { box: [0, 0, 4, 4] }), /out of memory/);
  assert.equal(fake.studies.length, 2, 'out of memory is not answered with another study');
  assert.equal(fake.service.generation, undefined, 'no generation in the contract');
});

test('I3: one reference is one study, whatever the boxes; studies are bounded and the evicted forgotten', async t => {
  const folder = await scratch(t);
  const { draw, shapes, sides } = guideSetup(folder, { listed: [4000, 6000] });
  for (let i = 0; i < 10; i++)
    await draw.execute('g' + i, { element: 'Tower', from_reference: { reference_id: 'goal', shape: { box: [i * 100, i * 100, 200, 300] }, target: [0, 0, 200, 300] } });
  assert.equal(shapes.studies.length, 1, 'ten boxes, one study');
  assert.equal(new Set(sides).size, 1, 'the decode does not follow the box');
  const host = { shapes: shapes.service };
  const picture = image(400, 600, cluttered);
  for (let i = 0; i <= SHAPE_STUDIES; i++) await findShape(host, 'k' + i, picture, { box: [0, 0, 4, 4] });
  assert.equal(host.shapeStudies.size, SHAPE_STUDIES);
  assert.deepEqual(shapes.forgotten, ['k0'], 'the oldest is evicted and the service told');
});

test('I4: points without a source fit the element into target, its proportions kept', async t => {
  const folder = await scratch(t);
  const { calls, draw } = guideSetup(folder);
  await draw.execute('g1', { element: 'Tower', from_reference: { reference_id: 'goal', shape: { points: [[200, 300, 1]] }, target: [0, 0, 400, 560] } });
  // The shape's bounds [100,40,200,560] fit 400 x 560 at scale 1, centred: x + 0, y - 40.
  const mapped = strokeLines(calls[0].params.strokes).flatMap(line => along(line));
  for (const [x, y] of [[140, 250], [260, 250], [100, 400], [300, 400]])
    assert.ok(mapped.some(p => Math.hypot(p[0] - x, p[1] - (y - 40)) <= 6), `corner ${x},${y}`);
  assert.ok(mapped.every(([x]) => x >= 99 && x <= 301), 'centred in the target, not stretched');
  assert.match(draw.parameters.properties.from_reference.properties.target.description, /points/);
});

test('minor 1: shape lines are not clamped to the box; the canvas cuts them', async t => {
  const folder = await scratch(t);
  const { calls, draw } = guideSetup(folder);
  await draw.execute('g1', { element: 'Tower', from_reference: { reference_id: 'goal', shape: { box: [100, 300, 200, 300] }, target: [500, 500, 200, 300] } });
  const mapped = strokeLines(calls[0].params.strokes).flat();
  assert.ok(mapped.some(([, y]) => y < 480), 'the spire above the box is drawn above the target');
});

test('I5 and minor 3: mask files are bounded before inflating, and a bad header is damaged', async () => {
  const { deflateSync, crc32 } = await import('node:zlib');
  const chunk = (kind, body) => { const head = Buffer.alloc(8); head.writeUInt32BE(body.length); head.write(kind, 4, 'latin1');
    const tail = Buffer.alloc(4); tail.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), body]))); return Buffer.concat([head, body, tail]); };
  const header = (w, h) => { const b = Buffer.alloc(13); b.writeUInt32BE(w); b.writeUInt32BE(h, 4); b[8] = 8; return b; };
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), end = chunk('IEND', Buffer.alloc(0));
  const huge = Buffer.concat([sig, chunk('IHDR', header(60000, 60000)), chunk('IDAT', deflateSync(Buffer.alloc(3))), end]);
  assert.throws(() => decodePlane(huge, { width: 100, height: 100 }), /60000 x 60000/);
  const bomb = Buffer.concat([sig, chunk('IHDR', header(2, 1)), chunk('IDAT', deflateSync(Buffer.alloc(10_000_000))), end]);
  assert.throws(() => decodePlane(bomb, { width: 2, height: 1 }), /damaged/);
  const short = Buffer.concat([sig, chunk('IHDR', Buffer.alloc(4)), chunk('IDAT', deflateSync(Buffer.alloc(3))), end]);
  const late = Buffer.concat([sig, chunk('IDAT', deflateSync(Buffer.alloc(3))), chunk('IHDR', header(2, 1)), end]);
  for (const file of [short, late]) assert.throws(() => decodePlane(file), /damaged/);
});

test('minor 7: canvas shape files are capped per chat and pruned when the chat ends', async t => {
  const { folder, tools } = await canvasSetup(t);
  const pass = tools.find(x => x.name === 'paint_pass');
  for (let i = 0; i < CANVAS_SHAPES + 3; i++) await pass.execute('p' + i, { ...PASS, inside_shape: { box: [250 + i, 190, 100, 100] } });
  const files = async () => (await readdir(join(folder, '.shapes'))).filter(name => name.startsWith('canvas-'));
  assert.equal((await files()).length, CANVAS_SHAPES);
  await prunePreviews(folder);
  assert.deepEqual(await files(), [], 'none left once the chat ends');
  await pruneShapes(join(folder, 'missing'), 0);                       // no folder: nothing to do
});

test('a prompt scaled to a decode stays inside it: an epsilon past the edge is clamped, not refused', () => {
  assert.deepEqual(scalePrompt({ box: [0, 0, 100, 50] }, 1.0000001, 1.0000001, { width: 100, height: 50 }), { box: [0, 0, 100, 50] });
  assert.deepEqual(scalePrompt({ box: [10, 10, 20, 20] }, 0.5, 0.5, { width: 100, height: 50 }), { box: [5, 5, 10, 10] });
  assert.deepEqual(scalePrompt({ points: [[100, 50, 1], [-0.0001, 3, 0]] }, 1.000001, 1, { width: 100, height: 50 }), { points: [[100, 50, 1], [0, 3, 0]] });
});

test('one wording for an empty shape, and the chat, the service and the worker keep the same number of studies', async t => {
  const folder = await scratch(t);
  const host = { shapes: { async study() { return {}; }, async shape() { return { bounds: [3, 3, 0, 0], score: 0.9, mask_path: '', model: 'm', revision: 'r', ms: 1, peak_mb: 1, provider: 'cpu' }; },
    async forget() {}, async close() {} } };
  await assert.rejects(findShape(host, 'canvas:e', tiny, { box: [0, 0, 4, 4] }), error => error.message === EMPTY_SHAPE);
  assert.equal(SHAPE_STUDIES, KEPT_REFERENCES); assert.equal(SHAPE_STUDIES, KEPT_STUDIES);
  void folder;
});

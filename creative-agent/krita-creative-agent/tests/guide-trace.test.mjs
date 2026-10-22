// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Guides from a reference's own edges (guide-trace.ts): a synthetic stepped tower with a spire is outlined within a few
// pixels and within the caps, texture noise gives few or no lines, the brightest shapes are outlined as light, and
// draw_guide's from_reference maps the lines onto the target. Images are made in memory; writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, truncate, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { traceOutlines, traceLights, simplifyPolyline, TRACE_LIMITS, LIGHT_LIMIT } from '../src/guide-trace.ts';
import { guideTools, GUIDE_POINTS, traceSide } from '../src/guide-tool.ts';
import { mapReferencePoint } from '../src/reference-generator.mjs';
import { traceReferencePixels, TRACE_REFERENCE_MB } from '../src/reference-tool.mjs';

function random(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ t >>> 15, t | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
/** An RGBA image from a grey level (and optionally an alpha) per pixel centre. */
function image(width, height, grey, alpha = () => 255) {
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const v = Math.max(0, Math.min(255, Math.round(grey(x + 0.5, y + 0.5)))), i = (y * width + x) * 4;
    data[i] = data[i + 1] = data[i + 2] = v; data[i + 3] = alpha(x + 0.5, y + 0.5);
  }
  return { width, height, data };
}
/** Every second pixel of an image: what a decode at half size gives. */
const half = picture => image(picture.width / 2, picture.height / 2, (x, y) => picture.data[((Math.floor(y) * 2) * picture.width + Math.floor(x) * 2) * 4]);
// The tower's outline (reference pixels), base on the bottom edge: base block, middle tier, top tier, spire.
const TOWER = [[100, 600], [100, 400], [140, 400], [140, 250], [175, 250], [175, 150], [190, 150], [200, 40], [210, 150], [225, 150],
  [225, 250], [260, 250], [260, 400], [300, 400], [300, 600]];
function insidePolygon(x, y, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i], [xj, yj] = polygon[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function towerImage({ noise = 0, windows = true } = {}) {
  const rand = random(7);
  return image(400, 600, (x, y) => {
    const n = noise ? (rand() - 0.5) * 2 * noise : 0;
    if (!insidePolygon(x, y, TOWER)) return 210 + n;
    // Lit windows: 4 x 4 px every 16 px on the tiers, texture a guide should not outline.
    if (windows && y > 260 && (Math.floor(x) % 16) < 4 && (Math.floor(y) % 16) < 4) return 200 + n;
    return 50 + n;
  });
}
const segmentDistance = (p, a, b) => {
  const dx = b[0] - a[0], dy = b[1] - a[1], length = dx * dx + dy * dy;
  const t = length ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length)) : 0;
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
};
const polylineDistance = (p, points) => Math.min(...points.slice(1).map((q, i) => segmentDistance(p, points[i], q)));
/** Points every `step` along a polyline. */
function samples(points, step = 2) {
  const out = [];
  for (let i = 1; i < points.length; i++) {
    const [a, b] = [points[i - 1], points[i]], n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / step));
    for (let k = 0; k <= n; k++) out.push([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n]);
  }
  return out;
}
/** How well lines follow an outline: the worst distance of a line point from it, and the share of it the lines cover. */
function fit(lines, outline, tolerance) {
  const worst = Math.max(...lines.flatMap(line => samples(line).map(p => polylineDistance(p, outline))));
  const along = samples(outline, 3);
  const covered = along.filter(p => lines.some(line => polylineDistance(p, line) <= tolerance)).length / along.length;
  return { worst, covered };
}

test('the stepped tower with its spire is outlined within a few pixels, within the caps', () => {
  for (const detail of ['simple', 'medium']) {
    const lines = traceOutlines(towerImage({ noise: 12 }), [0, 0, 400, 600], detail);
    assert.ok(lines.length >= 1 && lines.length <= TRACE_LIMITS[detail], `${detail}: ${lines.length} lines`);
    assert.ok(lines.every(line => line.length >= 2 && line.length <= GUIDE_POINTS), 'each a polyline draw_guide takes');
    const { worst, covered } = fit(lines, TOWER, 4);
    assert.ok(worst <= 4, `${detail}: every line point within 4 px of the outline (worst ${worst.toFixed(1)})`);
    assert.ok(covered >= 0.9, `${detail}: the lines cover the outline, spire included (${(covered * 100).toFixed(0)}%)`);
    const points = lines.reduce((n, line) => n + line.length, 0);
    assert.ok(points <= 80, `${detail}: simplified to clean straight runs (${points} points)`);
  }
});

test('a source crop outlines only what is inside it, in reference pixels', () => {
  const lines = traceOutlines(towerImage(), [120, 0, 160, 300], 'simple');
  assert.ok(lines.length >= 1);
  for (const line of lines) for (const [x, y] of line) assert.ok(x >= 120 && x <= 280 && y >= 0 && y <= 300, `${x},${y} inside the crop`);
  const top = [[140, 300], ...TOWER.slice(3, 12), [260, 300]];   // the tiers and spire above y 300
  assert.ok(fit(lines, top, 4).worst <= 4, 'the crop’s lines follow the tower’s upper outline');
});

test('texture noise produces few or no lines', () => {
  const rand = random(3);
  const noise = image(300, 300, () => rand() * 255);
  for (const detail of ['simple', 'medium']) {
    assert.ok(traceOutlines(noise, [0, 0, 300, 300], detail).length <= 2, detail);
    assert.ok(traceLights(noise, [0, 0, 300, 300], detail).length <= 2, detail + ' lights');
  }
  const flat = image(100, 100, () => 128);
  assert.deepEqual(traceOutlines(flat, [0, 0, 100, 100], 'medium'), [], 'a flat area has no outline');
  assert.deepEqual(traceLights(flat, [0, 0, 100, 100], 'medium'), [], 'and no light');
});

function nightImage() {
  const rand = random(11);
  const windows = Array.from({ length: 12 }, () => [20 + Math.floor(rand() * 200), 180 + Math.floor(rand() * 100)]);
  return image(400, 300, (x, y) => {
    if (Math.hypot(x - 300, y - 80) <= 30) return 245;                                   // the moon
    if (windows.some(([wx, wy]) => x >= wx && x < wx + 3 && y >= wy && y < wy + 3)) return 235;   // tiny lit windows
    if (x < 240 && y > 160) return 60;                                                    // a dim building
    return 20;
  });
}

test('the brightest shapes are outlined as light; tiny lit windows are not', () => {
  const lights = traceLights(nightImage(), [0, 0, 400, 300], 'simple');
  assert.ok(lights.length >= 1 && lights.length <= LIGHT_LIMIT);
  for (const line of lights) for (const p of samples(line))
    assert.ok(Math.abs(Math.hypot(p[0] - 300, p[1] - 80) - 30) <= 3, 'on the moon’s rim');
  const rim = Array.from({ length: 72 }, (_, i) => [300 + 30 * Math.cos(i * Math.PI / 36), 80 + 30 * Math.sin(i * Math.PI / 36)]);
  assert.ok(rim.filter(p => lights.some(line => polylineDistance(p, line) <= 3)).length / rim.length >= 0.9, 'all round it');
});

test('Douglas-Peucker keeps the corners of a noisy straight run', () => {
  const run = [...Array.from({ length: 51 }, (_, i) => [i, (i % 2) * 0.3]), ...Array.from({ length: 50 }, (_, i) => [50, i + 1])];
  assert.deepEqual(simplifyPolyline(run, 1).map(p => p.map(Math.round)), [[0, 0], [50, 0], [50, 50]]);
});

test('draw_guide from_reference draws the outline mapped onto the target, as contour lines', async () => {
  const calls = [];
  const runtime = { study: { references: [{ id: 'tower', width: 400, height: 600 }, { id: 'night', width: 400, height: 300 }] },
    decisionObservation: { width: 2000, height: 1600 }, emit() {} };
  const pixels = { tower: towerImage(), night: nightImage() };
  const read = [];
  const tools = guideTools(runtime, {
    execute: operation => async (id, params) => { calls.push({ operation, params, id }); return { content: [], details: {} }; },
    mapPoint: mapReferencePoint,
    referencePixels: async (id, side) => { read.push(id); assert.ok(side >= Math.min(1440, Math.max(...[pixels[id].width, pixels[id].height])), 'decoded large enough to trace'); return pixels[id]; },
  });
  const draw = tools.find(t => t.name === 'draw_guide');
  // Source [50,0,300,600] onto target [500,200,500,1000]: scale 5/3.
  await draw.execute('t1', { element: 'Tower', from_reference: { reference_id: 'tower', source: [50, 0, 300, 600], target: [500, 200, 500, 1000], detail: 'simple' } });
  const strokes = calls[0].params.strokes;
  assert.ok(strokes.length >= 1 && strokes.length <= TRACE_LIMITS.simple + 2, 'within the cap (a line cut by the canvas may become two)');
  assert.ok(strokes.every(s => s.weight === 'contour'));
  const map = mapReferencePoint([50, 0, 300, 600], [500, 200, 500, 1000]);
  const outline = TOWER.map(([x, y]) => map(x, y));
  const lines = strokes.map(s => [s.start, ...s.segments.map(seg => seg.slice(4))]);
  const { worst, covered } = fit(lines, outline, 4 * 5 / 3);
  assert.ok(worst <= 4 * 5 / 3, `mapped onto the target (worst ${worst.toFixed(1)} canvas px)`);
  assert.ok(covered >= 0.9);
  assert.deepEqual(read, ['tower'], 'the reference is read once, and only its lines reach the plugin');
  assert.ok(Object.keys(calls[0].params).every(key => ['element', 'strokes'].includes(key)), 'no pixels in the call');
  // Lights in the warm guide colour, the painter's own lines after the traced ones.
  await draw.execute('t2', { element: 'Moon', from_reference: { reference_id: 'night', target: [0, 0, 800, 600], lights: true },
    lines: [{ points: [[0, 300], [800, 300]], weight: 'construction' }] });
  const weights = calls[1].params.strokes.map(s => s.weight);
  assert.ok(weights.includes('light') && weights.at(-1) === 'construction');
  const refused = [
    [{ reference_id: 'tower', source: [0, 0, 400, 600], target: [0, 0, 400, 400] }, /matching aspect ratios/],
    [{ reference_id: 'tower', source: [300, 0, 200, 600], target: [0, 0, 200, 600] }, /Source crop must fit the reference/],
    [{ reference_id: 'missing', target: [0, 0, 400, 600] }, /Unknown reference ID/],
  ];
  for (const [from_reference, message] of refused)
    await assert.rejects(draw.execute('bad', { element: 'Tower', from_reference }), message, JSON.stringify(from_reference));
  assert.equal(calls.length, 2, 'a refused guide reaches nothing');
  delete runtime.decisionObservation;
  await assert.rejects(draw.execute('blind', { element: 'Tower', from_reference: { reference_id: 'tower', target: [0, 0, 400, 600] } }), /look at the canvas/i);
});

test('a large reference is traced from a smaller decode, and its lines are scaled back', async () => {
  const calls = [], asked = [];
  // Listed at 800 x 1200; the plugin hands back a decode at half size.
  const runtime = { study: { references: [{ id: 'tower', width: 800, height: 1200 }] }, decisionObservation: { width: 2000, height: 2000 }, emit() {} };
  const big = towerImage();                                  // 400 x 600: the tower at half its listed size
  const tools = guideTools(runtime, {
    execute: () => async (id, params) => { calls.push(params); return { content: [], details: {} }; },
    mapPoint: mapReferencePoint,
    referencePixels: async (id, side) => { asked.push(side); return big; },
  });
  await tools.find(t => t.name === 'draw_guide').execute('big', { element: 'Tower', from_reference: { reference_id: 'tower', target: [400, 200, 800, 1200] } });
  const lines = calls[0].strokes.map(s => [s.start, ...s.segments.map(seg => seg.slice(4))]);
  const map = mapReferencePoint([0, 0, 800, 1200], [400, 200, 800, 1200]);
  const { worst, covered } = fit(lines, TOWER.map(([x, y]) => map(2 * x, 2 * y)), 8);
  assert.ok(worst <= 8 && covered >= 0.9, `back in the listed size (worst ${worst.toFixed(1)})`);
  for (const line of lines) for (const [x, y] of line) assert.ok(x >= 400 && x <= 1200 && y >= 200 && y <= 1400, 'never past the target');
  assert.equal(traceSide(1600, 1067, [0, 0, 1600, 1067]), 1440, 'about four times the working grid');
  assert.equal(traceSide(800, 600, [0, 0, 800, 600]), 800, 'never larger than the reference');
  assert.ok(traceSide(4800, 3200, [4400, 0, 400, 300]) > 1440, 'a small crop of a large image asks for more');
  const side = traceSide(20000, 20000, [0, 0, 100, 100]);
  assert.ok(side * side <= 4_000_000, 'never past four million pixels');
});

test('traceReferencePixels asks the plugin for a reduced decode once per reference and size', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'guide-trace-'));
  try {
    const path = join(folder, 'goal.png');
    await writeFile(path, 'not really a png');
    const native = [];
    const runtime = { study: { directory: folder, references: [{ id: 'goal', path, width: 4800, height: 3200 }] },
      async callNative(operation, params) {
        native.push({ operation, params });
        return { status: 'ok', sha256: params.sha256, width: 1440, height: 960, rgba_base64: Buffer.alloc(1440 * 960 * 4).toString('base64') };
      } };
    const first = await traceReferencePixels(runtime, 'goal', 1440);
    assert.deepEqual([first.width, first.height, first.data.length], [1440, 960, 1440 * 960 * 4]);
    assert.equal(native[0].operation, 'trace_reference', 'a decode path of its own, not the reference tools\' one');
    assert.equal(native[0].params.max_side, 1440);
    await traceReferencePixels(runtime, 'goal', 1440);
    assert.equal(native.length, 1, 'cached for the chat');
    await writeFile(path, 'a different picture');
    await traceReferencePixels(runtime, 'goal', 1440);
    assert.equal(native.length, 2, 'a changed file is decoded again');
    await truncate(path, (TRACE_REFERENCE_MB + 1) * 1024 * 1024);
    await assert.rejects(traceReferencePixels(runtime, 'goal', 1440), /too large to trace a guide from/);
    await assert.rejects(traceReferencePixels(runtime, 'nope', 1440), /attached reference/);
  } finally { await rm(folder, { recursive: true, force: true }); }
});

test('a part (transparent around it) has no light outline round its whole silhouette', () => {
  const disc = image(200, 200, () => 128, (x, y) => Math.hypot(x - 100, y - 100) <= 60 ? 255 : 0);
  assert.deepEqual(traceLights(disc, [0, 0, 200, 200], 'simple'), [], 'an opaque grey disc is not a light');
  const outline = traceOutlines(disc, [0, 0, 200, 200], 'simple');
  assert.ok(outline.length >= 1 && outline.every(line => samples(line).every(p => Math.abs(Math.hypot(p[0] - 100, p[1] - 100) - 60) <= 3)), 'its silhouette is its alpha');
});

test('a light that fills most of its crop is still outlined warm', () => {
  // The moon cropped to its bounding box covers about 78% of it.
  const lights = traceLights(nightImage(), [270, 50, 60, 60], 'simple');
  assert.ok(lights.length >= 1);
  for (const line of lights) for (const p of samples(line)) assert.ok(Math.abs(Math.hypot(p[0] - 300, p[1] - 80) - 30) <= 3, 'on the rim');
});

test('tiny and uniform crops trace to nothing without failing', () => {
  for (const source of [[0, 0, 1, 1], [10, 10, 3, 2], [0, 0, 400, 30]]) {
    for (const detail of ['simple', 'medium']) {
      assert.ok(Array.isArray(traceOutlines(towerImage(), source, detail)), JSON.stringify(source));
      assert.ok(Array.isArray(traceLights(towerImage(), source, detail)));
    }
  }
  assert.deepEqual(traceOutlines(towerImage(), [0, 0, 60, 60], 'medium'), [], 'all sky');
  assert.deepEqual(traceLights(towerImage(), [0, 0, 60, 60], 'medium'), []);
});

test('medium detail adds the inner structural lines: the corner between a building’s two faces', () => {
  const building = image(400, 400, (x, y) => x >= 100 && x < 300 && y >= 120 ? (x < 200 ? 60 : 120) : 220);
  const corner = line => line.every(([x, y]) => Math.abs(x - 200) <= 3 && y >= 120) && Math.abs(line.at(-1)[1] - line[0][1]) > 150;
  assert.ok(traceOutlines(building, [0, 0, 400, 400], 'medium').some(corner), 'the corner, top to bottom');
  const simple = traceOutlines(building, [0, 0, 400, 400], 'simple');
  assert.ok(simple.length >= 1 && simple.length <= TRACE_LIMITS.simple);
});

// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The mass map (draw_guide from_reference masses): VTracer's SVG parsed into polylines, the big masses' boundaries as
// guide lines (each boundary once, light masses warm, tiny ones dropped, inside a shape only), the painter's summary,
// and the draw_guide option end to end with a fake plugin. Images are made in memory; writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSvgMasses, traceMasses, describeMasses, MASS_LINES, MASS_OPTIONS } from '../src/guide-masses.ts';
import { GUIDE_POINTS } from '../src/guide-tool.ts';
import { paintingTools } from '../src/tools.mjs';
import { mapReferencePoint } from '../src/reference-generator.mjs';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/** A w x h RGBA image from colour(x, y) -> [r, g, b] (alpha 255). */
function image(w, h, colour) {
  const data = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const [r, g, b] = colour(x, y), i = (y * w + x) * 4;
    data[i] = r; data[i + 1] = g; data[i + 2] = b; data[i + 3] = 255;
  }
  return { width: w, height: h, data };
}
const MOON = [180, 35, 16];
/** A night scene as smoothed masses: a dark blue sky, a moon, a brown building on the left, green ground. */
const night = () => image(240, 160, (x, y) => {
  if (Math.hypot(x - MOON[0], y - MOON[1]) <= MOON[2]) return [250, 240, 200];
  if (x >= 20 && x < 110 && y >= 50 && y < 120) return [110, 70, 40];
  if (y >= 120) return [40, 90, 50];
  return [20, 30, 80];
});
const samples = points => points.slice(1).flatMap((p, i) => {
  const q = points[i], n = Math.max(1, Math.ceil(Math.hypot(p[0] - q[0], p[1] - q[1])));
  return Array.from({ length: n }, (_, k) => [q[0] + (p[0] - q[0]) * k / n, q[1] + (p[1] - q[1]) * k / n]);
});
const length = points => points.slice(1).reduce((sum, p, i) => sum + Math.hypot(p[0] - points[i][0], p[1] - points[i][1]), 0);

test('VTracer polygon paths parse into rings: absolute and relative moves and lines, closes, transforms', () => {
  const svg = '<svg><path d="M0,0L10,0l0,10l-10,0Zm2,2l3,0l0,3Z" fill="#102030"/>'
    + '<path d="M1 1 H 5 V 5 h -4 z" fill="#FFFFFF" transform="translate(100,50)"/></svg>';
  const masses = parseSvgMasses(svg);
  assert.equal(masses.length, 2);
  assert.deepEqual(masses[0].fill, [16, 32, 48]);
  assert.deepEqual(masses[0].rings, [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[2, 2], [5, 2], [5, 5], [2, 2]]],
    'a relative move after a close starts from the closed subpath’s start');
  assert.deepEqual(masses[1].rings, [[[101, 51], [105, 51], [105, 55], [101, 55], [101, 51]]]);
});

test('the masses of a scene: each boundary once, the light mass warm, nothing tiny, capped', async () => {
  const { lines, masses } = await traceMasses(night());
  assert.ok(lines.length >= 3 && lines.length <= MASS_LINES, `${lines.length} lines`);
  const lights = lines.filter(line => line.light);
  assert.ok(lights.length >= 1, 'the moon is a light mass');
  for (const line of lights) for (const [x, y] of samples(line.points))
    assert.ok(Math.abs(Math.hypot(x - MOON[0], y - MOON[1]) - MOON[2]) <= 3, `light lines run round the moon (${x}, ${y})`);
  for (const line of lines) assert.ok(line.points.length >= 2 && line.points.length <= GUIDE_POINTS);
  // Each boundary is drawn once: no line runs along another one.
  const all = lines.map(line => samples(line.points));
  for (const [a, mine] of all.entries()) {
    const others = all.filter((_, b) => b !== a).flat();
    const shared = mine.filter(([x, y]) => others.some(([u, v]) => Math.hypot(x - u, y - v) < 1.5)).length;
    assert.ok(shared <= Math.max(4, 0.1 * mine.length), `line ${a} shares ${shared} of ${mine.length} samples`);
  }
  // The building's top edge (y 50, x 20-110) is there.
  const top = all.flat().filter(([x, y]) => Math.abs(y - 50) <= 2 && x > 30 && x < 100).length;
  assert.ok(top >= 40, 'the building’s top is traced');
  assert.deepEqual(masses.map(m => m.light), masses.map(m => m.lum > 0.8), 'only the bright mass is light');
  const speck = image(240, 160, (x, y) => (Math.hypot(x - 60, y - 60) <= 3 ? [255, 255, 255] : y < 80 ? [20, 30, 80] : [40, 90, 50]));
  const few = await traceMasses(speck);
  for (const line of few.lines) for (const [, y] of samples(line.points)) assert.ok(y > 70, 'a speck gives no line, only the horizon');
});

test('inside a shape: masses found only there, and the shape’s own outline is left to the outline', async () => {
  const inside = (x, y) => x >= 10 && x < 120 && y >= 40 && y < 150;
  const { lines } = await traceMasses(night(), { inside });
  assert.ok(lines.length >= 1);
  const points = lines.flatMap(line => samples(line.points));
  for (const [x, y] of points) assert.ok(x >= 9 && x <= 121 && y >= 39 && y <= 151, `inside the shape (${x}, ${y})`);
  const onEdge = points.filter(([x, y]) => Math.min(Math.abs(x - 10), Math.abs(x - 120), Math.abs(y - 40), Math.abs(y - 150)) < 2).length;
  assert.ok(onEdge <= 0.05 * points.length, `${onEdge} of ${points.length} samples on the shape’s outline`);
  assert.ok(points.filter(([x, y]) => Math.abs(y - 50) <= 2).length >= 40, 'the building’s top inside the shape is traced');
});

test('the painter’s summary names each big mass by share, place, colour and value, in few words', async () => {
  const { masses } = await traceMasses(night());
  const text = describeMasses(masses);
  assert.match(text, /^\d+ masses/);
  assert.match(text, /\d+% dark .*blue.* top/, text);
  assert.match(text, /light .*moon|light/, text);
  assert.match(text, /green.* bottom/, text);
  assert.ok(text.split(/\s+/).length <= 90, `${text.split(/\s+/).length} words`);
});

test('draw_guide from_reference masses: the plugin smooths the crop, the boundaries reach it as guide lines', async () => {
  assert.deepEqual(MASS_OPTIONS, { hierarchical: 'cutout', mode: 'polygon', maxColors: 6, filterSpeckle: 12 });
  const folder = await mkdtemp(join(tmpdir(), 'guide-masses-'));
  try {
  await writeFile(join(folder, 'goal.png'), 'a goal image');
  const REFERENCE = { id: 'goal', role: 'reference', name: 'final_goal.png', path: join(folder, 'goal.png'), width: 480, height: 320 };
  const calls = [];
  const runtime = { calls, faulted: false, study: { directory: folder, references: [REFERENCE] }, emit() {},
    decisionObservation: { width: 960, height: 640 },
    async callNative(operation, params) {
      calls.push({ operation, params });
      if (operation === 'mass_reference') {
        const scene = night();       // the smoothed crop: 240 x 160 for a 480 x 320 source
        return { status: 'ok', width: 240, height: 160, source: params.source ?? [0, 0, 480, 320], original_width: 480, original_height: 320,
          sha256: params.sha256, ms: 5, rgba_base64: Buffer.from(scene.data).toString('base64') };
      }
      return { status: 'ok', layer_id: 'L1' };
    } };
  const tools = paintingTools(runtime);
  const draw = tools.find(t => t.name === 'draw_guide');
  await draw.execute('m1', { element: 'Scene', from_reference: { reference_id: 'goal', target: [0, 0, 960, 640], masses: true } });
  const mass = calls.find(c => c.operation === 'mass_reference');
  assert.ok(mass, 'the plugin smooths the reference');
  assert.deepEqual(mass.params.source, [0, 0, 480, 320]);
  const guide = calls.find(c => c.operation === 'draw_guide');
  const weights = new Set(guide.params.strokes.map(s => s.weight));
  assert.ok(weights.has('light') && weights.has('construction'), [...weights].join());
  // The moon (smoothed 180,35 r16 = reference 360,70 r32 = canvas 720,140 r64) comes back on the canvas.
  const map = mapReferencePoint([0, 0, 480, 320], [0, 0, 960, 640]);
  const [mx, my] = map(360, 70);
  for (const stroke of guide.params.strokes.filter(s => s.weight === 'light'))
    for (const [x, y] of [stroke.start, ...stroke.segments.map(s => s.slice(4))])
      assert.ok(Math.abs(Math.hypot(x - mx, y - my) - 64) <= 8, 'the moon’s outline on the canvas');
  } finally { await rm(folder, { recursive: true, force: true }); }
});

test('no guides by default: the painter\u2019s guidance starts from the underpainting; masses are an option of draw_guide', async () => {
  const { readFile } = await import('node:fs/promises');
  const prompt = await readFile(new URL('../src/prompt.mjs', import.meta.url), 'utf8');
  const studio = await readFile(new URL('../src/studio.mjs', import.meta.url), 'utf8');
  for (const text of [prompt, studio]) assert.doesNotMatch(text, /masses: true[^.]*unless the artist said otherwise/, 'masses are not a default');
  assert.match(prompt, /guides[^.]*only when the artist asks/i);
  assert.match(prompt, /first move[^.]*paint_from_reference/i, 'the default first move on a goal reference is the underpainting');
});

test('a whole-picture block-in with masses never asks for the shapes model; a ready one adds the big shapes’ outlines', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'guide-masses-'));
  try {
    await writeFile(join(folder, 'goal.png'), 'a goal image');
    const make = shapes => {
      const calls = [];
      const runtime = { calls, faulted: false, shapes, study: { directory: folder, references: [{ id: 'goal', role: 'reference', path: join(folder, 'goal.png'), width: 480, height: 320 }] },
        emit() {}, decisionObservation: { width: 960, height: 640 },
        async callNative(operation, params) {
          calls.push({ operation, params });
          if (operation === 'mass_reference') return { status: 'ok', width: 240, height: 160, source: [0, 0, 480, 320], sha256: params.sha256, ms: 5,
            rgba_base64: Buffer.from(night().data).toString('base64') };
          if (operation === 'trace_reference') return { status: 'ok', sha256: params.sha256, width: 480, height: 320, rgba_base64: Buffer.alloc(480 * 320 * 4).toString('base64') };
          if (operation === 'trace_edges') return { status: 'ok', silhouette: 'shapes', ms: 1, lines: [
            { kind: 'outline', points: [[10, 10], [200, 10]] }, { kind: 'structure', points: [[10, 50], [200, 50]] }] };
          return { status: 'ok', layer_id: 'L1' };
        } };
      return { runtime, calls };
    };
    const asked = [];
    const absent = { ready: async () => false, study: async () => { asked.push('study'); throw new Error('no'); }, shape: async () => { asked.push('shape'); throw new Error('no'); } };
    const one = make(absent);
    await paintingTools(one.runtime).find(t => t.name === 'draw_guide').execute('a', { element: 'Scene', from_reference: { reference_id: 'goal', target: [0, 0, 960, 640], masses: true } });
    assert.deepEqual(asked, [], 'no study, no download question from a block-in');
    assert.ok(!one.calls.some(c => c.operation === 'trace_edges'), 'masses only');
    // A ready model: its big shapes' outlines (contour) are drawn too, not their inner structure.
    const ready = { ready: async () => true, study: async () => ({ ms: 1, load_ms: 0, peak_mb: 1, provider: 'cpu', studied: true, attempt: 1 }),
      shape: async () => { throw Object.assign(new Error('empty'), { code: 'empty' }); }, forget: async () => {}, close: async () => {} };
    const two = make(ready);
    await paintingTools(two.runtime).find(t => t.name === 'draw_guide').execute('b', { element: 'Scene', from_reference: { reference_id: 'goal', target: [0, 0, 960, 640], masses: true } });
    const guide = two.calls.find(c => c.operation === 'draw_guide');
    assert.ok(two.calls.some(c => c.operation === 'trace_edges'), 'the outlines are traced');
    const contours = guide.params.strokes.filter(s => s.weight === 'contour');
    assert.ok(contours.length <= 1, 'at most the one outline, never the structure line');
  } finally { await rm(folder, { recursive: true, force: true }); }
});

// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// paint_accents (openspec crisp-accents; the artist, 2026-10-23): the accents the canvas lacks (find_accents, tested in
// test_accent_find.py) mapped onto the canvas and adjusted there by the plugin's `accents` operation (test_accent_adjust.py). A fake plugin; the
// reference and the canvas view are small files in a temporary folder, removed after each test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { paintingTools } from '../src/tools.mjs';
import { ASK_ABOVE, chooseAccents, ADJUSTS } from '../src/accents-tool.ts';
import { encodePlane } from '../src/shapes/png.ts';

const CANVAS = { width: 4000, height: 3000 };
const light = (x, y, strength, extra = {}) => ({ kind: 'lights', x, y, size: 3, colour: '#fff0c0', strength, shape: 'dot', direction: [1, 0], length: 3, glow: 0.4, ...extra });
const glint = (x, y, strength, extra = {}) => ({ kind: 'glints', x, y, size: 1, colour: '#ffffff', strength, shape: 'stroke', direction: [0, 1], length: 6, glow: 0, ...extra });
const dark = (x, y, strength, extra = {}) => ({ kind: 'darks', x, y, size: 2, colour: '#100c0c', strength, shape: 'dot', direction: [1, 0], length: 3, glow: 0, ...extra });
const line = (points, strength, extra = {}) => ({ kind: 'lines', x: points[1][0], y: points[1][1], size: 1.5, colour: '#181820', strength, shape: 'stroke', points, length: 100, bright: false, ...extra });

async function setup(t, { accents = [light(100, 100, 0.9)], observation = {}, shapes = null } = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'accents-tool-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const png = encodePlane({ width: 4, height: 3, data: new Uint8Array(12) });
  await writeFile(join(directory, 'goal.png'), png);
  await writeFile(join(directory, 'view.png'), png);
  const calls = [], events = [];
  let layer = 0;
  const asked = [];
  let answer = null;
  const runtime = {
    calls, faulted: false, mode: 'agent', emit(event) { events.push(event); },
    study: { directory, references: [{ id: 'goal', role: 'reference', name: 'goal.png', path: join(directory, 'goal.png'), width: 1000, height: 750 }], ...(shapes === 'declined' ? { shapes_declined: true } : {}) },
    ...(shapes ? { shapes: { ready: async () => true } } : {}),
    accentsKey: () => 'move-' + (runtime.move ?? 1),
    askAccents: question => { asked.push(question); },
    takeAccentsAnswer: key => { const given = answer && answer.key === key ? answer : null; answer = null; return given; },
    async callNative(operation, params, id) {
      calls.push({ operation, params, id });
      if (operation === 'observe') return { status: 'ok', ...CANVAS, revision: 'r1', image_path: join(directory, 'view.png'), image_width: 1000, image_height: 750,
        layers: [], protected_areas: [], ...observation };
      if (operation === 'find_accents') return { status: 'ok', accents: structuredClone(accents), found: {}, ms: 5, width: 1000, height: 750, original_width: 1000, original_height: 750 };
      if (operation === 'select') return { status: 'ok', name: params.name, bounds: [400, 400, 400, 400], selected_pixels: 1000 };
      if (operation === 'accents') return { status: 'ok', layer_id: 'G' + (++layer), layer_type: 'group', revision: 'r' + (calls.length + 1),
        image_path: join(directory, 'view.png'), width: 4000, height: 3000, accents: {}, adjustments: [{ kind: 'lights', filter: 'dodge' }] };
      return { status: 'ok' };
    },
  };
  const tools = paintingTools(runtime);
  const tool = tools.find(item => item.name === 'paint_accents');
  return { runtime, calls, events, tool, asked, answer: given => { answer = given; }, passes: () => calls.filter(c => c.operation === 'accents').flatMap(c => c.params.accents), adjusts: () => calls.filter(c => c.operation === 'accents') };
}
const text = result => result.content.filter(c => c.type === 'text').map(c => c.text).join('\n');

test('accents in a protected area are skipped and counted; the canvas view is always sent', async t => {
  const { tool, passes, calls } = await setup(t, {
    accents: [light(100, 100, 0.9), light(600, 600, 0.7)],
    observation: { protected_areas: [{ id: 'p1', name: 'Moon', bounds: [2300, 2300, 200, 200] }] },
  });
  const result = await tool.execute('a1', { reference_id: 'goal', kinds: ['lights'] });
  assert.equal(passes().length, 1);
  assert.match(text(result), /"protected":1/);
  assert.ok(calls.find(c => c.operation === 'find_accents').params.canvas, 'the plugin compares with the canvas view');
  assert.match(text(result), /skipped/i);
});

test('a box: only the accents inside it, found in the part of the reference under it', async t => {
  const { tool, calls, passes } = await setup(t, { accents: [light(150, 150, 0.9), light(600, 600, 0.8)] });
  await tool.execute('a1', { reference_id: 'goal', kinds: ['lights'], area: { box: [400, 400, 800, 800] } });
  assert.deepEqual(calls.find(c => c.operation === 'find_accents').params.source, [100, 100, 200, 200]);
  assert.equal(passes().length, 1);
});

test('a named selection: found in its bounds', async t => {
  const { tool, calls, passes } = await setup(t, { accents: [light(150, 150, 0.9)] });
  await tool.execute('a1', { reference_id: 'goal', kinds: ['lights'], area: { selection: 'Sky - Moon' } });
  assert.deepEqual(calls.find(c => c.operation === 'find_accents').params.source, [100, 100, 100, 100]);
  assert.equal(passes().length, 1, 'found in the selection\u2019s bounds');
});

test('an element shape only when the shapes model is already allowed', async t => {
  const { tool, calls } = await setup(t, { shapes: 'declined' });
  await assert.rejects(tool.execute('a1', { reference_id: 'goal', area: { shape: { box: [0, 0, 100, 100] } } }), /box or a selection/);
  assert.ok(!calls.some(c => c.operation === 'paint_pass'));
});

test('more than ASK_ABOVE accents: an actual question to the artist first; only their yes, for that move and count, lets it paint', async t => {
  const many = Array.from({ length: ASK_ABOVE + 10 }, (_, i) => light(10 + (i % 40) * 20, 10 + Math.floor(i / 40) * 20, 0.9 - i / 1000));
  const { tool, passes, asked, answer } = await setup(t, { accents: many });
  const first = await tool.execute('a1', { reference_id: 'goal', kinds: ['lights'], count: 400 });
  assert.equal(passes().length, 0, 'nothing adjusted');
  assert.equal(asked.length, 1, 'the artist is asked');
  assert.match(asked[0].question, new RegExp(`${ASK_ABOVE + 10} accents`));
  assert.equal(asked[0].count, ASK_ABOVE + 10); assert.equal(asked[0].key, 'move-1'); assert.ok(asked[0].options.length >= 2);
  assert.match(text(first), /asked the artist/i);
  await assert.rejects(tool.execute('a2', { reference_id: 'goal', kinds: ['lights'], count: 400, confirmed: true }), /artist/i, 'no answer yet');
  answer({ key: 'move-1', count: ASK_ABOVE + 10, yes: false });
  await assert.rejects(tool.execute('a3', { reference_id: 'goal', kinds: ['lights'], count: 400, confirmed: true }), /artist/i, 'a no is a no');
  answer({ key: 'move-1', count: ASK_ABOVE + 5, yes: true });
  await assert.rejects(tool.execute('a4', { reference_id: 'goal', kinds: ['lights'], count: 400, confirmed: true }), /artist/i, 'more than the artist agreed to');
  answer({ key: 'move-0', count: ASK_ABOVE + 10, yes: true });
  await assert.rejects(tool.execute('a5', { reference_id: 'goal', kinds: ['lights'], count: 400, confirmed: true }), /artist/i, 'another move\u2019s answer');
  answer({ key: 'move-1', count: ASK_ABOVE + 10, yes: true });
  await tool.execute('a6', { reference_id: 'goal', kinds: ['lights'], count: 400, confirmed: true });
  assert.equal(passes().length, ASK_ABOVE + 10);
  await assert.rejects(tool.execute('a7', { reference_id: 'goal', kinds: ['lights'], count: 400, confirmed: true }), /artist/i, 'an answer is used once');
});

test('a named selection or an element shape goes to the plugin, which cuts the masks to its own pixels', async t => {
  const { tool, adjusts } = await setup(t, { accents: [light(150, 150, 0.9)] });
  await tool.execute('a1', { reference_id: 'goal', kinds: ['lights'], area: { selection: 'Sky - Moon' } });
  assert.equal(adjusts()[0].params.selection, 'Sky - Moon');
});

test('accent sizes are capped and points stay on the canvas', async t => {
  const { tool, passes } = await setup(t, { accents: [light(100, 100, 0.9, { size: 400 }), line([[-50, 10], [10, 10], [2000, 10]], 0.8)] });
  await tool.execute('a1', { reference_id: 'goal', kinds: ['lights', 'lines'] });
  for (const a of passes()) {
    assert.ok(a.size <= 96, `size ${a.size}`);
    for (const [x, y] of a.points ?? []) assert.ok(x >= 0 && x <= 4000 && y >= 0 && y <= 3000, `${x},${y}`);
    if (a.points) assert.ok(Math.max(...a.points.map(p => p[0])) - Math.min(...a.points.map(p => p[0])) <= 1024, 'within the plugin\u2019s line span');
  }
});

test('exempt from the 2x stretch limit: a 4x enlargement on a painted canvas still paints', async t => {
  const { tool, passes } = await setup(t, { observation: { painted_share: 0.9, filename: 'painting.kra', layers: [{ id: 'a' }, { id: 'b' }] } });
  await tool.execute('a1', { reference_id: 'goal', kinds: ['lights'] });
  assert.equal(passes().length, 1);
});

test('the count is shared fairly between the kinds asked for, then strongest first', () => {
  const candidates = [...Array.from({ length: 10 }, (_, i) => light(i, 0, 0.9 - i * 0.01)), line([[0, 0], [1, 1], [2, 2]], 0.3), line([[0, 0], [1, 1], [2, 2]], 0.2)];
  const chosen = chooseAccents(candidates, ['lights', 'lines'], 6);
  assert.equal(chosen.length, 6);
  assert.equal(chosen.filter(a => a.kind === 'lines').length, 2, 'every line asked for, though weaker than the lights');
  assert.deepEqual(chosen.map(a => a.strength), [...chosen.map(a => a.strength)].sort((a, b) => b - a));
});

test('no accents there: nothing is painted and the painter is told', async t => {
  const { tool, passes } = await setup(t, { accents: [] });
  const result = await tool.execute('a1', { reference_id: 'goal' });
  assert.equal(passes().length, 0);
  assert.match(text(result), /already has the accents/i);
});

test('painter guidance: after the underpainting, crispness is paint_accents; the layer-need accents hint names it', async () => {
  const { PAINTING_INSTRUCTIONS } = await import('../src/prompt.mjs');
  const { NEED_HINTS } = await import('../src/layer-need.mjs');
  assert.match(PAINTING_INSTRUCTIONS, /stage two[^.]*paint_accents/i);
  assert.doesNotMatch(PAINTING_INSTRUCTIONS, /realism comes from paint_reference_edges/);
  assert.doesNotMatch(PAINTING_INSTRUCTIONS, /\/trace|traced lines/, 'no visible tracing');
  assert.match(NEED_HINTS.accents, /paint_accents/);
  const { readFileSync } = await import('node:fs');
  const skill = readFileSync(new URL('../skills/reference-transfer/SKILL.md', import.meta.url), 'utf8');
  assert.match(skill, /paint_accents/, 'the reference-transfer skill finishes with accents');
  assert.ok(skill.split(/\s+/).filter(Boolean).length <= 700);
});

test('specks of dark are dropped unless very strong; without a whole-canvas view nothing is found', async t => {
  const { tool, passes } = await setup(t, { accents: [
    dark(400, 400, 0.6, { size: 0.5 }), dark(500, 400, 0.9, { size: 0.5 }), dark(600, 400, 0.6, { size: 3 }),
  ] });
  const result = await tool.execute('a1', { reference_id: 'goal', kinds: ['darks'] });
  assert.equal(passes().length, 2, 'the strong speck and the sized dark');
  assert.match(text(result), /"small":1/);
  const bare = await setup(t, { observation: { image_path: undefined } });
  await assert.rejects(bare.tool.execute('a2', { reference_id: 'goal' }), /view of the whole canvas/);
  assert.ok(!bare.calls.some(c => c.operation === 'find_accents'));
});


const TIP = { png_base64: 'iVBORw0KGgo=', size: 96, core_share: 0.33, angle: 0, source: [100, 100] };

test('the canvas\u2019s own paint is adjusted: one accents call per paint_accents, the accents mapped onto the canvas by kind', async t => {
  const { tool, calls, adjusts } = await setup(t, { accents: [light(100, 100, 0.9), line([[200, 100], [210, 200], [220, 300]], 0.8),
    glint(500, 600, 0.7), dark(800, 700, 0.6)] });
  const result = await tool.execute('a1', { reference_id: 'goal', kinds: ['lights', 'lines', 'glints', 'darks'], count: 10 });
  assert.equal(adjusts().length, 1, 'one reversible pass');
  assert.ok(!calls.some(c => c.operation === 'paint_pass' || c.operation === 'accent_brush'), 'no marks: no strokes, no stamps');
  const { name, accents } = adjusts()[0].params;
  assert.equal(name, 'Accents');
  const by = Object.fromEntries(accents.map(a => [a.kind + ':' + a.x, a]));
  assert.deepEqual(new Set(accents.map(a => a.kind)), new Set(['lights', 'darks', 'detail']));
  assert.deepEqual([ADJUSTS.glints, ADJUSTS.lines], ['lights', 'detail']);
  const lamp = by['lights:400'];
  assert.ok(lamp && lamp.y === 400 && lamp.size === 12 && lamp.strength === 0.9, 'the light at 4x: (100, 100) is (400, 400), size 3 is 12');
  const streak = by['lights:2000'];
  assert.equal(streak.size, 24, 'a glint brightens along its length');
  const post = accents.find(a => a.kind === 'detail');
  assert.deepEqual(post.points, [[800, 400], [840, 800], [880, 1200]], 'a line is sharpened along itself, in canvas pixels');
  assert.equal(by['darks:3200'].kind, 'darks');
  assert.match(text(result), /"layer_id":"G1"/); assert.match(text(result), /"painted":4/);
  await tool.execute('a2', { reference_id: 'goal', kinds: ['lights'] });
  assert.equal(adjusts().length, 2, 'a later call is its own group in the move: Undo of the move removes both');
});

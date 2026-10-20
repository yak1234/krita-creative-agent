// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Guided trace (project-folder A2): the draw_guide and finish_guide tools, their mapping from reference pixels, and the
// setting that offers them. A fake runtime; writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { paintingTools, BATCH_TOOLS } from '../src/tools.mjs';
import { mapReferencePoint } from '../src/reference-generator.mjs';
import { StudioRuntime } from '../src/studio.mjs';
import { executionSettings } from '../src/execution-settings.mjs';
import { PaintingRuntime } from '../src/runtime.mjs';
import { SETTINGS } from '../src/settings-schema.mjs';

const REFERENCE = { id: 'reference-1', role: 'reference', name: 'final_goal.png', path: '/nonexistent/goal.png', width: 400, height: 300 };
function fakeRuntime(answer = () => ({ status: 'ok', layer_id: 'L1' })) {
  const calls = [], events = [];
  const runtime = { calls, faulted: false, study: { directory: '/nonexistent', references: [REFERENCE] }, emit(event) { events.push(event); },
    async callNative(operation, params, id) { calls.push({ operation, params, id }); return answer(operation, params, calls.length); } };
  return { runtime, calls, events, tools: paintingTools(runtime) };
}
const byName = (tools, name) => tools.find(t => t.name === name);

test('draw_guide in canvas pixels reaches the plugin as strokes', async () => {
  const { tools, calls, events } = fakeRuntime();
  const draw = byName(tools, 'draw_guide');
  assert.ok(draw && byName(tools, 'finish_guide'), 'both tools exist');
  assert.ok(!BATCH_TOOLS.includes('draw_guide'), 'a guide is its own call, not part of a painting batch');
  await draw.execute('g1', { element: 'Kremlin towers', lines: [{ points: [[0, 500], [768, 480]] }, { points: [[100, 400], [120, 200], [140, 400]], width: 4 }] });
  assert.equal(calls.length, 1);
  const [{ operation, params, id }] = calls;
  assert.equal(operation, 'draw_guide'); assert.equal(id, 'g1');
  assert.equal(params.element, 'Kremlin towers');
  assert.deepEqual(params.strokes, [
    { start: [0, 500], segments: [[0, 500, 768, 480, 768, 480]] },
    { start: [100, 400], segments: [[100, 400, 120, 200, 120, 200], [120, 200, 140, 400, 140, 400]], size: 4 },
  ], 'each polyline is one stroke of straight segments; the plugin forces the guide brush');
  assert.ok(events.some(e => e.type === 'action' && /guide/i.test(e.message) && /Kremlin towers/.test(e.message)), 'the panel says a guide was drawn');
});

test('draw_guide maps reference points through source and target', async () => {
  const { tools, calls } = fakeRuntime();
  const draw = byName(tools, 'draw_guide');
  // Source [100,50,200,100] (centre 200,100) onto target [300,600,400,200] (centre 500,700).
  await draw.execute('g2', { element: 'Towers', reference_id: 'reference-1', source: [100, 50, 200, 100], target: [300, 600, 400, 200],
    lines: [{ points: [[200, 100], [300, 150]] }] });
  assert.deepEqual(calls[0].params.strokes[0].start, [500, 700], 'the source centre lands at the target centre');
  assert.deepEqual(calls[0].params.strokes[0].segments[0].slice(4), [700, 800], 'the source corner lands at the target corner');
  // Without source the whole reference is the source.
  await draw.execute('g3', { element: 'Sky', reference_id: 'reference-1', target: [0, 0, 800, 600], lines: [{ points: [[0, 0], [400, 300]] }] });
  assert.deepEqual(calls[1].params.strokes[0].segments[0].slice(4), [800, 600]);
  const refused = [
    [{ reference_id: 'reference-1', source: [0, 0, 200, 100], target: [0, 0, 100, 100] }, /matching aspect ratios; crop instead of stretching/],
    [{ reference_id: 'reference-1', source: [300, 0, 200, 100], target: [0, 0, 200, 100] }, /Source crop must fit the reference/],
    [{ reference_id: 'reference-9', target: [0, 0, 400, 300] }, /Unknown reference ID/],
    [{ reference_id: 'reference-1' }, /target/],
    [{ target: [0, 0, 400, 300] }, /reference_id/],
  ];
  for (const [extra, message] of refused)
    await assert.rejects(draw.execute('bad', { element: 'Towers', lines: [{ points: [[0, 0], [10, 10]] }], ...extra }), message, JSON.stringify(extra));
  assert.equal(calls.length, 2, 'a refused guide reaches nothing');
  assert.throws(() => mapReferencePoint([0, 0, 200, 100], [0, 0, 100, 100]), /matching aspect ratios/);
  assert.deepEqual(mapReferencePoint([10, 10, 100, 50], [0, 0, 200, 100])(60, 35), [100, 50]);
});

test('finish_guide reaches its operation', async () => {
  const { tools, calls, events } = fakeRuntime(() => ({ status: 'ok', layer_id: 'L1', visible: false }));
  await byName(tools, 'finish_guide').execute('f1', { element: 'Kremlin towers' });
  assert.deepEqual(calls, [{ operation: 'finish_guide', params: { element: 'Kremlin towers' }, id: 'f1' }]);
  assert.ok(events.some(e => e.type === 'action' && /hidden/i.test(e.message)), 'the panel says the guide was hidden');
});

test('the guides setting off removes both tools from the offered list', () => {
  assert.equal(executionSettings().guides, true, 'on by default');
  assert.throws(() => executionSettings({ guides: 'yes' }), /guides must be true or false/);
  const offered = (settings, name, forkTools = true) => StudioRuntime.prototype.toolOffered.call({ executionSettings: executionSettings(settings), forkTools }, name);
  for (const name of ['draw_guide', 'finish_guide']) {
    assert.equal(offered({}, name), true, name);
    assert.equal(offered({ guides: false }, name), false, name);
    assert.equal(offered({}, name, false), false, name + ': stock Krita cannot paint a guide layer of its own');
    assert.equal(offered({}, name, null), false, name + ': a plugin too old to say');
  }
  assert.equal(offered({ guides: false }, 'paint_pass'), true, 'only the guide tools');
  assert.match(SETTINGS.find(s => s.key === 'guides').tooltip, /until the element is finished, then/);
  const runtime = { emit() {}, listModels: () => [], listProviders: () => [] };
  PaintingRuntime.prototype.acceptBridgeHealth.call(runtime, { protocol_version: 2, capabilities: {}, guides_view: true });
  assert.equal(runtime.guidesView, true, 'the plugin can make views without guides');
  PaintingRuntime.prototype.acceptBridgeHealth.call(runtime, { protocol_version: 2, capabilities: {} });
  assert.equal(runtime.guidesView, false, 'an older plugin cannot');
});

test('lines are clipped to the canvas, so one point off it does not refuse the guide', async () => {
  const { runtime, tools, calls } = fakeRuntime();
  runtime.decisionObservation = { width: 800, height: 600 };
  const draw = byName(tools, 'draw_guide');
  await draw.execute('c1', { element: 'Road', lines: [{ points: [[-200, 300], [400, 300], [400, 900]] }, { points: [[100, 100], [200, 100]] }] });
  const [first, second, third] = calls[0].params.strokes;
  assert.deepEqual(first.start, [0, 300], 'the part before the canvas edge is dropped');
  assert.deepEqual(first.segments, [[0, 300, 400, 300, 400, 300], [400, 300, 400, 600, 400, 600]], 'and the part past it');
  assert.deepEqual(second.start, [100, 100]);
  assert.equal(third, undefined);
  // A line that leaves and comes back is two lines.
  await draw.execute('c2', { element: 'Arch', lines: [{ points: [[100, 50], [100, -50], [200, -50], [200, 50]] }] });
  assert.equal(calls[1].params.strokes.length, 2);
  await assert.rejects(draw.execute('c3', { element: 'Moon', lines: [{ points: [[-50, -50], [-10, -80]] }] }), /outside the canvas/);
  assert.equal(calls.length, 2);
  // Before any look at the canvas there is nothing to clip to: the plugin checks the points.
  delete runtime.decisionObservation;
  await draw.execute('c4', { element: 'Road', lines: [{ points: [[-200, 300], [400, 300]] }] });
  assert.deepEqual(calls[2].params.strokes[0].start, [-200, 300]);
});

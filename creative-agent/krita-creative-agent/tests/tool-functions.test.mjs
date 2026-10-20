// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Krita's own tools as painter tools (krita-fork 5.3): bucket_fill, enclose_and_fill, krita_gradient and smart_patch.
// Schemas, batching, what the painter is told about when to use which, and what comes back. A fake runtime; writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { paintingTools, BATCH_TOOLS, modelResultText } from '../src/tools.mjs';
import { CRAFT_TOOLS, CRAFT_OPERATIONS } from '../src/craft.mjs';
import { methodsOf } from '../src/tool-choice.ts';
import { PAINTING_INSTRUCTIONS } from '../src/prompt.mjs';

const TOOLS = ['bucket_fill', 'enclose_and_fill', 'krita_gradient', 'smart_patch'];
function fakeRuntime(answer = () => ({ status: 'ok', layer_id: 'L1' })) {
  const calls = [];
  const runtime = { calls, faulted: false, study: { directory: '/nonexistent', references: [] }, emit() {},
    async callNative(operation, params, id) { calls.push({ operation, params, id }); return answer(operation, params, calls.length); } };
  return { runtime, calls, tools: paintingTools(runtime) };
}
const byName = (tools, name) => tools.find(t => t.name === name);
const AREA = [{ shape: 'rectangle', bounds: [0, 0, 100, 100] }];
const valid = {
  bucket_fill: { name: 'Wall', x: 40, y: 50, color: '#3a6ea5', options: { mode: 'similar', threshold: 20, sample: 'all' } },
  enclose_and_fill: { name: 'Windows', enclose_area: AREA, color: '#ffd27f', options: { regions: 'transparent', includeContourRegions: true } },
  krita_gradient: { name: 'Dusk', start: [0, 0], end: [0, 400], options: { colors: ['#112244', '#ffaa66'], shape: 'linear', dither: 'bayer4' } },
  smart_patch: { name: 'Seam repair', area: AREA, options: { accuracy: 60, patchRadius: 5 }, context: 96 },
};

test('the four tools exist, are craft tools that batch, and reach the operation of their own name', async () => {
  const { tools, calls } = fakeRuntime();
  for (const name of TOOLS) {
    assert.ok(byName(tools, name), name);
    assert.ok(CRAFT_TOOLS.includes(name) && CRAFT_OPERATIONS.includes(name) && BATCH_TOOLS.includes(name), name + ' is offered, journalled as a canvas change and batchable');
    await byName(tools, name).execute('id-' + name, valid[name]);
  }
  assert.deepEqual(calls.map(c => c.operation), TOOLS);
  assert.deepEqual(calls.map(c => c.params), TOOLS.map(name => valid[name]), 'sent as given');
});

test('they batch, naming a layer an earlier action made', async () => {
  const { tools, calls } = fakeRuntime((_operation, _params, n) => ({ status: 'ok', layer_id: 'layer-' + n }));
  await byName(tools, 'paint_batch').execute('batch', { actions: [
    { tool: 'bucket_fill', arguments: valid.bucket_fill },
    { tool: 'smart_patch', arguments: { name: 'Fix', area: AREA, layer_id: '$1' } },
    { tool: 'krita_gradient', arguments: { ...valid.krita_gradient, clip_to: '$1', blend_mode: 'multiply' } }] });
  assert.equal(calls[1].params.layer_id, 'layer-1');
  assert.equal(calls[2].params.clip_to, 'layer-1');
});

test('bad input is refused by the schema before anything runs', async () => {
  const { tools, calls } = fakeRuntime();
  const bad = [
    ['bucket_fill', { x: -1 }], ['bucket_fill', { x: 1.5 }], ['bucket_fill', { color: 'red' }], ['bucket_fill', { color: '#12345' }],
    ['bucket_fill', { options: { threshold: 0 } }], ['bucket_fill', { options: { threshold: 101 } }], ['bucket_fill', { options: { grow: 401 } }],
    ['bucket_fill', { options: { opacity: 2 } }], ['bucket_fill', { options: { mode: 'flood' } }], ['bucket_fill', { options: { name: 'x' } }],
    ['bucket_fill', { options: { regions: 'all' } }], ['bucket_fill', { options: { labels: [9] } }], ['bucket_fill', { extra: 1 }],
    ['bucket_fill', { x: 1e12 }], ['bucket_fill', { name: '' }], ['bucket_fill', { selection: 'x'.repeat(41) }],
    ['enclose_and_fill', { options: { regions: 'some' } }], ['enclose_and_fill', { color: 5 }], ['enclose_and_fill', { enclose_area: [] }],
    ['krita_gradient', { start: [0] }], ['krita_gradient', { end: [0, 0, 0] }], ['krita_gradient', { options: { shape: 'zigzag' } }],
    ['krita_gradient', { options: { colors: ['#000000'] } }], ['krita_gradient', { options: { colors: ['black', 'white'] } }],
    ['krita_gradient', { options: { dither: 'perlin' } }], ['krita_gradient', { options: { antiAliasThreshold: 1.5 } }],
    ['krita_gradient', { options: { colors: Array(17).fill('#000000') } }],
    ['smart_patch', { options: { accuracy: 100 } }], ['smart_patch', { options: { patchRadius: 1 } }], ['smart_patch', { options: { opacity: 1 } }],
    ['smart_patch', { context: 5 }], ['smart_patch', { context: 513 }], ['smart_patch', { color: '#000000' }],
  ];
  for (const [tool, change] of bad) {
    const args = { ...valid[tool], ...change, options: change.options ?? valid[tool].options };
    await assert.rejects(byName(tools, 'paint_batch').execute('bad', { actions: [{ tool, arguments: args }] }), /does not match its schema/, tool + ' ' + JSON.stringify(change));
  }
  assert.equal(calls.length, 0);
});

test('NaN, infinity and huge numbers cannot be sent (JSON has no NaN; the schema bounds the rest)', async () => {
  const { tools, calls } = fakeRuntime();
  for (const value of [NaN, Infinity, -Infinity, 1e300])
    await assert.rejects(byName(tools, 'paint_batch').execute('bad', { actions: [{ tool: 'krita_gradient', arguments: { ...valid.krita_gradient, start: [value, 0] } }] }), /does not match its schema/);
  assert.equal(calls.length, 0);
});

test('the descriptions say when to use which tool, and the limits', () => {
  const { tools } = fakeRuntime();
  const text = Object.fromEntries(TOOLS.map(name => [name, byName(tools, name).description]));
  assert.match(text.bucket_fill, /one region .*from a point/i);
  assert.match(text.bucket_fill, /fill_region/);
  assert.match(text.enclose_and_fill, /inside a drawn area|inside the enclosing area/i);
  assert.match(text.krita_gradient, /conical|spiral/);
  assert.match(text.krita_gradient, /fill_region/);
  assert.match(text.smart_patch, /repairs a seam inside a small area/);
  assert.match(text.smart_patch, /512 x 512/);
  for (const name of TOOLS) assert.match(text[name], /new layer|NEW layer/i, name + ' says it paints a new layer');
  for (const name of TOOLS) assert.ok(text[name].length < 1400, name + ' stays short');
  assert.match(PAINTING_INSTRUCTIONS, /smart_patch/);
  assert.match(PAINTING_INSTRUCTIONS, /bucket_fill/);
});

test('their results reach the model without host bookkeeping, and say what the call did', () => {
  const result = { status: 'ok', layer_id: 'L2', tool_call: { call: 'Node.fill', returned: true, did: 'Filled from (1, 1) with #3a6ea5.' },
    image_path: '/study/view.png', passes: [{ id: 'a' }], checkpoint: 'saved.kra', timings_ms: { total: 5 }, source_prior: {}, patched_bounds: [0, 0, 8, 8] };
  const text = JSON.parse(modelResultText(result));
  assert.deepEqual(text.tool_call, result.tool_call);
  assert.deepEqual(text.patched_bounds, [0, 0, 8, 8]);
  for (const key of ['image_path', 'passes', 'checkpoint', 'timings_ms', 'source_prior']) assert.equal(text[key], undefined, key + ' is host-only');
});

test('a fill, enclose-and-fill or gradient counts as a fill for tool choice, a smart patch as a patch', () => {
  const canvas = { width: 1000, height: 1000 };
  assert.deepEqual(methodsOf({ tool: 'bucket_fill', args: {} }, canvas), ['fill']);
  assert.deepEqual(methodsOf({ tool: 'enclose_and_fill', args: {} }, canvas), ['fill']);
  assert.deepEqual(methodsOf({ tool: 'krita_gradient', args: {} }, canvas), ['fill']);
  assert.deepEqual(methodsOf({ tool: 'smart_patch', args: {} }, canvas), ['patch']);
});

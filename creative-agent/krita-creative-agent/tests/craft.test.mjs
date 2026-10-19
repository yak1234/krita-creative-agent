// Layer craft tools in the companion: schemas, batching, layer references and result budgets. Writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { paintingTools, BATCH_TOOLS } from '../src/tools.mjs';
import { CRAFT_TOOLS } from '../src/craft.mjs';
import { StudioRuntime } from '../src/studio.mjs';

function fakeRuntime(answer) {
  const calls = [];
  const runtime = { calls, faulted: false, study: { directory: '/nonexistent', references: [] }, emit() {},
    async callNative(operation, params, id) { calls.push({ operation, params, id }); return answer(operation, params, calls.length); } };
  return { runtime, calls, tools: paintingTools(runtime) };
}
const byName = (tools, name) => tools.find(t => t.name === name);

test('craft tools exist, reach their plugin operations and can be batched', async () => {
  const { tools, calls } = fakeRuntime(() => ({ status: 'ok', layer_id: 'L1' }));
  for (const name of ['create_layer', 'set_layer', 'krita_capabilities']) assert.ok(byName(tools, name), name);
  assert.ok(BATCH_TOOLS.includes('create_layer') && BATCH_TOOLS.includes('set_layer'));
  await byName(tools, 'create_layer').execute('a', { name: 'Shadow', type: 'paint', blend_mode: 'multiply' });
  await byName(tools, 'set_layer').execute('b', { layer_id: 'L1', blend_mode: 'screen' });
  await byName(tools, 'krita_capabilities').execute('c', {});
  assert.deepEqual(calls.map(c => c.operation), ['create_layer', 'set_layer', 'capabilities']);
});

test('a batch can clip to a layer an earlier action created', async () => {
  const { tools, calls } = fakeRuntime((operation, _params, n) => ({ status: 'ok', layer_id: 'layer-' + n }));
  const result = await byName(tools, 'paint_batch').execute('batch', { actions: [
    { tool: 'create_layer', arguments: { name: 'Flats', type: 'paint', clip_base: true } },
    { tool: 'create_layer', arguments: { name: 'Shadow', type: 'paint', blend_mode: 'multiply', clip_to: '$1' } },
    { tool: 'set_layer', arguments: { layer_id: '$2', opacity: 0.5 } }] });
  assert.equal(calls[1].params.clip_to, 'layer-1');
  assert.equal(calls[2].params.layer_id, 'layer-2');
  assert.match(result.content[0].text, /"action":3/);
});

test('a reference to a later or missing action stops the batch before it runs', async () => {
  const { tools, calls } = fakeRuntime(() => ({ status: 'ok' }));
  await assert.rejects(byName(tools, 'paint_batch').execute('batch', { actions: [
    { tool: 'create_layer', arguments: { name: 'Shadow', type: 'paint', clip_to: '$2' } },
    { tool: 'create_layer', arguments: { name: 'Flats', type: 'paint' } }] }), /earlier action/);
  assert.equal(calls.length, 0);
});

test('the capability manifest reaches the painter whole', async () => {
  const filters = Object.fromEntries(Array.from({ length: 60 }, (_, i) => ['filter_' + i, { radius: 5, strength: 0.5, mode: 'soft' }]));
  const { tools } = fakeRuntime(() => ({ status: 'ok', capabilities: { blend_modes: { darken: ['multiply'] }, common_filters: filters } }));
  const text = (await byName(tools, 'krita_capabilities').execute('c', {})).content[0].text;
  assert.ok(text.length > 2000, 'larger than the ordinary result budget');
  assert.ok(JSON.parse(text).capabilities.common_filters.filter_59, 'not truncated');
});

test('a batch selects a region, then fills it onto the flats from an earlier action', async () => {
  const { tools, calls } = fakeRuntime((operation, _params, n) => operation === 'select'
    ? { status: 'ok', name: 'Figure', bounds: [0, 0, 8, 8], selected_pixels: 40 } : { status: 'ok', layer_id: 'layer-' + n });
  assert.ok(BATCH_TOOLS.includes('select') && BATCH_TOOLS.includes('fill_region'));
  const result = await byName(tools, 'paint_batch').execute('batch', { actions: [
    { tool: 'create_layer', arguments: { name: 'Flats', type: 'paint', clip_base: true } },
    { tool: 'select', arguments: { name: 'Figure', steps: [{ layer_id: 'artist-1', grow: 4 }, { shape: 'rectangle', bounds: [0, 0, 8, 2], mode: 'subtract' }] } },
    { tool: 'fill_region', arguments: { layer_id: '$1', selection: 'Figure', color: '#3a6ea5' } },
    { tool: 'fill_region', arguments: { name: 'Shadow', area: [{ saved: 'Figure', shrink: 2 }], blend_mode: 'multiply', clip_to: '$1',
      gradient: { type: 'radial', start: [4, 4], end: [8, 8], stops: [{ offset: 0, color: '#000000' }, { offset: 1, color: '#404040' }] } } }] });
  assert.deepEqual(calls.map(c => c.operation), ['create_layer', 'select', 'fill_region', 'fill_region']);
  assert.equal(calls[2].params.layer_id, 'layer-1');
  assert.equal(calls[3].params.clip_to, 'layer-1');
  assert.match(result.content[0].text, /"status":"ok"/);
});

test('selection steps and fills are checked against their schema before anything runs', async () => {
  const { tools, calls } = fakeRuntime(() => ({ status: 'ok' }));
  for (const action of [
    { tool: 'select', arguments: { name: 'Sky', steps: [] } },
    { tool: 'select', arguments: { name: 'Sky', steps: [{ shape: 'star', bounds: [0, 0, 1, 1] }] } },
    { tool: 'fill_region', arguments: { name: 'Sky', area: [{ shape: 'rectangle', bounds: [0, 0, 1, 1] }], color: 'blue' } },
    { tool: 'fill_region', arguments: { name: 'Sky', selection: 'Sky', gradient: { start: [0, 0], end: [1, 1], stops: [{ offset: 0, color: '#000000' }] } } }])
    await assert.rejects(byName(tools, 'paint_batch').execute('batch', { actions: [action] }), /does not match its schema/);
  assert.equal(calls.length, 0);
});

test('a batch grades the group an earlier action made with a filter', async () => {
  const { tools, calls } = fakeRuntime((operation, _params, n) => ({ status: 'ok', layer_id: 'layer-' + n }));
  assert.ok(BATCH_TOOLS.includes('apply_filter'));
  await byName(tools, 'paint_batch').execute('batch', { actions: [
    { tool: 'create_layer', arguments: { name: 'Painting', type: 'group' } },
    { tool: 'apply_filter', arguments: { target: '$1', filter: 'colorbalance', mode: 'layer', config: { cyan_red_midtones: 20 } } },
    { tool: 'apply_filter', arguments: { target: 'L9', filter: 'gaussian blur', area: [{ shape: 'ellipse', bounds: [0, 0, 10, 10] }] } }] });
  assert.deepEqual(calls.map(c => c.operation), ['create_layer', 'apply_filter', 'apply_filter']);
  assert.equal(calls[1].params.target, 'layer-1');
  await assert.rejects(byName(tools, 'paint_batch').execute('bad', { actions: [
    { tool: 'apply_filter', arguments: { target: 'L9', filter: 'gaussian blur', mode: 'smudge' } }] }), /does not match its schema/);
});

test('colorize_flats reaches the plugin, can colour line art made earlier in a batch, and checks its seeds', async () => {
  const { tools, calls } = fakeRuntime((operation, _params, n) => ({ status: 'ok', layer_id: 'layer-' + n }));
  const seeds = [{ x: 10, y: 10, color: '#3a6ea5' }, { x: 90, y: 10, color: 'transparent', radius: 4 }];
  await byName(tools, 'paint_batch').execute('batch', { actions: [
    { tool: 'create_layer', arguments: { name: 'Lines', type: 'paint' } },
    { tool: 'colorize_flats', arguments: { line_layer: '$1', seeds } },
    { tool: 'create_layer', arguments: { name: 'Shadow', type: 'paint', blend_mode: 'multiply', clip_to: '$2' } }] });
  assert.deepEqual(calls.map(c => c.operation), ['create_layer', 'colorize_flats', 'create_layer']);
  assert.deepEqual([calls[1].params.line_layer, calls[2].params.clip_to], ['layer-1', 'layer-2']);
  for (const bad of [[seeds[0]], [seeds[0], { x: 1, y: 1, color: 'red' }], [seeds[0], { x: 1, y: 1, color: '#000000', radius: 30 }]])
    await assert.rejects(byName(tools, 'paint_batch').execute('bad', { actions: [{ tool: 'colorize_flats', arguments: { line_layer: 'L', seeds: bad } }] }), /does not match its schema/);
  assert.equal(calls.length, 3);
});

test('native_craft off hides the craft tools from the painter and from paint_batch', async () => {
  const offered = [];
  const studio = { mode: 'autopilot', study: {}, models: { getModel: () => ({ input: ['text', 'image'] }) }, lunaMode: () => 'off',
    session: { setActiveToolsByName: names => offered.push(names), agent: {} }, executionSettings: { native_craft: false }, kritaActions: 13,
    toolOffered: StudioRuntime.prototype.toolOffered, applyPhaseReasoning: () => {} };
  StudioRuntime.prototype.selectTools.call(studio, 'agent');
  studio.executionSettings = { native_craft: true };
  StudioRuntime.prototype.selectTools.call(studio, 'agent');
  StudioRuntime.prototype.selectTools.call(studio, 'plan');
  const [off, on, plan] = offered;
  assert.deepEqual(CRAFT_TOOLS.filter(name => off.includes(name)), [], 'off: none offered');
  assert.deepEqual(CRAFT_TOOLS.filter(name => on.includes(name)), CRAFT_TOOLS, 'on: all offered while painting');
  assert.ok(off.includes('paint_batch') && off.includes('paint_pass'), 'strokes stay');
  assert.deepEqual(CRAFT_TOOLS.filter(name => plan.includes(name)), [], 'never while planning');

  const { runtime, calls } = fakeRuntime(() => ({ status: 'ok', layer_id: 'L1' }));
  runtime.toolOffered = name => !CRAFT_TOOLS.includes(name);
  const batch = byName(paintingTools(runtime), 'paint_batch');
  await assert.rejects(batch.execute('craft', { actions: [{ tool: 'paint_pass', arguments: { name: 'A', preset: 'b', strokes: [{ start: [0, 0], segments: [[1, 1, 2, 2, 3, 3]], size: 4, opacity: 1, flow: 1, color: '#000000' }] } },
    { tool: 'fill_region', arguments: { name: 'Sky', area: [{ shape: 'rectangle', bounds: [0, 0, 4, 4] }], color: '#3a6ea5' } }] }), /Action 2: fill_region is not available/);
  assert.equal(calls.length, 0, 'refused before anything paints');
});

test('set_layer takes a live layer style and checks it against its schema', async () => {
  const { tools, calls } = fakeRuntime(() => ({ status: 'ok', layer_id: 'L1' }));
  await byName(tools, 'set_layer').execute('a', { layer_id: 'L1', style: { drop_shadow: { distance: 6, size: 12 }, outer_glow: null } });
  assert.deepEqual(calls[0].params.style, { drop_shadow: { distance: 6, size: 12 }, outer_glow: null });
  for (const style of [{ bevel: {} }, { drop_shadow: { opacity: 2 } }, { outline: { position: 'around' } }])
    await assert.rejects(byName(tools, 'paint_batch').execute('bad', { actions: [{ tool: 'set_layer', arguments: { layer_id: 'L1', style } }] }), /does not match its schema/);
  assert.equal(calls.length, 1);
});

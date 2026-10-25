// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// paint_snow (openspec snow; the artist approved "a real snow method", 2026-10-25): part names become Find it areas
// through the studio's own path (proposeArea), faces are kept clear by default, settled snow and then falling snow are
// each one reversible plugin pass (snow_craft.py, tested in test_snow_craft.py), and the result counts what was painted.
// A fake plugin and studio; no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { paintingTools } from '../src/tools.mjs';
import { toolCatalogue } from '../src/tool-catalogue.ts';
import { exemption } from '../src/goal-likeness.ts';

const CANVAS = { width: 6000, height: 4500 };
const area = name => ({ part: name, mask_path: `/chat/.shapes/found-${name.replace(/\W/g, '')}.png`, bounds: [10, 20, 300, 200], share: 0.01, score: 0.9 });

function setup({ found = ['faces', 'hats', 'posts'] } = {}) {
  const calls = [], events = [], asked = [];
  const runtime = {
    faulted: false, mode: 'agent', study: { directory: '/chat' }, emit(event) { events.push(event); },
    async proposeArea(part, options) { asked.push({ part, options }); return found.includes(part) ? area(part) : null; },
    async callNative(operation, params, id) {
      calls.push({ operation, params, id });
      if (operation === 'observe') return { status: 'ok', ...CANVAS, revision: 'r1', image_path: '/chat/view.png', layers: [] };
      if (operation === 'snow' && params.mode === 'falling') return { status: 'ok', layer_id: 'L1', revision: 'r2', ...CANVAS,
        snow: { mode: 'falling', layers: { far: { flakes: 4200 }, mid: { flakes: 1100 }, near: { flakes: 55 } }, light: [200, 220, 250], kept_clear: 12, ms: 4000 } };
      if (operation === 'snow') return { status: 'ok', layer_id: 'L2', revision: 'r3', ...CANVAS,
        snow: { mode: 'settled', parts: params.settle_on.map((p, i) => ({ name: p.name, caps: 3 + i, cap_px: 9000, thickness_px: 24 + i })), ms: 2000 } };
      return { status: 'ok' };
    },
  };
  const tool = paintingTools(runtime).find(item => item.name === 'paint_snow');
  return { tool, calls, events, asked, snows: () => calls.filter(c => c.operation === 'snow') };
}
const text = result => result.content.filter(c => c.type === 'text').map(c => c.text).join('\n');

test('falling snow by default, faces found and kept clear, and the result counts the flakes per depth', async () => {
  const { tool, snows, asked, events } = setup();
  assert.ok(tool, 'paint_snow is a painting tool');
  const result = await tool.execute('c1', {});
  assert.deepEqual(asked.map(a => a.part), ['faces'], 'faces looked up by default');
  assert.ok(asked.every(a => a.options?.quiet), 'found quietly');
  const [call] = snows();
  assert.equal(call.id, 'c1', 'one call: the tool call’s own id');
  assert.deepEqual(call.params, { name: 'Snow: falling', mode: 'falling', density: 1, wind_deg: 10, layers: 3,
    keep_clear: [{ mask_path: '/chat/.shapes/found-faces.png', bounds: [10, 20, 300, 200] }] });
  const report = JSON.parse(text(result).split('\n').at(-1));
  assert.deepEqual(report.snow.falling.flakes, { far: 4200, mid: 1100, near: 55, total: 5355 });
  assert.deepEqual(report.snow.kept_clear, { found: ['faces'], not_found: [] });
  assert.match(events.at(-1).message, /5,355 flakes in 3 depths/);
});

test('both: settled snow on the named parts first, then falling, each its own pass; a part not found is reported', async () => {
  const { tool, snows, asked } = setup();
  const result = await tool.execute('c2', { settle_on: ['hats', 'posts', 'rooftops'], wind_deg: -20, density: 2, depth_layers: 2, thickness: 'thick' });
  assert.deepEqual(asked.map(a => a.part), ['faces', 'hats', 'posts', 'rooftops']);
  const [settled, falling] = snows();
  assert.equal(settled.id, 'c2/settled'); assert.equal(falling.id, 'c2/falling');
  assert.equal(settled.params.mode, 'settled'); assert.equal(settled.params.name, 'Snow: settled on hats, posts');
  assert.deepEqual(settled.params.settle_on.map(p => p.name), ['hats', 'posts']);
  assert.equal(settled.params.thickness, 1.6);
  assert.deepEqual(settled.params.keep_clear.length, 1);
  assert.deepEqual({ ...falling.params, keep_clear: undefined }, { name: 'Snow: falling', mode: 'falling', density: 2, wind_deg: -20, layers: 2, keep_clear: undefined });
  const report = JSON.parse(text(result).split('\n').at(-1));
  assert.deepEqual(report.snow.settled.parts, [{ part: 'hats', caps: 3, thickness_px: 24 }, { part: 'posts', caps: 4, thickness_px: 25 }]);
  assert.deepEqual(report.snow.settled.not_found, ['rooftops']);
  assert.match(report.note, /rooftops/);
});

test('settled snow with no part found paints nothing and says so; keep_clear [] looks for nothing', async () => {
  const { tool, snows } = setup({ found: [] });
  await assert.rejects(tool.execute('c3', { mode: 'settled', settle_on: ['roofs'] }), /roofs[^]*Nothing was painted/);
  assert.equal(snows().length, 0);
  await assert.rejects(tool.execute('c4', { mode: 'settled' }), /settle_on/);
  const clear = setup();
  await clear.tool.execute('c5', { keep_clear: [] });
  assert.equal(clear.asked.length, 0);
  assert.equal(clear.snows()[0].params.keep_clear, undefined);
});

test('painting_tool_help’s catalogue lists paint_snow with a rough time; goal likeness never undoes it', () => {
  const { tool } = setup();
  const catalogue = toolCatalogue({ tools: [tool], canvas: CANVAS });
  const entry = catalogue.tools.find(t => t.name === 'paint_snow');
  assert.ok(entry); assert.match(entry.rough_time, /s|min/);
  assert.match(tool.description, /falling[^]*settled/);
  assert.equal(exemption('paint_snow'), 'effect');
});

// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// paint_finish (openspec finish-stage; approved by the artist 2026-10-24): the goal where the underpainting placed it, the
// area, and the plugin's `finish` operation (finish_pass.py, tested in test_finish_pass.py). A fake plugin and studio; the
// goal and the area's mask are small files in a temporary folder, removed after each test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createHash } from 'node:crypto';
import { paintingTools } from '../src/tools.mjs';
import { NOT_UNDERPAINTED, NO_GOAL, goalEnlargement } from '../src/finish-tool.ts';
import { exemption } from '../src/goal-likeness.ts';
import { encodePlane } from '../src/shapes/png.ts';

const CANVAS = { width: 6000, height: 4500 };

async function setup(t, { underpainted = true, placed = 'transfer', sharpened = false, sharpenFirst = undefined } = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'finish-tool-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const bytes = encodePlane({ width: 4, height: 3, data: new Uint8Array(12) });
  const path = join(directory, sharpened ? 'goal.x4.png' : 'goal.png');
  await writeFile(path, bytes);
  await writeFile(join(directory, 'view.png'), bytes);
  const reference = { id: 'goal', role: 'reference', name: 'final_goal.png', path, width: sharpened ? 5792 : 1448, height: sharpened ? 4344 : 1086,
    ...(sharpened ? { sharpened: { from: { width: 1448, height: 1086 } } } : {}) };
  const calls = [], events = [], asked = [];
  const runtime = {
    calls, faulted: false, mode: 'agent', emit(event) { events.push(event); },
    study: { directory, references: [reference] },
    finishGoal: async canvas => {
      asked.push(canvas);
      const goal = placed === 'none' ? null : { reference, source: [0, 0, reference.width, reference.height], target: [0, 0, CANVAS.width, CANVAS.height], from: placed };
      return { goal, underpainted };
    },
    ...(sharpenFirst ? { finishSharpenFirst: sharpenFirst } : {}),
    async callNative(operation, params, id) {
      calls.push({ operation, params, id });
      if (operation === 'observe') return { status: 'ok', ...CANVAS, revision: 'r1', image_path: join(directory, 'view.png'), layers: [] };
      if (operation === 'finish') return { status: 'ok', layer_id: 'F1', layer_type: 'group', revision: 'r2', image_path: join(directory, 'view.png'), ...CANVAS,
        finish: { tiles: 108, of_tiles: 108, blend_tiles: 60, stroke_tiles: 90, strokes: 1465111, soft_share: 0.41, ms: 61000 } };
      return { status: 'ok' };
    },
  };
  const tool = paintingTools(runtime).find(item => item.name === 'paint_finish');
  return { runtime, calls, events, asked, tool, reference, sha: createHash('sha256').update(bytes).digest('hex'), finishes: () => calls.filter(c => c.operation === 'finish') };
}
const text = result => result.content.filter(c => c.type === 'text').map(c => c.text).join('\n');

test('the whole picture by default: the goal file, its hash and where the underpainting placed it go to the plugin', async t => {
  const { tool, finishes, sha, reference, events } = await setup(t);
  const result = await tool.execute('f1', {});
  const [call] = finishes();
  assert.deepEqual(call.params, { name: 'Finish', goal: { path: reference.path, sha256: sha, size: [1448, 1086], source: [0, 0, 1448, 1086], target: [0, 0, 6000, 4500] } });
  assert.equal(call.id, 'f1', 'one reversible pass under the tool call’s id');
  assert.match(text(result), /"enlargement":4.14/);
  assert.match(text(result), /paint_accents/, 'the next stage is named');
  assert.match(events.at(-1).message, /Finished 108 squares[^]*1,465,111 form strokes/);
  assert.ok(events.some(e => e.type === 'status' && /Finish/.test(e.message)), 'the Now card says what runs');
});

test('a sharpened goal is the file the plugin reads', async t => {
  const { tool, finishes, reference } = await setup(t, { sharpened: true });
  const result = await tool.execute('f1', {});
  assert.equal(finishes()[0].params.goal.path, reference.path);
  assert.deepEqual(finishes()[0].params.goal.size, [5792, 4344]);
  assert.match(text(result), /"sharpened":true/);
});

test('refused before the whole picture is underpainted, and without a goal on the canvas; nothing reaches the plugin', async t => {
  const fresh = await setup(t, { underpainted: false });
  await assert.rejects(fresh.tool.execute('f1', {}), error => error.message === NOT_UNDERPAINTED);
  const none = await setup(t, { placed: 'none' });
  await assert.rejects(none.tool.execute('f1', {}), error => error.message === NO_GOAL);
  assert.equal(fresh.finishes().length + none.finishes().length, 0);
});

// Review finding: an unsharpened goal enlarged more than 2x mostly blurs; the studio says whether to offer Sharpen first.
test('the studio may refuse a call to offer Sharpen first; nothing reaches the plugin then, and the next call paints', async t => {
  let asked = 0;
  const { tool, finishes } = await setup(t, { sharpenFirst: async goal => (asked++ ? null : `Sharpen first: ${goal.reference.id}`) });
  await assert.rejects(tool.execute('f1', {}), /Sharpen first: goal/);
  assert.equal(finishes().length, 0);
  await tool.execute('f2', {});
  assert.equal(finishes().length, 1);
});

test('the area: a box or a selection as named, the artist’s Paint only here area by default, a shape only with the shapes model', async t => {
  const { tool, finishes, runtime } = await setup(t);
  await tool.execute('f1', { area: { box: [100, 200, 300, 400] } });
  await tool.execute('f2', { area: { selection: 'Sky - Moon' } });
  assert.deepEqual(finishes()[0].params.box, [100, 200, 300, 400]);
  assert.equal(finishes()[1].params.selection, 'Sky - Moon');
  await mkdir(join(runtime.study.directory, '.shapes'), { recursive: true });
  const mask_path = join(runtime.study.directory, '.shapes', 'paint-only-0123456789abcdef01234567.png');
  await writeFile(mask_path, encodePlane({ width: 20, height: 10, data: new Uint8Array(200).fill(255) }));
  runtime.paintOnlyArea = () => ({ mask_path, bounds: [40, 50, 20, 10] });
  await tool.execute('f3', {});
  assert.deepEqual(finishes()[2].params.inside_shape, { mask_path, bounds: [40, 50, 20, 10] }, 'the plugin cuts both layers to the area');
  await tool.execute('f4', { area: 'whole' });
  assert.equal(finishes()[3].params.inside_shape, undefined, 'an area the painter names still goes');
  runtime.study.shapes_declined = true;
  await assert.rejects(tool.execute('f5', { area: { shape: { prompt: 'the towers' } } }), /shapes model/);
});

test('the action line names the finish', async () => {
  const { PaintingRuntime } = await import('../src/runtime.mjs');
  const events = [], runtime = Object.create(PaintingRuntime.prototype);
  Object.assign(runtime, { pendingTools: new Map(), emit: event => events.push(event), setActivity() {}, turns: 0 });
  runtime.onEvent({ type: 'tool_execution_start', toolCallId: 'c1', toolName: 'paint_finish', args: {} });
  runtime.onEvent({ type: 'tool_execution_end', toolCallId: 'c1', toolName: 'paint_finish', isError: false, result: {} });
  assert.equal(events.find(e => e.type === 'action').message, 'Painted: Finish');
});

test('measured by goal likeness, never undone by it; the enlargement is the placement’s', () => {
  assert.equal(exemption('paint_finish'), 'finish');
  assert.equal(goalEnlargement({ source: [0, 0, 1448, 1086], target: [0, 0, 6000, 4500] }).toFixed(2), '4.14');
});

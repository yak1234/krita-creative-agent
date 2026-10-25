// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// refine_to_goal (openspec finish-stage goal 8, the artist 2026-10-24: "i want the end result where our accents and finishes
// make it move eventually to the final"): the host ranks the canvas by what is left at full size (area_compare.py
// refine_map) and runs a fine Finish then accents on the worst regions, a finer Finish where fine was not enough, until every
// region is close or a budget is spent. A fake plugin whose regions get closer as they are finished; the goal is a small file
// in a temporary folder, removed after each test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { paintingTools } from '../src/tools.mjs';
import { DONE_SCORE, LEVELS, NO_GAIN, NO_GAIN_SHARE, SOFT_REGION, TOUCH_UP, refineToGoalNote } from '../src/refine-goal.ts';
import { exemption } from '../src/goal-likeness.ts';
import { encodePlane, decodePlane } from '../src/shapes/png.ts';

const CANVAS = { width: 6000, height: 4500 };
const GAIN = { fine: 3, finer: 2 };

// The squares a finish's mask covers (their centres), as the plugin paints them.
async function covered(params, keys) {
  const plane = decodePlane(await readFile(params.inside_shape.mask_path)), [bx, by] = params.inside_shape.bounds;
  return keys.filter(key => { const [x, y] = key.split(',').map(Number), cx = x + 256 - bx, cy = y + 256 - by;
    return cx >= 0 && cy >= 0 && cx < plane.width && cy < plane.height && plane.data[cy * plane.width + cx] > 127; });
}

// `gains`: (square, detail) -> how much a pass takes off (GAIN by default); `soft`: square -> the goal's soft share there.
async function setup(t, { scores = { '0,0': 9, '512,0': 6, '1024,0': 3 }, underpainted = true, placed = true, protectedAreas = [], gains = null, soft = {} } = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'refine-goal-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const bytes = encodePlane({ width: 4, height: 3, data: new Uint8Array(12) });
  const path = join(directory, 'goal.png');
  await writeFile(path, bytes); await writeFile(join(directory, 'view.png'), bytes);
  const reference = { id: 'goal', role: 'reference', name: 'goal.png', path, width: 5792, height: 4344, sharpened: { from: { width: 1448, height: 1086 } } };
  const calls = [], events = [], left = { ...scores };
  const cell = key => { const [x, y] = key.split(',').map(Number); return [x, y, 512, 512]; };
  const runtime = {
    calls, faulted: false, mode: 'agent', emit(event) { events.push(event); },
    study: { directory, references: [reference] },
    finishGoal: async () => ({ goal: placed ? { reference, source: [0, 0, 5792, 4344], target: [0, 0, 6000, 4500], from: 'transfer' } : null, underpainted }),
    async callNative(operation, params, id) {
      calls.push({ operation, params, id });
      if (operation === 'observe') return { status: 'ok', ...CANVAS, revision: 'r' + calls.length, image_path: join(directory, 'view.png'), image_width: 1568, image_height: 1176, layers: [], protected_areas: protectedAreas };
      if (operation === 'refine_map') {
        const cells = Object.entries(left).map(([key, score]) => ({ rect: cell(key), colour: score / 2, edges: score / 2, score,
          ...(params.soft ? { soft: soft[key] ?? 0 } : {}) })).sort((a, b) => b.score - a.score);
        return { status: 'ok', rect: params.rect, cells, colour: 1, edges: 1, ms: 700 };
      }
      if (operation === 'finish') { const keys = await covered(params, Object.keys(left)); calls.at(-1).squares = keys;
        for (const key of keys) left[key] = Math.max(0, Math.round((left[key] - (gains ? gains(key, params.detail) : GAIN[params.detail])) * 10) / 10);
        return { status: 'ok', layer_id: 'F' + calls.length, finish: { detail: params.detail, strokes: 100000 * keys.length, tiles: keys.length, of_tiles: keys.length, ms: 2000 }, image_path: join(directory, 'view.png'), ...CANVAS }; }
      if (operation === 'area_likeness') { const score = left[params.rect.slice(0, 2).join(',')]; return { status: 'ok', colour: score / 2, edges: score / 2, rect: params.rect, ms: 13 }; }
      if (operation === 'area_accents') return { status: 'ok', rect: params.rect, scale: 1, ms: 500, found: { lights: 1 },
        accents: [{ kind: 'lights', x: params.rect[0] + 10, y: params.rect[1] + 10, size: 3, colour: '#ffeeaa', strength: 0.8, shape: 'dot' },
          { kind: 'darks', x: params.rect[0] + 30, y: params.rect[1] + 30, size: 3, colour: '#100c0c', strength: 0.5, shape: 'dot' }] };
      if (operation === 'accents') return { status: 'ok', layer_id: 'A' + calls.length, adjustments: [] };
      if (operation === 'flatten_passes') return { status: 'ok', layer_id: 'M' + calls.length, layer_type: 'merged', flattened_passes: params.pass_ids.length, removed_layers: 3 * params.pass_ids.length };
      return { status: 'ok' };
    },
  };
  const tool = paintingTools(runtime).find(item => item.name === 'refine_to_goal');
  const of = op => calls.filter(c => c.operation === op);
  return { runtime, calls, events, tool, of, left };
}
const report = result => JSON.parse(result.content.filter(c => c.type === 'text').at(-1).text);

test('worst regions first: a fine Finish then accents on each region above the bar, finer where fine was not enough, until all are close', async t => {
  const { tool, of, events } = await setup(t);
  const result = report(await tool.execute('r1', {}));
  // Review finding: one finish pass per batch of squares (a mask of them) and one accents pass per round, not two passes a square.
  assert.deepEqual(of('finish').map(c => [c.squares, c.params.detail]), [[['0,0', '512,0'], 'fine'], [['0,0'], 'finer']]);
  assert.ok(of('finish').every(c => c.params.goal?.sha256 && !c.params.box));
  assert.equal(of('accents').length, 2, 'one accents pass a round');
  assert.equal(of('accents')[0].params.accents.length, 4, 'both squares’ accents, 2-4 px darks kept at full size');
  const ids = of('finish').concat(of('accents')).map(c => c.id);
  assert.equal(new Set(ids).size, ids.length, 'every pass its own id');
  assert.ok(ids.every(id => id.startsWith('r1/')), 'under the tool call');
  assert.equal(result.converged, true);
  assert.equal(result.rounds.length, 2);
  assert.deepEqual(result.rounds[0].regions.map(r => [r.before, r.after, r.detail]), [[9, 6, 'fine'], [6, 3, 'fine']]);
  assert.deepEqual(result.rounds[1].regions.map(r => [r.before, r.after, r.detail]), [[6, 4, 'finer']]);
  assert.ok(result.rounds.every(r => Number.isFinite(r.seconds)));
  assert.ok(events.some(e => e.type === 'status' && /^Refine: round 1, region 2 of 2, difference 6\.0 → 3\.0$/.test(e.message)), events.map(e => e.message).join('\n'));
  assert.equal(DONE_SCORE, 4); assert.deepEqual(LEVELS, ['fine', 'finer']);
});

test('a region finished at every level and still above the bar is left, and the report says so', async t => {
  const { tool, of } = await setup(t, { scores: { '0,0': 12 } });
  const result = report(await tool.execute('r1', {}));
  assert.deepEqual(of('finish').map(c => c.params.detail), ['fine', 'finer']);
  assert.equal(result.converged, false);
  assert.equal(result.left_above, 1);
  assert.match(result.message, /as close as the strokes get/);
});

test('the time and stroke budgets end the loop between regions; Stop does too and keeps what is done', async t => {
  const timed = await setup(t);
  let clock = 0;
  timed.runtime.refineClock = () => (clock += 400000);
  const byTime = report(await timed.tool.execute('r1', { budget_minutes: 10 }));
  assert.equal(timed.of('finish').length, 1); assert.match(byTime.ended, /time budget/);
  const strokes = await setup(t);
  const byStrokes = report(await strokes.tool.execute('r1', { max_strokes: 150000 }));
  assert.equal(strokes.of('finish').length, 1); assert.match(byStrokes.ended, /stroke budget/);
  const stopped = await setup(t);
  const controller = new AbortController();
  const native = stopped.runtime.callNative;
  stopped.runtime.callNative = async (op, params, id) => { const out = await native(op, params, id); if (op === 'accents') controller.abort(); return out; };
  const byStop = report(await stopped.tool.execute('r1', {}, controller.signal));
  assert.equal(stopped.of('finish').length, 1); assert.match(byStop.ended, /Stopped by the artist/);
});

test('the area: the artist’s Paint only here area or a box limits the map; refused before an underpainting or without a goal', async t => {
  const { tool, of, runtime } = await setup(t);
  await mkdir(join(runtime.study.directory, '.shapes'), { recursive: true });
  const mask = join(runtime.study.directory, '.shapes', 'paint-only-0123456789abcdef01234567.png');
  await writeFile(mask, encodePlane({ width: 1100, height: 600, data: new Uint8Array(1100 * 600).fill(255) }));
  runtime.paintOnlyArea = () => ({ mask_path: mask, bounds: [0, 0, 1100, 600] });
  await tool.execute('r1', {});
  assert.deepEqual(of('refine_map')[0].params.rect, [0, 0, 1100, 600]);
  const boxed = await setup(t);
  await boxed.tool.execute('r1', { area: { box: [0, 0, 600, 600] } });
  assert.deepEqual(boxed.of('refine_map')[0].params.rect, [0, 0, 600, 600]);
  const fresh = await setup(t, { underpainted: false });
  await assert.rejects(fresh.tool.execute('r1', {}), /underpainting/);
  const none = await setup(t, { placed: false });
  await assert.rejects(none.tool.execute('r1', {}), /goal image/);
  assert.equal(fresh.of('finish').length + none.of('finish').length, 0);
});

test('accents in a protected area are skipped, and squares mostly protected or outside Paint only here are left; likeness never undoes it', async t => {
  const { tool, of } = await setup(t, { scores: { '0,0': 9 }, protectedAreas: [{ name: 'Moon', bounds: [0, 0, 20, 20] }] });
  await tool.execute('r1', {});
  assert.deepEqual(of('accents')[0].params.accents.map(a => [a.x, a.y]), [[30, 30]], 'the accent in the protected area skipped');
  const shielded = await setup(t, { scores: { '0,0': 9, '512,0': 8 }, protectedAreas: [{ name: 'Moon', bounds: [0, 0, 400, 512] }] });
  await shielded.tool.execute('r1', {});
  assert.deepEqual(shielded.of('finish').map(c => c.squares), [['512,0'], ['512,0']], 'the mostly protected square is left');
  const scoped = await setup(t, { scores: { '0,0': 9, '512,0': 8 } });
  await mkdir(join(scoped.runtime.study.directory, '.shapes'), { recursive: true });
  const mask = join(scoped.runtime.study.directory, '.shapes', 'paint-only-0123456789abcdef01234567.png');
  const area = new Uint8Array(1024 * 512); for (let y = 0; y < 512; y++) for (let x = 0; x < 600; x++) area[y * 1024 + x] = 255;
  await writeFile(mask, encodePlane({ width: 1024, height: 512, data: area }));
  scoped.runtime.paintOnlyArea = () => ({ mask_path: mask, bounds: [0, 0, 1024, 512] });
  await scoped.tool.execute('r1', {});
  assert.deepEqual(scoped.of('finish').map(c => c.squares), [['0,0'], ['0,0']], 'the square mostly outside the area is left');
  assert.equal(exemption('refine_to_goal'), 'finish');
});

test('a refine request without an area after the whole-picture Finish: the host runs refine_to_goal', () => {
  assert.match(refineToGoalNote({ text: 'Refine the painting, make it closer to the final', area: false, finished: true }), /refine_to_goal/);
  assert.equal(refineToGoalNote({ text: 'Refine the church', area: true, finished: true }), '');
  assert.equal(refineToGoalNote({ text: 'Refine it', area: false, finished: false }), '');
  assert.equal(refineToGoalNote({ text: 'Paint a cat', area: false, finished: true }), '');
});

// Review finding: a refine request naming a part, or a negated one, ran refine_to_goal over the whole canvas.
test('the refine note: only for the whole picture, never negated; a named part is asked for its area and refined fine there', () => {
  for (const text of ['Add more detail to the church windows', 'Refine the domed church', 'Sharpen the left buildings please'])
    { const note = refineToGoalNote({ text, area: false, finished: true });
      assert.doesNotMatch(note, /Call refine_to_goal/, text); assert.match(note, /ask_for_selection[^]*paint_finish with detail "fine"/, text); }
  for (const text of ['Don’t add detail', 'Do not refine anything yet', 'No more detail, thanks'])
    assert.equal(refineToGoalNote({ text, area: false, finished: true }), '', text);
  for (const text of ['Refine the painting, make it closer to the final', 'Add more detail', 'Refine it', 'Sharpen everything'])
    assert.match(refineToGoalNote({ text, area: false, finished: true }), /Call refine_to_goal/, text);
});

// Review finding: Stop during a square's finish threw instead of reporting what was kept; so did the painting allowance.
test('Stop or the allowance during a square ends the run with the report: what is done is kept and the rounds recorded', async t => {
  for (const [failure, expected] of [['stop', /Stopped by the artist[^]*kept/], ['allowance', /Painting allowance reached/], ['stopped', /Stopped by the artist/]]) {
    const s = await setup(t);
    const controller = new AbortController();
    const native = s.runtime.callNative;
    let finishes = 0;
    s.runtime.callNative = async (op, params, id) => {
      if (op === 'finish' && ++finishes === 2) {
        if (failure === 'stop') { controller.abort(); throw Object.assign(new Error('This operation was aborted'), { name: 'AbortError' }); }
        if (failure === 'allowance') throw new Error('Painting allowance reached.');
        const out = await native(op, params, id); return { ...out, stopped: 'Stopped by the artist: the finish is kept where it was painted (0 of 1 squares).' };
      }
      return native(op, params, id);
    };
    const result = report(await s.tool.execute('r1', {}, controller.signal));
    assert.match(result.ended, expected, failure);
    assert.equal(result.rounds[0].regions.length, 2, failure + ': the first round recorded');
    assert.equal(result.converged, false);
  }
});

// Review finding: ~300 passes and ~1,000 layers on New Moscow. Squares go in batches of at most 15% of the canvas.
test('thirty squares: three finish passes and one accents pass a round', async t => {
  const scores = {}; for (let i = 0; i < 30; i++) scores[`${(i % 10) * 512},${Math.floor(i / 10) * 512}`] = 6;
  const { tool, of } = await setup(t, { scores });
  const result = report(await tool.execute('r1', {}));
  assert.equal(of('finish').length, 3); assert.equal(of('accents').length, 1);
  assert.deepEqual(of('finish').map(c => c.squares.length), [14, 14, 2]);
  assert.equal(result.converged, true);
  assert.equal(of('refine_map').length, 1, 'no extra map after the last round: every square is under the bar (measured after its pass)');
});

test('the full-size checks have the long operations’ time; the action line names the step', async () => {
  const { LONG_OPERATIONS } = await import('../src/craft.mjs');
  for (const op of ['area_likeness', 'area_accents', 'refine_map', 'flatten_passes']) assert.ok(LONG_OPERATIONS.includes(op), op);
  // flatten_passes changes the painting: journalled under the move's stage, with the revision checked.
  const { mutates } = await import('../src/craft.mjs');
  assert.ok(mutates('flatten_passes'));
  const bridge = await readFile(new URL('../src/bridge.mjs', import.meta.url), 'utf8');
  assert.match(bridge, /const mutating = \[[^\]]*'flatten_passes'/);
  const runtime = await readFile(new URL('../src/runtime.mjs', import.meta.url), 'utf8');
  assert.match(runtime, /refine_to_goal' \? 'Refine to the goal'/);
});

// Merged with luna-review: Luna's reading of the message (message-reading.ts) decides a named part and a negation when it
// answered; the keyword rules are the fallback.
test('the refine note follows Luna’s reading of the message when there is one, the keywords otherwise', () => {
  const read = (one_part, negation, element = null) => ({ element, one_part, negation, hand_painting: null, reference: null, elapsed_ms: 1, cost: 0, input_tokens: 0 });
  assert.match(refineToGoalNote({ text: 'Make that bit crisper', area: false, finished: true, reading: read(0.9, 0.1) }), /REFINE A PART/);
  assert.match(refineToGoalNote({ text: 'Refine the church', area: false, finished: true, reading: read(0.1, 0.1) }), /Call refine_to_goal/, 'Luna: the whole picture');
  assert.equal(refineToGoalNote({ text: 'Refine it', area: false, finished: true, reading: read(0.1, 0.95) }), '', 'Luna: negated');
  assert.match(refineToGoalNote({ text: 'Refine it', area: false, finished: true, reading: read(0.1, 0.1, { name: 'Domed church', confidence: 0.9 }) }), /REFINE A PART[^]*\(Domed church\)/);
  assert.match(refineToGoalNote({ text: 'Refine the church', area: false, finished: true, reading: { ...read(null, null), fallback: 'not_connected' } }), /REFINE A PART[^]*\(church\)/, 'no answer: the keywords');
});

// The artist, 2026-10-25 (New Moscow, "Refine: Moonlit sky and historic buildings" ran 7.5+ minutes): round 2 repainted
// regions whose first pass had done nothing ("14.6 → 14.6", "4.7 → 4.7"). A region a pass did not bring closer by at least
// NO_GAIN (and NO_GAIN_SHARE of its difference) is not refined again in that call.
test('a region a pass did not bring closer is not refined again; one that gained keeps its finer pass', async t => {
  assert.equal(NO_GAIN, 0.3); assert.equal(NO_GAIN_SHARE, 0.05);
  const gains = (key, detail) => ({ '0,0': 3, '512,0': 0, '1024,0': 0.5, '1536,0': 0.7 })[key] ?? (detail ? 3 : 0);
  const { tool, of } = await setup(t, { scores: { '0,0': 9, '512,0': 14.6, '1024,0': 14.6, '1536,0': 12 }, gains });
  const result = report(await tool.execute('r1', {}));
  assert.deepEqual(of('finish').map(c => [c.params.detail, c.squares.sort()]), [['fine', ['0,0', '1024,0', '1536,0', '512,0']], ['finer', ['0,0', '1536,0']]],
    '14.6 → 14.6 and 14.6 → 14.1 (under 5%) stop; 12.0 → 11.3 (over 5%) and 9 → 6 go on to finer');
  assert.deepEqual(result.rounds[0].regions.filter(r => r.stalled).map(r => r.rect[0]).sort((a, b) => a - b), [512, 1024]);
  assert.equal(result.stalled, 2);
  assert.equal(of('refine_map').length, 2, 'no third map: nothing is left to try');
});

// The artist, 2026-10-25: soft areas (sky, mist, water: the Finish's soft mask, low goal structure) get the fine pass at most.
test('a mostly soft region gets the fine pass only, never the finer one; the first map asks for the soft shares', async t => {
  assert.equal(SOFT_REGION, 0.5);
  const { tool, of } = await setup(t, { scores: { '0,0': 9, '512,0': 9 }, soft: { '0,0': 0.8, '512,0': 0.2 } });
  const result = report(await tool.execute('r1', {}));
  assert.deepEqual(of('finish').map(c => [c.params.detail, c.squares]), [['fine', ['0,0', '512,0']], ['finer', ['512,0']]]);
  assert.deepEqual(of('refine_map').map(c => !!c.params.soft), [true, false], 'the goal does not change: asked once');
  assert.equal(result.soft, 1);
  assert.equal(result.left_above, 1); assert.match(result.message, /as close as the strokes get/);
});

// The artist, 2026-10-25: one whole-picture refine, then each "Refine: <parts>" step a short touch-up of its area.
test('a touch-up: one round in a short budget, each region at the level after the one it had, nothing it has had every level of', async t => {
  assert.deepEqual(TOUCH_UP, { rounds: 1, budget_minutes: 3 });
  const s = await setup(t, { scores: { '0,0': 9, '512,0': 9, '1024,0': 12 } });
  const recorded = [];
  s.runtime.refineLimits = () => TOUCH_UP;
  // Grid squares (column,row): the whole-picture refine gave 0,0 its fine pass and 1,0 both.
  s.runtime.refineHistory = () => ({ side: 512, levels: { '0,0': 1, '1,0': 2 } });
  s.runtime.recordRefine = entry => recorded.push(entry);
  const result = report(await s.tool.execute('r1', {}));
  assert.deepEqual(s.of('finish').map(c => [c.params.detail, c.squares]), [['fine', ['1024,0']], ['finer', ['0,0']]]);
  assert.equal(result.rounds.length, 1, 'one round although 1024,0 is still above the bar');
  assert.deepEqual(recorded, [{ side: 512, whole: true, levels: { '0,0': 2, '1,0': 2, '2,0': 1 } }]);
  assert.equal(result.touch_up, true);
  const timed = await setup(t);
  let clock = 0;
  timed.runtime.refineClock = () => (clock += 200000);
  timed.runtime.refineLimits = () => TOUCH_UP;
  const byTime = report(await timed.tool.execute('r1', { budget_minutes: 10 }));
  assert.equal(timed.of('finish').length, 0); assert.match(byTime.ended, /time budget \(3 minutes\)/);
});

test('a touch-up with nothing left says so on the Now card; a refine records its levels for a later touch-up', async t => {
  const s = await setup(t, { scores: { '0,0': 9 } });
  s.runtime.refineLimits = () => TOUCH_UP;
  s.runtime.refineHistory = () => ({ side: 512, levels: { '0,0': 2 } });
  const result = report(await s.tool.execute('r1', {}));
  assert.equal(s.of('finish').length, 0);
  assert.equal(result.rounds.length, 0);
  assert.ok(s.events.some(e => e.type === 'action' && /^Refine: nothing more to refine here/.test(e.message)), s.events.map(e => e.message).join('\n'));
  assert.ok(s.events[0].type === 'status' && /^Refine: comparing/.test(s.events[0].message), 'the card shows the map is being made');
  // A history made on a canvas of another size (another grid) is not used.
  const other = await setup(t, { scores: { '0,0': 9 } });
  other.runtime.refineHistory = () => ({ side: 300, levels: { '0,0': 2 } });
  await other.tool.execute('r1', {});
  assert.deepEqual(other.of('finish').map(c => c.params.detail), ['fine', 'finer']);
});

// The artist, 2026-10-25: after one refine step the painting had 146 layers (a group of two a finish pass, of up to four an
// accents pass) and Krita reported 10.1 GiB. Each round ends with its finish passes flattened into one layer and its
// accents passes into another (flatten_passes, flatten_craft.py), in the move's stage, so the move's Undo hides them.
test('each round ends with one finish layer and one accents layer: its passes flattened, under the call', async t => {
  const scores = {}; for (let i = 0; i < 30; i++) scores[`${(i % 10) * 512},${Math.floor(i / 10) * 512}`] = 6;
  const { tool, of } = await setup(t, { scores });
  const result = report(await tool.execute('r1', {}));
  assert.deepEqual(of('flatten_passes').map(c => [c.params.name, c.params.pass_ids, c.id]), [
    ['Refine 1', ['r1/r1-1-fine', 'r1/r1-2-fine', 'r1/r1-3-fine'], 'r1/r1-flatten'],
    ['Refine 1 accents', ['r1/r1-accents-1'], 'r1/r1-accents-flatten']]);
  assert.equal(result.layers_removed, 3 * 4 - 2, 'the passes’ groups and layers gone, two layers made');
  const two = await setup(t);
  await two.tool.execute('r1', {});
  assert.deepEqual(two.of('flatten_passes').map(c => c.params.name), ['Refine 1', 'Refine 1 accents', 'Refine 2', 'Refine 2 accents']);
  // A finish that painted nothing has no pass to flatten; a refused flatten keeps the layers and the run goes on.
  const empty = await setup(t, { scores: { '0,0': 9 } });
  const native = empty.runtime.callNative;
  empty.runtime.callNative = async (op, params, id) => {
    if (op === 'finish') { const out = await native(op, params, id); return { ...out, layer_id: undefined, contribution_removed: true }; }
    if (op === 'flatten_passes') {
      await native(op, params, id);      // recorded, then refused
      throw Object.assign(new Error('Other layers lie between the passes: nothing was flattened.'), { code: 'validation_rejected' });
    }
    return native(op, params, id);
  };
  const kept = report(await empty.tool.execute('r1', {}));
  assert.deepEqual(empty.of('flatten_passes').map(c => c.params.pass_ids), [['r1/r1-accents-1'], ['r1/r2-accents-1']], 'only passes that exist');
  assert.match(kept.flatten_errors[0], /between the passes/);
});

test('an architectural step’s form strokes carry its grain: every finish of the refine gets it, none without it', async t => {
  const grain = [{ pattern: 'Texture: Bricks008', inside_shape: { mask_path: '/chat/.shapes/found-a.png', bounds: [0, 0, 600, 600] }, tile_px: 220, strength: 0.3 }];
  const s = await setup(t);
  s.runtime.refineGrain = async () => grain;
  await s.tool.execute('g1', {});
  assert.ok(s.of('finish').length > 0 && s.of('finish').every(c => JSON.stringify(c.params.grain) === JSON.stringify(grain)));
  const plain = await setup(t);
  plain.runtime.refineGrain = async () => { throw new Error('the model is down'); };
  await plain.tool.execute('g2', {});
  assert.ok(plain.of('finish').every(c => !('grain' in c.params)), 'a grain that cannot be had never stops the refine');
});

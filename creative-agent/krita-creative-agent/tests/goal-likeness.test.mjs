// Goal likeness (crisp-accents goal 8): how close the canvas is to the goal before and after a painting batch, on the
// plugin's blurred Lab grids, and the shipped Pi extension that undoes a batch that made it clearly less like the goal.
// Grids are made here in memory; a fake `pi` and a fake host (the studio's port); writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { measure, clearlyWorse, gridSize, decodeGrid, departureRequested, returnToReference, exemption, goalMapping, likenessLine, describeWorse,
  AREA_WORSE, WHOLE_WORSE, MIN_CELLS, GRID_SIDE, CELL_CLEARLY, NET_WORSE_SHARE } from '../src/goal-likeness.ts';
import goalLikeness, { UNDO_CAP } from '../extensions/goal-likeness.ts';

const W = 64, H = 48, frame = [0, 0, 6000, 4500];
/** A grid whose cell (x, y) is f(x, y) = [L, a, b]. */
const grid = f => { const lab = new Float32Array(W * H * 3); for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) lab.set(f(x, y), (y * W + x) * 3); return { width: W, height: H, lab }; };
// The goal: a cool night sky over a warm lit street.
const goal = grid((x, y) => y < 24 ? [30, 5, -25] : [55, 15, 35]);
// The underpainting: the goal plus a little noise (dabs that do not average out exactly).
const noise = (x, y) => ((x * 7 + y * 13) % 5) - 2;
const under = grid((x, y) => { const [l, a, b] = y < 24 ? [30, 5, -25] : [55, 15, 35]; return [l + noise(x, y), a + noise(y, x) / 2, b]; });
const paint = (base, inside, f) => grid((x, y) => { const i = (y * W + x) * 3, c = [base.lab[i], base.lab[i + 1], base.lab[i + 2]]; return inside(x, y) ? f(c, x, y) : c; });
const foreground = (x, y) => y >= 32 && x >= 2 && x < 35;             // a lower-left passage, 528 cells

test('the grid keeps the target’s proportions, GRID_SIDE cells on its long side', () => {
  assert.deepEqual(gridSize([0, 0, 6000, 4500]), [GRID_SIDE, 48]);
  assert.deepEqual(gridSize([0, 0, 1000, 3000]), [21, GRID_SIDE]);
  const lab = new Float32Array([1, 2, 3, 4, 5, 6]);
  const decoded = decodeGrid({ grid: [2, 1], lab_base64: Buffer.from(lab.buffer).toString('base64') });
  assert.deepEqual([decoded.width, decoded.height, [...decoded.lab]], [2, 1, [1, 2, 3, 4, 5, 6]]);
});

test('brushwork that follows the goal is not worse; texture alone is not either', () => {
  const refined = paint(under, foreground, (c, x, y) => { const i = (y * W + x) * 3; return [goal.lab[i], goal.lab[i + 1], goal.lab[i + 2]]; });
  const m = measure(goal, under, refined, frame);
  assert.ok(m.area.change < 0, 'closer to the goal where it painted');
  assert.equal(clearlyWorse(m), false);
  const textured = paint(under, foreground, ([l, a, b], x, y) => [l + ((x + y) % 2 ? 2 : -2), a + ((x * y) % 3) - 1, b + (x % 2 ? 1.5 : -1.5)]);
  const t = measure(goal, under, textured, frame);
  assert.ok(t.area.change < AREA_WORSE / 2, `texture: ${t.area.change}`);
  assert.equal(clearlyWorse(t), false);
});

test('a batch that darkens and greys a passage is clearly worse, and says what and where', () => {
  const after = paint(under, foreground, ([l, a, b]) => [l - 18, a * 0.3, b * 0.3]);
  const m = measure(goal, under, after, frame);
  assert.ok(m.area.change >= AREA_WORSE, `area +${m.area.change}`);
  assert.ok(m.area.cells >= MIN_CELLS);
  assert.ok(m.whole.after > m.whole.before);
  assert.equal(clearlyWorse(m), true);
  assert.ok(m.worse, 'where it got worse');
  const [x, y, w, h] = m.worse.rect;
  assert.ok(x < 600 && y >= 2900 && x + w <= 3800 && y + h <= 4500, `rect ${m.worse.rect}`);
  assert.equal(m.worse.where, 'lower left');
  assert.deepEqual(m.worse.what, ['darker', 'greyer']);
  assert.match(describeWorse(m), /lower left .*\[\d+,\d+,\d+,\d+\].*darker and greyer than the goal/);
  assert.match(describeWorse(m), /changed area .*ΔE \d+\.\d → \d+\.\d/);
  // Where the batch changed anything at this scale (goal-comparison.ts compares there when no pass has an area).
  const [cx, cy, cw, ch] = m.changed;
  assert.ok(cx < 300 && cy >= 2900 && cx + cw <= 3400 && cy + ch === 4500, `changed ${m.changed}`);
  assert.equal(measure(goal, under, under, frame).changed, null, 'nothing changed: no area');
});

// The real case (34deca0e move 2, 2 batches over the underpainting): its changed cells moved +1.1 on average, because
// some got better while a passage (the coat, the car) got much worse (90th percentile +7). The tail decides, net of the
// cells that got clearly better.
test('a passage made clearly worse is undone even when the batch\u2019s mean barely moves (the 34deca0e shape)', () => {
  const worsePassage = (x, y) => y >= 34 && y < 40 && x >= 5 && x < 15;          // 60 cells, about 2% of the canvas
  const betterPassage = (x, y) => y >= 34 && y < 40 && x >= 40 && x < 45;        // 30 cells
  const wide = (x, y) => y >= 30;                                                // a light pass over the lower third
  const start = paint(under, betterPassage, ([l, a, b]) => [l + 9, a, b]);       // that passage starts off the goal
  const after = paint(paint(paint(start, wide, ([l, a, b], x, y) => [l + ((x + y) % 2 ? 1.6 : -1.6), a, b]),
    worsePassage, ([l, a, b]) => [l - 11, a - 4, b - 6]), betterPassage, (c, x, y) => { const i = (y * W + x) * 3; return [goal.lab[i], goal.lab[i + 1], goal.lab[i + 2]]; });
  const m = measure(goal, start, after, frame);
  assert.ok(m.area.change < AREA_WORSE / 2, `mean +${m.area.change}: the old rule kept it`);
  assert.equal(m.area.worse_cells, 60); assert.equal(m.area.better_cells, 30);
  assert.ok(Number.isFinite(m.area.p90), 'the tail is reported');
  assert.ok(m.area.worse_cells - m.area.better_cells >= NET_WORSE_SHARE * W * H && CELL_CLEARLY === 6);
  assert.equal(clearlyWorse(m), true);
  assert.deepEqual(m.worse.rect.slice(0, 2), [469, 3188], 'where: the worse passage, not the light pass');
});

test('scattered cells made worse by normal brushwork stay kept, and so does a passage repaired as much as damaged', () => {
  const scattered = (x, y) => (x * 7 + y * 3) % 97 === 0;                         // about 32 cells over the canvas, isolated
  const few = measure(goal, under, paint(under, (x, y) => scattered(x, y) && y > 24 && x < 30, ([l, a, b]) => [l - 12, a, b]), frame);
  assert.ok(few.area.worse_cells > 0 && few.area.worse_cells < NET_WORSE_SHARE * W * H, `${few.area.worse_cells} cells`);
  assert.equal(clearlyWorse(few), false);
  const off = paint(under, (x, y) => y >= 34 && x >= 40 && x < 50, ([l, a, b]) => [l + 10, a, b]);
  const traded = paint(paint(off, (x, y) => y >= 34 && x >= 40 && x < 50, (c, x, y) => { const i = (y * W + x) * 3; return [goal.lab[i], goal.lab[i + 1], goal.lab[i + 2]]; }),
    (x, y) => y >= 34 && x >= 5 && x < 15, ([l, a, b]) => [l - 12, a, b]);
  const m = measure(goal, off, traded, frame);
  assert.equal(m.area.worse_cells, m.area.better_cells, 'as much repaired as damaged');
  assert.equal(clearlyWorse(m), false);
});

test('a small damaged patch is reported but too small to undo; a wide shift of the whole is undone', () => {
  const patch = paint(under, (x, y) => x >= 10 && x < 13 && y >= 40 && y < 43, ([l, a, b]) => [l + 40, a, b]);
  const small = measure(goal, under, patch, frame);
  assert.ok(small.area.change >= AREA_WORSE && small.area.cells < MIN_CELLS);
  assert.equal(clearlyWorse(small), false, '9 cells: about 0.3% of the canvas');
  const wide = measure(goal, under, grid((x, y) => { const i = (y * W + x) * 3; return [under.lab[i] + 3, under.lab[i + 1], under.lab[i + 2] - 2.5]; }), frame);
  assert.ok(wide.whole.change >= WHOLE_WORSE || wide.area.change >= AREA_WORSE);
  assert.equal(clearlyWorse(wide), true);
});

test('departures the artist asks for are found in their message; plain requests are not departures', () => {
  assert.ok(departureRequested('Make the sky warmer than the reference'));
  assert.ok(departureRequested('Paint the car red instead of the reference’s black'));
  assert.ok(departureRequested('Make the whole night cooler and more muted'));
  assert.ok(departureRequested('ignore the goal image for the sky, I want a sunset'));
  assert.equal(departureRequested('Paint the underpainting from the goal image'), null);
  assert.equal(departureRequested('Kept. Continue my request with the next move.'), null);
  assert.equal(departureRequested('Soften the foreground into readable masses'), null);
  // The lead's ruling: additions, recolouring, "make it ...", atmosphere, grade and style are departures too.
  for (const text of ['Add a cat on the bonnet', 'Paint the car deep red', 'make it moodier', 'Give it a foggy atmosphere',
    'Colour grade it teal and orange', 'In the style of Monet', 'Add some mist over the river'])
    assert.ok(departureRequested(text), text);
});

test('a message that points back to the reference ends a departure; one against it does not', () => {
  for (const text of ['Bring it closer to the reference', 'like the goal again please', 'Make it look like the original again', 'Back to the reference colours'])
    assert.ok(returnToReference(text), text);
  assert.equal(returnToReference('Make the sky warmer than the reference'), null);
  assert.equal(returnToReference('not like the reference: a sunset'), null);
  assert.equal(returnToReference('Soften the foreground'), null);
});

test('accents and colour transfers are measured, never undone; a departure the artist asked for too', () => {
  assert.equal(exemption('paint_accents', {}), 'accents');
  assert.equal(exemption('paint_batch', { actions: [{ tool: 'paint_accents', arguments: {} }, { tool: 'paint_accents', arguments: {} }] }), 'accents');
  assert.equal(exemption('paint_batch', { actions: [{ tool: 'paint_accents', arguments: {} }, { tool: 'paint_pass', arguments: {} }] }), null, 'mixed: the hand strokes count');
  assert.equal(exemption('paint_from_reference', {}), 'transfer');
  assert.equal(exemption('continue_reference_painting', {}), 'transfer');
  assert.equal(exemption('paint_pass', {}), null);
  assert.equal(exemption('paint_pass', {}, { departure: 'warmer than the reference' }), 'departure');
  assert.equal(exemption('set_layer', {}), 'layer_settings');
  assert.equal(exemption('paint_batch', { actions: [{ tool: 'paint_pass', arguments: {} }, { tool: 'set_layer', arguments: {} }] }), 'layer_settings',
    'a batch with a layer setting (opacity, blend mode) is measured only');
});

test('the goal maps onto the canvas as the whole transfer mapped it, else whole when the proportions match', () => {
  const canvas = { width: 6000, height: 4500 };
  const refs = [{ id: 'asset', role: 'asset', width: 1448, height: 1086 }, { id: 'goal', role: 'reference', purpose: 'composition', width: 1448, height: 1086 }];
  assert.deepEqual(goalMapping({ references: refs, transfers: [{ recipe: { reference_id: 'goal', source: [10, 0, 1400, 1086], target: [0, 0, 6000, 4500] } }], canvas }),
    { reference_id: 'goal', source: [10, 0, 1400, 1086], target: [0, 0, 6000, 4500], from: 'transfer' });
  assert.deepEqual(goalMapping({ references: refs, transfers: [], canvas }), { reference_id: 'goal', source: [0, 0, 1448, 1086], target: [0, 0, 6000, 4500], from: 'proportions' });
  assert.equal(goalMapping({ references: [{ id: 'goal', role: 'reference', width: 1000, height: 2000 }], transfers: [], canvas }), null, 'a figure for a landscape is not the picture');
  assert.equal(goalMapping({ references: [refs[0]], transfers: [], canvas }), null, 'no goal reference');
  assert.equal(goalMapping({ references: refs, transfers: [{ recipe: { reference_id: 'asset', source: [0, 0, 1448, 1086], target: [0, 0, 6000, 4500] } }], canvas }).reference_id, 'goal',
    'a transfer of an asset is not the goal');
});

test('a transfer made from the goal before it was sharpened maps onto the sharpened goal (the same picture, larger)', () => {
  const canvas = { width: 6000, height: 4500 };
  const sharpened = { id: 'goal', role: 'reference', purpose: 'composition', source: 'folder', width: 2309, height: 1732,
    sharpened: { from: { sha256: 'old', width: 1448, height: 1086 } } };
  const old = { reference_hash: 'old', recipe: { reference_id: 'goal', source: [10, 0, 1400, 1086], target: [0, 0, 6000, 4500] } };
  const mapped = goalMapping({ references: [sharpened], transfers: [old], canvas });
  assert.equal(mapped.from, 'transfer'); assert.deepEqual(mapped.target, [0, 0, 6000, 4500]);
  assert.deepEqual(mapped.source, [16, 0, 2232, 1732], 'its source rect in the sharpened goal\u2019s pixels');
  const fresh = { reference_hash: 'new', recipe: { reference_id: 'goal', source: [0, 0, 2309, 1732], target: [0, 0, 6000, 4500] } };
  assert.deepEqual(goalMapping({ references: [sharpened], transfers: [fresh], canvas }).source, [0, 0, 2309, 1732], 'a transfer of the sharpened goal as it is');
});

test('the move line: likeness before and after, and what was undone', () => {
  assert.equal(likenessLine({ batches: 3, before: 6.04, after: 5.71, undone: 0, kept_worse: 0 }), 'Goal likeness: ΔE 6.0 → 5.7 over 3 batches');
  assert.equal(likenessLine({ batches: 7, before: 5.9, after: 6.1, undone: 2, kept_worse: 1, last_undone: 'darker than the goal, lower left' }),
    'Goal likeness: ΔE 5.9 → 6.1 over 7 batches; undid 2 (darker than the goal, lower left); 1 less like the goal kept (accents, an asked-for change or free colours)');
  // Luna's goal comparison (luna-goal-reviewer goal 1) on the same line: how many batches it compared, how many were further.
  assert.equal(likenessLine({ batches: 3, before: 6, after: 5.5, undone: 1, kept_worse: 0, luna: { compared: 3, further: 1, closer: 1, undone: 1 } }),
    'Goal likeness: ΔE 6.0 → 5.5 over 3 batches; undid 1; Luna compared 3 with the goal: 1 further (undone), 1 closer');
  assert.equal(likenessLine({ batches: 2, before: 6, after: 5.5, undone: 0, kept_worse: 0, luna: { compared: 2, further: 0, closer: 0, undone: 0 } }),
    'Goal likeness: ΔE 6.0 → 5.5 over 2 batches; Luna compared 2 with the goal: none further');
});

// The extension, through a fake host.
const before = { type: 'image', data: 'YmVmb3Jl', mimeType: 'image/png' };
const undoneImage = { type: 'image', data: 'dW5kb25l', mimeType: 'image/png' };
const damaged = paint(under, foreground, ([l, a, b]) => [l - 18, a * 0.3, b * 0.3]);
function setup({ grids = { 'before.png': under, 'after.png': damaged }, active = 'protect', why = null, departure = null, undo = passes => ({ pass_ids: passes.map(p => p.id), image: undoneImage, image_path: 'undone.png', revision: 'r-undone' }), frameOf = { goal, target: frame, protect: true }, shared = new Map(), passes = id => [{ id: id + '-0', before_path: 'before.png', title: 'Foreground' }], luna = null, compare = null } = {}) {
  const handlers = {};
  const calls = { grid: [], undo: [], record: [], stop: [], compare: [], compared: [] };
  const host = {
    active: () => host.activeValue, activeValue: active,
    why: () => why,
    undos: { count: move => shared.get(move) ?? 0, add: move => shared.set(move, (shared.get(move) ?? 0) + 1) },
    move: () => host.moveValue, moveValue: 1,
    painting: name => name !== 'adjust_layer',
    frame: async () => frameOf,
    grid: async (path, target) => { calls.grid.push([path, target]); if (!grids[path]) throw new Error('no grid'); return grids[path]; },
    batch: id => passes(id),
    departure: () => departure,
    undo: async passes => { calls.undo.push(passes); return undo(passes); },
    record: entry => { calls.record.push(entry); },
    stop: message => { calls.stop.push(message); },
    ...(luna ? { lunaMode: () => host.lunaValue, lunaValue: luna,
      compare: async input => { calls.compare.push(input); return typeof compare === 'function' ? compare(input) : compare; },
      compared: entry => { calls.compared.push(entry); } } : {}),
  };
  goalLikeness(host)({ on: (name, handler) => { handlers[name] = handler; } });
  let n = 0;
  const result = (toolName = 'paint_batch', input = {}, details = { image_path: 'after.png' }) => handlers.tool_result({ type: 'tool_result', toolCallId: 'call' + ++n, toolName, input, isError: false,
    content: [{ type: 'text', text: '{"status":"ok"}' }, before], details: { revision: 'r' + n, ...details } }, {});
  return { host, calls, result };
}
const noteOf = changed => JSON.parse(changed.content.find(c => c.type === 'text' && c.text.includes('goal_likeness')).text).goal_likeness;

test('protect: a batch that makes the canvas clearly less like the goal is undone and the painter is told what and where', async () => {
  const { calls, result } = setup();
  const changed = await result();
  assert.ok(!changed.content.includes(before) && changed.content.includes(undoneImage));
  const note = noteOf(changed);
  assert.match(note.note, /^The host undid this batch: it made the canvas clearly less like the goal image/);
  assert.match(note.note, /lower left/); assert.match(note.note, /darker and greyer/);
  assert.equal(changed.details.image_path, 'undone.png'); assert.equal(changed.details.host_undone, 'goal_likeness');
  assert.deepEqual(calls.undo, [[{ id: 'call1-0', before_path: 'before.png', title: 'Foreground' }]]);
  assert.deepEqual(calls.grid.map(g => g[0]), ['before.png', 'after.png']);
  const [entry] = calls.record;
  assert.equal(entry.status, 'undone'); assert.equal(entry.move, 1); assert.equal(entry.tool, 'paint_batch');
  assert.ok(entry.area.change >= AREA_WORSE && entry.whole.after > entry.whole.before);
  assert.ok(Number.isFinite(entry.ms) && entry.ms >= 0);
});

test('a batch that keeps to the goal is recorded and its result unchanged', async () => {
  const { calls, result } = setup({ grids: { 'before.png': under, 'after.png': under } });
  assert.equal(await result(), undefined);
  assert.equal(calls.record[0].status, 'kept'); assert.equal(calls.undo.length, 0);
});

test('accents, a departure the artist asked for, and Measure only are measured but not undone', async () => {
  for (const [options, tool, input, exempt] of [[{}, 'paint_accents', {}, 'accents'], [{ departure: 'warmer than the reference' }, 'paint_pass', {}, 'departure'], [{ active: 'measure' }, 'paint_pass', {}, undefined]]) {
    const { calls, result } = setup(options);
    const changed = await result(tool, input);
    assert.equal(calls.undo.length, 0, tool);
    assert.equal(calls.record[0].status, 'worse_kept');
    assert.equal(calls.record[0].exempt, exempt);
    assert.match(noteOf(changed).note, /less like the goal image .*kept/);
  }
});

test('no goal, an error, a look or a layer setting: nothing measured, never a failed call', async () => {
  const none = setup({ frameOf: null });
  assert.equal(await none.result(), undefined); assert.equal(none.calls.record.length, 0);
  const missing = setup({ grids: {} });
  assert.equal(await missing.result(), undefined);
  assert.equal(missing.calls.record[0].status, 'fallback');
  const look = setup();
  assert.equal(await look.result('adjust_layer'), undefined);
  look.host.moveValue = null;
  assert.equal(await look.result(), undefined);
  look.host.activeValue = 'off';
  assert.equal(await look.result(), undefined);
  assert.equal(look.calls.record.length, 0);
});

test('measure only, with the reason: no kept whole transfer to protect, the studio\u2019s reason (Reference colours off, an unclassified message)', async () => {
  const unprotected = setup({ frameOf: { goal, target: frame, protect: false } });
  assert.match(noteOf(await unprotected.result()).note, /kept because this chat has no kept whole-picture transfer of the goal/);
  assert.equal(unprotected.calls.undo.length, 0); assert.equal(unprotected.calls.record[0].status, 'worse_kept');
  const unclassified = setup({ active: 'measure', why: 'the artist\u2019s message could not be classified' });
  assert.match(noteOf(await unclassified.result()).note, /kept because the artist\u2019s message could not be classified/);
  assert.equal(unclassified.calls.undo.length, 0);
  const layer = setup();
  await layer.result('paint_batch', { actions: [{ tool: 'paint_pass', arguments: {} }, { tool: 'set_layer', arguments: {} }] });
  assert.equal(layer.calls.undo.length, 0); assert.equal(layer.calls.record[0].exempt, 'layer_settings');
});

test('the undo cap is shared with Luna review: past it the batch stays, marked so Luna does not undo it either', async () => {
  const shared = new Map([[1, 1]]);                              // Luna already undid one batch in this move
  const { calls, result } = setup({ shared });
  await result();
  assert.equal(shared.get(1), 2, 'this undo counts in the same move counter');
  const capped = await result();
  assert.equal(calls.undo.length, 1);
  assert.equal(capped.details.host_undone, 'goal_likeness_cap');
  assert.match(noteOf(capped).note, /already undid 2 batches/);
  assert.equal(calls.stop.length, 1);
});

test('a partial undo says what could not be undone, as Luna does', async () => {
  const { calls, result } = setup({ passes: id => [{ id: id + '-0', before_path: 'before.png' }, { id: id + '-1', before_path: 'before.png' }],
    undo: () => ({ pass_ids: ['call1-1'], image_path: 'undone.png' }) });
  const note = noteOf(await result()).note;
  assert.match(note, /^The host undid part of this batch: .*call1-0 could not be undone; repair what remains\./);
  assert.equal(calls.record[0].status, 'undone'); assert.equal(calls.record[0].partial, true);
});

test('past UNDO_CAP undos in a move the batch stays and the move stops for the artist', async () => {
  const { calls, result } = setup();
  for (let i = 0; i < UNDO_CAP; i++) await result();
  const third = noteOf(await result());
  assert.equal(calls.undo.length, UNDO_CAP);
  assert.equal(calls.record.at(-1).status, 'worse_kept');
  assert.match(third.note, /already undid 2 batches/);
  assert.equal(calls.stop.length, 1);
});

// Full size in an area (finish-stage goal 7, the artist 2026-10-24: "yess we need both"): on New Moscow a fine Finish of the
// church moved the 64-cell grid 0.4 -> 0.2 while at full size it went from blobs to windows (colour ΔE 4.95 -> 2.45). In a
// move with an area the host also measures the area at full size before and after each batch (area_compare.py
// area_likeness); it is reported, never used to undo (the undo thresholds stay the grid's).
test('in an area the batch is also measured at full size there: recorded, told to the painter, never undone by it', async () => {
  const { host, calls, result } = setup({ grids: { 'before.png': under, 'after.png': under } });
  const asked = [];
  host.area = async id => { asked.push(id); return { rect: [1150, 750, 550, 750], before: { colour: 4.95, edges: 3.59 }, after: { colour: 2.45, edges: 2.44 } }; };
  const changed = await result('paint_finish');
  assert.deepEqual(asked, ['call1']);
  assert.deepEqual(calls.record[0].area_full, { rect: [1150, 750, 550, 750], before: { colour: 4.95, edges: 3.59 }, after: { colour: 2.45, edges: 2.44 } });
  assert.equal(calls.record[0].status, 'kept'); assert.equal(calls.undo.length, 0);
  assert.match(noteOf(changed).area_full_size.note, /the area at full size: colour ΔE 4\.95 → 2\.45, edges 3\.59 → 2\.44/);
  const failing = setup({ grids: { 'before.png': under, 'after.png': under } });
  failing.host.area = async () => { throw new Error('no area'); };
  assert.equal(await failing.result(), undefined, 'a failed full-size measure changes nothing');
  assert.equal(failing.calls.record[0].area_full, undefined);
});

test('the move line adds the area at full size', () => {
  assert.equal(likenessLine({ batches: 2, before: 0.4, after: 0.2, undone: 0, kept_worse: 0, area: { before: 4.95, after: 2.45 } }),
    'Goal likeness: ΔE 0.4 → 0.2 over 2 batches; the area at full size ΔE 5.0 → 2.5');
});

// Luna's goal comparison (luna-goal-reviewer goal 1): "further" with good confidence counts as clearly worse beside the ΔE
// rule, under the same exemptions and the same shared undo cap. Blobs in the right colours: the ΔE grid barely moves.
const further = { verdict: 'further', confidence: 0.9, crops: 1, per_crop: [{ verdict: 'further', confidence: 0.9 }], elapsed_ms: 1100, cost: 0.0006, input_tokens: 2500, area: [600, 3000, 2400, 1200] };
const same = { ...further, verdict: 'same', confidence: 0.8, per_crop: [{ verdict: 'same', confidence: 0.8 }] };
const blobbed = { 'before.png': under, 'after.png': under };      // the right colours: no change the grid can see

test('guide: a batch Luna finds further from the goal is undone even when ΔE is not worse, and the painter is told', async () => {
  const { calls, result } = setup({ grids: blobbed, luna: 'guide', compare: further });
  const changed = await result();
  assert.equal(calls.compare.length, 1);
  const [asked] = calls.compare;
  assert.deepEqual([asked.before, asked.after, asked.target], ['before.png', 'after.png', frame]);
  assert.ok(asked.measure && Array.isArray(asked.passes));
  assert.equal(calls.undo.length, 1);
  const note = noteOf(changed);
  assert.match(note.note, /^The host undid this batch: Luna compared the batch\u2019s area \[600,3000,2400,1200\] with the goal image: further from it than before \(confidence 0\.90\)/);
  assert.equal(changed.details.host_undone, 'goal_likeness');
  const [entry] = calls.record;
  assert.equal(entry.status, 'undone'); assert.equal(entry.by, 'luna'); assert.deepEqual(entry.luna, further);
});

test('guide: Luna\u2019s same or an unsure further keeps the batch, recorded with Luna\u2019s answer', async () => {
  for (const answer of [same, { ...further, confidence: 0.6 }, { ...further, verdict: null, fallback: 'timeout' }]) {
    const { calls, result } = setup({ grids: blobbed, luna: 'guide', compare: answer });
    assert.equal(await result(), undefined);
    assert.equal(calls.undo.length, 0); assert.equal(calls.record[0].status, 'kept'); assert.deepEqual(calls.record[0].luna, answer);
  }
});

test('Luna is not asked when ΔE already decides, when the batch is exempt or measured only, or when Luna is off', async () => {
  const worse = setup({ luna: 'guide', compare: further });                     // ΔE is clearly worse: no call needed
  await worse.result();
  assert.equal(worse.calls.compare.length, 0); assert.equal(worse.calls.record[0].by, 'delta_e');
  for (const options of [{ departure: 'warmer than the reference' }, { active: 'measure' }, { frameOf: { goal, target: frame, protect: false } }]) {
    const { calls, result } = setup({ grids: blobbed, luna: 'guide', compare: further, ...options });
    await result();
    assert.equal(calls.compare.length, 0, JSON.stringify(options)); assert.equal(calls.undo.length, 0);
  }
  const accents = setup({ grids: blobbed, luna: 'guide', compare: further });
  await accents.result('paint_accents');
  assert.equal(accents.calls.compare.length, 0, 'accents are exempt');
  const off = setup({ grids: blobbed, luna: 'off', compare: further });
  await off.result();
  assert.equal(off.calls.compare.length, 0); assert.equal(off.calls.undo.length, 0);
  const thrown = setup({ grids: blobbed, luna: 'guide', compare: () => { throw new Error('no crops'); } });
  assert.equal(await thrown.result(), undefined, 'a failed comparison never fails the painting call');
  assert.equal(thrown.calls.record[0].status, 'kept'); assert.equal(thrown.calls.record[0].luna.fallback, 'service_or_response_error');
});

test('evaluate: Luna\u2019s comparison is recorded after the result, never delaying the painter or undoing', async () => {
  let release; const pending = new Promise(resolve => { release = resolve; });
  const { calls, result } = setup({ grids: blobbed, luna: 'evaluate', compare: () => pending.then(() => further) });
  assert.equal(await result(), undefined);
  assert.equal(calls.record[0].status, 'kept'); assert.equal(calls.compared.length, 0);
  release(); await new Promise(resolve => setImmediate(resolve)); await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.compared.length, 1); assert.deepEqual(calls.compared[0].luna, further); assert.equal(calls.compared[0].move, 1);
  assert.equal(calls.undo.length, 0);
});

test('Luna\u2019s undo shares the move\u2019s cap: past it the batch stays and the move stops', async () => {
  const shared = new Map([[1, 2]]);
  const { calls, result } = setup({ grids: blobbed, luna: 'guide', compare: further, shared });
  const capped = await result();
  assert.equal(calls.undo.length, 0); assert.equal(capped.details.host_undone, 'goal_likeness_cap');
  assert.equal(calls.stop.length, 1); assert.equal(calls.record[0].by, 'luna');
});

test('a batch ΔE finds clearly better is never compared or undone by Luna (review, 2026-10-24)', async () => {
  const { calls, result } = setup({ grids: { 'before.png': damaged, 'after.png': under }, luna: 'guide', compare: further });
  assert.equal(await result(), undefined);
  assert.equal(calls.compare.length, 0); assert.equal(calls.undo.length, 0); assert.equal(calls.record[0].status, 'kept');
});

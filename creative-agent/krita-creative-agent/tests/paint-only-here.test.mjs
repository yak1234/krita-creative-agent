// Paint only here (openspec element-scoped-painting goals 1, 5, 6): the artist's selection as the one area the painter
// may paint in. The plugin enforces it (paint_only_here.py); here: the area the companion keeps, the painter's context,
// the dab filter of a scoped transfer, the transfer rules that let it through, and the ask-for-a-selection question.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm, readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { encodePlane, decodePlane } from '../src/shapes/png.ts';
import { adoptArea, applyPaintOnlyCommand, areaContext, areaLabel, loadAreaMask, scopePlan, insideTest, scopedShare,
  selectionTools, SELECT_OPTIONS, chipLine } from '../src/paint-only-here.ts';
import { referenceTools, transferRefusal } from '../src/reference-tool.mjs';

async function folder() { return mkdtemp(join(tmpdir(), 'paint-only-')); }
/** A w x h plane with the rectangle [x, y, rw, rh] at 255. */
function plane(w, h, [x, y, rw, rh]) {
  const data = new Uint8Array(w * h);
  for (let j = y; j < y + rh; j++) for (let i = x; i < x + rw; i++) data[j * w + i] = 255;
  return { width: w, height: h, data };
}
async function panelMask(directory, bounds, inner) {
  const path = join(directory, 'panel-mask.png');
  await writeFile(path, encodePlane(plane(bounds[2], bounds[3], inner)));
  return path;
}

test('the panel\'s selection becomes the chat\'s area: a mask in the chat folder for the plugin, its bounds and its share', async () => {
  const dir = await folder();
  try {
    const mask_path = await panelMask(dir, [10, 0, 40, 20], [0, 0, 40, 10]);   // the top half of the bounds
    const area = await adoptArea(dir, { action: 'set', mask_path, bounds: [10, 0, 40, 20], canvas: [100, 50], name: '  the sky ' });
    assert.equal(area.name, 'the sky');
    assert.deepEqual(area.bounds, [10, 0, 40, 20]);
    assert.ok(Math.abs(area.share - 400 / 5000) < 1e-9, 'the selected pixels, not the bounds');
    assert.match(area.mask_path, /\/\.shapes\/paint-only-[0-9a-f]{24}\.png$/, 'where the plugin reads shapes (shape_mask.py)');
    const written = decodePlane(await readFile(area.mask_path));
    assert.equal(written.width, 40); assert.equal(written.data[0], 255); assert.equal(written.data[40 * 15], 0);
    assert.equal(areaLabel(area), 'the sky');
    assert.equal(areaLabel({ ...area, name: null }), 'your selection');
    assert.equal(chipLine(area), 'Painting only inside your selection: the sky');
    assert.equal(chipLine({ ...area, name: null }), 'Painting only inside your selection');
    assert.ok((await readdir(dir)).includes('panel-mask.png'), 'a file outside the panel\u2019s pasted folder is never removed');
    const pasted = join(dir, 'creative-agent-pasted'), { mkdir } = await import('node:fs/promises'); await mkdir(pasted);
    const waiting = join(pasted, 'creative-paint-only-' + '0'.repeat(32) + '.png');
    await writeFile(waiting, encodePlane(plane(40, 20, [0, 0, 40, 10])));
    await adoptArea(dir, { action: 'set', mask_path: waiting, bounds: [10, 0, 40, 20], canvas: [100, 50] });
    assert.ok(!(await readdir(pasted)).length, 'the panel\u2019s waiting mask is removed once adopted');
    const empty = await panelMask(dir, [0, 0, 8, 8], [0, 0, 0, 0]);
    await assert.rejects(adoptArea(dir, { action: 'set', mask_path: empty, bounds: [0, 0, 8, 8], canvas: [100, 50] }), /empty/);
    await assert.rejects(adoptArea(dir, { action: 'set', mask_path, bounds: [90, 0, 40, 20], canvas: [100, 50] }), /canvas/);
    await assert.rejects(adoptArea(dir, { action: 'set', mask_path, bounds: [0, 0, 30, 20], canvas: [100, 50] }), /size/);
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('set, replace and clear: one area at a time, kept on the goal (so it survives resume), told in one line', async () => {
  const dir = await folder();
  try {
    const goal = {}, said = [];
    const host = { study: { directory: dir }, goal, persist: async () => {}, publish() {}, say: m => said.push(m) };
    const first = await panelMask(dir, [0, 0, 10, 10], [0, 0, 10, 10]);
    await applyPaintOnlyCommand(host, { action: 'set', mask_path: first, bounds: [0, 0, 10, 10], canvas: [20, 20] });
    assert.equal(goal.paint_only_here.name, null);
    const second = await panelMask(dir, [5, 5, 10, 10], [0, 0, 10, 10]);
    await applyPaintOnlyCommand(host, { action: 'set', mask_path: second, bounds: [5, 5, 10, 10], canvas: [20, 20], name: 'the moon' });
    assert.deepEqual(goal.paint_only_here.bounds, [5, 5, 10, 10], 'a new area replaces the old one');
    await applyPaintOnlyCommand(host, { action: 'clear' });
    assert.equal(goal.paint_only_here, null);
    assert.deepEqual(said, ['Painting only inside your selection', 'Painting only inside your selection: the moon', 'Painting everywhere again: the area was cleared.']);
    await applyPaintOnlyCommand(host, undefined);              // a prompt without an area changes nothing
    assert.equal(goal.paint_only_here, null);
    await assert.rejects(applyPaintOnlyCommand({ ...host, goal: null }, { action: 'clear' }), /chat/);
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('the painter\'s context carries the area: bounds, a short description, what the host does, and how to name it', () => {
  const area = { name: 'the sky', bounds: [0, 0, 600, 200], share: 0.21, mask_path: '/x.png', sha256: 'a', canvas: [600, 450] };
  const context = areaContext(area);
  assert.deepEqual(context.bounds, [0, 0, 600, 200]);
  assert.equal(context.name, 'the sky');
  assert.match(context.description, /21% of the canvas/);
  assert.match(context.rules, /Krita blocks every write outside it/);
  assert.match(context.rules, /paint_from_reference/);
  assert.match(context.reply, /^Painting only inside your selection: the sky/);
  assert.equal(areaContext(null), undefined);
});

test('a scoped transfer keeps only the dabs whose centre lies inside the area, deterministically', () => {
  const mask = { ...plane(20, 20, [0, 0, 10, 20]), bounds: [10, 10, 20, 20] };   // canvas x 10-19 of y 10-29 is inside
  const inside = insideTest(mask);
  assert.equal(inside(10, 10), true); assert.equal(inside(19.9, 29.5), true);
  assert.equal(inside(20, 15), false); assert.equal(inside(9, 15), false); assert.equal(inside(15, 31), false);
  const dab = (x0, y0, x1, y1) => ({ start: [x0, y0], segments: [[x0, y0, x1, y1, x1, y1]], size: 4 });
  const plan = { version: 2, total: 4, passes: [{ name: 'Coarse coverage', strokes: [dab(11, 12, 13, 12), dab(14, 20, 16, 20), dab(18, 15, 22, 15)] },
    { name: 'Fine detail', strokes: [dab(40, 40, 41, 41)] }] };
  const scoped = scopePlan(plan, mask);
  assert.deepEqual(scoped.passes.map(p => p.strokes.length), [2], 'the centre (20, 15) of the third dab is outside; an empty pass goes');
  assert.equal(scoped.total, 2);
  assert.deepEqual(scopePlan(plan, mask), scoped);
  assert.equal(plan.passes[0].strokes.length, 3, 'the plan itself is left alone');
});

test('a scoped transfer is measured by its area: the part of the area under the target', () => {
  const area = { bounds: [0, 0, 100, 50], share: 0.25 };
  assert.equal(scopedShare(area, [0, 0, 200, 200]), 0.25);
  assert.equal(scopedShare(area, [0, 0, 50, 50]), 0.125, 'half the area\'s bounds under the target');
  assert.equal(scopedShare(area, [150, 150, 10, 10]), 0);
});

test('goal 6: a transfer inside an untouched area passes the size caps and the late-plan rule; once that area has a transfer they hold', () => {
  const goal = { revision: 1, current_step: 0, brief: { steps: [{}, {}, {}, {}] } }, canvas = { width: 6000, height: 4500 };
  const whole = { name: 'Sky', reference_id: 'r', preset: 'p', source: [0, 0, 3000, 2250], target: [0, 0, 6000, 4500] };
  assert.match(transferRefusal(goal, whole, canvas, 0, { established: true }), /already exists/);
  assert.equal(transferRefusal(goal, whole, canvas, 0, { established: true, inside: { share: 0.3, painted: false } }), null);
  assert.equal(transferRefusal(goal, whole, canvas, 1, { inside: { share: 0.3, painted: false } }), null, 'after a whole transfer too');
  assert.match(transferRefusal(goal, whole, canvas, 1, { inside: { share: 0.3, painted: true } }), /at most 20%/, 'the same area again: a patch');
  assert.equal(transferRefusal(goal, whole, canvas, 1, { inside: { share: 0.1, painted: true } }), null, 'measured by the area');
  assert.equal(transferRefusal({ ...goal, current_step: 3 }, whole, canvas, 0, { inside: { share: 0.3, painted: false } }), null,
    'late in the plan (a folder plan\u2019s element steps come last) an untouched area may still be transferred');
  assert.match(transferRefusal({ ...goal, current_step: 3 }, whole, canvas, 1, { inside: { share: 0.3, painted: true } }), /off from step/,
    'once that area has a transfer, the late-plan rule holds');
});

// The reference tools with an area set on the goal (the studio's runtime.goal), on a small canvas.
const W = 40, H = 40;
const image = { width: 20, height: 20, data: Buffer.alloc(20 * 20 * 4) };
for (let i = 0; i < 400; i++) image.data.set([200, 120, 40, 255], i * 4);
async function transferHarness({ established = false, area = [0, 0, 40, 16] } = {}) {
  const directory = await folder(); const ref = join(directory, 'ref.png'); await writeFile(ref, 'fixture');
  let revision = 'r0', layer = 0; const calls = [], receipts = new Map();
  const mask_path = await panelMask(directory, area, [0, 0, area[2], area[3]]);
  const goal = { revision: 1, current_step: 0, brief: { steps: [{}, {}, {}, {}] } };
  goal.paint_only_here = await adoptArea(directory, { action: 'set', mask_path, bounds: area, canvas: [W, H], name: 'the sky' });
  const runtime = { config: { reference_batch: 4096 }, mode: 'agent', executionPhase: 'agent', goal,
    study: { directory, references: [{ id: 'ref', path: ref, role: 'reference' }], canvas: { mode: established ? 'current' : 'new' } }, emit() {},
    async callNative(op, p) {
      if (op === 'decode_reference') return { width: 20, height: 20, rgba_base64: image.data.toString('base64'), sha256: p.sha256 };
      if (op === 'observe') return { width: W, height: H, revision, painted_share: established ? 0.9 : 0 };
      if (op === 'operation_status') return { found: receipts.has(p.id), result: receipts.get(p.id) };
      throw new Error(op);
    } };
  const execute = async (id, args) => { calls.push({ id, args }); const result = { status: 'ok', revision: 'r' + calls.length, layer_id: args.continue_layer_id ?? 'layer-' + (++layer) }; revision = result.revision; receipts.set(id, result); return { details: result }; };
  const fill = async () => { revision = 'g'; return { details: { status: 'ok', revision: 'g', layer_id: 'ground' } }; };
  return { runtime, calls, tools: referenceTools(runtime, execute, fill), directory, close: () => rm(directory, { recursive: true, force: true }) };
}
const wholeRecipe = { name: 'Sky', reference_id: 'ref', preset: 'Basic', source: [0, 0, 20, 20], target: [0, 0, 40, 40], steps: [4, 2, 1] };
const centre = s => { const end = s.segments.at(-1); return [(s.start[0] + end[4]) / 2, (s.start[1] + end[5]) / 2]; };

test('goal 5: paint_from_reference inside the area paints the same transfer, only the dabs centred inside, and resumes identically', async () => {
  const h = await transferHarness({ established: true });
  try {
    const result = await h.tools[0].execute('sky', wholeRecipe);
    assert.equal(result.details.status, 'complete', 'an existing painting, the whole reference: let through inside the area');
    const strokes = h.calls.flatMap(c => c.args.strokes);
    assert.ok(strokes.length > 0);
    assert.ok(strokes.every(s => centre(s)[1] < 16), 'every dab centre lies inside the area');
    assert.match(JSON.stringify(result.details), /inside your selection: the sky/i, 'the painter is told where it painted');
    const [name] = (await readdir(join(h.directory, 'reference-paintings'))).filter(n => n.endsWith('.json'));
    const job = JSON.parse(await readFile(join(h.directory, 'reference-paintings', name)));
    assert.equal(job.inside.sha256, h.runtime.goal.paint_only_here.sha256, 'the job keeps its area');
    assert.equal(job.total, strokes.length);
    // Resume: the plan is rebuilt with the job's own area, whatever the chat's area is now.
    h.runtime.goal.paint_only_here = null;
    const again = await h.tools[1].execute('again', { job_id: job.id });
    assert.equal(again.details.status, 'complete');
    // A second whole transfer into the same (large) area is a patch now.
    const h2 = h.runtime; h2.goal.paint_only_here = { ...job.inside, share: 0.4, bounds: [0, 0, 40, 16], name: 'the sky' };
    await assert.rejects(h.tools[0].execute('sky-again', { ...wholeRecipe, seed: 9 }), /at most 20%/);
  } finally { await h.close(); }
});

test('goal 6: on a fresh canvas the scoped transfer may be the first one: no whole-picture refusal for a regional target', async () => {
  const h = await transferHarness();
  try {
    const regional = { ...wholeRecipe, source: [0, 0, 20, 8], target: [0, 0, 40, 16] }, area = h.runtime.goal.paint_only_here;
    h.runtime.goal.paint_only_here = null;
    await assert.rejects(h.tools[0].execute('unscoped', regional), /canvas.s proportions/, 'without an area the rule holds');
    h.runtime.goal.paint_only_here = area;
    const result = await h.tools[0].execute('first', regional);
    assert.equal(result.details.status, 'complete');
  } finally { await h.close(); }
});

test('a target that misses the area is refused before anything paints', async () => {
  const h = await transferHarness();
  try {
    await assert.rejects(h.tools[0].execute('miss', { ...wholeRecipe, source: [0, 10, 20, 10], target: [0, 20, 40, 20] }), /outside the area/);
    assert.equal(h.calls.length, 0);
  } finally { await h.close(); }
});

test('the painter asks for a selection: a question card in Agent, never a stall in Autopilot, nothing when an area is set', async () => {
  const events = [], goal = { status: 'active' };
  const host = { mode: 'agent', goal, emit: e => events.push(e), persist: async () => {}, publish() {}, yieldTurn() { host.yielded = true; } };
  const [tool] = selectionTools(host);
  assert.equal(tool.name, 'ask_for_selection');
  const asked = await tool.execute('q', { part: 'the sky' });
  assert.equal(goal.status, 'needs_input'); assert.ok(host.yielded);
  assert.equal(goal.question.question, 'Select the sky with the Freehand Selection tool (or the Magnetic one, which snaps to edges), then press Paint only here.');
  assert.deepEqual(goal.question.options, SELECT_OPTIONS);
  assert.deepEqual(SELECT_OPTIONS, ['Select with Freehand', 'Use my selection', 'Paint everywhere']);
  assert.deepEqual(goal.question.select_area, { part: 'the sky' });
  assert.equal(events.at(-1).type, 'question'); assert.deepEqual(events.at(-1).select_area, { part: 'the sky' });
  assert.match(asked.content[0].text, /Stop now/);

  const auto = { ...host, mode: 'autopilot', goal: { status: 'active' }, yielded: false };
  const said = []; auto.emit = e => said.push(e);
  const [autoTool] = selectionTools(auto);
  const went = await autoTool.execute('q2', { part: 'the hair' });
  assert.equal(auto.goal.question, undefined, 'Autopilot never stops for it'); assert.ok(!auto.yielded);
  assert.match(went.content[0].text, /Autopilot.*without an area/);
  assert.match(said.at(-1).message, /the hair/);

  const set = { ...host, goal: { status: 'active', paint_only_here: { name: 'the car', bounds: [0, 0, 1, 1] } }, yielded: false };
  const already = await selectionTools(set)[0].execute('q3', { part: 'the car' });
  assert.equal(set.goal.question, undefined);
  assert.match(already.content[0].text, /already.*Painting only inside your selection: the car/);
});

test('the area\'s mask is read back for scoping, refused when its file is gone', async () => {
  const dir = await folder();
  try {
    const mask_path = await panelMask(dir, [2, 3, 6, 4], [0, 0, 3, 4]);
    const area = await adoptArea(dir, { action: 'set', mask_path, bounds: [2, 3, 6, 4], canvas: [20, 20] });
    const mask = await loadAreaMask(area, dir);
    assert.deepEqual(mask.bounds, [2, 3, 6, 4]);
    assert.equal(insideTest(mask)(3, 4), true); assert.equal(insideTest(mask)(6, 4), false);
    await assert.rejects(loadAreaMask({ ...area, mask_path: mask_path }, dir), /chat folder/, 'only the chat folder\u2019s .shapes/paint-only-*.png');
    await assert.rejects(loadAreaMask(area, join(dir, 'other-chat')), /chat folder/);
    await rm(area.mask_path);
    await assert.rejects(loadAreaMask(area, dir), /no longer there/);
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('no card when the artist negates the part ("don\'t paint the sky"): the painter is told to leave it alone', async () => {
  const goal = { status: 'active' }, events = [];
  const host = { mode: 'agent', goal, emit: e => events.push(e), persist: async () => {}, publish() {}, yieldTurn() { host.yielded = true; },
    latestRequest: () => 'Brighten the towers, but don’t paint the sky.' };
  const answer = await selectionTools(host)[0].execute('q', { part: 'the sky' });
  assert.equal(goal.question, undefined); assert.ok(!host.yielded); assert.equal(events.length, 0);
  assert.match(answer.content[0].text, /said not to work on the sky/);
  host.latestRequest = () => 'Paint the sky, not the towers.';
  await selectionTools(host)[0].execute('q2', { part: 'the sky' });
  assert.ok(goal.question, 'named without a negation: asked');
});

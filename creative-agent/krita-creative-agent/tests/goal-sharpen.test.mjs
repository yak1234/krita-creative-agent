// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Sharpen goal (src/goal-sharpen.ts): when the folder's goal is enlarged more than 2x, the chat offers once per goal to
// sharpen it, shows the result side by side, and on approval the goal reference becomes the sharpened picture (same id
// and placement). Fakes stand in for the model download, the sharpening worker and the plugin; temporary folders only.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { goalSharpener, enlargement, estimateSeconds, ENLARGEMENT, OFFER_PIXELS, staleGoalSource, goalSourceFile, sharpenedContext, noMoreDetailNote, refineRequested, pictureGoal, MATCHED_DE } from '../src/goal-sharpen.ts';
import { UPSCALE_MODEL } from '../src/upscale/model.ts';
import { modelDirectory } from '../src/shapes/model.ts';
import { UpscaleError } from '../src/upscale/index.ts';

const sha = data => createHash('sha256').update(data).digest('hex');
const GOAL = Buffer.from('goal image bytes');

async function setup(t, { setting = 'ask', canvas = { width: 6000, height: 4500 }, goal = { width: 1448, height: 1086 }, modelReady = true, busy = false,
  platform = 'darwin', fail = null, slow = false, whole = false } = {}) {
  const root = await mkdtemp(join(tmpdir(), 'goal-sharpen-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const chat = join(root, 'chat'), data = join(root, 'data');
  await mkdir(chat, { recursive: true });
  const goalPath = join(chat, 'reference-goal.png');
  await writeFile(goalPath, GOAL);
  if (modelReady) {                                          // a verified model folder, as downloadModel leaves it
    const dir = modelDirectory(data, UPSCALE_MODEL);
    await mkdir(dir, { recursive: true });
    for (const file of UPSCALE_MODEL.files) await writeFile(join(dir, file.name), Buffer.alloc(0));
    await writeFile(join(dir, 'verified.json'), JSON.stringify({ revision: UPSCALE_MODEL.revision, files: Object.fromEntries(UPSCALE_MODEL.files.map(f => [f.name, f.sha256])) }));
  }
  const events = [], calls = [], state = { busy, setting, canvas, persisted: 0, changed: 0, published: 0 };
  const study = { id: 'chat-1', directory: chat, references: [
    { id: 'reference-goal', path: goalPath, source_path: '/artist/final_goal.png', width: goal.width, height: goal.height, mimeType: 'image/png', source: 'folder', role: 'reference',
      purpose: 'composition', name: 'final_goal.png', folder_name: 'final_goal.png', mass_map: { version: 2 } },
    { id: 'reference-element', path: join(chat, 'e.png'), width: 10, height: 10, source: 'folder', role: 'asset' }] };
  const host = {
    get study() { return state.study === undefined ? study : state.study; },
    canvas: () => state.canvas, setting: () => state.setting, busy: () => state.busy, dataDir: () => data, platform,
    emit: event => events.push(event), persist: async () => { state.persisted++; }, publish: () => { state.published++; }, goalChanged: () => { state.changed++; },
    async callNative(operation, params) {
      calls.push({ operation, params });
      if (operation === 'decode_reference') return { width: goal.width, height: goal.height, sha256: params.sha256, rgba_base64: Buffer.alloc(goal.width * goal.height * 4).toString('base64') };
      if (operation === 'jpeg_copy') return { kept: false, image_base64: Buffer.alloc(params.quality === 95 ? 6_000_000 : 3_000_000).toString('base64') };
      throw new Error('unexpected ' + operation);
    },
  };
  const jobs = [];
  const service = { async upscale(input, { onProgress, signal }) {
    jobs.push(input);
    if (fail) throw fail;
    for (let i = 1; i <= 4; i++) {
      if (signal?.aborted) throw new UpscaleError('cancelled', 'Sharpening was stopped.');
      onProgress(i, 4);
      if (slow) await new Promise(resolve => setTimeout(resolve, 30));
    }
    if (signal?.aborted) throw new UpscaleError('cancelled', 'Sharpening was stopped.');
    await writeFile(input.outputs.full, 'full'); await writeFile(input.outputs.compare, 'compare');
    if (!whole) await writeFile(input.outputs.reference, 'reference');
    const reference = whole ? { width: input.width * 4, height: input.height * 4, path: input.outputs.full, bytes: 4 } : { width: 2309, height: 1732, path: input.outputs.reference, bytes: 9 };
    return { ms: 12000, load_ms: 2000, peak_mb: 1070, provider: 'coreml', tiles: 154, ms_per_tile: 51,
      full: { width: input.width * 4, height: input.height * 4 }, reference, compare: { width: 968, height: 480, crop: [0, 0, 10] } };
  } };
  const downloads = [];
  const download = async ({ directory, onProgress }) => { downloads.push(directory); onProgress?.(50, 100); onProgress?.(100, 100);
    await mkdir(directory, { recursive: true });
    for (const file of UPSCALE_MODEL.files) await writeFile(join(directory, file.name), Buffer.alloc(0));
    await writeFile(join(directory, 'verified.json'), JSON.stringify({ revision: UPSCALE_MODEL.revision, files: Object.fromEntries(UPSCALE_MODEL.files.map(f => [f.name, f.sha256])) })); };
  // The fake model files are empty: a pinned spec with their real sizes would never be ready, so the tests pin size 0.
  const spec = { ...UPSCALE_MODEL, files: UPSCALE_MODEL.files.map(f => ({ ...f, size: 0 })) };
  const sharpener = goalSharpener(host, { spec, download, service });
  return { sharpener, events, calls, state, study, host, jobs, downloads, data, chat, goalPath };
}
const last = (events, type) => events.filter(e => e.type === type).at(-1);
const settle = async sharpener => { await sharpener.running(); };

test('enlargement and the time estimate', () => {
  assert.equal(enlargement({ width: 1448, height: 1086 }, { width: 6000, height: 4500 }).toFixed(1), '4.1');
  assert.equal(enlargement({ width: 3000, height: 2000 }, { width: 6000, height: 4500 }), 2.25);
  assert.equal(enlargement({ width: 10, height: 10 }, null), 0);
  assert.equal(ENLARGEMENT, 2);
  assert.equal(estimateSeconds(1448, 1086, { msPerTile: 51 }), 15);
  assert.ok(estimateSeconds(1448, 1086, { platform: 'linux' }) > 200, 'the CPU is far slower');
});

test('a goal enlarged more than 2x is offered once, with the size, the time and nothing uploaded', async t => {
  const h = await setup(t);
  await h.sharpener.check();
  const offer = last(h.events, 'goal_sharpen_offer');
  assert.match(offer.message, /^Your goal image is 4\.1x smaller than the canvas, so detail will blur\. Sharpen it 4x on this Mac \(about \d+ s, nothing uploaded\)\?$/);
  assert.deepEqual(offer.options, ['Sharpen', 'Use as is']);
  assert.equal(offer.download_mb, 0);
  await h.sharpener.check(); await h.sharpener.check();
  assert.equal(h.events.filter(e => e.type === 'goal_sharpen_offer').length, 1, 'once');
  assert.equal(h.jobs.length, 0, 'nothing runs before the artist says so');
  assert.equal(h.calls.length, 0, 'and Krita is not asked anything');
});

test('no offer for a goal 2x or less, without a canvas, with Never, or for a reference that is not the whole-picture goal', async t => {
  for (const options of [{ goal: { width: 3000, height: 2250 } }, { canvas: null }, { setting: 'never' }]) {
    const h = await setup(t, options);
    await h.sharpener.check();
    assert.equal(h.events.length, 0, JSON.stringify(options));
  }
  for (const change of [{ width: 1448, height: 600 }, { purpose: 'palette' }, { part_kind: 'crop' }, { role: 'asset' }]) {
    const h = await setup(t);
    Object.assign(h.study.references[0], { source: undefined, folder_name: undefined }, change);
    await h.sharpener.check();
    assert.equal(h.events.length, 0, 'not the picture: ' + JSON.stringify(change));
  }
});

// Fix 4 (finish-stage, approved 2026-10-24): an attached goal, not a folder's, gets the same card; tonight's case was
// final_goal.png (1448 x 1086) attached to a 6000 x 4500 canvas underpainted in an earlier chat.
test('an attached goal of the canvas’s proportions enlarged more than 2x is offered once, and Use sharpened swaps it', async t => {
  const h = await setup(t);
  Object.assign(h.study.references[0], { source: undefined, folder_name: undefined, purpose: 'general' });
  await h.sharpener.check(); await h.sharpener.check();
  const offer = last(h.events, 'goal_sharpen_offer');
  assert.equal(h.events.filter(e => e.type === 'goal_sharpen_offer').length, 1, 'once');
  assert.equal(offer.factor, 4.1);
  assert.equal(h.sharpener.status().state, 'offered', 'the state of the chat’s picture goal');
  await h.sharpener.answer({ id: offer.id, action: 'sharpen' });
  await settle(h.sharpener);
  await h.sharpener.answer({ id: last(h.events, 'goal_sharpen_review').id, action: 'use' });
  const goal = h.study.references[0];
  assert.deepEqual([goal.id, goal.width, goal.height, goal.sharpened.from.width], ['reference-goal', 2309, 1732, 1448]);
});

test('Sharpen: progress, then the side by side; Use sharpened makes the goal reference the sharpened picture, same id', async t => {
  const h = await setup(t);
  await h.sharpener.check();
  const offer = last(h.events, 'goal_sharpen_offer');
  await h.sharpener.answer({ id: offer.id, action: 'sharpen' });
  await settle(h.sharpener);
  const progress = h.events.filter(e => e.type === 'goal_sharpen_progress');
  assert.deepEqual(progress.filter(e => !e.finished).slice(-4).map(e => e.done / e.total), [0.25, 0.5, 0.75, 1]);
  assert.ok(progress.at(-1).finished);
  assert.equal(h.jobs[0].max_pixels, 26_000_000, 'the reference tools\u2019 pixels');
  assert.ok(h.jobs[0].outputs.full.startsWith(join(h.chat, 'goal-sharpen')), 'cached in the chat folder, never the artist’s');
  const review = last(h.events, 'goal_sharpen_review');
  assert.deepEqual(review.options, ['Use sharpened', 'Keep original']);
  assert.match(review.question, /5792 x 4344/); assert.match(review.question, /2309 x 1732/);
  assert.equal(review.image_path, h.jobs[0].outputs.compare);
  const goal = h.study.references[0], before = { ...goal };
  assert.equal(goal.path, before.path, 'nothing changes before the artist approves');
  await h.sharpener.answer({ id: review.id, action: 'use' });
  assert.equal(goal.id, 'reference-goal');
  assert.deepEqual([goal.width, goal.height, goal.path], [2309, 1732, h.jobs[0].outputs.reference]);
  assert.deepEqual(goal.sharpened.from, { path: before.path, width: 1448, height: 1086, sha256: sha(GOAL), mimeType: 'image/png' });
  assert.equal(goal.sharpened.full, h.jobs[0].outputs.full);
  assert.equal(goal.mass_map, undefined, 'the mass map is found again for the new pixels');
  assert.equal(goal.source_path, '/artist/final_goal.png', 'still the folder’s goal image');
  assert.equal(h.state.changed, 1);
  const saved = JSON.parse(await readFile(join(h.data, 'goal-sharpen.json'), 'utf8'));
  assert.equal(saved.choices[sha(GOAL)].choice, 'sharpened'); assert.equal(saved.ms_per_tile, 51);
  assert.deepEqual(h.sharpener.status().state, 'used');
  await h.sharpener.check();
  assert.equal(h.jobs.length, 1, 'a sharpened goal is not offered again');
});

test('Use as is and Keep original are remembered per goal content: a new chat of the same goal asks nothing', async t => {
  const h = await setup(t);
  await h.sharpener.check();
  await h.sharpener.answer({ id: last(h.events, 'goal_sharpen_offer').id, action: 'original' });
  const again = goalSharpener(h.host, { service: { upscale: async () => assert.fail('not run') } });
  h.study.goal_sharpen = undefined;                                 // a new chat
  await again.check();
  assert.equal(h.events.filter(e => e.type === 'goal_sharpen_offer').length, 1);
  const other = await setup(t);
  await other.sharpener.check();
  await other.sharpener.answer({ id: last(other.events, 'goal_sharpen_offer').id, action: 'sharpen' }); await settle(other.sharpener);
  await other.sharpener.answer({ id: last(other.events, 'goal_sharpen_review').id, action: 'keep' });
  assert.equal(other.study.references[0].width, 1448, 'kept');
  assert.equal(JSON.parse(await readFile(join(other.data, 'goal-sharpen.json'), 'utf8')).choices[sha(GOAL)].choice, 'original');
});

test('a goal sharpened before is sharpened again by itself in a new chat; Always does it without asking', async t => {
  const h = await setup(t, { setting: 'always' });
  await h.sharpener.check(); await settle(h.sharpener);
  assert.equal(h.events.filter(e => e.type === 'goal_sharpen_offer' || e.type === 'goal_sharpen_review').length, 0);
  assert.equal(h.study.references[0].width, 2309);
  const next = await setup(t);
  await writeFile(join(next.data, 'goal-sharpen.json'), JSON.stringify({ version: 1, choices: { [sha(GOAL)]: { choice: 'sharpened', at: 'x' } } }));
  await next.sharpener.check(); await settle(next.sharpener);
  assert.equal(next.study.references[0].width, 2309);
  assert.match(last(next.events, 'action').message, /The goal image is now the sharpened one/);
});

test('the first time downloads the model, with its size on the card and progress on the Now card', async t => {
  const h = await setup(t, { modelReady: false });
  await h.sharpener.check();
  const offer = last(h.events, 'goal_sharpen_offer');
  assert.equal(offer.download_mb, 62);
  assert.match(offer.message, /first time downloads the sharpening model, Real-ESRGAN x4plus \(BSD-3-Clause, 62 MB\)/);
  await h.sharpener.answer({ id: offer.id, action: 'sharpen' }); await settle(h.sharpener);
  assert.equal(h.downloads.length, 1);
  assert.ok(h.events.some(e => e.type === 'goal_sharpen_progress' && /Downloading the sharpening model: 50%/.test(e.message)));
  assert.ok(last(h.events, 'goal_sharpen_review'));
});

test('a sharpened goal the reference tools read whole becomes the reference at full size (64 MB, 26 million pixels)', async t => {
  const h = await setup(t, { whole: true });
  await h.sharpener.check();
  await h.sharpener.answer({ id: last(h.events, 'goal_sharpen_offer').id, action: 'sharpen' }); await settle(h.sharpener);
  assert.deepEqual([h.jobs[0].max_pixels, h.jobs[0].max_bytes], [26_000_000, 64 * 1024 * 1024]);
  const review = last(h.events, 'goal_sharpen_review');
  assert.match(review.question, /The painter reads it at full size\./);
  await h.sharpener.answer({ id: review.id, action: 'use' });
  const goal = h.study.references[0];
  assert.deepEqual([goal.width, goal.height, goal.path], [5792, 4344, h.jobs[0].outputs.full], 'the 4x file itself, not a copy');
  assert.equal(goal.sharpened.scale, 4);
  assert.equal(h.calls.filter(c => c.operation === 'jpeg_copy').length, 0, 'no JPEG on Krita\u2019s side');
});

test('a failure keeps the original with a message; a Stop keeps it and offers the card again', async t => {
  const h = await setup(t, { fail: new UpscaleError('out_of_memory', 'Sharpening ran out of memory. Close some apps and try again.') });
  await h.sharpener.check();
  await h.sharpener.answer({ id: last(h.events, 'goal_sharpen_offer').id, action: 'sharpen' }); await settle(h.sharpener);
  assert.equal(h.study.references[0].width, 1448);
  assert.match(last(h.events, 'action').message, /ran out of memory\. Close some apps and try again\. The original goal image is used\./);
  assert.equal(h.sharpener.status().state, 'failed');

  const s = await setup(t, { slow: true });
  await s.sharpener.check();
  const first = last(s.events, 'goal_sharpen_offer');
  await s.sharpener.answer({ id: first.id, action: 'sharpen' });
  await new Promise(resolve => setTimeout(resolve, 40));
  await s.sharpener.answer({ action: 'cancel' }); await settle(s.sharpener);
  assert.equal(s.study.references[0].width, 1448);
  assert.match(last(s.events, 'action').message, /Sharpening stopped: the original goal image is used/);
  const offered = last(s.events, 'goal_sharpen_offer');
  assert.notEqual(offered.id, first.id, 'a fresh card to try again');
  await s.sharpener.answer({ id: first.id, action: 'sharpen' });
  assert.equal(s.jobs.length, 1, 'the old card’s button does nothing');
});

test('a chat closed while it sharpens shows nothing and changes nothing', async t => {
  const h = await setup(t, { slow: true });
  await h.sharpener.check();
  await h.sharpener.answer({ id: last(h.events, 'goal_sharpen_offer').id, action: 'sharpen' });
  h.state.study = null;
  await settle(h.sharpener);
  assert.equal(h.events.filter(e => e.type === 'goal_sharpen_review').length, 0);
  assert.equal(h.study.references[0].width, 1448);
});

test('approved while a move paints: the swap waits for the run to end', async t => {
  const h = await setup(t);
  await h.sharpener.check();
  await h.sharpener.answer({ id: last(h.events, 'goal_sharpen_offer').id, action: 'sharpen' }); await settle(h.sharpener);
  h.state.busy = true;
  await h.sharpener.answer({ id: last(h.events, 'goal_sharpen_review').id, action: 'use' });
  assert.equal(h.study.references[0].width, 1448);
  assert.match(last(h.events, 'action').message, /as soon as this move ends/);
  h.state.busy = false;
  await h.sharpener.settle();
  assert.equal(h.study.references[0].width, 2309);
});

// Review fixes (2026-10-24).
test('changing the goal while it sharpens or waits for review: nothing sharpened lands on the new goal', async t => {
  const h = await setup(t, { slow: true });
  await h.sharpener.check();
  await h.sharpener.answer({ id: last(h.events, 'goal_sharpen_offer').id, action: 'sharpen' });
  h.sharpener.goalChanged();                                      // the goal picker, mid-run
  await settle(h.sharpener);
  assert.equal(h.events.filter(e => e.type === 'goal_sharpen_review').length, 0);
  assert.equal(h.study.references[0].width, 1448);
  assert.ok(!h.events.some(e => e.type === 'action' && /Sharpening stopped/.test(e.message)), 'no card for the old goal');

  const r = await setup(t);
  await r.sharpener.check();
  await r.sharpener.answer({ id: last(r.events, 'goal_sharpen_offer').id, action: 'sharpen' }); await settle(r.sharpener);
  const review = last(r.events, 'goal_sharpen_review');
  const other = join(r.chat, 'reference-other.png'); await writeFile(other, 'another goal');
  r.study.references[0].path = other;                             // the goal changed under the waiting card
  await r.sharpener.answer({ id: review.id, action: 'use' });
  assert.equal(r.study.references[0].width, 1448); assert.equal(r.study.references[0].path, other);
  assert.match(last(r.events, 'action').message, /goal image changed since it was sharpened/);
  const same = await setup(t);
  await same.sharpener.check();
  await same.sharpener.answer({ id: last(same.events, 'goal_sharpen_offer').id, action: 'sharpen' }); await settle(same.sharpener);
  await writeFile(same.goalPath, 'edited in place');                // same path, other pixels
  await same.sharpener.answer({ id: last(same.events, 'goal_sharpen_review').id, action: 'use' });
  assert.equal(same.study.references[0].width, 1448);
});

test('a goal of more pixels than OFFER_PIXELS is not offered, however small against the canvas', async t => {
  assert.equal(OFFER_PIXELS, 2_000_000);
  const h = await setup(t, { goal: { width: 1700, height: 1300 }, canvas: { width: 12000, height: 9000 } });
  await h.sharpener.check();
  assert.equal(h.events.length, 0);
});

test('stale source rects: the old whole picture, or a rect an old transfer used, scale to the sharpened pixels', () => {
  const ref = { id: 'goal', width: 5792, height: 4344, sharpened: { from: { sha256: 'old', width: 1448, height: 1086, path: '/c/old.png' } } };
  assert.deepEqual(staleGoalSource([0, 0, 1448, 1086], ref, []), [0, 0, 5792, 4344]);
  const earlier = [{ reference_hash: 'old', recipe: { reference_id: 'goal', source: [100, 50, 300, 200] } }];
  assert.deepEqual(staleGoalSource([100, 50, 300, 200], ref, earlier), [400, 200, 1200, 800]);
  assert.equal(staleGoalSource([100, 50, 300, 200], ref, []), null, 'a new rect is taken as written');
  assert.equal(staleGoalSource([0, 0, 1448, 1086], { ...ref, sharpened: undefined }, []), null);
  assert.equal(goalSourceFile({ path: '/c/new.png', sharpened: ref.sharpened }, 'old'), '/c/old.png', 'an old job resumes on its own picture');
  assert.equal(goalSourceFile({ path: '/c/new.png', sharpened: ref.sharpened }, 'new'), '/c/new.png');
  const told = sharpenedContext(ref);
  assert.deepEqual([told.width, told.height, told.was, told.scale], [5792, 4344, [1448, 1086], 4]);
  assert.match(told.note, /now 5792 x 4344 \(they were 1448 x 1086\).*multiply any earlier rect by 4/);
  assert.equal(sharpenedContext({ width: 10, height: 10 }), undefined);
});

// Rehearsal fix (2026-10-24, live in Toska): Start painting ran the underpainting from the small goal with no card. The
// underpainting waits for the offer: gate() before the move that transfers the goal.
test('gate: Agent mode waits for the artist’s answer before the underpainting; the answer settles it', async t => {
  const h = await setup(t);
  const settled = [];
  h.host.settled = () => settled.push(h.sharpener.status()?.state);
  assert.equal(await h.sharpener.gate({ wait: true }), 'wait', 'the card first: nothing paints');
  const offer = last(h.events, 'goal_sharpen_offer');
  assert.ok(offer, 'the card is shown by the gate itself');
  assert.equal(await h.sharpener.gate({ wait: true }), 'wait', 'still waiting, the card is not shown twice');
  assert.equal(h.events.filter(e => e.type === 'goal_sharpen_offer').length, 1);
  await h.sharpener.answer({ id: offer.id, action: 'sharpen' });
  assert.equal(await h.sharpener.gate({ wait: true }), 'wait', 'while it sharpens');
  await settle(h.sharpener);
  assert.equal(await h.sharpener.gate({ wait: true }), 'wait', 'the side by side waits for Use sharpened or Keep original');
  assert.deepEqual(settled, []);
  await h.sharpener.answer({ id: last(h.events, 'goal_sharpen_review').id, action: 'use' });
  assert.deepEqual(settled, ['used'], 'the answer lets the underpainting start');
  assert.equal(await h.sharpener.gate({ wait: true }), 'paint');
  assert.equal(h.study.references[0].width, 2309, 'from the sharpened goal');
});

test('gate: Use as is, a failure, and a goal that needs no sharpening paint at once or after the answer', async t => {
  const h = await setup(t);
  const settled = [];
  h.host.settled = () => settled.push('settled');
  assert.equal(await h.sharpener.gate({ wait: true }), 'wait');
  await h.sharpener.answer({ id: last(h.events, 'goal_sharpen_offer').id, action: 'original' });
  assert.deepEqual(settled, ['settled']);
  assert.equal(await h.sharpener.gate({ wait: true }), 'paint');

  const f = await setup(t, { fail: new UpscaleError('failed', 'It broke') });
  let failed = 0; f.host.settled = () => failed++;
  await f.sharpener.gate({ wait: true });
  await f.sharpener.answer({ id: last(f.events, 'goal_sharpen_offer').id, action: 'sharpen' }); await settle(f.sharpener);
  assert.equal(failed, 1, 'a failure keeps the original and lets the move start');
  assert.equal(await f.sharpener.gate({ wait: true }), 'paint');

  for (const options of [{ goal: { width: 3000, height: 2250 } }, { setting: 'never' }, { canvas: null }]) {
    const n = await setup(t, options);
    assert.equal(await n.sharpener.gate({ wait: true }), 'paint', JSON.stringify(options));
  }
});

test('gate: Autopilot follows the setting: Ask shows the card and paints; Always sharpens first and paints from it', async t => {
  const ask = await setup(t, { busy: true });
  assert.equal(await ask.sharpener.gate({ wait: false }), 'paint');
  assert.ok(last(ask.events, 'goal_sharpen_offer'), 'the card is there for later');
  assert.equal(ask.jobs.length, 0);

  const always = await setup(t, { setting: 'always', busy: true });  // inside the run: busy, but nothing paints yet
  assert.equal(await always.sharpener.gate({ wait: false }), 'paint');
  assert.equal(always.study.references[0].width, 2309, 'the underpainting reads the sharpened goal');
  const agent = await setup(t, { setting: 'always', busy: true });
  assert.equal(await agent.sharpener.gate({ wait: true }), 'paint', 'Always in Agent mode: sharpened without asking, then painted');
  assert.equal(agent.study.references[0].width, 2309);
});

// Fix 5 (finish-stage, approved 2026-10-24): chat "Creative painting 22" spent 20 passes inventing strokes on a canvas that
// already matched a 4.1x enlarged goal (ΔE 1.7).
test('no more detail: a refine request on a canvas matching an enlarged, unsharpened goal gets the note; anything else none', () => {
  const asked = { text: 'Refine the left buildings, more detail please.', distance: 1.7, enlargement: 4.14, sharpened: false, offer: true };
  assert.match(noMoreDetailNote(asked), /^GOAL RESOLUTION: the canvas already matches the goal image at the goal’s own resolution \(goal likeness ΔE 1\.7\)[^]*4\.1x larger[^]*offer to sharpen/);
  // Review finding: with Never, or after the artist kept the original, the painter only says the goal has no more detail.
  const kept = noMoreDetailNote({ ...asked, offer: false });
  assert.match(kept, /no more detail to give here/); assert.doesNotMatch(kept, /sharpen/i);
  for (const change of [{ sharpened: true }, { enlargement: 2 }, { distance: MATCHED_DE + 0.1 }, { distance: null }, { text: 'Add a red car on the bridge.' }])
    assert.equal(noMoreDetailNote({ ...asked, ...change }), null, JSON.stringify(change));
  for (const said of ['Make the towers sharper', 'crisper windows', 'clean up the bridge', 'refine the sky', 'add detail to the dome'])
    assert.ok(refineRequested(said), said);
  for (const said of ['Paint a dog', 'finish the sky', 'Finished? define the plan'])
    assert.equal(refineRequested(said), null, said);
});

test('offerable: not with Never, not after the artist kept the original (here or in an earlier chat), not once sharpened', async t => {
  const h = await setup(t);
  const goal = h.study.references[0];
  assert.equal(await h.sharpener.offerable(goal), true);
  h.state.setting = 'never'; assert.equal(await h.sharpener.offerable(goal), false); h.state.setting = 'ask';
  await h.sharpener.check();
  await h.sharpener.answer({ id: last(h.events, 'goal_sharpen_offer').id, action: 'original' });
  assert.equal(await h.sharpener.offerable(goal), false, 'Use as is');
  const again = await setup(t);
  await writeFile(join(again.data, 'goal-sharpen.json'), JSON.stringify({ version: 1, choices: { [sha(GOAL)]: { choice: 'original', at: 'then' } } }));
  assert.equal(await again.sharpener.offerable(again.study.references[0]), false, 'remembered from an earlier chat');
  assert.equal(await again.sharpener.offerable({ ...again.study.references[0], sharpened: {} }), false);
});

test('the picture goal: the folder\u2019s first, else the first attached goal reference of the canvas\u2019s proportions', () => {
  const canvas = { width: 6000, height: 4500 };
  const palette = { id: 'p', path: 'p', role: 'reference', purpose: 'palette', width: 1448, height: 1086 };
  const own = { id: 'g', path: 'g', role: 'reference', purpose: 'general', width: 1448, height: 1086 };
  const folder = { id: 'f', path: 'f', role: 'reference', source: 'folder', width: 100, height: 300 };
  assert.equal(pictureGoal([palette, own], canvas)?.id, 'g');
  assert.equal(pictureGoal([palette, own, folder], canvas)?.id, 'f');
  assert.equal(pictureGoal([{ ...own, width: 1000 }], canvas), null, 'other proportions');
  assert.equal(pictureGoal([own], null), null, 'no canvas yet');
});

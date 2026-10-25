// Luna review: the shipped Pi extension that reviews each painting batch of an Agent move. A fake `pi` and a fake
// host (the studio's port); writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import lunaReview, { UNDO_CAP } from '../extensions/luna-review.ts';

const moon = { type: 'covered_feature', feature: 'Moon', label: 'Moon covered', probability: 0.9, location: 'top_right' };
const before = { type: 'image', data: 'YmVmb3Jl', mimeType: 'image/png' };
const undoneImage = { type: 'image', data: 'dW5kb25l', mimeType: 'image/png' };

function setup({ mode = 'guide', move = 1, reviews = [], undo = passes => ({ pass_ids: passes.map(p => p.id), image: undoneImage, image_path: 'undone.png', revision: 'r-undone' }),
  painting = name => name !== 'adjust_layer', batch = id => [{ id: id + '-0', before_path: 'before.png', title: 'Clouds' }] } = {}) {
  const handlers = {};
  const calls = { review: [], undo: [], record: [], stop: [] };
  const host = {
    mode: () => host.modeValue, modeValue: mode,
    move: () => host.moveValue, moveValue: move,
    painting, batch,
    features: async () => ['Moon'],
    review: async input => { calls.review.push(input); const next = reviews.shift(); return typeof next === 'function' ? next() : next ?? { findings: [] }; },
    undo: async passes => { calls.undo.push(passes); return undo(passes); },
    record: verdict => { calls.record.push(verdict); },
    stop: message => { calls.stop.push(message); },
  };
  lunaReview(host)({ on: (name, handler) => { handlers[name] = handler; } });
  let n = 0;
  const result = (toolName = 'paint_batch', extra = {}) => handlers.tool_result({ type: 'tool_result', toolCallId: 'call' + ++n, toolName, input: {}, isError: false,
    content: [{ type: 'text', text: '{"status":"ok"}' }, before], details: { image_path: 'after.png', revision: 'r' + n }, ...extra }, {});
  return { host, calls, result };
}
const reviewOf = changed => JSON.parse(changed.content.find(c => c.type === 'text' && c.text.includes('luna_review')).text).luna_review;

test('guide: a covered moon is undone and the painter told what was lost', async () => {
  const { calls, result } = setup({ reviews: [{ findings: [moon] }] });
  const changed = await result();
  assert.ok(!changed.content.includes(before), 'the old canvas image is dropped');
  assert.ok(changed.content.includes(undoneImage));
  const review = reviewOf(changed);
  assert.match(review.note, /^Luna undid this batch: Moon covered \(top_right\)\./);
  assert.match(review.note, /propose_protection/);
  assert.deepEqual(review.undone_pass_ids, ['call1-0']);
  assert.deepEqual(calls.undo, [[{ id: 'call1-0', before_path: 'before.png', title: 'Clouds' }]]);
  assert.deepEqual(calls.review[0], { before: 'before.png', after: 'after.png', features: ['Moon'] });
  assert.equal(calls.record[0].status, 'undone'); assert.equal(calls.record[0].move, 1);
  assert.equal(changed.details.image_path, 'undone.png'); assert.equal(changed.details.revision, 'r-undone');
});

test('guide: a clean batch is recorded kept and the result is unchanged', async () => {
  const { calls, result } = setup();
  assert.equal(await result(), undefined);
  assert.equal(calls.record[0].status, 'kept');
  assert.equal(calls.undo.length, 0);
});

test('the third finding in one move is not undone and stops the move', async () => {
  const { calls, result } = setup({ reviews: [{ findings: [moon] }, { findings: [moon] }, { findings: [moon] }] });
  await result(); await result();
  const third = reviewOf(await result());
  assert.equal(UNDO_CAP, 2);
  assert.equal(calls.undo.length, 2);
  assert.equal(calls.record[2].status, 'warned');
  assert.match(third.note, /already undid 2 batches in this move, so this one stays/);
  assert.equal(calls.stop.length, 1);
  assert.match(calls.stop[0], /Luna undid 2 batches/);
});

test('the cap is per move', async () => {
  const { host, calls, result } = setup({ reviews: [{ findings: [moon] }, { findings: [moon] }, { findings: [moon] }] });
  await result(); await result();
  host.moveValue = 2;
  await result();
  assert.equal(calls.undo.length, 3);
  assert.equal(calls.record[2].status, 'undone');
});

test('a failed undo is warned and does not count toward the cap', async () => {
  let fail = true;
  const { calls, result } = setup({ reviews: [{ findings: [moon] }, { findings: [moon] }, { findings: [moon] }],
    undo: passes => { if (fail) { fail = false; return null; } return { pass_ids: passes.map(p => p.id) }; } });
  const first = reviewOf(await result());
  assert.match(first.note, /could not be undone/);
  assert.equal(calls.record[0].status, 'warned');
  await result(); await result();
  assert.deepEqual(calls.record.map(r => r.status), ['warned', 'undone', 'undone']);
  assert.equal(calls.stop.length, 0);
});

test('evaluate records without delaying the result', async () => {
  let release;
  const { calls, result } = setup({ mode: 'evaluate', reviews: [() => new Promise(resolve => { release = () => resolve({ findings: [moon] }); })] });
  assert.equal(await result(), undefined);
  assert.equal(calls.record.length, 0, 'the result returned before the review resolved');
  await new Promise(resolve => setImmediate(resolve));
  release();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.record.length, 1);
  assert.equal(calls.record[0].status, 'warned');
  assert.equal(calls.undo.length, 0);
});

test('off, no move, layer settings, errors and empty batches are skipped', async () => {
  for (const [options, tool, extra] of [[{ mode: 'off' }], [{ move: null }], [{}, 'adjust_layer'], [{}, 'paint_batch', { isError: true }], [{ batch: () => [] }]]) {
    const { calls, result } = setup(options);
    assert.equal(await result(tool, extra), undefined);
    assert.equal(calls.review.length, 0, JSON.stringify(options) + ' ' + tool);
  }
});

test('a fallback keeps the batch', async () => {
  const { calls, result } = setup({ reviews: [{ fallback: 'timeout', elapsed_ms: 4000 }] });
  assert.equal(await result(), undefined);
  assert.equal(calls.record[0].status, 'fallback');
  assert.equal(calls.undo.length, 0);
});

test('a host that throws is recorded as a fallback, not an approval', async () => {
  const { calls, result } = setup({ reviews: [() => { throw new Error('canvas missing'); }] });
  assert.equal(await result(), undefined);
  assert.deepEqual([calls.record[0].status, calls.record[0].reason], ['fallback', 'canvas missing']);
});

test('mode is read on every call', async () => {
  const { host, calls, result } = setup();
  await result();
  host.modeValue = 'off';
  await result();
  assert.equal(calls.review.length, 1);
});

test('the companion registers it by name, bound to a host', async () => {
  const { lunaReviewExtension } = await import('../src/extensions.mjs');
  const extension = lunaReviewExtension({ mode: () => 'off' });
  assert.equal(extension.name, 'luna-review');
  assert.equal(typeof extension.factory, 'function');
});

test('a verdict carries the chat it was made in, so a late one cannot land in another chat', async () => {
  let release;
  const { host, calls, result } = setup({ mode: 'evaluate', reviews: [() => new Promise(resolve => { release = () => resolve({ findings: [moon] }); })] });
  host.scope = () => host.scopeValue; host.scopeValue = 'chat-A';
  await result();
  await new Promise(resolve => setImmediate(resolve));
  host.scopeValue = 'chat-B';
  release();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.record[0].scope, 'chat-A', 'the host can drop it');
  assert.equal(calls.review[0].scope, 'chat-A', 'and reads the images of the chat it started in');
});

test('a background record that throws does not escape', async () => {
  const { host, result } = setup({ mode: 'evaluate' });
  host.record = () => { throw new Error('store closed'); };
  let unhandled = null; const onUnhandled = error => { unhandled = error; };
  process.once('unhandledRejection', onUnhandled);
  await result();
  await new Promise(resolve => setTimeout(resolve, 10));
  process.removeListener('unhandledRejection', onUnhandled);
  assert.equal(unhandled, null);
});

test('a partial undo is reported as partial and counts toward the cap', async () => {
  const { calls, result } = setup({ reviews: [{ findings: [moon] }],
    batch: id => [{ id: id + '-0', before_path: 'before.png' }, { id: id + '-1', before_path: 'b.png' }],
    undo: () => ({ pass_ids: ['call1-1'], image: undoneImage }) });
  const review = reviewOf(await result());
  assert.match(review.note, /^Luna undid part of this batch: Moon covered \(top_right\)\. call1-0 could not be undone/);
  assert.deepEqual([calls.record[0].status, calls.record[0].partial], ['undone', true]);
});

test('a batch result without a canvas image is reviewed against the latest canvas', async () => {
  const { host, calls, result } = setup();
  host.canvas = () => 'latest.png';
  await result('paint_batch', { details: {} });
  assert.equal(calls.review[0].after, 'latest.png');
});

test('the batch is judged without guide lines, or the verdict says the image had them', async () => {
  const { calls, result } = setup();
  await result('paint_batch', { details: { image_path: 'after.png', unguided_path: 'after-clean.png' } });
  assert.equal(calls.review[0].after, 'after-clean.png', 'the painting without the agent’s guide lines');
  assert.equal(calls.record[0].guides_note, undefined);
  await result('paint_batch', { details: { image_path: 'after.png', guides_note: 'The guide lines are still in this view.' } });
  assert.equal(calls.review[1].after, 'after.png');
  assert.equal(calls.record[1].guides_note, 'The guide lines are still in this view.', 'Luna’s verdict knows the image had guides');
});

test('a batch the goal-likeness check already undid is not reviewed or undone again', async () => {
  const { calls, result } = setup({ reviews: [{ findings: [moon] }] });
  assert.equal(await result('paint_batch', { details: { image_path: 'undone.png', host_undone: 'goal_likeness' } }), undefined);
  assert.deepEqual([calls.review.length, calls.undo.length, calls.record.length], [0, 0, 0]);
});

test('the undo cap is shared with the goal-likeness check: two undos in the move already, Luna only reports', async () => {
  const shared = new Map([[1, 1]]);
  const { host, calls, result } = setup({ reviews: [{ findings: [moon] }, { findings: [moon] }] });
  host.undos = { count: move => shared.get(move) ?? 0, add: move => shared.set(move, (shared.get(move) ?? 0) + 1) };
  await result();
  assert.equal(shared.get(1), 2, 'Luna’s undo counts in the shared counter');
  await result();
  assert.equal(calls.undo.length, 1); assert.equal(calls.stop.length, 1);
});

test('a batch the goal-likeness check undid releases its pass baseline', async () => {
  const released = [];
  const { host, result } = setup();
  host.release = id => released.push(id);
  await result('paint_batch', { details: { image_path: 'undone.png', host_undone: 'goal_likeness' } });
  assert.deepEqual(released, ['call1']);
});

// Review finding (finish-stage goal 8): one finding must not undo a whole Refine to the goal run (many squares, minutes of
// work); its findings are recorded and told, as goal likeness keeps it.
test('guide: refine_to_goal is never undone by Luna review; its findings are recorded and told', async () => {
  const { calls, result } = setup({ reviews: [{ findings: [moon] }] });
  const changed = await result('refine_to_goal');
  assert.equal(calls.undo.length, 0);
  assert.equal(calls.record[0].status, 'warned'); assert.match(calls.record[0].reason, /refine_to_goal/);
  assert.match(reviewOf(changed).note, /Luna found Moon covered[^]*kept/);
});

// Live 2026-10-24: 16 Luna undos in 8 chats, most of them a blend (a k) Blender Basic smudge, a paint_reference_surface
// "soft masses" or a sky surface blend) flagged as texture over forms; one hit the cap and ended the move. Softening the dab
// texture is what a blend is for: that finding is recorded, never undone, and does not count toward the cap.
const texture = { type: 'texture_over_forms', label: 'texture over forms', probability: 0.86, location: 'center' };
const smudge = { actions: [{ tool: 'paint_pass', arguments: { name: 'Soften', preset: 'k) Blender Basic', strokes: [] } }] };

test('guide: texture over forms on a blending pass is recorded, never undone', async () => {
  for (const [tool, input] of [['paint_reference_surface', { preset: 'k) Blender Basic', edges: false }], ['paint_batch', smudge],
    ['paint_pass', { preset: 'k) Blender Blur' }]]) {
    const { calls, result } = setup({ reviews: [{ findings: [texture] }, { findings: [texture] }, { findings: [texture] }] });
    for (let i = 0; i < 3; i++) {
      const changed = await result(tool, { input });
      assert.match(reviewOf(changed).note, /Luna found texture over forms \(center\); it is kept/, tool);
      assert.ok(changed.content.includes(before), 'the canvas image stays');
    }
    assert.deepEqual([calls.undo.length, calls.stop.length], [0, 0], tool + ': no undo, and the move goes on');
    assert.equal(calls.record[0].status, 'warned'); assert.match(calls.record[0].reason, /blending pass/);
  }
});

test('guide: a blending pass is still undone for another finding, and a colour pass for texture', async () => {
  const { calls, result } = setup({ reviews: [{ findings: [texture, moon] }, { findings: [texture] }, { findings: [texture] }] });
  await result('paint_reference_surface', { input: {} });
  assert.equal(calls.undo.length, 1, 'the covered moon is acted on');
  await result('paint_batch', { input: { actions: [...smudge.actions, { tool: 'paint_pass', arguments: { preset: 'b) Basic-1' } }] } });
  assert.equal(calls.undo.length, 2, 'a batch that also lays colour is not a blend');
  const rake = await result('paint_pass', { input: { preset: 'k) Blender Rake' } });
  assert.match(reviewOf(rake).note, /already undid 2 batches/, 'a rake drags streaks: texture');
});

// Review (2026-10-25): paint_finish lays new goal-coloured strokes and paint_reference_surface repaints edges unless told
// not to, so neither is a blend by its name; an action that names no preset (a fill, a gradient, the toolbox) lays colour.
test('only a call whose every painting action names a blender preset is a blend', async () => {
  const { blending } = await import('../extensions/luna-review.ts');
  assert.equal(blending('paint_finish', {}), false);
  assert.equal(blending('paint_reference_surface', { preset: 'k) Blender Basic' }), false, 'its edge pass repaints edges');
  assert.equal(blending('paint_reference_surface', { preset: 'k) Blender Basic', edges: false }), true);
  assert.equal(blending('paint_batch', { actions: [...smudge.actions, { tool: 'fill_region', arguments: { name: 'Sky', area: [] } }] }), false);
  assert.equal(blending('paint_batch', { actions: [...smudge.actions, { tool: 'painting_toolbox', arguments: { commands: [{ tool: 'set_brush', parameters_json: '{"preset":"k) Blender Basic"}' }] } }] }), false);
  assert.equal(blending('paint_batch', smudge), true);
  assert.equal(blending('krita_gradient', {}), false);
});

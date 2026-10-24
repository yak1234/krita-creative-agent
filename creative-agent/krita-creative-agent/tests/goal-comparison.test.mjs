// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Luna's goal comparison (luna-goal-reviewer goal 1): the batch's area, the crops cut from it at one scale, and the one
// question, closer / same / further, asked of each crop.
import test from 'node:test';
import assert from 'node:assert/strict';
import { comparisonArea, cropPlan, goalSource, compareWithGoal, furtherFromGoal, describeFurther, CROP_SIDE, MAX_CROPS, FURTHER_CONFIDENCE }
  from '../src/goal-comparison.ts';

const target = [0, 0, 6000, 4500];

test('the area is the batch’s passes, else the cells it changed, padded for context and kept inside the goal’s target', () => {
  assert.deepEqual(comparisonArea([[1000, 1000, 400, 200], [1600, 1100, 200, 300]], null, target), [920, 960, 960, 480],
    'the union of the passes’ areas, padded by a tenth of its size each side');
  assert.deepEqual(comparisonArea([null, undefined], [100, 4000, 600, 500], target), [40, 3950, 720, 550], 'the changed cells when no pass has an area');
  assert.deepEqual(comparisonArea([], null, target), target, 'the whole target when nothing says where');
  assert.deepEqual(comparisonArea([[-50, -50, 300, 300]], null, [100, 100, 5800, 4300]), [100, 100, 180, 180], 'clamped inside the target');
  assert.equal(comparisonArea([[7000, 7000, 10, 10]], null, target), null, 'an area outside the goal: nothing to compare');
});

test('crops: one at the view’s scale when the area fits, several when it does not, never more than MAX_CROPS', () => {
  // A 6000 px canvas in a 1568 px view: scale 0.261. A 1000 x 600 area is 261 x 157 view pixels: one crop at that size.
  const scale = 1568 / 6000;
  assert.deepEqual(cropPlan([1000, 1000, 1000, 600], scale), [{ rect: [1000, 1000, 1000, 600], out: [261, 157] }]);
  // The whole canvas at scale 1 (a canvas no larger than the view): 6000 x 4500 needs tiles; at most MAX_CROPS, each at
  // most CROP_SIDE, so they are reduced below the view's scale when the area is that large.
  const tiles = cropPlan(target, 1);
  assert.ok(tiles.length <= MAX_CROPS && tiles.length > 1, JSON.stringify(tiles));
  for (const t of tiles) assert.ok(Math.max(...t.out) <= CROP_SIDE, JSON.stringify(t));
  const covered = tiles.reduce((s, t) => s + t.rect[2] * t.rect[3], 0);
  assert.equal(covered, 6000 * 4500, 'the tiles cover the area exactly');
  // A 2000 x 900 area at scale 1 with 1024 px crops: two tiles side by side, each 1:1.
  assert.deepEqual(cropPlan([0, 0, 2000, 900], 1, 1024), [{ rect: [0, 0, 1000, 900], out: [1000, 900] }, { rect: [1000, 0, 1000, 900], out: [1000, 900] }]);
  assert.deepEqual(cropPlan([0, 0, 10, 10], 0.1), [{ rect: [0, 0, 10, 10], out: [16, 16] }], 'never smaller than a readable minimum');
});

test('the goal’s crop is the same canvas area mapped back into the goal’s pixels', () => {
  const mapping = { source: [100, 0, 1500, 1125], target: [0, 0, 6000, 4500] };
  assert.deepEqual(goalSource([1200, 900, 600, 450], mapping), [400, 225, 150, 113]);
  assert.deepEqual(goalSource([0, 0, 6000, 4500], mapping), [100, 0, 1500, 1125]);
});

const image = name => ({ type: 'image', data: Buffer.from(name).toString('base64'), mimeType: 'image/jpeg' });
const crop = i => ({ goal: image('goal' + i), before: image('before' + i), after: image('after' + i) });
function luna(answers, usage = { input_tokens: 2400, output_tokens: 6, cost: 0.0004 }) {
  const requests = [];
  return { requests, decide: async request => { requests.push(request); return typeof answers === 'function' ? answers(request) : { answers, model: 'luna', elapsed_ms: 900, usage }; } };
}
const choice = (choice, p) => ({ type: 'choice', choice, confidence: p, probabilities: { closer: 0, same: 0, further: 0, [choice]: p } });

test('one decision for all crops: GOAL, BEFORE and AFTER of each, one closer / same / further question a crop', async () => {
  const client = luna({ crop_0: choice('same', 0.8), crop_1: choice('further', 0.9) });
  const result = await compareWithGoal({ client, crops: [crop(0), crop(1)] });
  assert.equal(client.requests.length, 1);
  const [request] = client.requests;
  assert.equal(request.purpose, 'compare-with-goal');
  assert.deepEqual(Object.keys(request.questions), ['crop_0', 'crop_1']);
  assert.equal(request.questions.crop_0.type, 'choice');
  assert.deepEqual(Object.keys(request.questions.crop_0.criteria), ['closer', 'same', 'further']);
  assert.match(request.questions.crop_1.instructions, /CROP 2/);
  assert.match(request.questions.crop_0.instructions, /even in the right colours/, 'blobs in the right colours are further: what the ΔE check misses');
  const labels = request.parts.filter(p => typeof p === 'string');
  assert.deepEqual(labels.slice(0, 3).map(l => l.split(' (')[0]), ['CROP 1 GOAL', 'CROP 1 BEFORE', 'CROP 1 AFTER']);
  assert.equal(request.parts.filter(p => typeof p !== 'string').length, 6);
  assert.equal(result.verdict, 'same', 'one crop of two further is no majority (review, 2026-10-24)'); assert.equal(result.confidence, 0.8);
  assert.deepEqual(result.per_crop, [{ verdict: 'same', confidence: 0.8 }, { verdict: 'further', confidence: 0.9 }]);
  assert.equal(result.cost, 0.0004); assert.equal(result.elapsed_ms, 900); assert.equal(result.input_tokens, 2400);
  assert.equal(furtherFromGoal(result), false);
});

test('further counts only with good confidence, and not when another crop got clearly closer', async () => {
  const unsure = await compareWithGoal({ client: luna({ crop_0: choice('further', FURTHER_CONFIDENCE - 0.1) }), crops: [crop(0)] });
  assert.equal(unsure.verdict, 'further'); assert.equal(furtherFromGoal(unsure), false, 'an unsure further is recorded, never acted on');
  const mixed = await compareWithGoal({ client: luna({ crop_0: choice('closer', 0.9), crop_1: choice('further', 0.9) }), crops: [crop(0), crop(1)] });
  assert.equal(mixed.verdict, 'same', 'as much better as worse'); assert.equal(furtherFromGoal(mixed), false);
  const closer = await compareWithGoal({ client: luna({ crop_0: choice('closer', 0.95) }), crops: [crop(0)] });
  assert.equal(closer.verdict, 'closer'); assert.equal(furtherFromGoal(closer), false);
});

test('a fallback or an answer that is not one of the choices is no verdict, never a guess', async () => {
  const timeout = await compareWithGoal({ client: luna(() => ({ fallback: 'timeout', elapsed_ms: 4000 })), crops: [crop(0)] });
  assert.deepEqual([timeout.verdict, timeout.fallback, timeout.elapsed_ms], [null, 'timeout', 4000]);
  assert.equal(furtherFromGoal(timeout), false);
  const odd = await compareWithGoal({ client: luna({ crop_0: { type: 'choice', choice: 'maybe', confidence: 0.9 } }), crops: [crop(0)] });
  assert.deepEqual([odd.verdict, odd.fallback], [null, 'service_or_response_error']);
  const thrown = await compareWithGoal({ client: { decide: async () => { throw new Error('boom'); } }, crops: [crop(0)] });
  assert.equal(thrown.fallback, 'service_or_response_error');
  const none = await compareWithGoal({ client: luna({}), crops: [] });
  assert.equal(none.fallback, 'no_crops');
});

test('what the painter and the artist are told when Luna finds the batch further from the goal', () => {
  const text = describeFurther({ verdict: 'further', confidence: 0.86, crops: 2, per_crop: [], elapsed_ms: 1200, cost: 0.001, input_tokens: 3000, area: [1000, 2000, 900, 600] });
  assert.equal(text, 'Luna compared the batch’s area [1000,2000,900,600] with the goal image: further from it than before (confidence 0.86), in its forms, edges or detail');
});

// Review fixes (2026-10-24).
test('further needs a majority of the crops and no crop closer at 0.6 or more', async () => {
  const { compareWithGoal: compare, furtherFromGoal: further } = await import('../src/goal-comparison.ts');
  const ask = async answers => compare({ client: luna(answers), crops: Object.keys(answers).map((_, i) => crop(i)) });
  const outvoted = await ask({ crop_0: choice('closer', 0.55), crop_1: choice('closer', 0.55), crop_2: choice('further', 0.9) });
  assert.notEqual(outvoted.verdict, 'further', 'one further against two closer'); assert.equal(further(outvoted), false);
  const vetoed = await ask({ crop_0: choice('further', 0.9), crop_1: choice('further', 0.9), crop_2: choice('closer', 0.6) });
  assert.notEqual(vetoed.verdict, 'further', 'a crop closer at 0.6 vetoes');
  const majority = await ask({ crop_0: choice('further', 0.9), crop_1: choice('further', 0.85), crop_2: choice('same', 0.7) });
  assert.equal(majority.verdict, 'further'); assert.equal(further(majority), true);
  const half = await ask({ crop_0: choice('further', 0.9), crop_1: choice('same', 0.9) });
  assert.notEqual(half.verdict, 'further', 'half is no majority');
});

test('the goal’s crop is kept inside the goal image', async () => {
  const { goalSource: source } = await import('../src/goal-comparison.ts');
  const mapping = { source: [0, 0, 1500, 1125], target: [0, 0, 6000, 4500] };
  assert.deepEqual(source([5800, 4400, 400, 300], mapping, [1500, 1125]), [1450, 1100, 50, 25]);
  assert.deepEqual(source([-100, -100, 400, 400], mapping, [1500, 1125]), [0, 0, 75, 75]);
});

test('a tiny batch is compared with a few hundred view pixels of context around it', async () => {
  const { withContext } = await import('../src/goal-comparison.ts');
  // A 20 x 20 px batch on a 6000 px canvas in a 1568 px view (scale 0.26): at least 256 view px, about 980 canvas px.
  const scale = 1568 / 6000, area = withContext([3000, 2000, 20, 20], scale, target);
  assert.ok(area[2] * scale >= 255 && area[3] * scale >= 255, JSON.stringify(area));
  assert.ok(area[0] <= 3000 && area[0] + area[2] >= 3020, 'still around the batch');
  const corner = withContext([0, 0, 10, 10], scale, target);
  assert.deepEqual(corner.slice(0, 2), [0, 0], 'kept inside the target');
  assert.deepEqual(withContext([0, 0, 3000, 2000], scale, target), [0, 0, 3000, 2000], 'a large area is left as it is');
});

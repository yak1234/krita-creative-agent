// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Luna picks each architectural part's material by looking (src/luna-materials.ts): the goal cropped to the part and the
// allowed materials' swatches, one decision a part; a confident pick replaces the planner's, else the planner's stays,
// marked unsure; Luna offline or failing changes nothing. A fake decision client; no network, no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { candidatesFor, pickMaterial, applyPicks, chooseByLook, cropOut, MAX_CANDIDATES, PICK_CONFIDENCE, PICK_MARGIN } from '../src/luna-materials.ts';
import { allowedMaterials } from '../src/texture-library.ts';

const IMG = { type: 'image', data: 'AAAA', mimeType: 'image/jpeg' };
const swatch = async () => IMG;
/** A fake Luna: answers each request with `probs(letters, parts)` -> {letter: p}. */
function fakeClient(probs) {
  const requests = [];
  return { requests, decide: async request => {
    requests.push(request);
    const q = request.questions.material, letters = Object.keys(q.criteria), p = probs(letters, request);
    const choice = Object.entries(p).sort((a, b) => b[1] - a[1])[0][0];
    return { answers: { material: { type: 'choice', choice, confidence: p[choice], probabilities: p } }, model: 'fake/luna', elapsed_ms: 12, usage: { input_tokens: 900, output_tokens: 5, cost: 0.0021 } };
  } };
}

test('candidates: every allowed material, the planner’s pick first, the kind’s own materials before shared ones', () => {
  const list = candidatesFor('wall', 'Bricks085');
  assert.equal(list[0].id, 'Bricks085');
  assert.ok(list.length <= MAX_CANDIDATES && list.length === Math.min(MAX_CANDIDATES, allowedMaterials('wall').length));
  assert.ok(list.every(m => m.kinds.includes('wall')));
  assert.equal(new Set(list.map(m => m.id)).size, list.length);
  assert.ok(['ph_old_sandstone_02', 'ph_castle_brick_02_red', 'Plaster001'].every(id => list.some(m => m.id === id)), 'the castle brick, the cream and plain surfaces are among them');
  assert.deepEqual(candidatesFor('dome').map(m => m.id).sort(), allowedMaterials('dome').map(m => m.id).sort());
});

test('one decision a part: the goal crop, then each swatch under its letter; probabilities by material; confident at 0.5 and clear of the second', async () => {
  const client = fakeClient(letters => Object.fromEntries(letters.map((l, i) => [l, i === 2 ? 0.7 : 0.3 / (letters.length - 1)])));
  const pick = await pickMaterial({ client, part: { part: 'historic buildings', kind: 'wall', crop: IMG }, planned: 'Bricks085', swatch });
  assert.equal(client.requests.length, 1);
  const parts = client.requests[0].parts;
  assert.equal(parts.filter(p => typeof p === 'object').length, 1 + pick.candidates.length);
  assert.ok(parts.includes('A:') && parts.includes('C:'));
  assert.match(client.requests[0].questions.material.instructions, /courses|blocks/);
  assert.equal(pick.top, pick.candidates[2]);
  assert.equal(pick.confident, true);
  assert.equal(pick.p, 0.7);
  assert.equal(Object.keys(pick.probabilities).length, pick.candidates.length);
  assert.equal(pick.cost, 0.0021);
  assert.ok(PICK_CONFIDENCE === 0.5 && PICK_MARGIN > 0);
});

test('not confident: below the threshold, or too close to the second', async () => {
  const flat = fakeClient(letters => Object.fromEntries(letters.map(l => [l, 1 / letters.length])));
  const low = await pickMaterial({ client: flat, part: { part: 'towers', kind: 'tower', crop: IMG }, planned: null, swatch });
  assert.equal(low.confident, false);
  const close = fakeClient(letters => Object.fromEntries(letters.map((l, i) => [l, i === 0 ? 0.52 : i === 1 ? 0.4 : 0.08 / (letters.length - 2)])));
  assert.equal((await pickMaterial({ client: close, part: { part: 'towers', kind: 'tower', crop: IMG }, planned: null, swatch })).confident, false);
});

test('Luna unavailable, failing, throwing or with no crop: a fallback, never a pick', async () => {
  const part = { part: 'towers', kind: 'tower', crop: IMG };
  assert.equal((await pickMaterial({ client: null, part, planned: null, swatch })).fallback, 'not_connected');
  assert.equal((await pickMaterial({ client: { decide: async () => ({ fallback: 'timeout', elapsed_ms: 4000 }) }, part, planned: null, swatch })).fallback, 'timeout');
  assert.equal((await pickMaterial({ client: { decide: async () => { throw new Error('boom'); } }, part, planned: null, swatch })).fallback, 'service_or_response_error');
  assert.equal((await pickMaterial({ client: fakeClient(() => ({ A: 1 })), part: { ...part, crop: null }, planned: null, swatch })).fallback, 'no_crop');
  assert.equal((await pickMaterial({ client: fakeClient(() => ({ A: 1 })), part, planned: null, swatch: async () => { throw new Error('no maps'); } })).fallback, 'no_swatches');
  const odd = { decide: async () => ({ answers: { material: { type: 'choice', choice: 'Z' } }, model: 'x', elapsed_ms: 1, usage: { input_tokens: 1, output_tokens: 1, cost: 0 } }) };
  assert.equal((await pickMaterial({ client: odd, part, planned: null, swatch })).fallback, 'service_or_response_error');
});

const pick = (part, kind, aspect, top, confident, extra = {}) => ({ part, kind, aspect, planned: null, candidates: [top], probabilities: { [top]: confident ? 0.8 : 0.3 }, top, p: confident ? 0.8 : 0.3, second: 0.1, confident, cost: 0.002, input_tokens: 900, elapsed_ms: 10, ...extra });

test('applying picks: a confident pick replaces the planner’s for its aspect (hints kept); unsure keeps it, marked; a fallback changes nothing', () => {
  const planned = [{ aspect: 'walls', id: 'Bricks085', material: 'red brick', scale: 'coarse' }, { aspect: 'roofs', id: 'Metal021', material: 'rusty painted metal' }];
  const out = applyPicks(planned, [pick('historic buildings', 'wall', 'walls', 'ph_old_sandstone_02', true), pick('roofs', 'roof', 'roofs', 'ph_green_metal_rust', false)]);
  assert.deepEqual(out[0], { aspect: 'walls', id: 'ph_old_sandstone_02', material: 'old cream sandstone', scale: 'coarse', source: 'luna' });
  assert.deepEqual(out[1], { aspect: 'roofs', id: 'Metal021', material: 'rusty painted metal', unsure: true });
  assert.deepEqual(applyPicks(planned, [{ ...pick('x', 'wall', 'walls', 'Bricks094', false), fallback: 'timeout' }]), planned);
  assert.deepEqual(applyPicks(undefined, [pick('towers', 'tower', 'walls', 'ph_castle_brick_02_red', true)]),
    [{ aspect: 'walls', id: 'ph_castle_brick_02_red', material: 'old red castle brick', source: 'luna' }], 'no planned material: Luna’s pick is the plan’s');
});

test('two parts of one aspect that Luna sees differently each get their own entry', () => {
  const planned = [{ aspect: 'walls', id: 'Bricks085', material: 'red brick' }];
  const out = applyPicks(planned, [pick('Kremlin towers', 'tower', 'walls', 'ph_castle_brick_02_red', true), pick('historic buildings', 'wall', 'walls', 'ph_old_sandstone_02', true)]);
  assert.deepEqual(out.map(m => [m.aspect, m.part ?? null, m.id, m.source ?? null]),
    [['walls', 'Kremlin towers', 'ph_castle_brick_02_red', 'luna'], ['walls', 'historic buildings', 'ph_old_sandstone_02', 'luna']]);
  const mixed = applyPicks(planned, [pick('Kremlin towers', 'tower', 'walls', 'ph_castle_brick_02_red', true), pick('historic buildings', 'wall', 'walls', 'Plaster001', false)]);
  assert.deepEqual(mixed.map(m => [m.part ?? null, m.id, m.unsure ?? false]), [['Kremlin towers', 'ph_castle_brick_02_red', false], [null, 'Bricks085', true]]);
});

test('the artist’s materials win: their parts are not asked', async () => {
  const client = fakeClient(letters => ({ [letters[0]]: 0.9 }));
  const materials = [{ aspect: 'walls', id: 'Bricks094', material: 'old red brick', source: 'artist' }, { aspect: 'roofs', id: 'Metal021' }];
  const result = await chooseByLook({ client, parts: [{ name: 'walls', kind: 'wall', bounds: [0, 0, 10, 10] }, { name: 'roofs', kind: 'roof', bounds: [0, 0, 10, 10] }],
    materials, crops: async parts => parts.map(() => IMG), swatch });
  assert.equal(client.requests.length, 1, 'only the roofs were asked');
  assert.deepEqual(result.materials[0], materials[0]);
  assert.equal(result.materials[1].source, 'luna');
  assert.deepEqual(result.picks.map(p => p.part), ['roofs']);
});

test('chooseByLook never throws: crops failing keep the plan', async () => {
  const materials = [{ aspect: 'walls', id: 'Bricks085' }];
  const result = await chooseByLook({ client: fakeClient(() => ({ A: 1 })), parts: [{ name: 'walls', kind: 'wall', bounds: [0, 0, 10, 10] }], materials,
    crops: async () => { throw new Error('no goal'); }, swatch });
  assert.deepEqual(result.materials, materials);
  assert.equal(result.picks[0].fallback, 'no_crop');
});

test('the crop size: the long side at most 384 px, never enlarged, at least 16', () => {
  assert.deepEqual(cropOut([0, 0, 800, 400]), [384, 192]);
  assert.deepEqual(cropOut([0, 0, 100, 50]), [100, 50]);
  assert.deepEqual(cropOut([0, 0, 4, 2]), [16, 16]);
});

test('against the planner’s pick: Luna’s top replaces it when at least twice as likely and three times chance (live: 0.21 against red brick’s 0.08)', async () => {
  const live = (top, planned) => fakeClient(letters => Object.fromEntries(letters.map((l, i) => [l, i === 0 ? planned : i === 1 ? top : (1 - top - planned) / (letters.length - 2)])));
  const part = { part: 'historic buildings', kind: 'wall', crop: IMG };
  const moved = await pickMaterial({ client: live(0.21, 0.08), part, planned: 'Bricks085', swatch });
  assert.equal(moved.confident, true, 'clearly not the planner’s red brick');
  assert.notEqual(moved.top, 'Bricks085');
  assert.equal((await pickMaterial({ client: live(0.3, 0.24), part, planned: 'Bricks085', swatch })).confident, false, 'a look-alike of the plan’s: keep it');
  assert.equal((await pickMaterial({ client: live(0.1, 0.04), part, planned: 'Bricks085', swatch })).confident, false, 'too close to chance (1/25)');
  assert.equal((await pickMaterial({ client: live(0.29, 0.13), part, planned: null, swatch })).confident, false, 'no plan to compare: the absolute rule only');
});

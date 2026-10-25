// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The planner's typed texture choice (src/texture-choice.ts): the request, the reply read as JSON, and the host's
// validation and clamping; a default by part kind when the model is missing or useless. No model is called: a fake reader.
import test from 'node:test';
import assert from 'node:assert/strict';
import { texturePrompt, readChoice, clampPart, defaultPart, chooseTextures, STRENGTH, TILE_MIN } from '../src/texture-choice.ts';

const canvas = { width: 6000, height: 4500 };
const facade = { name: 'left classical buildings', kind: 'wall', bounds: [0, 1500, 1800, 1600] };
const street = { name: 'cobbled street', kind: 'street', bounds: [0, 3600, 6000, 900] };

test('the request lists each part with its bounds, note and only the materials it may get', () => {
  const prompt = texturePrompt({ canvas, parts: [{ ...facade, note: 'cream stucco facades with white columns' }, street] });
  assert.match(prompt, /left classical buildings/);
  assert.match(prompt, /cream stucco facades/);
  assert.match(prompt, /\[0,1500,1800,1600\]/);
  assert.match(prompt, /Bricks085/);
  assert.match(prompt, /PavingStones046/);
  assert.match(prompt, /JSON/);
  const wallLine = prompt.split('\n').find(line => line.includes('left classical buildings'));
  assert.doesNotMatch(wallLine, /Snow/);
});

test('a reply is read from its JSON, with or without a code fence or words around it', () => {
  const body = { parts: [{ part: 'left classical buildings', materials: [{ id: 'Concrete012', weight: 1 }], tile_px: { near: 160, far: 120 }, direction_deg: 0, vanishing: null, strength: 0.2, blend: 'soft_light' }] };
  assert.deepEqual(readChoice(JSON.stringify(body)), body);
  assert.deepEqual(readChoice('Here you go:\n```json\n' + JSON.stringify(body) + '\n```\nDone.'), body);
  assert.equal(readChoice('no json here'), null);
  assert.equal(readChoice('{"parts": "nope"}'), null);
});

test('the host clamps what the model chose: materials of the part kind only, sizes, strength, blend', () => {
  const clamped = clampPart({ part: 'x', materials: [{ id: 'Snow013', weight: 1 }, { id: 'Bricks085', weight: 3 }, { id: 'Nope', weight: 1 }, { id: 'Bricks094', weight: 1 }, { id: 'Bricks097', weight: 1 }],
    tile_px: { near: 5, far: 9000 }, direction_deg: 400, vanishing: [1e9, 2], strength: 0.9, blend: 'multiply' }, facade, canvas);
  assert.deepEqual(clamped.materials.map(m => m.id), ['Bricks085', 'Bricks094']);         // no snow on a wall, at most 2, known only
  assert.ok(Math.abs(clamped.materials.reduce((s, m) => s + m.weight, 0) - 1) < 1e-9);
  assert.ok(clamped.tile_px.near >= TILE_MIN && clamped.tile_px.far <= clamped.tile_px.near && clamped.tile_px.far >= clamped.tile_px.near * 0.2);
  assert.equal(clamped.direction_deg, 40);
  assert.equal(clamped.vanishing, null);
  assert.equal(clamped.strength, STRENGTH[1]);
  assert.equal(clamped.blend, 'soft_light');
  assert.equal(clamped.source, 'model');
  const low = clampPart({ part: 'x', materials: [{ id: 'Bricks085', weight: 1 }], strength: 0.01 }, facade, canvas);
  assert.equal(low.strength, STRENGTH[0]);
});

test('a window grid never goes above its own cap', () => {
  const tower = { name: 'Moscow City skyscrapers', kind: 'skyscraper', bounds: [4000, 200, 1500, 2800] };
  const clamped = clampPart({ part: 'x', materials: [{ id: 'Facade009', weight: 1 }], strength: 0.3 }, tower, canvas);
  assert.equal(clamped.strength, 0.12);
});

test('a vanishing point inside the part, or far off the canvas, is dropped; a fair one kept', () => {
  assert.equal(clampPart({ materials: [{ id: 'Bricks085' }], vanishing: [900, 2000] }, facade, canvas).vanishing, null);
  assert.deepEqual(clampPart({ materials: [{ id: 'Bricks085' }], vanishing: [3000, 1800] }, facade, canvas).vanishing, [3000, 1800]);
});

test('the default for a kind: its material, a tile from its metres and the part size, the street in perspective', () => {
  const wall = defaultPart(facade, canvas);
  assert.equal(wall.source, 'default');
  assert.ok(wall.materials.length === 1 && wall.materials[0].weight === 1);
  assert.equal(wall.tile_px.near, wall.tile_px.far);
  const road = defaultPart(street, canvas);
  assert.ok(road.tile_px.far < road.tile_px.near);
  assert.equal(road.direction_deg, -90);
  for (const part of [wall, road]) assert.ok(part.strength >= STRENGTH[0] && part.strength <= STRENGTH[1]);
});

test('chooseTextures: the model reply per part, defaults for what it left out or when it fails', async () => {
  const reader = async ({ prompt, images }) => {
    assert.equal(images.length, 1);
    assert.match(prompt, /cobbled street/);
    return { text: JSON.stringify({ parts: [{ part: 'Cobbled Street', materials: [{ id: 'PavingStones150', weight: 1 }], tile_px: { near: 300, far: 120 }, direction_deg: -90, strength: 0.25 }] }), cost: 0.001, model: 'fake/qwen' };
  };
  const view = { label: 'CANVAS', picture: { data: 'AAAA', mimeType: 'image/jpeg' } };
  const chosen = await chooseTextures({ reader, view, canvas, parts: [facade, street], signal: AbortSignal.timeout(5000) });
  assert.equal(chosen.parts[0].source, 'default');
  assert.equal(chosen.parts[1].source, 'model');
  assert.equal(chosen.parts[1].materials[0].id, 'PavingStones150');
  assert.equal(chosen.model, 'fake/qwen');
  const failed = await chooseTextures({ reader: async () => { throw new Error('provider_error'); }, view, canvas, parts: [facade], signal: AbortSignal.timeout(5000) });
  assert.equal(failed.parts[0].source, 'default');
  assert.equal(failed.fallback, 'provider_error');
  const none = await chooseTextures({ reader: null, view, canvas, parts: [facade], signal: AbortSignal.timeout(5000) });
  assert.equal(none.fallback, 'no_model');
});

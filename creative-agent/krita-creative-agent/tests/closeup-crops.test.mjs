// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Close-up crops of the area an Agent move works in (eyes-and-history 2): where, how many, how large, labelled.
import test from 'node:test';
import assert from 'node:assert/strict';
import { callArea, cropRects, addCloseupCrops, MAX_CROPS } from '../src/closeup-crops.ts';

test('the area a call works in: region, projection region, target, area box, shape box, a batch’s union', () => {
  assert.deepEqual(callArea({ region: [10, 20, 30, 40] }), [10, 20, 30, 40]);
  assert.deepEqual(callArea({ projection_region: [1, 2, 3, 4] }), [1, 2, 3, 4]);
  assert.deepEqual(callArea({ area: { box: [5, 6, 7, 8] } }), [5, 6, 7, 8]);
  assert.deepEqual(callArea({ inside_shape: { box: [5, 6, 70, 80] } }), [5, 6, 70, 80]);
  // Only an area the call names (the spec: crops only when there's an area), not where strokes happen to land.
  assert.equal(callArea({ strokes: [{ start: [100, 200], segments: [[110, 210, 150, 250, 300, 220]] }] }), null);
  assert.equal(callArea({ steps: [{ shape: 'rectangle', bounds: [0, 0, 9, 9] }], bounds: [0, 0, 9, 9] }), null);
  assert.deepEqual(callArea({ actions: [{ arguments: { region: [0, 0, 10, 10] } }, { arguments: { region: [100, 50, 10, 10] } }] }), [0, 0, 110, 60]);
  assert.equal(callArea({ name: 'Sky' }), null);
  assert.equal(callArea({ region: [0, 0, 0, 10] }), null, 'an empty rect is no area');
});

test('crops: none without an area or on a canvas the view shows whole; one around a small area; two along a large one', () => {
  const canvas = { width: 6000, height: 4000 };
  assert.deepEqual(cropRects(null, canvas), []);
  assert.deepEqual(cropRects([10, 10, 100, 100], { width: 1200, height: 900 }), [], 'the whole view is actual pixels already');
  assert.deepEqual(cropRects([1000, 1000, 800, 600], canvas), [[1000, 1000, 800, 600]]);
  assert.deepEqual(cropRects([5900, 3950, 40, 40], canvas), [[5488, 3488, 512, 512]], 'a small area: at least 512 a side, kept on the canvas');
  const wide = cropRects([0, 1000, 5000, 1000], canvas, 1536);
  assert.equal(wide.length, MAX_CROPS);
  for (const [x, y, w, h] of wide) assert.ok(w <= 1536 && h <= 1536 && x >= 0 && y >= 0 && x + w <= 6000 && y + h <= 4000, JSON.stringify(wide));
  assert.ok(wide[0][0] < wide[1][0], 'side by side along the long side');
  assert.ok(cropRects([0, 0, 1000, 3800], canvas, 1536).every(([, , w, h]) => w <= 1536 && h <= 1536));
});

test('added to the observation: a label with the canvas rectangle and scale, then the image; another revision dropped', async () => {
  const peeks = [];
  const host = { area: () => [1000, 1000, 800, 600], side: () => 1536, image: async path => ({ type: 'image', data: path, mimeType: 'image/png' }),
    peek: async region => { peeks.push(region); return { image_path: '/v/crop.png', revision: 'r1', scale: 1 }; } };
  const content = [{ type: 'text', text: '{}' }];
  assert.equal(await addCloseupCrops(host, { width: 6000, height: 4000, revision: 'r1' }, content), 1);
  assert.deepEqual(peeks, [[1000, 1000, 800, 600]]);
  assert.match(content[1].text, /^CLOSE-UP 1 of the area you work in: canvas \[1000, 1000, 800, 600\].*scale 1 \(actual pixels\)/);
  assert.equal(content[2].type, 'image');
  const stale = [];
  assert.equal(await addCloseupCrops({ ...host, peek: async () => ({ image_path: '/v/c.png', revision: 'r0' }) }, { width: 6000, height: 4000, revision: 'r1' }, stale), 0);
  assert.equal(await addCloseupCrops({ ...host, area: () => null }, { width: 6000, height: 4000, revision: 'r1' }, stale), 0);
  assert.equal(await addCloseupCrops({ ...host, peek: async () => { throw new Error('busy'); } }, { width: 6000, height: 4000, revision: 'r1' }, stale), 0, 'a failed crop never fails the look');
  assert.deepEqual(stale, []);
});

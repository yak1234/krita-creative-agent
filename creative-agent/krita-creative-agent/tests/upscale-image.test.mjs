// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The sharpening model's pixel side (src/upscale/image.ts, png.ts): fixed 128-pixel tiles with an overlap margin that is
// cut away, stitched into one 4x picture; the size the reference tools can read; the most detailed crop for the
// side-by-side; RGB PNGs. A nearest-neighbour fake stands in for the model, so a correct stitch is exactly a nearest 4x.
import test from 'node:test';
import assert from 'node:assert/strict';
import { inflateSync } from 'node:zlib';
import { tilePlan, tileInput, placeTile, referenceSize, detailCrop, rgbFromRgba, compareImage } from '../src/upscale/image.ts';
import { encodeRgb } from '../src/upscale/png.ts';

const TILE = 128, SCALE = 4;
/** The fake model: each input pixel becomes a SCALE x SCALE block (channels first, 0..1). */
function nearestTile(input, tile = TILE) {
  const out = new Float32Array(3 * tile * SCALE * tile * SCALE), side = tile * SCALE;
  for (let c = 0; c < 3; c++) for (let y = 0; y < side; y++) for (let x = 0; x < side; x++)
    out[c * side * side + y * side + x] = input[c * tile * tile + Math.floor(y / SCALE) * tile + Math.floor(x / SCALE)];
  return out;
}
function picture(width, height) {
  const rgb = new Uint8Array(width * height * 3);
  for (let i = 0; i < rgb.length; i++) rgb[i] = (i * 37 + (i >> 7) * 11) & 255;
  return rgb;
}
function upscaleWith(run, rgb, width, height, pad) {
  const out = new Uint8Array(width * SCALE * height * SCALE * 3);
  for (const cell of tilePlan(width, height, { tile: TILE, pad })) placeTile(out, width * SCALE, run(tileInput(rgb, width, height, cell, TILE)), cell, TILE, SCALE);
  return out;
}

test('the tiles cover the picture once: cores in a grid, each window 128 pixels inside the picture and holding its core', () => {
  for (const [width, height] of [[1448, 1086], [300, 200], [128, 128], [90, 40], [1, 1]]) {
    const plan = tilePlan(width, height, { tile: TILE, pad: 10 }), seen = new Uint8Array(width * height);
    for (const { core: [x, y, w, h], window: [wx, wy] } of plan) {
      assert.ok(wx >= 0 && wy >= 0 && (width < TILE ? wx === 0 : wx + TILE <= width) && (height < TILE ? wy === 0 : wy + TILE <= height));
      assert.ok(x >= wx && y >= wy && x + w <= wx + TILE && y + h <= wy + TILE, 'the core lies in its window');
      for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) seen[j * width + i]++;
    }
    assert.ok(seen.every(n => n === 1), `${width}x${height}: every pixel in exactly one core`);
  }
  assert.equal(tilePlan(1448, 1086, { tile: TILE, pad: 10 }).length, 14 * 11);
});

test('stitched tiles are the whole picture made 4x larger: a nearest fake gives exactly the nearest 4x, small pictures padded', () => {
  for (const [width, height] of [[300, 200], [90, 40], [129, 257]]) {
    const rgb = picture(width, height), out = upscaleWith(t => nearestTile(t), rgb, width, height, 10), W = width * SCALE;
    let wrong = 0;
    for (let y = 0; y < height * SCALE; y++) for (let x = 0; x < W; x++) for (let c = 0; c < 3; c++)
      if (out[(y * W + x) * 3 + c] !== rgb[(Math.floor(y / SCALE) * width + Math.floor(x / SCALE)) * 3 + c]) wrong++;
    assert.equal(wrong, 0, `${width}x${height}`);
  }
});

test('a tile’s margin is cut away: what a model paints near a tile’s edge never reaches the picture', () => {
  // A fake that is right in the middle but paints its outer 8 output pixels (2 input pixels) white, as a model guessing past the edge would.
  const edgy = input => { const out = nearestTile(input), side = TILE * SCALE;
    for (let c = 0; c < 3; c++) for (let y = 0; y < side; y++) for (let x = 0; x < side; x++)
      if (x < 8 || y < 8 || x >= side - 8 || y >= side - 8) out[c * side * side + y * side + x] = 1;
    return out; };
  const width = 400, height = 300, rgb = new Uint8Array(width * height * 3).fill(20);
  const out = upscaleWith(edgy, rgb, width, height, 10);
  // Only the picture's own border (where no tile has a margin to spare) may show it.
  let inside = 0;
  for (let y = 8; y < height * SCALE - 8; y++) for (let x = 8; x < width * SCALE - 8; x++) if (out[(y * width * SCALE + x) * 3] !== 20) inside++;
  assert.equal(inside, 0);
});

test('referenceSize: the largest size of the same proportions within the reference tools’ pixels', () => {
  assert.deepEqual(referenceSize(5792, 4344, 4_000_000), [2309, 1732]);
  assert.deepEqual(referenceSize(800, 600, 4_000_000), [800, 600], 'never enlarged');
  const [w, h] = referenceSize(5792, 4344, 4_000_000);
  assert.ok(w * h <= 4_000_000 && Math.abs(w / h - 5792 / 4344) < 0.002);
});

test('detailCrop finds the busiest square; compareImage puts the original, enlarged, beside the sharpened crop', () => {
  const width = 200, height = 100, rgb = new Uint8Array(width * height * 3).fill(128);
  for (let y = 60; y < 90; y++) for (let x = 150; x < 180; x++) rgb[(y * width + x) * 3] = (x + y) % 2 ? 0 : 255;  // a checker
  const [x, y, side] = detailCrop(rgb, width, height, 40);
  assert.equal(side, 40);
  assert.ok(x <= 150 && x + side >= 180 && y <= 60 && y + side >= 90, `the crop ${[x, y, side]} holds the detail`);
  const sharp = new Uint8Array(width * SCALE * height * SCALE * 3).fill(200);
  const compare = compareImage(rgb, width, sharp, SCALE, [x, y, side], 160);
  assert.deepEqual([compare.width, compare.height], [160 * 2 + 8, 160]);
  assert.equal(compare.data[((80) * compare.width + 160 + 8 + 80) * 3], 200, 'the right half is the sharpened crop');
  assert.equal(compare.data[(80 * compare.width + 164) * 3], 255, 'a white gap between them');
});

test('rgbFromRgba drops alpha over white, and encodeRgb writes a PNG that inflates to its rows', () => {
  const rgba = Uint8Array.from([10, 20, 30, 255, 200, 100, 0, 0]);
  assert.deepEqual([...rgbFromRgba(rgba, 2, 1)], [10, 20, 30, 255, 255, 255]);
  const rgb = picture(7, 5), file = encodeRgb(7, 5, rgb);
  assert.ok(file.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])));
  assert.deepEqual([file.readUInt32BE(16), file.readUInt32BE(20), file[24], file[25]], [7, 5, 8, 2]);
  const idat = file.indexOf('IDAT'), length = file.readUInt32BE(idat - 4), raw = inflateSync(file.subarray(idat + 4, idat + 4 + length));
  assert.equal(raw.length, 5 * (7 * 3 + 1));
  // Undo the filters and compare with the pixels.
  const rows = [], stride = 21;
  for (let y = 0; y < 5; y++) {
    const kind = raw[y * (stride + 1)], row = new Uint8Array(stride), prev = rows[y - 1] ?? new Uint8Array(stride);
    for (let i = 0; i < stride; i++) {
      const v = raw[y * (stride + 1) + 1 + i], a = i >= 3 ? row[i - 3] : 0, b = prev[i], c = i >= 3 ? prev[i - 3] : 0;
      const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
      row[i] = (v + [0, a, b, (a + b) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? b : c][kind]) & 255;
    }
    rows.push(row);
  }
  assert.deepEqual([...Buffer.concat(rows)], [...rgb]);
});

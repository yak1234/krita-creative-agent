// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The companion's bounded PNG reader for large references (src/png-rgba.ts): the same RGBA as an unbounded reference
// reader for every plain 8-bit PNG and every row filter; null (left to the plugin) for anything with colour management,
// interlacing, palettes, 16 bits, too many pixels or damage. Images are made in memory.
import test from 'node:test';
import assert from 'node:assert/strict';
import { decodeRgba, pngSize } from '../src/png-rgba.ts';
import { encodeRgb } from '../src/upscale/png.ts';
import { encodePng, decodePng } from './fixtures/png-rgba.ts';

const noise = (n, seed = 7) => { const out = new Uint8Array(n); let a = seed; for (let i = 0; i < n; i++) { a = (a * 1103515245 + 12345) & 0x7fffffff; out[i] = (a >> 8) & 255; } return out; };
const smooth = (w, h, c) => { const out = new Uint8Array(w * h * c); for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) for (let k = 0; k < c; k++) out[(y * w + x) * c + k] = (x * 3 + y * 5 + k * 40) & 255; return out; };

test('every plain 8-bit PNG decodes to the same RGBA as the reference reader', () => {
  for (const channels of [1, 2, 3, 4]) {
    for (const data of [noise(37 * 23 * channels), smooth(37, 23, channels)]) {
      const file = encodePng({ width: 37, height: 23, channels, data });
      const mine = decodeRgba(file), theirs = decodePng(file);
      assert.deepEqual([mine.width, mine.height], [37, 23]);
      assert.ok(Buffer.from(mine.data).equals(Buffer.from(theirs.data)), `channels ${channels}`);
    }
  }
  const rgb = smooth(300, 40, 3), file = encodeRgb(300, 40, rgb);   // the sharpener's own files: every filter in use
  const mine = decodeRgba(file);
  for (let i = 0; i < 300 * 40; i++) assert.deepEqual([...mine.data.subarray(i * 4, i * 4 + 4)], [rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2], 255]);
  assert.deepEqual(pngSize(file), { width: 300, height: 40 });
});

test('anything else is left to the plugin: colour profile, gamma, 16 bits, palette, interlace, too large, damaged', () => {
  const file = encodePng({ width: 4, height: 4, channels: 3, data: noise(48) });
  const withChunk = kind => { const c = Buffer.alloc(16); c.writeUInt32BE(4, 0); c.write(kind, 4, 'latin1'); return Buffer.concat([file.subarray(0, 33), c, file.subarray(33)]); };
  for (const kind of ['iCCP', 'gAMA', 'cHRM']) assert.equal(decodeRgba(withChunk(kind)), null, kind);
  const patched = (offset, value) => { const copy = Buffer.from(file); copy[offset] = value; return copy; };
  assert.equal(decodeRgba(patched(24, 16)), null, '16 bits');
  assert.equal(decodeRgba(patched(25, 3)), null, 'palette');
  assert.equal(decodeRgba(patched(28, 1)), null, 'interlaced');
  assert.equal(decodeRgba(file, 15), null, 'more pixels than allowed: refused from the header');
  assert.equal(decodeRgba(file.subarray(0, file.length - 20)), null, 'cut short');
  assert.equal(decodeRgba(Buffer.from('not a png at all, not a png at all')), null);
});

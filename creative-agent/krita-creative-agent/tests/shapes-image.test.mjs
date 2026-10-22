// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Element shapes, the pixel side (src/shapes/image.ts; masks are written with png.ts's encodePlane): the resize matches Pillow's bilinear exactly
// (the proven Python reference resizes with Pillow), the encoder input is normalised as the reference does, prompts are
// scaled into the model's 1024 space, and a mask is thresholded, bounded, cropped and written as an 8-bit PNG. Writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resizeBilinear, encoderInput, decoderPrompt, maskFromLogits, maskBounds, cropMask, checkPrompt, ENCODER_SIZE } from '../src/shapes/image.ts';
import { encodePng, decodePng } from './fixtures/png-rgba.ts';
import { encodePlane, decodePlane } from '../src/shapes/png.ts';

const PIL = JSON.parse(readFileSync(new URL('./fixtures/shapes-pil-resize.json', import.meta.url), 'utf8'));

test('the bilinear resize matches Pillow byte for byte, shrinking and enlarging', () => {
  const source = Uint8Array.from(PIL.rgb);
  for (const target of [PIL.down, PIL.up]) {
    const out = resizeBilinear(source, PIL.width, PIL.height, 3, target.width, target.height);
    assert.deepEqual([...out], target.rgb, `${target.width}x${target.height}`);
  }
  const mask = PIL.mask;
  assert.deepEqual([...resizeBilinear(Uint8Array.from(mask.data), mask.width, mask.height, 1, mask.up.width, mask.up.height)], mask.up.data);
});

test('the encoder input is the image squashed to 1024 square, scaled to 0-1 and normalised per channel, channels first', () => {
  const width = 3, height = 2, rgba = new Uint8Array(width * height * 4);
  for (let i = 0; i < width * height; i++) rgba.set([255, 128, 0, i % 2 ? 0 : 255], i * 4);   // alpha is ignored, as RGB conversion does
  const input = encoderInput(rgba, width, height);
  assert.equal(ENCODER_SIZE, 1024);
  assert.equal(input.length, 3 * 1024 * 1024);
  const plane = 1024 * 1024;
  assert.ok(Math.abs(input[0] - (1 - 0.485) / 0.229) < 1e-5);
  assert.ok(Math.abs(input[plane + 5000] - (128 / 255 - 0.456) / 0.224) < 1e-5);
  assert.ok(Math.abs(input[2 * plane + plane - 1] - (0 - 0.406) / 0.225) < 1e-5);
});

test('a box prompt [x,y,w,h] becomes corners in 1024 space with no points; points carry their labels', () => {
  const box = decoderPrompt({ box: [100, 50, 200, 100] }, 2048, 1000);
  assert.deepEqual([...box.box], [50, 51.2, 150, 153.6].map(Math.fround));
  assert.equal(box.count, 0); assert.equal(box.points.length, 0); assert.equal(box.labels.length, 0);
  const points = decoderPrompt({ points: [[1024, 500, 1], [0, 0, 0]] }, 2048, 1000);
  assert.equal(points.box, null);
  assert.equal(points.count, 2);
  assert.deepEqual([...points.points], [512, 512, 0, 0]);
  assert.deepEqual([...points.labels], [1n, 0n]);
});

test('prompts outside the image or malformed are refused with a plain reason', () => {
  assert.doesNotThrow(() => checkPrompt({ box: [0, 0, 10, 10] }, 10, 10));
  assert.throws(() => checkPrompt({ box: [5, 5, 10, 10] }, 10, 10), /inside the reference/);
  assert.throws(() => checkPrompt({ box: [0, 0, 0, 4] }, 10, 10), /width and height/);
  assert.throws(() => checkPrompt({ points: [] }, 10, 10), /point/);
  assert.throws(() => checkPrompt({ points: [[1, 1, 2]] }, 10, 10), /label/);
  assert.throws(() => checkPrompt({ points: [[11, 1, 1]] }, 10, 10), /inside the reference/);
  assert.throws(() => checkPrompt({ box: [0, 0, 4, 4], points: [[1, 1, 1]] }, 10, 10), /box or points/);
  assert.throws(() => checkPrompt({}, 10, 10), /box or points/);
});

test('mask logits are thresholded at 0, resized to the image as the reference does, then bounded and cropped', () => {
  const size = 4, logits = new Float32Array(size * size).fill(-3);
  logits[1 * size + 1] = 2; logits[1 * size + 2] = 2; logits[2 * size + 1] = 2; logits[2 * size + 2] = 2;   // a 2x2 square in the middle
  const mask = maskFromLogits(logits, size, 8, 8);
  assert.equal(mask.length, 64);
  assert.ok(mask.every(v => v === 0 || v === 255));
  const bounds = maskBounds(mask, 8, 8);
  assert.deepEqual(bounds, [2, 2, 4, 4]);
  const crop = cropMask(mask, 8, bounds);
  assert.equal(crop.length, 16);
  assert.ok(crop.every(v => v === 255));
  assert.equal(maskBounds(new Uint8Array(16), 4, 4), null, 'an empty mask has no bounds');
});

test('a mask written with encodePlane reads back through the bounded decodePlane and the tests\' RGBA reader', () => {
  const data = Uint8Array.from({ length: 7 * 4 }, (_, i) => i % 3 ? 255 : 0), png = encodePlane({ width: 7, height: 4, data });
  assert.deepEqual([...decodePlane(png, { width: 7, height: 4 }).data], [...data]);
  assert.throws(() => decodePlane(png, { width: 6, height: 4 }), /larger/);
  assert.deepEqual(Array.from({ length: 28 }, (_, i) => decodePng(png).data[i * 4]), [...data]);
});

test('the tests\' PNG helper: an 8-bit grey PNG round-trips, and RGB and RGBA PNGs decode to RGBA', () => {
  const data = Uint8Array.from({ length: 5 * 3 }, (_, i) => (i * 37) % 256);
  const png = encodePng({ width: 5, height: 3, channels: 1, data });
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  const back = decodePng(png);
  assert.equal(back.width, 5); assert.equal(back.height, 3);
  for (let i = 0; i < 15; i++) assert.deepEqual([...back.data.subarray(i * 4, i * 4 + 4)], [data[i], data[i], data[i], 255]);
  const rgb = Uint8Array.from({ length: 4 * 2 * 3 }, (_, i) => (i * 53) % 256);
  const decoded = decodePng(encodePng({ width: 4, height: 2, channels: 3, data: rgb }));
  assert.deepEqual([...decoded.data.subarray(4, 8)], [rgb[3], rgb[4], rgb[5], 255]);
  const rgba = Uint8Array.from({ length: 2 * 2 * 4 }, (_, i) => (i * 29) % 256);
  assert.deepEqual([...decodePng(encodePng({ width: 2, height: 2, channels: 4, data: rgba })).data], [...rgba]);
  assert.throws(() => decodePng(Buffer.from('not a png')), /PNG/);
});

test('the mask is resized only where the shape can reach, with exactly the bytes of a whole resize', () => {
  let seed = 3; const random = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  for (const [width, height] of [[1448, 1086], [97, 300], [40, 20]]) {
    const size = 32, logits = new Float32Array(size * size).fill(-1);
    for (let y = 9; y < 20; y++) for (let x = 5; x < 14; x++) if (random() > 0.2) logits[y * size + x] = 1;
    const low = Uint8Array.from(logits, v => v > 0 ? 255 : 0);
    const whole = resizeBilinear(low, size, size, 1, width, height).map(v => v > 127 ? 255 : 0);
    assert.deepEqual(maskFromLogits(logits, size, width, height), whole, `${width}x${height}`);
  }
});

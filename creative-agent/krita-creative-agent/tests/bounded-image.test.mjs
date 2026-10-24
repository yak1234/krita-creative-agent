// A bounded copy of a large picture (bounded-image.ts): a goal sharpened 4x (25 million pixels) is reduced in the companion,
// once per content and size, for the tools that only need a working size (Find it, the masses, the likeness grid, the
// accents finder), so Krita's GUI thread never decodes the whole file for them. Every file goes to a temporary folder.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { boundedImage, boundedPixels, reduceRgba, BOUNDED_KEPT } from '../src/bounded-image.ts';
import { encodeRgba } from '../src/shapes/png.ts';
import { decodeRgba, pngSize } from '../src/png-rgba.ts';

const sha = data => createHash('sha256').update(data).digest('hex');
/** A w x h RGBA picture: red on the left half, blue on the right. */
function halves(width, height) {
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) data.set(x < width / 2 ? [255, 0, 0, 255] : [0, 0, 255, 255], (y * width + x) * 4);
  return { width, height, data };
}

test('reduceRgba averages each block of pixels to at most maxPixels, on the picture\'s proportions; clear pixels add no colour', () => {
  const small = reduceRgba(halves(400, 300), 30_000);
  assert.ok(small.width * small.height <= 30_000, `${small.width} x ${small.height}`);
  assert.ok(Math.abs(small.width / small.height - 4 / 3) < 0.02);
  const px = (x, y) => [...small.data.subarray((y * small.width + x) * 4, (y * small.width + x) * 4 + 4)];
  assert.deepEqual(px(2, 2), [255, 0, 0, 255]); assert.deepEqual(px(small.width - 3, 2), [0, 0, 255, 255]);
  // A fully clear green pixel beside an opaque red one: the average is red, half covered.
  const mixed = reduceRgba({ width: 2, height: 1, data: new Uint8Array([255, 0, 0, 255, 0, 255, 0, 0]) }, 1);
  assert.deepEqual([...mixed.data], [255, 0, 0, 128]);
  const same = halves(10, 10);
  assert.equal(reduceRgba(same, 1000), same, 'a picture already within bounds is returned as it is');
});

test('a large PNG gets one bounded copy in the chat folder, reused; a small one, or one only Krita reads, is used as it is', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'bounded-'));
  try {
    const big = join(directory, 'goal.png'), file = encodeRgba(halves(400, 300)); await writeFile(big, file);
    const copy = await boundedImage(directory, big, 30_000);
    assert.equal(copy.reduced, true); assert.equal(copy.source_sha256, sha(file));
    assert.ok(copy.path.startsWith(join(directory, '.bounded') + '/'), copy.path);
    assert.deepEqual(pngSize(await readFile(copy.path)), { width: copy.width, height: copy.height });
    assert.ok(copy.width * copy.height <= 30_000);
    assert.equal(copy.sha256, sha(await readFile(copy.path))); assert.equal(copy.sha256, sha(copy.data));
    const made = (await stat(copy.path)).mtimeMs;
    const again = await boundedImage(directory, big, 30_000);
    assert.deepEqual([again.path, again.sha256, (await stat(again.path)).mtimeMs], [copy.path, copy.sha256, made], 'reused, not made again');
    const pixels = await boundedPixels(directory, big, 30_000);
    assert.deepEqual([pixels.sha, pixels.pixels.width, pixels.pixels.height], [copy.sha256, copy.width, copy.height]);
    assert.deepEqual([...pixels.pixels.data.subarray(0, 4)], [255, 0, 0, 255]);
    // Within bounds: the file itself.
    const kept = await boundedImage(directory, big, 200_000);
    assert.deepEqual([kept.reduced, kept.path, kept.sha256], [false, big, sha(file)]);
    assert.equal((await boundedPixels(directory, big, 200_000)).pixels.width, 400);
    // Not a plain PNG this module reads (a JPEG here): the file itself, and no pixels from the companion.
    const jpeg = join(directory, 'goal.jpg'); await writeFile(jpeg, Buffer.from([255, 216, 255, 224, 0, 16, 1, 2, 3]));
    const other = await boundedImage(directory, jpeg, 30_000);
    assert.deepEqual([other.reduced, other.path], [false, jpeg]);
    assert.equal(await boundedPixels(directory, jpeg, 30_000), null);
    assert.equal(decodeRgba(copy.data).width, copy.width, 'the copy is a plain PNG');
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('only the newest bounded copies are kept', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'bounded-'));
  try {
    for (let i = 0; i < BOUNDED_KEPT + 2; i++) {
      const path = join(directory, `goal-${i}.png`), picture = halves(60 + i, 40);
      await writeFile(path, encodeRgba(picture));
      await boundedImage(directory, path, 600);
    }
    assert.equal((await readdir(join(directory, '.bounded'))).filter(n => n.endsWith('.png')).length, BOUNDED_KEPT);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

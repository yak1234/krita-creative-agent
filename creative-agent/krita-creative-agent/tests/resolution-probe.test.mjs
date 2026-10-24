// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The resolution probe (luna-goal-reviewer goal 3): a synthetic picture with fine detail of a fixed pixel size, at each
// probed size and as 1:1 crops; questions with known answers; the score; the sizes it recommends. And view-size.ts, which
// turns the setting and the recorded results into the view's long side and Luna's crop side.
import test from 'node:test';
import assert from 'node:assert/strict';
import { probeImage, probeCrops, probeQuestions, scoreProbe, recommendSides, PROBE_SIZES } from '../src/resolution-probe.ts';
import { resolvedViewSide, resolvedCropSide, modelKey, VIEW_SIDE_TODAY, MAX_VIEW_SIDE } from '../src/view-size.ts';
import { decodeRgba } from '../src/png-rgba.ts';
import { encodeRgba } from '../src/shapes/png.ts';

test('the probe picture: five framed boxes, each a digit and a row of dots of a fixed pixel size, answers known', () => {
  const { image, boxes } = probeImage({ width: 2048, height: 1536, seed: 7 });
  assert.deepEqual([image.width, image.height, image.data.length], [2048, 1536, 2048 * 1536 * 4]);
  assert.deepEqual(boxes.map(b => b.id), ['top_left', 'top_right', 'centre', 'bottom_left', 'bottom_right']);
  for (const b of boxes) {
    assert.ok(b.digit >= 0 && b.digit <= 9 && b.dots >= 1 && b.dots <= 9, JSON.stringify(b));
    const [x, y, w, h] = b.rect; assert.ok(x >= 0 && y >= 0 && x + w <= 2048 && y + h <= 1536);
  }
  // Same seed, same picture and answers; another seed, other answers.
  const again = probeImage({ width: 2048, height: 1536, seed: 7 });
  assert.deepEqual(again.boxes, boxes); assert.ok(Buffer.from(again.image.data).equals(Buffer.from(image.data)));
  assert.notDeepEqual(probeImage({ width: 2048, height: 1536, seed: 8 }).boxes.map(b => [b.digit, b.dots]), boxes.map(b => [b.digit, b.dots]));
  // The detail is the same size in pixels at every probed size: the boxes' content does not scale with the picture.
  const small = probeImage({ width: 1024, height: 768, seed: 7 });
  const inner = b => [b.rect[2] - 2 * b.frame, b.rect[3] - 2 * b.frame];
  assert.deepEqual(small.boxes.map(inner), boxes.map(inner));
  // A real PNG round trip: the digit's ink is there, dark on light.
  const decoded = decodeRgba(encodeRgba(image));
  const [bx, by, bw, bh] = boxes[2].rect; let dark = 0;
  for (let y = by; y < by + bh; y++) for (let x = bx; x < bx + bw; x++) if (decoded.data[(y * 2048 + x) * 4] < 80) dark++;
  assert.ok(dark > 40, 'ink in the centre box: ' + dark);
});

test('1:1 crops: each box at its own pixels, with a margin', () => {
  const probe = probeImage({ width: 2560, height: 1920, seed: 3 });
  const crops = probeCrops(probe);
  assert.equal(crops.length, 5);
  for (const [i, c] of crops.entries()) {
    assert.equal(c.id, probe.boxes[i].id);
    assert.ok(c.image.width > probe.boxes[i].rect[2] && c.image.width < 400, String(c.image.width));
  }
});

test('questions: a digit and a dot count a box, as choices; scored against the known answers', () => {
  const probe = probeImage({ width: 1024, height: 768, seed: 1 });
  const questions = probeQuestions(probe.boxes);
  assert.equal(questions.length, 10);
  assert.match(questions[0].text, /box at the top left/);
  assert.deepEqual(questions[0].options, ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']);
  assert.deepEqual(questions[1].options, ['1', '2', '3', '4', '5', '6', '7', '8', '9']);
  const right = Object.fromEntries(questions.map(q => [q.id, String(q.answer)]));
  assert.deepEqual(scoreProbe(questions, right), { correct: 10, total: 10, accuracy: 1 });
  const half = { ...right, [questions[0].id]: String((questions[0].answer + 1) % 10), [questions[1].id]: null };
  assert.deepEqual(scoreProbe(questions, half), { correct: 8, total: 10, accuracy: 0.8 });
  const crops = probeQuestions(probe.boxes, { crops: true });
  assert.match(crops[0].text, /CROP 1/);
});

test('the recommended sizes: the largest probed size the model reads as well as the 1:1 crops, the view capped', () => {
  assert.deepEqual(PROBE_SIZES, [1024, 1280, 1536, 1792, 2048, 2560]);
  const at = (accuracies, crops = 1) => ({ crops: { accuracy: crops }, sizes: Object.fromEntries(PROBE_SIZES.map((s, i) => [s, { accuracy: accuracies[i] }])) });
  const fill = (result, key, values) => { values.forEach((v, i) => { result.sizes[PROBE_SIZES[i]][key] = v; }); return result; };
  assert.deepEqual(recommendSides(at([1, 1, 1, 0.9, 0.5, 0.2])), { view_side: 1792, crop_side: 1536, reads: 1792 });
  assert.deepEqual(recommendSides(at([1, 1, 1, 1, 1, 1])), { view_side: 2000, crop_side: 1536, reads: 2560 }, 'the view stops at 2000 (Pi shrinks past it), a crop at 1536');
  assert.deepEqual(recommendSides(at([0.9, 0.5, 0.3, 0.1, 0.1, 0.1])), { view_side: 1024, crop_side: 1024, reads: 1024 });
  assert.deepEqual(recommendSides(at([1, 1, 0.5, 0.3, 0.1, 0.1])), { view_side: 1280, crop_side: 1280, reads: 1280 });
  assert.equal(recommendSides(at([0.2, 0.1, 0.1, 0.1, 0.1, 0.1], 0.3)), null, 'the crops not read either: the probe says nothing');
  // Input tokens that stop growing: the model shrinks larger pictures (deepseek-flash, live 2026-10-24: 1085, 1591, 1591, 1591).
  const tokens = fill(at([1, 1, 1, 0.9, 0.9, 0.5], 0.7), 'input_tokens', [1085, 1300, 1591, 1591, 1591, 1591]);
  assert.deepEqual(recommendSides(tokens), { view_side: 1536, crop_side: 1536, reads: 1536 });
  const growing = fill(at([1, 1, 1, 0.9, 0.9, 0.7], 0.9), 'input_tokens', [2768, 3200, 3729, 4400, 5073, 6801]);
  assert.deepEqual(recommendSides(growing), { view_side: 2000, crop_side: 1536, reads: 2048 }, 'Luna, live 2026-10-24');
  // Cached input counts (eyes-and-history 3a): Anthropic through OpenRouter reported 4 input tokens at every size while
  // the image went to the cache, so "tokens stopped growing" called claude-haiku-5.5 a 1024 reader at 10/10 up to 2560.
  const cached = fill(fill(at([1, 1, 1, 1, 1, 1]), 'input_tokens', [4, 4, 4, 4, 4, 4]), 'cache_write_tokens', [1200, 1800, 2600, 3500, 4600, 7100]);
  assert.deepEqual(recommendSides(cached), { view_side: 2000, crop_side: 1536, reads: 2560 });
  const read = fill(fill(at([1, 1, 1, 1, 1, 1]), 'input_tokens', [4, 4, 4, 4, 4, 4]), 'cache_read_tokens', [1200, 1800, 2600, 2600, 2600, 2600]);
  assert.deepEqual(recommendSides(read), { view_side: 1536, crop_side: 1536, reads: 1536 }, 'cache reads count too');
  // A dip below the bar at one size between sizes it reads is noise, not a limit: deepseek-flash scored 6/10 and 7/10 at
  // 1280 in two live runs (2026-10-24) and 10/10 and 9/10 at 1536, where its tokens stop growing (1591 from 1536 on).
  const dip = fill(fill(at([1, 0.6, 1, 0.9, 1, 0.6]), 'input_tokens', [189, 1327, 183, 1591, 183, 183]), 'cache_read_tokens', [896, 0, 1408, 0, 1408, 1408]);
  assert.deepEqual(recommendSides(dip), { view_side: 1536, crop_side: 1536, reads: 1536 });
  // No tokens reported: cost growth decides; a cost that stops growing means the picture was shrunk.
  const costs = fill(at([1, 1, 1, 1, 1, 1]), 'cost', [0.0004, 0.0005, 0.0006, 0.0006, 0.0006, 0.0006]);
  assert.deepEqual(recommendSides(costs), { view_side: 1536, crop_side: 1536, reads: 1536 });
  const neither = at([1, 1, 1, 1, 0.9, 0.9]);
  assert.deepEqual(recommendSides(neither), { view_side: 2000, crop_side: 1536, reads: 2560 }, 'no tokens and no cost: accuracy alone');
});

test('view-size: auto is the painter model’s measured side, else today’s; a chosen size is used as it is', () => {
  const records = { [modelKey('deepseek', 'deepseek-flash')]: { view_side: 2048, crop_side: 1024 }, [modelKey('openrouter', 'openai/gpt-6-luna-decisions')]: { crop_side: 1536 } };
  assert.equal(resolvedViewSide('auto', records[modelKey('deepseek', 'deepseek-flash')]), 2000, 'Pi shrinks past 2000 px');
  assert.equal(MAX_VIEW_SIDE, 2000);
  assert.equal(resolvedViewSide('auto', null), VIEW_SIDE_TODAY, 'not measured: today’s size');
  assert.equal(resolvedViewSide('auto', { view_side: 4000 }), MAX_VIEW_SIDE, 'never past the cap');
  assert.equal(resolvedViewSide(1024, records[modelKey('deepseek', 'deepseek-flash')]), 1024, 'the artist’s choice wins');
  assert.equal(resolvedCropSide(records[modelKey('openrouter', 'openai/gpt-6-luna-decisions')], 768), 1536);
  assert.equal(resolvedCropSide(null, 768), 768);
});

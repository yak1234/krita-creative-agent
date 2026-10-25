// /canvas-reference (openspec canvas-reference; the artist, 2026-10-25): an image model shows the canvas with an edit, as
// a reference the agent can paint toward; nothing is painted until the artist uses it. The module (src/canvas-reference.ts)
// with a fake host: no network, no Krita. Every test removes the folder it writes.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile, readdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { canvasReferenceRequest, editPrompt, differenceMask, canvasMask, compareImage, canvasReferencer, referenceMoveNote,
  CANVAS_REFERENCE_OPTIONS, WIDE_SHARE, MASK_RULES } from '../src/canvas-reference.ts';
import { decodeRgba } from '../src/png-rgba.ts';
import { decodePlane, encodeRgba } from '../src/shapes/png.ts';

/** A painting-like picture: a gradient with some structure, w x h RGBA. */
function picture(w, h) {
  const data = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4;
    data[i] = 40 + Math.round(120 * x / w); data[i + 1] = 60 + Math.round(80 * y / h); data[i + 2] = 120 + ((x >> 4) + (y >> 4)) % 2 * 30; data[i + 3] = 255;
  }
  return { width: w, height: h, data };
}
const copy = image => ({ ...image, data: image.data.slice() });
function paint(image, [x0, y0, w, h], rgb) {
  for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) { const i = (y * image.width + x) * 4; image.data.set(rgb, i); }
  return image;
}
/** The whole picture lighter and warmer: the drift an image model adds everywhere. */
function drift(image) {
  const out = copy(image);
  for (let i = 0; i < out.data.length; i += 4) { out.data[i] = Math.min(255, Math.round(out.data[i] * 1.08 + 9)); out.data[i + 1] = Math.min(255, Math.round(out.data[i + 1] * 1.05 + 6)); out.data[i + 2] = Math.round(out.data[i + 2] * 0.95); }
  return out;
}
const inside = (mask, x, y) => mask.data[y * mask.width + x] >= 128;

test('the command: an instruction, and "in <part>" at its end for an area', () => {
  assert.deepEqual(canvasReferenceRequest('/canvas-reference add more ghosts and ghost-like lighting'), { instruction: 'add more ghosts and ghost-like lighting', part: null });
  assert.deepEqual(canvasReferenceRequest('/canvas-reference more snow and crisp effects in the sky'), { instruction: 'more snow and crisp effects', part: 'the sky' });
  assert.deepEqual(canvasReferenceRequest('/Canvas-Reference: brighter windows in the left buildings.'), { instruction: 'brighter windows', part: 'the left buildings' });
  assert.deepEqual(canvasReferenceRequest('/skill:canvas-reference add a moon'), { instruction: 'add a moon', part: null }, 'the skill\'s own spelling too');
  assert.deepEqual(canvasReferenceRequest('/canvas-reference'), { instruction: '', part: null }, 'alone: the studio says how to use it');
  assert.equal(canvasReferenceRequest('add more ghosts'), null);
  assert.equal(canvasReferenceRequest('/refine the sky'), null);
  assert.deepEqual(canvasReferenceRequest('/canvas-reference paint him in a ghostly light'), { instruction: 'paint him in a ghostly light', part: null }, 'only "in the …" names an area');
});

test('the edit prompt asks for the change and keeps everything else identical', () => {
  const prompt = editPrompt('add more ghosts', null);
  assert.match(prompt, /add more ghosts/);
  for (const kept of [/composition/, /faces?/, /style/, /light/, /framing|crop/]) assert.match(prompt, kept);
  assert.match(prompt, /unless the change asks for it|except where the change asks/i, 'the light changes only when asked');
  assert.match(editPrompt('more snow', 'the sky'), /only in the sky/);
});

test('the difference mask finds the changed area, ignores a global tone drift, drops specks and grows a little', () => {
  const canvas = picture(200, 150);
  const reference = paint(drift(canvas), [100, 40, 40, 30], [250, 250, 250]);
  for (const [x, y] of [[20, 20], [160, 120], [30, 130]]) paint(reference, [x, y, 2, 2], [0, 0, 0]);   // the model's specks
  const mask = differenceMask(canvas, reference);
  assert.equal(mask.width, 200); assert.equal(mask.height, 150);
  assert.ok(inside(mask, 120, 55), 'the changed patch'); assert.ok(inside(mask, 100, 40) && inside(mask, 139, 69), 'to its corners');
  assert.ok(inside(mask, 98, 38), 'grown a little past its edge');
  assert.ok(!inside(mask, 60, 100) && !inside(mask, 10, 140), 'the drift elsewhere is no change');
  assert.ok(!inside(mask, 21, 21) && !inside(mask, 161, 121) && !inside(mask, 31, 131), 'specks are cleaned away');
  const patch = 40 * 30 / (200 * 150);
  assert.ok(mask.share > patch && mask.share < patch * 2.2, 'about the patch, dilated: ' + mask.share);
  const [bx, by, bw, bh] = mask.bounds;
  assert.ok(bx <= 100 && by <= 40 && bx + bw >= 140 && by + bh >= 70 && bw < 60 && bh < 50, 'its bounds: ' + mask.bounds);
  assert.ok(MASK_RULES.threshold > 0 && MASK_RULES.dilate > 0 && MASK_RULES.speck > 0);
});

test('no change but the drift is an empty mask; a whole new picture covers most of the canvas', () => {
  const canvas = picture(120, 90);
  const same = differenceMask(canvas, drift(canvas));
  assert.equal(same.share, 0); assert.equal(same.bounds, null);
  const inverted = copy(canvas);
  for (let i = 0; i < inverted.data.length; i += 4) { inverted.data[i] = 255 - inverted.data[i]; inverted.data[i + 1] = 255 - inverted.data[i + 1]; }
  const other = differenceMask(canvas, inverted);
  assert.ok(other.share > WIDE_SHARE, 'a different picture: ' + other.share);
});

test('an area ("in the sky") keeps the mask inside it', () => {
  const canvas = picture(200, 150);
  const reference = paint(paint(copy(canvas), [20, 10, 40, 30], [255, 255, 255]), [120, 100, 40, 30], [255, 255, 255]);
  const within = new Uint8Array(200 * 150); for (let y = 0; y < 60; y++) within.fill(255, y * 200, (y + 1) * 200);   // the top: "the sky"
  const mask = differenceMask(canvas, reference, { within });
  assert.ok(inside(mask, 40, 25)); assert.ok(!inside(mask, 140, 115), 'the change outside the area is not the target');
});

test('the mask at canvas size: its bounds on the canvas and one byte a pixel inside them', () => {
  const canvas = picture(100, 75), reference = paint(copy(canvas), [50, 25, 20, 20], [255, 255, 255]);
  const mask = differenceMask(canvas, reference);
  const area = canvasMask(mask, [400, 300]);
  const [x, y, w, h] = area.bounds;
  assert.equal(area.plane.width, w); assert.equal(area.plane.height, h); assert.equal(area.plane.data.length, w * h);
  assert.ok(x <= 200 && y <= 100 && x + w >= 280 && y + h >= 180 && x + w <= 400 && y + h <= 300, 'scaled 4x: ' + area.bounds);
  assert.equal(area.plane.data[(140 - y) * w + (240 - x)], 255, 'inside the change');
  assert.ok(Math.abs(area.share - mask.share) < 0.02);
});

test('the compare picture: the canvas and the reference side by side, the changed area outlined', () => {
  const canvas = picture(160, 120), reference = paint(copy(canvas), [60, 40, 30, 30], [255, 255, 255]);
  const mask = differenceMask(canvas, reference);
  const image = compareImage(canvas, reference, mask, { side: 200 });
  assert.equal(image.data.length, image.width * image.height * 3);
  assert.ok(image.width > 2 * 150 && image.width <= 2 * 200 + 16, 'two pictures in one row: ' + image.width);
  let red = 0; for (let i = 0; i < image.data.length; i += 3) if (image.data[i] > 200 && image.data[i + 1] < 80 && image.data[i + 2] < 80) red++;
  assert.ok(red > 40, 'an outline is drawn: ' + red);
});

// ----- the card ---------------------------------------------------------------------------------------------------------

async function fakeHost({ changed = [[100, 40, 40, 30]], wide = false, backend = 'codex', busy = false } = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'canvas-reference-'));
  const canvas = picture(200, 150), view = join(directory, 'view.png');
  await writeFile(view, encodeRgba(canvas));
  const events = [], generated = [], used = [], discarded = [];
  const goal = { limits: { ai_images: 3 }, ai_images_used: 0 };
  const host = {
    study: { directory }, goal, events, generated, used, discarded,
    backend: () => backend,
    allowance() { if (goal.ai_images_used >= goal.limits.ai_images) throw new Error('This chat\'s AI image allowance (3) is used up.'); },
    observe: async () => ({ image_path: view, width: 800, height: 600 }),
    async generate(request) {
      generated.push(request);
      let out = drift(canvas);
      for (const r of changed) out = paint(out, r, [250, 250, 250]);
      if (wide) for (let i = 0; i < out.data.length; i += 4) { out.data[i] = 255 - out.data[i]; out.data[i + 1] = 255 - out.data[i + 1]; }
      // An image model answers at its own size (Codex: 1536 x 1024): the module scales it to the canvas.
      return { data: encodeRgba(out), model: 'codex/test' };
    },
    decode: async data => decodeRgba(data),
    emit: event => events.push(event), persist: async () => {}, publish() {},
    busy: () => busy,
    async use(record, area) { used.push({ record, area }); },
    async discarded(record) { discarded.push(record); },
  };
  return { host, directory, close: () => rm(directory, { recursive: true, force: true }) };
}
const cards = host => host.events.filter(e => e.type === 'canvas_reference');

test('a canvas reference: the canvas goes to the image model with the edit prompt, and the card waits for the artist', async () => {
  const { host, directory, close } = await fakeHost();
  try {
    const referencer = canvasReferencer(host);
    await referencer.start({ instruction: 'add more ghosts', part: null });
    assert.equal(host.generated.length, 1);
    assert.match(host.generated[0].prompt, /add more ghosts/); assert.equal(host.generated[0].input.mimeType, 'image/png');
    assert.deepEqual(host.generated[0].input.data, await readFile(join(directory, 'view.png')), 'the canvas as observed');
    assert.equal(host.generated[0].aspect, '4:3', 'the canvas\'s proportions');
    assert.equal(host.goal.ai_images_used, 1, 'counted against the allowance');
    const [card] = cards(host);
    assert.deepEqual(card.options, [CANVAS_REFERENCE_OPTIONS.use, CANVAS_REFERENCE_OPTIONS.retry, CANVAS_REFERENCE_OPTIONS.discard]);
    assert.deepEqual(card.options, ['Use as the target', 'Try again', 'Discard']);
    assert.equal(card.auto_approve, false, 'never answered by Auto-approve');
    assert.ok(existsSync(card.image_path), 'the side-by-side picture');
    assert.match(card.message, /add more ghosts/); assert.match(card.message, /\d+% of the canvas/);
    assert.match(card.message, /ChatGPT/, 'the first use in a chat says where the canvas went');
    assert.ok(card.share > 0 && card.share < WIDE_SHARE); assert.equal(card.wide, false);
    const record = host.goal.canvas_references[card.id];
    assert.equal(record.state, 'ready');
    const reference = decodeRgba(await readFile(record.reference_path));
    assert.equal(reference.width / reference.height, 800 / 600, 'the reference has the canvas\'s exact proportions');
    await referencer.start({ instruction: 'more snow', part: null });
    assert.doesNotMatch(cards(host)[1].message, /ChatGPT/, 'the notice is said once a chat');
  } finally { await close(); }
});

test('OpenRouter is named in the notice when it is the image backend', async () => {
  const { host, close } = await fakeHost({ backend: 'openrouter' });
  try {
    await canvasReferencer(host).start({ instruction: 'add more ghosts', part: null });
    assert.match(cards(host)[0].message, /OpenRouter/);
  } finally { await close(); }
});

test('a change over most of the canvas is warned about in the card', async () => {
  const { host, close } = await fakeHost({ wide: true });
  try {
    await canvasReferencer(host).start({ instruction: 'more snow and crisp effects', part: null });
    const [card] = cards(host);
    assert.equal(card.wide, true);
    assert.match(card.message, /changed a lot/); assert.match(card.message, /narrower instruction|an area/);
  } finally { await close(); }
});

test('Try again makes a new picture with the same instruction and counts it; Discard drops it', async () => {
  const { host, close } = await fakeHost();
  try {
    const referencer = canvasReferencer(host);
    await referencer.start({ instruction: 'add more ghosts', part: null });
    const first = cards(host)[0];
    await referencer.answer({ id: first.id, action: 'retry' });
    assert.equal(host.generated.length, 2); assert.equal(host.generated[1].prompt, host.generated[0].prompt, 'the same instruction');
    assert.equal(host.goal.ai_images_used, 2);
    assert.ok(!existsSync(first.image_path), 'the first picture is gone');
    const second = cards(host)[1];
    assert.notEqual(second.id, first.id);
    await referencer.answer({ id: first.id, action: 'use' });
    assert.equal(host.used.length, 0, 'a replaced card is no longer answered');
    await referencer.answer({ id: second.id, action: 'discard' });
    assert.equal(host.goal.canvas_references[second.id].state, 'discarded');
    assert.ok(!existsSync(second.image_path) && !existsSync(host.goal.canvas_references[second.id].reference_path));
    assert.equal(host.discarded.length, 1); assert.equal(host.used.length, 0);
  } finally { await close(); }
});

test('the allowance is checked before anything is sent', async () => {
  const { host, close } = await fakeHost();
  try {
    host.goal.ai_images_used = 3;
    await assert.rejects(canvasReferencer(host).start({ instruction: 'add more ghosts', part: null }), /allowance/);
    assert.equal(host.generated.length, 0);
  } finally { await close(); }
});

test('Use as the target hands the host the difference area at canvas size and the reference', async () => {
  const { host, directory, close } = await fakeHost();
  try {
    const referencer = canvasReferencer(host);
    await referencer.start({ instruction: 'add more ghosts', part: null });
    const card = cards(host)[0];
    await referencer.answer({ id: card.id, action: 'use' });
    assert.equal(host.used.length, 1);
    const { record, area } = host.used[0];
    assert.equal(record.state, 'used');
    assert.deepEqual(area.canvas, [800, 600]);
    const [x, y, w, h] = area.bounds;
    assert.ok(x <= 400 && y <= 160 && x + w >= 560 && y + h >= 280 && w < 300, 'the change, at 4x: ' + area.bounds);
    const plane = decodePlane(await readFile(area.mask_path), { width: w, height: h });
    assert.equal(plane.width, w);
    assert.ok(area.mask_path.startsWith(directory));
    const note = referenceMoveNote(record, { asset_id: 'asset-1234abcd', canvas: [800, 600] });
    assert.match(note, /asset-1234abcd/); assert.match(note, /add more ghosts/); assert.match(note, /paint_from_reference/);
    assert.match(note, /target \[0,0,800,600\]/); assert.match(note, /only inside/i);
    await referencer.answer({ id: card.id, action: 'use' });
    assert.equal(host.used.length, 1, 'answered once');
  } finally { await close(); }
});

test('while a move paints, Use waits: the card is shown again', async () => {
  const { host, close } = await fakeHost({ busy: true });
  try {
    const referencer = canvasReferencer(host);
    await referencer.start({ instruction: 'add more ghosts', part: null });
    await referencer.answer({ id: cards(host)[0].id, action: 'use' });
    assert.equal(host.used.length, 0);
    assert.equal(cards(host).length, 2, 'offered again'); assert.equal(cards(host)[1].id, cards(host)[0].id);
  } finally { await close(); }
});

test('no visible change: the card offers only Try again and Discard', async () => {
  const { host, close } = await fakeHost({ changed: [] });
  try {
    await canvasReferencer(host).start({ instruction: 'add more ghosts', part: null });
    const [card] = cards(host);
    assert.deepEqual(card.options, ['Try again', 'Discard']); assert.match(card.message, /no clear change/);
  } finally { await close(); }
});

test('"in <part>" compares only the found area; a part not found compares the whole canvas and says so', async () => {
  const { host, directory, close } = await fakeHost({ changed: [[20, 10, 40, 30], [120, 100, 40, 30]] });
  try {
    const top = new Uint8Array(800 * 240).fill(255), maskPath = join(directory, 'found.png');
    const { encodePlane } = await import('../src/shapes/png.ts');
    await writeFile(maskPath, encodePlane({ width: 800, height: 240, data: top }));
    host.findArea = async part => part === 'the sky' ? { mask_path: maskPath, bounds: [0, 0, 800, 240], canvas: [800, 600] } : null;
    const referencer = canvasReferencer(host);
    await referencer.start({ instruction: 'more snow', part: 'the sky' });
    assert.match(host.generated[0].prompt, /only in the sky/);
    const sky = cards(host)[0];
    assert.ok(sky.bounds[1] + sky.bounds[3] <= 240, 'the change in the sky only (canvas pixels): ' + sky.bounds);
    await referencer.start({ instruction: 'more snow', part: 'the lake' });
    assert.match(cards(host)[1].message, /the lake was not found/i);
    assert.ok(cards(host)[1].share > sky.share);
  } finally { await close(); }
});

test('a record from a step that held the plan keeps the step', async () => {
  const { host, close } = await fakeHost();
  try {
    const referencer = canvasReferencer(host);
    await referencer.start({ instruction: 'snow on the roofs', part: null, step_key: 'add:snow' });
    const card = cards(host)[0];
    assert.equal(host.goal.canvas_references[card.id].step_key, 'add:snow');
    assert.match(card.message, /before the step paints|plan step/i);
    await referencer.answer({ id: card.id, action: 'retry' });
    assert.equal(host.goal.canvas_references[cards(host)[1].id].step_key, 'add:snow', 'Try again keeps it');
  } finally { await close(); }
});

test('files stay in the chat folder\'s canvas-reference folder', async () => {
  const { host, directory, close } = await fakeHost();
  try {
    await canvasReferencer(host).start({ instruction: 'add more ghosts', part: null });
    const names = await readdir(join(directory, 'canvas-reference'));
    assert.ok(names.length >= 1);
  } finally { await close(); }
});

test('a change over a third of a flat picture is not cancelled by the tone matching', () => {
  const canvas = paint(picture(120, 90), [0, 0, 120, 90], [90, 90, 120]);
  const reference = paint(copy(canvas), [0, 0, 40, 90], [240, 240, 250]);           // snow over the left third
  const mask = differenceMask(canvas, reference);
  assert.ok(inside(mask, 20, 45) && !inside(mask, 100, 45), 'the left third only');
  assert.ok(mask.share > 0.3 && mask.share < 0.45, String(mask.share));
});

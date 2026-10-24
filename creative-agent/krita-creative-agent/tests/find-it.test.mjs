// Find it for me (find-it.ts, find-it-locate.ts): a named part located by a decision model's numbered grid, each confident
// cell one point for the shapes model, leaking masks dropped, the rest merged and cleaned, resampled to the canvas and cached
// per view; a clicked point is one prompt. A fake shapes service and a fake decider; every file goes to a temporary folder.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { findArea, promptsFromCells, cleanMask, leakShare, toCanvas, timingLine, readFound, foundPath, checkRequest, FindError, POSITIVE, NEGATIVE } from '../src/find-it.ts';
import { decisionLocator, gridPicture, gridSize, cellRect, unanswered, GRID_CELLS, LOCATE_PIXELS } from '../src/find-it-locate.ts';
import { decodePlane, encodePlane } from '../src/shapes/png.ts';
import { pngSize } from '../src/png-rgba.ts';

// The scene, in view pixels (64 x 48; the canvas is 128 x 96): the sky above y 20, a tower x 40-47 from y 8 down, ground.
const VW = 64, VH = 48, CW = 128, CH = 96;
const inTower = (x, y) => x >= 40 && x < 48 && y >= 8;
const region = which => (x, y) => which === 'sky' ? y < 20 && !inTower(x, y) : which === 'tower' ? inTower(x, y) : which === 'all' ? true : y >= 20 && !inTower(x, y);
function fakeShapes(folder) {
  const calls = { study: 0, shape: [] };
  const service = {
    async study() { calls.study++; return { ms: 1, load_ms: 0, peak_mb: 1, provider: 'cpu', studied: true, attempt: 1 }; },
    async shape(_id, prompt) {
      calls.shape.push(prompt);
      const [x, y] = prompt.points[0];
      // a point in the top-right corner gets a mask that leaks over everything; a speck far off rides with every sky mask
      const which = x > 56 && y < 8 ? 'all' : inTower(x, y) ? 'tower' : y < 20 ? 'sky' : 'ground', inside = region(which);
      const full = new Uint8Array(VW * VH);
      for (let j = 0; j < VH; j++) for (let i = 0; i < VW; i++) if (inside(i, j)) full[j * VW + i] = 255;
      if (which === 'sky') full[40 * VW + 5] = 255;
      let x0 = VW, y0 = VH, x1 = -1, y1 = -1;
      for (let j = 0; j < VH; j++) for (let i = 0; i < VW; i++) if (full[j * VW + i]) { x0 = Math.min(x0, i); y0 = Math.min(y0, j); x1 = Math.max(x1, i); y1 = Math.max(y1, j); }
      const w = x1 - x0 + 1, h = y1 - y0 + 1, crop = new Uint8Array(w * h);
      for (let j = 0; j < h; j++) crop.set(full.subarray((y0 + j) * VW + x0, (y0 + j) * VW + x0 + w), j * w);
      const mask_path = join(folder, `mask-${calls.shape.length}.png`);
      await writeFile(mask_path, encodePlane({ width: w, height: h, data: crop }));
      return { bounds: [x0, y0, w, h], score: 0.97, mask_path, model: 'fake', revision: 'r', ms: 2, peak_mb: 1, provider: 'cpu', cached: false };
    },
    async forget() {}, async close() {},
  };
  return { service, calls };
}
const { cols, rows } = gridSize(VW, VH);
/** The fake decider's answers: rows 0-1 are the sky except the tower's cell, row 2 is unsure, the rest is not the sky. */
function skyCells() {
  return Array.from({ length: cols * rows }, (_, i) => {
    const r = Math.floor(i / cols), c = i % cols;
    return r === 0 ? 0.95 : r === 1 ? (c === 5 ? 0.1 : 0.9) : r === 2 ? 0.4 : 0.02;
  });
}
async function harness({ locate } = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'find-it-'));
  const { service, calls } = fakeShapes(directory);
  const view = join(directory, 'view.png'); await writeFile(view, 'view');
  const host = { directory, shapes: service, shapeStudies: new Map(),
    view: async () => ({ path: view, width: CW, height: CH, revision: 'rev-1' }),
    pixels: async () => ({ sha: 'a'.repeat(64), pixels: { width: VW, height: VH, data: new Uint8Array(VW * VH * 4) } }),
    locate: locate === undefined ? async () => ({ cols, rows, p: skyCells(), ms: 5, model: 'fake-luna' }) : locate };
  return { host, calls, directory, close: () => rm(directory, { recursive: true, force: true }) };
}
const at = (plane, bounds, x, y) => { const [bx, by, bw] = bounds; return plane.data[(y - by) * bw + (x - bx)]; };

test('the grid is about 48 cells on the canvas\'s proportions, numbered in yellow over the view', () => {
  assert.equal(GRID_CELLS, 48);
  assert.deepEqual(gridSize(1024, 768), { cols: 8, rows: 6 });
  assert.deepEqual(gridSize(768, 1024), { cols: 6, rows: 8 });
  assert.deepEqual(cellRect(9, 8, 6, 1024, 768), [128, 128, 256, 256]);
  const view = { width: 320, height: 240, data: new Uint8Array(320 * 240 * 4) };
  const picture = gridPicture(view, 8, 6);
  assert.equal(picture.data.length, 320 * 240 * 3);
  const px = (x, y) => [...picture.data.subarray((y * 320 + x) * 3, (y * 320 + x) * 3 + 3)];
  assert.deepEqual(px(40, 100), [255, 230, 0], 'a grid line');
  assert.deepEqual(px(20, 100), [0, 0, 0], 'the picture itself between lines');
  let yellow = 0;
  for (let y = 5; y < 35; y++) for (let x = 5; x < 35; x++) if (px(x, y)[0] === 255) yellow++;
  assert.ok(yellow > 4, 'cell 1 carries its number');
});

test('the decision locator asks one question a cell in one request with the numbered picture, and gives up on a fallback', async () => {
  const requests = [];
  const decider = { async decide(request) {
    requests.push(request);
    return { answers: Object.fromEntries(Object.keys(request.questions).map((name, i) => [name, { type: 'noul', noul: i < 8 ? 0.9 : 0.05 }])), model: 'luna' };
  } };
  const locate = decisionLocator(async () => decider);
  const cells = await locate('the sky.', { width: 64, height: 48, data: new Uint8Array(64 * 48 * 4) });
  assert.equal(requests.length, 1); assert.equal(requests[0].purpose, 'find-it');
  assert.equal(Object.keys(requests[0].questions).length, 48);
  assert.match(requests[0].questions.cell_12.instructions, /^Is cell 12 \(the yellow-outlined cell labelled 12\) mostly the sky\?$/);
  assert.equal(requests[0].parts.filter(p => typeof p === 'object').length, 1, 'one picture');
  assert.match(requests[0].parts[0], /8 columns and 6 rows/);
  assert.deepEqual([cells.cols, cells.rows, cells.p.length, cells.p[0], cells.p[47], cells.model], [8, 6, 48, 0.9, 0.05, 'luna']);
  assert.deepEqual(cells.picture, { width: 64, height: 48, bytes: Buffer.from(requests[0].parts[1].data, 'base64').length });
  // No answer comes back with why, for the diagnostics.
  const view = { width: 64, height: 48, data: new Uint8Array(64 * 48 * 4) };
  const refused = await decisionLocator(async () => ({ decide: async () => ({ fallback: 'images_unverified' }) }))('the sky', view);
  assert.equal(unanswered(refused), true); assert.equal(refused.fallback, 'images_unverified');
  const failed = await decisionLocator(async () => ({ decide: async () => ({ fallback: 'service_or_response_error', status: 413 }) }))('the sky', view);
  assert.deepEqual([failed.fallback, failed.status, failed.picture.width], ['service_or_response_error', 413, 64]);
  const thrown = await decisionLocator(async () => ({ decide: async () => { throw new TypeError('fetch failed'); } }))('the sky', view);
  assert.deepEqual([thrown.fallback, thrown.error], ['service_or_response_error', 'TypeError']);
  assert.equal((await decisionLocator(async () => null)('the sky', view)).fallback, 'not_connected');
});

test('the locator\'s picture is at most LOCATE_PIXELS whatever the view\'s size; its cells are proportions of the view', async () => {
  // LIVE rehearsal 2 (2026-10-24): a goal sharpened 4x was looked at as 2309 x 1732, and its 9.7 MB grid picture got no answer.
  const requests = [];
  const decider = { async decide(request) { requests.push(request); return { answers: { cell_1: { type: 'noul', noul: 0.9 } }, model: 'luna' }; } };
  const width = 2309, height = 1732, view = { width, height, data: new Uint8Array(width * height * 4) };
  const cells = await decisionLocator(async () => decider)('the sky', view);
  const sent = pngSize(Buffer.from(requests[0].parts[1].data, 'base64'));
  assert.ok(sent.width * sent.height <= LOCATE_PIXELS, `${sent.width} x ${sent.height}`);
  assert.ok(Math.abs(sent.width / sent.height - width / height) < 0.01, 'on the view\'s proportions');
  assert.deepEqual([cells.picture.width, cells.picture.height], [sent.width, sent.height]);
  assert.deepEqual([cells.cols, cells.rows], [gridSize(width, height).cols, gridSize(width, height).rows], 'the grid follows the view');
  assert.equal(cells.p[0], 0.9);
});

test('one point a confident cell, strongest first; the confident "not" cells guard against leaks', () => {
  const p = Array(48).fill(0.5); p[3] = 0.7; p[1] = 0.95; p[40] = 0.1; p[47] = NEGATIVE;
  const { prompts, negatives } = promptsFromCells({ cols: 8, rows: 6, p, ms: 0 }, 1024, 768);
  assert.deepEqual(prompts, [[[192, 64, 1]], [[448, 64, 1]]]);
  assert.deepEqual(negatives, [40, 47]);
  assert.equal(POSITIVE, 0.6);
  assert.deepEqual(promptsFromCells({ cols: 8, rows: 6, p: Array(48).fill(0.3), ms: 0 }, 1024, 768).prompts, []);
});

test('cleaning keeps the pieces holding a seed and fills small holes', () => {
  const w = 40, h = 30, mask = new Uint8Array(w * h);
  for (let y = 0; y < 10; y++) for (let x = 0; x < w; x++) mask[y * w + x] = 255;
  mask[4 * w + 20] = 0;                                     // a one-pixel hole in the sky
  mask[25 * w + 5] = 255;                                    // a speck far off
  cleanMask(mask, w, h, [[3, 3, 1]]);
  assert.equal(mask[4 * w + 20], 255, 'the hole is filled');
  assert.equal(mask[25 * w + 5], 0, 'the speck goes');
  assert.equal(mask[0], 255);
  assert.equal(leakShare({ bounds: [0, 0, 4, 4], data: new Uint8Array(16).fill(255) }, { cols: 2, rows: 2 }, [0], 8, 8), 1);
  const canvas = toCanvas(mask, { width: w, height: h }, { width: 80, height: 60 });
  assert.deepEqual(canvas.bounds, [0, 0, 80, 20]);
});

test('a named part: merged from its cells on one study, leaks dropped, specks cleaned, resampled to the canvas, then cached', async () => {
  const h = await harness();
  try {
    const found = await findArea(h.host, { part: 'The sky' });
    assert.equal(h.calls.study, 1, 'the view is studied once');
    assert.equal(h.calls.shape.length, 15, 'one prompt a confident cell (rows 0 and 1 but the tower’s cell)');
    assert.ok(h.calls.shape.every(prompt => prompt.points.length === 1 && prompt.points[0][2] === 1));
    assert.equal(found.prompts, 15); assert.equal(found.kept, 14, 'the mask that leaked over the ground is dropped');
    assert.deepEqual(found.bounds, [0, 0, CW, 40]); assert.deepEqual(found.canvas, [CW, CH]);
    assert.equal(found.part, 'The sky'); assert.equal(found.cached, false); assert.equal(found.located_by, 'fake-luna');
    assert.ok(foundPath(h.directory, found.mask_path), 'the chat folder’s .shapes/found-*.png');
    const plane = await readFound(h.directory, found);
    assert.equal(at(plane, found.bounds, 10, 10), 255);
    assert.equal(at(plane, found.bounds, 85, 30), 0, 'not the tower');
    assert.equal(at(plane, found.bounds, 85, 8), 255, 'the sky above the tower');
    assert.ok(found.share > 0.35 && found.share < 0.42, String(found.share));
    assert.ok(found.ms.total >= found.ms.shapes && 'locate' in found.ms);
    assert.match(timingLine(found), /^Found The sky in \d+\.\d s \(locating \d+\.\d s, shapes model \d+\.\d s\): 3\d% of the canvas\.$/);
    const again = await findArea(h.host, { part: 'the sky ' });
    assert.equal(again.cached, true); assert.equal(h.calls.shape.length, 15, 'no model on the same view');
    assert.equal(again.mask_path, found.mask_path); assert.deepEqual(again.bounds, found.bounds);
    assert.match(timingLine(again), /again at once/);
  } finally { await h.close(); }
});

test('a clicked point is one prompt in view pixels, the object under it', async () => {
  const h = await harness({ locate: null });
  try {
    const found = await findArea(h.host, { points: [[86, 60, 1]] });
    assert.deepEqual(h.calls.shape, [{ points: [[43, 30, 1]] }]);
    assert.deepEqual(found.bounds, [80, 16, 16, 80]);
    assert.equal(found.part, null);
    assert.match(timingLine(found), /^Found the part you clicked in .*shapes model/);
    assert.doesNotMatch(timingLine(found), /locating/);
  } finally { await h.close(); }
});

test('refusals the panel shows as they are: no locator for a name, nothing confident, an invalid click, no painting', async () => {
  const h = await harness({ locate: null });
  try {
    await assert.rejects(findArea(h.host, { part: 'the sky' }), e => e instanceof FindError && e.code === 'no_locator' && /Select it with the Freehand tool instead\.$/.test(e.message));
    h.host.locate = async () => null;
    await assert.rejects(findArea(h.host, { part: 'the sky' }), /did not answer where the sky is\. Try again, or select it with the Freehand tool\.$/);
    // The reason travels with the error for the diagnostics; the canvas click it once offered is gone from every message.
    h.host.locate = async () => ({ fallback: 'timeout', ms: 4003, picture: { width: 1024, height: 768, bytes: 3_000_000 } });
    await assert.rejects(findArea(h.host, { part: 'the sky' }), e => e.code === 'no_locator' && e.reason.fallback === 'timeout' && e.reason.ms === 4003
      && !/canvas/.test(e.message));
    h.host.locate = async () => ({ cols, rows, p: Array(cols * rows).fill(0.3), ms: 1 });
    await assert.rejects(findArea(h.host, { part: 'the sky' }), e => e.code === 'not_found' && /Freehand tool\.$/.test(e.message));
    await assert.rejects(findArea(h.host, { points: [[500, 10, 1]] }), /inside the painting/);
    await assert.rejects(findArea(h.host, { points: [[5, 10, 0]] }), /on the part itself/);
    await assert.rejects(findArea(h.host, { part: '  ' }), /Say what to find/);
    assert.equal(h.calls.shape.length, 0, 'nothing reached the model');
    h.host.view = async () => ({ path: null, width: 0, height: 0 });
    await assert.rejects(findArea(h.host, { part: 'the sky' }), /Open your painting first/);
    assert.deepEqual(checkRequest({ part: '  The   Sky ' }, { width: 1, height: 1 }), { part: 'the sky' });
  } finally { await h.close(); }
});

test('found areas are kept to the newest eight in .shapes, each with its record', async () => {
  const h = await harness({ locate: null });
  try {
    for (let i = 0; i < 10; i++) await findArea(h.host, { points: [[10 + i, 10, 1]] });
    const names = await readdir(join(h.directory, '.shapes'));
    assert.equal(names.filter(n => /^found-[0-9a-f]{24}\.png$/.test(n)).length, 8);
    assert.equal(names.filter(n => /^found-[0-9a-f]{24}\.json$/.test(n)).length, 8);
    await assert.rejects(readFound(h.directory, { mask_path: join(h.directory, 'mask-1.png'), bounds: [0, 0, 1, 1] }), /only from this chat folder/);
    const plane = decodePlane(await readFile(join(h.directory, 'mask-1.png')));
    assert.ok(plane.width > 0);
  } finally { await h.close(); }
});

// Rehearsal finding 4 (Toska, 2026-10-24): "the sky" on the dabbed canvas found the moon, the towers and a spire (4%); on
// the sharp goal the same request found the sky (21%). With a goal placed by a whole-picture transfer, a named part is
// found on the GOAL and its mask mapped onto the canvas through that transfer's source -> target placement.
test('a named part is found on the goal and mapped through its transfer placement; without a goal, on the canvas', async () => {
  const h = await harness();
  try {
    const goal = join(h.directory, 'goal.png'); await writeFile(goal, 'goal');
    const seen = [];
    h.host.pixels = async path => { seen.push(path); return { sha: (path === goal ? 'g' : 'a').repeat(64), pixels: { width: VW, height: VH, data: new Uint8Array(VW * VH * 4) } }; };
    // The goal is 256 x 192 (its view 64 x 48); a crop of it [64,48,128,96] was transferred onto the whole 128 x 96 canvas.
    h.host.goal = async () => ({ path: goal, width: 256, height: 192, placement: { source: [64, 48, 128, 96], target: [0, 0, CW, CH] } });
    const found = await findArea(h.host, { part: 'the sky' });
    assert.deepEqual(seen, [goal], 'the goal is read, never the canvas view');
    assert.equal(found.found_on, 'goal');
    // The sky (view y < 20) is goal y < 80, canvas y < 32 under this placement; the tower (view x 40-47) is canvas x 96-127.
    const plane = await readFound(h.directory, found);
    assert.deepEqual(found.canvas, [CW, CH]);
    assert.equal(at(plane, found.bounds, 10, 20), 255, 'the sky');
    assert.equal(found.bounds[1] + found.bounds[3] <= 33, true, 'nothing below the goal’s sky: ' + found.bounds);
    assert.equal(at(plane, found.bounds, 100, 20), 0, 'not the tower');
    assert.ok(found.share > 0.2 && found.share < 0.3, String(found.share));
    const clicked = await findArea(h.host, { points: [[10, 10, 1]] });
    assert.equal(clicked.found_on, 'canvas', 'a click is on the canvas itself');
    h.host.goal = async () => null;
    const plain = await findArea(h.host, { part: 'the ground' });
    assert.equal(plain.found_on, 'canvas', 'no goal placement: the canvas');
  } finally { await h.close(); }
});

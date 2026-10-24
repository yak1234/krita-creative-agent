// Find it for me (find-it.ts, find-it-locate.ts): a named part located by a decision model's numbered grid, each confident
// cell one point for the shapes model, leaking masks dropped, the rest merged and cleaned, resampled to the canvas and cached
// per view; a clicked point is one prompt. A fake shapes service and a fake decider; every file goes to a temporary folder.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { findArea, promptsFromCells, cleanMask, leakShare, toCanvas, timingLine, readFound, foundPath, checkRequest, FindError, POSITIVE, NEGATIVE } from '../src/find-it.ts';
import { decisionLocator, gridPicture, gridSize, cellRect, unanswered, fitRgba, GRID_CELLS, LOCATE_PIXELS, ENLARGE } from '../src/find-it-locate.ts';
import { decodePlane, encodePlane } from '../src/shapes/png.ts';
import { decodeRgba, pngSize } from '../src/png-rgba.ts';

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

test('the decision locator asks two questions a cell in one request with the numbered picture, and gives up on a fallback', async () => {
  const requests = [];
  const decider = { async decide(request) {
    requests.push(request);
    return { answers: Object.fromEntries(Object.keys(request.questions).map((name, i) => [name, { type: 'noul', noul: i < 8 ? 0.9 : 0.05 }])), model: 'luna' };
  } };
  const locate = decisionLocator(async () => decider);
  const cells = await locate('the sky.', { width: 64, height: 48, data: new Uint8Array(64 * 48 * 4) });
  assert.equal(requests.length, 1); assert.equal(requests[0].purpose, 'find-it');
  assert.equal(Object.keys(requests[0].questions).length, 96, 'mostly the part, and any part of it');
  assert.match(requests[0].questions.cell_12.instructions, /^Is cell 12 \(the yellow-outlined cell labelled 12\) mostly the sky\?$/);
  assert.match(requests[0].questions.any_12.instructions, /^Does cell 12 \(the yellow-outlined cell labelled 12\) show any part of the sky\?$/);
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
  assert.deepEqual(negatives, [[0, 640, 128, 768], [896, 640, 1024, 768]], 'the "not" cells, in view pixels');
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
  assert.equal(leakShare({ bounds: [0, 0, 4, 4], data: new Uint8Array(16).fill(255) }, [[0, 0, 4, 4]], 8, 8), 1);
  assert.equal(leakShare({ bounds: [0, 0, 4, 4], data: new Uint8Array(16).fill(255) }, [[0, 0, 2, 4]], 8, 8), 0.5);
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

// LIVE in Toska (2026-10-24): "the bridge" on New Moscow's goal failed in 1.5 s, "I could not see the bridge". The bridge is
// long and thin (about 7% of the height), so no cell of the grid is mostly bridge: the real model scored every cell 0.13 or
// less for "mostly the bridge", and 0.9-1.0 along the bridge for "any part of the bridge". A seeing fake: it reads the
// grid picture it is sent and answers from the share of the part's red pixels in each cell (grid and numbers left out).
const PART = [200, 30, 30], GROUND = [100, 100, 100];
function paintedView(width, height, inside) {
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) data.set([...(inside(x, y) ? PART : GROUND), 255], (y * width + x) * 4);
  return { width, height, data };
}
function seeingDecider() {
  const requests = [];
  return { requests, async decide(request) {
    requests.push(request);
    const [, c, r] = request.parts[0].match(/(\d+) columns and (\d+) rows/).map(Number);
    const picture = decodeRgba(Buffer.from(request.parts[1].data, 'base64'));
    const answers = {};
    for (const name of Object.keys(request.questions)) {
      const [kind, n] = name.split('_'), [x0, y0, x1, y1] = cellRect(Number(n) - 1, c, r, picture.width, picture.height);
      let part = 0, ground = 0;
      for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
        const k = (y * picture.width + x) * 4, red = picture.data[k] === PART[0] && picture.data[k + 1] === PART[1];
        if (red) part++; else if (picture.data[k] === GROUND[0] && picture.data[k + 1] === GROUND[0]) ground++;
      }
      const share = part / Math.max(1, part + ground);
      answers[name] = { type: 'noul', noul: (kind === 'cell' ? share > 0.5 : share > 0) ? 0.95 : 0.02 };
    }
    return { answers, model: 'seeing' };
  } };
}
// The bridge in a 1024 x 768 view: y 400-439 (5% of the height), x 240-879; the grid's cells are 128 px.
const onBridge = (x, y) => y >= 400 && y < 440 && x >= 240 && x < 880;

test('a thin part that fills no cell: the cells showing any of it are looked at again, enlarged, until cells are mostly it', async () => {
  const decider = seeingDecider(), view = paintedView(1024, 768, onBridge);
  const cells = await decisionLocator(async () => decider)('the bridge', view);
  assert.equal(decider.requests.length, 2, 'the whole view, then the cells showing the bridge');
  assert.ok(decider.requests.every(r => r.purpose === 'find-it'));
  assert.match(decider.requests[0].questions.any_12.instructions, /^Does cell 12 \(the yellow-outlined cell labelled 12\) show any part of the bridge\?$/);
  const zoomed = pngSize(Buffer.from(decider.requests[1].parts[1].data, 'base64'));
  // Row 4, columns 2-7 of the first grid: a 768 x 128 cut of the view, enlarged on its proportions.
  assert.ok(zoomed.width >= 2 * 768 && Math.abs(zoomed.width / zoomed.height - 6) < 0.05, `${zoomed.width} x ${zoomed.height}`);
  assert.deepEqual(cells.area, [128 / 1024, 384 / 768, 896 / 1024, 512 / 768]);
  assert.equal(cells.looks, 2);
  const { prompts, negatives } = promptsFromCells(cells, 1024, 768);
  assert.ok(prompts.length >= 8, String(prompts.length));
  assert.ok(prompts.every(([[x, y]]) => onBridge(x, y)), 'every point is on the bridge: ' + JSON.stringify(prompts));
  // The guard is where no part of it shows (a cell can show the bridge without being mostly bridge).
  const blocked = (x, y) => negatives.some(([x0, y0, x1, y1]) => x >= x0 && x < x1 && y >= y0 && y < y1);
  assert.ok(!blocked(400, 420) && !blocked(400, 450), 'the bridge\'s cells are not guarded');
  assert.ok(blocked(400, 100) && blocked(400, 600) && blocked(400, 500), 'the cells showing none of it are');
  // A part that is nowhere: one look, nothing confident.
  const none = seeingDecider(), empty = await decisionLocator(async () => none)('the bridge', paintedView(1024, 768, () => false));
  assert.equal(none.requests.length, 1); assert.equal(promptsFromCells(empty, 1024, 768).prompts.length, 0);
});

test('a thin part is found end to end: points on it, its outline merged, not "I could not see it"', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'find-it-'));
  try {
    const W = 1024, H = 768, shapes = [];
    const service = {
      async study() { return { ms: 1, load_ms: 0, peak_mb: 1, provider: 'cpu', studied: true, attempt: 1 }; },
      async shape(_id, prompt) {
        shapes.push(prompt);
        const [x, y] = prompt.points[0], bridge = onBridge(x, y), w = bridge ? 640 : W, h = bridge ? 40 : H, crop = new Uint8Array(w * h);
        for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) if (bridge || !onBridge(i, j)) crop[j * w + i] = 255;
        const mask_path = join(directory, `mask-${shapes.length}.png`);
        await writeFile(mask_path, encodePlane({ width: w, height: h, data: crop }));
        return { bounds: bridge ? [240, 400, w, h] : [0, 0, w, h], score: 0.95, mask_path, model: 'fake', revision: 'r', ms: 2, peak_mb: 1, provider: 'cpu', cached: false };
      },
      async forget() {}, async close() {},
    };
    const view = join(directory, 'view.png'); await writeFile(view, 'view');
    const host = { directory, shapes: service, shapeStudies: new Map(),
      view: async () => ({ path: view, width: 2 * W, height: 2 * H, revision: 'rev-1' }),
      pixels: async () => ({ sha: 'b'.repeat(64), pixels: paintedView(W, H, onBridge) }),
      locate: decisionLocator(async () => seeingDecider()) };
    const found = await findArea(host, { part: 'the bridge' });
    assert.deepEqual(found.bounds, [480, 800, 1280, 80], 'the bridge on the 2048 x 1536 canvas');
    assert.equal(found.locate_looks, 2);
    assert.ok(shapes.length >= 8 && found.kept === shapes.length, `${found.kept} of ${shapes.length}`);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

// LIVE in Toska (2026-10-24, the build with the thin-part fix): "Domed church" on New Moscow's goal, "I could not see Domed
// church". The church is small: it showed in six cells of the whole view and in two of the enlarged look, and no cell was
// ever mostly it (0.21-0.34), so the zoom ran on into a 272 x 181 cut the grid's numbers covered. A small part: a 20 px
// square on the corner of four cells of a 1024 x 768 view.
const onSquare = (x, y) => x >= 374 && x < 394 && y >= 374 && y < 394;

test('an enlarged look is a larger picture: a small cut grows 2-4 times a side; one that would grow less is sent as it is', () => {
  const small = fitRgba({ width: 272, height: 181, data: new Uint8Array(272 * 181 * 4) }, LOCATE_PIXELS);
  assert.deepEqual([small.width, small.height], [272 * ENLARGE, 181 * ENLARGE]);
  const large = { width: 1086, height: 724, data: new Uint8Array(1086 * 724 * 4) };
  assert.equal(fitRgba(large, LOCATE_PIXELS), large, 'the bridge\'s cut: grown 1.15 times it is sent as it is');
  const huge = fitRgba({ width: 2309, height: 1732, data: new Uint8Array(2309 * 1732 * 4) }, LOCATE_PIXELS);
  assert.ok(huge.width * huge.height <= LOCATE_PIXELS);
});

test('a small part that no cell is mostly, even enlarged: the few cells showing it, one box around them half a cell wider', async () => {
  const decider = seeingDecider(), view = paintedView(1024, 768, onSquare);
  const cells = await decisionLocator(async () => decider)('the church', view);
  assert.equal(decider.requests.length, 2, 'the whole view, then the four cells showing it, enlarged');
  const sent = pngSize(Buffer.from(decider.requests[1].parts[1].data, 'base64'));
  assert.deepEqual([sent.width, sent.height], [1024, 1024], 'the 256 x 256 cut, four times a side');
  assert.equal(cells.small, true); assert.equal(cells.looks, 2);
  const { prompts, box } = promptsFromCells(cells, 1024, 768);
  assert.deepEqual(prompts, [], 'no point at a cell\'s centre');
  const [x, y, w, h] = box;
  assert.ok(x <= 374 && y <= 374 && x + w >= 394 && y + h >= 394, 'the box holds the part: ' + box);
  assert.ok(w < 100 && h < 100, 'and little else: ' + box);
  // A thin part keeps its points (the bridge); the sky its cells; neither is small.
  const bridge = await decisionLocator(async () => seeingDecider())('the bridge', paintedView(1024, 768, onBridge));
  assert.equal(bridge.small, undefined); assert.ok(promptsFromCells(bridge, 1024, 768).prompts.length >= 8);
});

test('a small part is found end to end from its box; a mask mostly outside the box is something else and is dropped', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'find-it-'));
  try {
    const W = 1024, H = 768, asked = [];
    let behind = false;                                   // the shapes model answers the box with the building behind it
    const service = {
      async study() { return { ms: 1, load_ms: 0, peak_mb: 1, provider: 'cpu', studied: true, attempt: 1 }; },
      async shape(_id, prompt) {
        asked.push(prompt);
        const square = prompt.box && !behind, [bx, by, w, h] = square ? [374, 374, 20, 20] : [300, 0, 200, 400];
        const mask_path = join(directory, `mask-${asked.length}.png`);
        await writeFile(mask_path, encodePlane({ width: w, height: h, data: new Uint8Array(w * h).fill(255) }));
        return { bounds: [bx, by, w, h], score: 0.9, mask_path, model: 'fake', revision: 'r', ms: 2, peak_mb: 1, provider: 'cpu', cached: false };
      },
      async forget() {}, async close() {},
    };
    const view = join(directory, 'view.png'); await writeFile(view, 'view');
    const host = { directory, shapes: service, shapeStudies: new Map(),
      view: async () => ({ path: view, width: 2 * W, height: 2 * H, revision: 'rev-1' }),
      pixels: async () => ({ sha: 'c'.repeat(64), pixels: paintedView(W, H, onSquare) }),
      locate: decisionLocator(async () => seeingDecider()) };
    const found = await findArea(host, { part: 'Domed church' });
    assert.equal(asked.length, 1); assert.ok(asked[0].box, 'one box prompt');
    assert.deepEqual(found.bounds, [748, 748, 40, 40], 'the square on the 2048 x 1536 canvas');
    assert.deepEqual([found.prompts, found.kept, found.locate_looks], [1, 1, 2]);
    behind = true; host.view = async () => ({ path: view, width: 2 * W, height: 2 * H, revision: 'rev-2' });
    host.pixels = async () => ({ sha: 'd'.repeat(64), pixels: paintedView(W, H, onSquare) });
    await assert.rejects(findArea(host, { part: 'Domed church' }), e => e.code === 'not_found' && /No outline of Domed church/.test(e.message));
  } finally { await rm(directory, { recursive: true, force: true }); }
});

// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Find it for me (openspec element-scoped-painting goal 1, "Select object"; the artist, 2026-10-24): the artist names a part
// ("the sky") or clicks a point on it, and the shapes model (SAM 2.1 base-plus, src/shapes) finds that object's outline on
// the CURRENT painting (the canvas view, never a reference). The panel loads it as a normal Krita selection (marching ants)
// the artist can still change with Freehand (Shift adds, Alt subtracts) before pressing Paint only here or Use this.
//
//   const found = await findArea(host, { part: 'the sky' });         // or { points: [[x, y, 1]] } in canvas pixels
//   // -> { mask_path (.shapes/found-<24 hex>.png, 255 inside, cropped to bounds), bounds, canvas, share, score, ms, cached }
//
// - A clicked point is one prompt: the object under it.
// - A name goes through a locator (find-it-locate.ts: a decision model that reads images marks which grid cells are the
//   part). Each confident cell is a positive point, with its two nearest confident neighbours and the nearest confident
//   "not the part" cells as negative points (the buildings, for the sky); every cell's mask is decoded on the one study of
//   the view, a mask that leaks into the "not" cells is dropped, and the rest are merged. A region split by other objects
//   (the sky between towers) is covered piece by piece, which one prompt cannot do.
// - The study (the image encoder) runs once per view: findShape keys it by the view's content, so a later shape the
//   painter asks for on the same view reuses it. The result is cached in the chat folder's .shapes by (finder version, model
//   revision, view content, request): the same request on the same revision of the painting answers at once.
// - Timings (view, locate, shapes, total) come back with the result for the status line and the diagnostics.
// Mechanism only: the studio passes a host (the view, its pixels, the shapes service, the locator); no .mjs imports.
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, rename, stat, unlink, writeFile } from 'node:fs/promises';
import { basename, dirname, isAbsolute, join, resolve } from 'node:path';
import { findShape, type Found, type ShapeHost } from './shapes/use.ts';
import { decodePlane, encodePlane } from './shapes/png.ts';
import { SHAPES_MODEL } from './shapes/model.ts';
import { cellRect, type Cells, type PartLocator, type Rgba } from './find-it-locate.ts';

export const FINDER_VERSION = 1;
/** A cell at or above this probability is the part; at or below NEGATIVE it is not (a negative point). */
export const POSITIVE = 0.6, NEGATIVE = 0.15;
/** A cell's mask is dropped when more than this share of it lies in "not" cells: it leaked into another object. */
export const LEAK = 0.25;
/** A clicked point's mask below this score is still loaded (the artist sees it and adjusts), with a note. */
export const UNSURE = 0.6;
/** Found areas kept in a chat's .shapes. */
export const FOUND_KEPT = 8;
const FOUND_FILE = /^found-[0-9a-f]{24}\.png$/;
const NAME_LIMIT = 60;

export type Rect = [number, number, number, number];
/** The painting's current view: the file the plugin wrote (about 1024 px), and the canvas's own size. */
export type View = { path: string; width: number; height: number; revision?: string | null };
export type FindRequest = { part?: string | null; points?: number[][] | null };
export type FindTiming = { view: number; locate: number; shapes: number; total: number };
export type FoundArea = { part: string | null; mask_path: string; bounds: Rect; canvas: [number, number]; share: number; score: number;
  prompts: number; kept: number; cached: boolean; ms: FindTiming; revision: string | null; note?: string; located_by?: string };
export type FindHost = ShapeHost & {
  /** The chat folder: found areas go to its .shapes. */
  directory: string;
  view(): Promise<View>;
  pixels(path: string): Promise<{ sha: string; pixels: Rgba }>;
  /** Where a named part is (find-it-locate.ts); absent or null: only a clicked point can be found. */
  locate?: PartLocator | null;
  signal?: AbortSignal;
};
export type FindErrorCode = 'invalid' | 'no_locator' | 'not_found';
export class FindError extends Error {
  readonly code: FindErrorCode;
  constructor(code: FindErrorCode, message: string) { super(message); this.name = 'FindError'; this.code = code; }
}

/** Whether `path` is a found area of the chat folder `directory`: <directory>/.shapes/found-<24 hex>.png. */
export const foundPath = (directory: string, path: unknown): path is string =>
  typeof path === 'string' && isAbsolute(path) && FOUND_FILE.test(basename(path)) && dirname(path) === resolve(directory, '.shapes');

/** The request as the cache and the worker see it: a part name (trimmed, lower case, at most 60 characters), or 1-16
 * points [x, y, label] in canvas pixels inside the canvas. */
export function checkRequest(request: FindRequest, canvas: { width: number; height: number }): { part: string } | { points: number[][] } {
  if (request.points?.length) {
    const points = request.points;
    if (points.length > 16 || points.some(p => !Array.isArray(p) || p.length !== 3 || !p.every(Number.isFinite) || (p[2] !== 0 && p[2] !== 1)))
      throw new FindError('invalid', 'Find it takes 1-16 points [x, y, label] on the canvas (label 1 on the part, 0 beside it).');
    if (!points.some(p => p[2] === 1)) throw new FindError('invalid', 'Click on the part itself.');
    if (points.some(([x = 0, y = 0]) => x < 0 || y < 0 || x > canvas.width || y > canvas.height)) throw new FindError('invalid', 'Click inside the painting.');
    return { points: points.map(([x = 0, y = 0, label]) => [Math.round(x), Math.round(y), label === 1 ? 1 : 0]) };
  }
  const part = String(request.part ?? '').trim().replace(/\s+/g, ' ').slice(0, NAME_LIMIT);
  if (!part) throw new FindError('invalid', 'Say what to find (“the sky”), or click it on the canvas.');
  return { part: part.toLowerCase() };
}

type Point = [number, number, number];
/** The prompts for a named part from its cells, in view pixels: one point at the centre of each confident cell (strongest
 * first), and the "not" cells for the leak check. Empty when no cell is confident.
 * Why one point a prompt: on New Moscow's sky (real SAM 2.1 base-plus, 2026-10-24) single points scored 0.96-0.99 and
 * merged into a clean sky; adding the two nearest "not" cells as negative points dropped scores to 0.28-0.94 and left
 * holes, four of them to 0.31-0.86, and all the cells in one prompt missed the moon. "Not" cells guard instead: a mask
 * that leaks into them is dropped. */
export function promptsFromCells(cells: Cells, width: number, height: number): { prompts: Point[][]; negatives: number[] } {
  const centre = (i: number): [number, number] => { const [x0, y0, x1, y1] = cellRect(i, cells.cols, cells.rows, width, height); return [(x0 + x1) / 2, (y0 + y1) / 2]; };
  const yes = cells.p.map((p, i) => [p, i] as const).filter(([p]) => p >= POSITIVE).sort((a, b) => b[0] - a[0] || a[1] - b[1]).map(([, i]) => i);
  const no = cells.p.map((p, i) => [p, i] as const).filter(([p]) => p <= NEGATIVE).map(([, i]) => i);
  return { prompts: yes.map(i => [[...centre(i), 1] as Point]), negatives: no };
}

/** The share of a found mask (view pixels) lying in the given cells. */
export function leakShare(found: { bounds: Rect; data: Uint8Array }, cells: { cols: number; rows: number }, indices: number[], width: number, height: number): number {
  const [bx, by, bw, bh] = found.bounds;
  let inside = 0, leaked = 0;
  const blocked = new Uint8Array(width * height);
  for (const i of indices) { const [x0, y0, x1, y1] = cellRect(i, cells.cols, cells.rows, width, height); for (let y = y0; y < y1; y++) blocked.fill(1, y * width + x0, y * width + x1); }
  for (let j = 0; j < bh; j++) for (let i = 0; i < bw; i++) {
    if ((found.data[j * bw + i] ?? 0) < 128) continue;
    inside++;
    if (blocked[(by + j) * width + bx + i]) leaked++;
  }
  return inside ? leaked / inside : 0;
}

/** Holes smaller than this share of the view are filled (a star, a window lit inside the sky). */
export const HOLE_SHARE = 0.001;
/** The merged mask cleaned in place: only the connected pieces holding a seed point stay (specks a mask left elsewhere,
 * in the river on New Moscow, go), and holes smaller than HOLE_SHARE of the view are filled. 4-connected. */
export function cleanMask(mask: Uint8Array, width: number, height: number, seeds: number[][]): void {
  const label = new Int32Array(width * height), queue = new Int32Array(width * height);
  const flood = (start: number, inside: boolean, id: number): number[] => {
    let head = 0, tail = 0; const members: number[] = [];
    queue[tail++] = start; label[start] = id;
    while (head < tail) {
      const k = queue[head++]!, x = k % width; members.push(k);
      for (const n of [x > 0 ? k - 1 : -1, x < width - 1 ? k + 1 : -1, k - width, k + width]) {
        if (n < 0 || n >= width * height || label[n] || (mask[n]! >= 128) !== inside) continue;
        label[n] = id; queue[tail++] = n;
      }
    }
    return members;
  };
  const keep = new Set<number>();
  let id = 0;
  for (const [x = -1, y = -1] of seeds) {
    const k = Math.floor(y) * width + Math.floor(x);
    if (x < 0 || y < 0 || x >= width || y >= height || mask[k]! < 128) continue;
    if (!label[k]) flood(k, true, ++id);
    keep.add(label[k]!);
  }
  for (let k = 0; k < mask.length; k++) {
    if (mask[k]! >= 128) { if (!label[k]) flood(k, true, ++id); if (!keep.has(label[k]!)) mask[k] = 0; }
  }
  const hole = HOLE_SHARE * width * height;
  label.fill(0); id = 0;
  for (let k = 0; k < mask.length; k++) {
    if (mask[k]! >= 128 || label[k]) continue;
    const members = flood(k, false, ++id);
    const edge = members.some(m => { const x = m % width, y = Math.floor(m / width); return x === 0 || y === 0 || x === width - 1 || y === height - 1; });
    if (!edge && members.length < hole) for (const m of members) mask[m] = 255;
  }
}

const covers = (found: { bounds: Rect; data: Uint8Array }, x: number, y: number) => {
  const [bx, by, bw, bh] = found.bounds, i = Math.floor(x) - bx, j = Math.floor(y) - by;
  return i >= 0 && j >= 0 && i < bw && j < bh && (found.data[j * bw + i] ?? 0) >= 128;
};

/** The merged mask (view pixels) resampled to the canvas (bilinear, so the edge stays soft) and cut to its bounds. */
export function toCanvas(union: Uint8Array, view: { width: number; height: number }, canvas: { width: number; height: number }): { bounds: Rect; data: Uint8Array; inside: number } | null {
  let x0 = view.width, y0 = view.height, x1 = -1, y1 = -1;
  for (let y = 0; y < view.height; y++) for (let x = 0; x < view.width; x++) if (union[y * view.width + x]) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  if (x1 < 0) return null;
  const kx = view.width / canvas.width, ky = view.height / canvas.height;
  const left = Math.max(0, Math.floor(x0 / kx)), top = Math.max(0, Math.floor(y0 / ky));
  const right = Math.min(canvas.width, Math.ceil((x1 + 1) / kx)), bottom = Math.min(canvas.height, Math.ceil((y1 + 1) / ky));
  const w = right - left, h = bottom - top, data = new Uint8Array(w * h);
  const at = (i: number, j: number) => i < 0 || j < 0 || i >= view.width || j >= view.height ? 0 : union[j * view.width + i] ?? 0;
  let inside = 0;
  for (let y = 0; y < h; y++) {
    const sy = (top + y + 0.5) * ky - 0.5, j = Math.floor(sy), fy = sy - j;
    for (let x = 0; x < w; x++) {
      const sx = (left + x + 0.5) * kx - 0.5, i = Math.floor(sx), fx = sx - i;
      const value = Math.round((at(i, j) * (1 - fx) + at(i + 1, j) * fx) * (1 - fy) + (at(i, j + 1) * (1 - fx) + at(i + 1, j + 1) * fx) * fy);
      data[y * w + x] = value; if (value >= 128) inside++;
    }
  }
  return inside ? { bounds: [left, top, w, h], data, inside } : null;
}

async function pruneFound(folder: string, keep = FOUND_KEPT): Promise<void> {
  let names: string[];
  try { names = (await readdir(folder)).filter(name => FOUND_FILE.test(name)); } catch { return; }
  const dated = await Promise.all(names.map(async name => ({ name, time: await stat(join(folder, name)).then(info => info.mtimeMs, () => 0) })));
  dated.sort((a, b) => b.time - a.time || a.name.localeCompare(b.name));
  await Promise.all(dated.slice(keep).flatMap(({ name }) => [join(folder, name), join(folder, name.replace(/\.png$/, '.json'))]).map(file => unlink(file).catch(() => {})));
}

const elapsed = (since: number) => Math.round(performance.now() - since);

/** The part's outline on the current painting, written into the chat folder's .shapes. Throws a FindError the panel can
 * show as it is (nothing found, no locator for a name, an invalid click); a ShapeError from the shapes service (declined,
 * out of memory) passes through. */
export async function findArea(host: FindHost, request: FindRequest): Promise<FoundArea> {
  const started = performance.now();
  const view = await host.view();
  if (!(view.width > 0 && view.height > 0) || typeof view.path !== 'string') throw new FindError('invalid', 'Open your painting first: Find it looks at the painting.');
  const checked = checkRequest(request, view);
  const { sha, pixels } = await host.pixels(view.path);
  const viewMs = elapsed(started);
  const folder = join(host.directory, '.shapes');
  const key = createHash('sha256').update(JSON.stringify([FINDER_VERSION, SHAPES_MODEL.revision, sha, checked])).digest('hex').slice(0, 24);
  const mask_path = join(folder, 'found-' + key + '.png'), record = join(folder, 'found-' + key + '.json');
  const part = 'part' in checked ? String(request.part).trim().slice(0, NAME_LIMIT) : null;
  try {                                                   // the same request on the same view: at once, no model
    const kept = JSON.parse(await readFile(record, 'utf8'));
    await stat(mask_path);
    return { ...kept, part, mask_path, cached: true, ms: { view: viewMs, locate: 0, shapes: 0, total: elapsed(started) } };
  } catch { /* not found before */ }

  const view_w = pixels.width, view_h = pixels.height, kx = view_w / view.width, ky = view_h / view.height;
  const data = pixels.data instanceof Uint8Array ? pixels.data : new Uint8Array(pixels.data);
  let prompts: Point[][], negatives: number[] = [], cells: Cells | null = null, locateMs = 0;
  if ('points' in checked) prompts = [checked.points.map(([x = 0, y = 0, label = 1]) => [Math.min(view_w, x * kx), Math.min(view_h, y * ky), label] as Point)];
  else {
    if (!host.locate) throw new FindError('no_locator', `Finding ${part} by name needs a decision model that reads images (Settings › Decisions). Click it on the canvas instead.`);
    const locating = performance.now();
    cells = await host.locate(checked.part, { width: view_w, height: view_h, data }, host.signal);
    locateMs = elapsed(locating);
    if (!cells) throw new FindError('no_locator', `The decision model did not answer where ${part} is. Click it on the canvas instead.`);
    ({ prompts, negatives } = promptsFromCells(cells, view_w, view_h));
    if (!prompts.length) throw new FindError('not_found', `I could not see ${part} on the painting. Click it on the canvas instead.`);
  }
  const shaping = performance.now(), union = new Uint8Array(view_w * view_h), scores: number[] = [];
  const studyKey = `canvas:${sha.slice(0, 24)}`;           // the key canvasShape uses: one study per view
  for (const prompt of prompts) {
    host.signal?.throwIfAborted();
    let found: Found;
    try { found = await findShape(host, studyKey, { width: view_w, height: view_h, data }, { points: prompt }); }
    catch (error) { if ((error as { code?: unknown }).code === 'empty' || /No shape was found/.test((error as Error).message)) continue; throw error; }
    const [px = 0, py = 0] = prompt[0]!;
    if (cells) {
      if (!covers(found, px, py)) continue;                                                 // it found something else
      if (negatives.length && leakShare(found, cells, negatives, view_w, view_h) > LEAK) continue;
    }
    const [bx, by, bw, bh] = found.bounds;
    for (let j = 0; j < bh; j++) for (let i = 0; i < bw; i++) if ((found.data[j * bw + i] ?? 0) >= 128) union[(by + j) * view_w + bx + i] = 255;
    scores.push(found.result.score);
  }
  cleanMask(union, view_w, view_h, prompts.flatMap(prompt => prompt.filter(point => point[2] === 1)));
  const shapesMs = elapsed(shaping);
  const merged = toCanvas(union, { width: view_w, height: view_h }, view);
  if (!merged) throw new FindError('not_found', part ? `No outline of ${part} was found. Click it on the canvas instead.` : 'No shape was found there. Click on the part itself.');
  await mkdir(folder, { recursive: true });
  await writeFile(mask_path, encodePlane({ width: merged.bounds[2], height: merged.bounds[3], data: merged.data }));
  const score = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length * 100) / 100;
  const result: Omit<FoundArea, 'part' | 'mask_path' | 'cached' | 'ms'> = { bounds: merged.bounds, canvas: [view.width, view.height],
    share: Math.round(merged.inside / (view.width * view.height) * 10000) / 10000, score, prompts: prompts.length, kept: scores.length,
    revision: view.revision ?? null, ...(cells?.model ? { located_by: cells.model } : {}),
    ...(!cells && score < UNSURE ? { note: `The outline is uncertain (score ${score}): adjust it with Freehand (Shift adds, Alt subtracts), or click again.` } : {}) };
  const temporary = record + '.' + process.pid;
  await writeFile(temporary, JSON.stringify(result)); await rename(temporary, record);
  await pruneFound(folder);
  return { ...result, part, mask_path, cached: false, ms: { view: viewMs, locate: locateMs, shapes: shapesMs, total: elapsed(started) } };
}

/** A found area's mask, read back (only from the chat folder's .shapes). */
export async function readFound(directory: string, found: { mask_path: unknown; bounds: number[] }): Promise<{ width: number; height: number; data: Uint8Array }> {
  if (!foundPath(directory, found.mask_path)) throw new Error('A found area is read only from this chat folder’s .shapes.');
  const [, , w = 0, h = 0] = found.bounds;
  return decodePlane(await readFile(found.mask_path), { width: w, height: h });
}

/** "Found the sky in 2.4 s" with what took the time, for the status line. */
export function timingLine(found: FoundArea): string {
  const s = (ms: number) => (ms / 1000).toFixed(1) + ' s', what = found.part ?? 'the part you clicked';
  if (found.cached) return `Found ${what} again at once (this painting has not changed since).`;
  const parts = [found.part ? `locating ${s(found.ms.locate)}` : '', `shapes model ${s(found.ms.shapes)}`].filter(Boolean).join(', ');
  return `Found ${what} in ${s(found.ms.total)} (${parts}): ${Math.max(1, Math.round(found.share * 100))}% of the canvas.`;
}

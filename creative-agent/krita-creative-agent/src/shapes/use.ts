// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Element shapes in use (element-shapes phase 1: 1.4 guides, 1.5 painting inside, 1.6 protection). The painter names an
// element by one box or a few points; the shape service (injected as runtime.shapes) studies the image once and returns
// the element's pixels. Here a shape becomes what Krita already has: guide lines (guide-tool.ts), a selection for one
// pass, a proposed protected area. A shape is never a layer and never a Krita mask; the painter and the panel read
// "shape". Nothing here paints: the plugin gets lines, or a mask file in the chat folder with its bounds.
import { Type } from 'typebox';
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, stat, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { EMPTY_SHAPE, type ShapePrompt, type ShapeResult, type ShapeService } from './index.ts';
import { decodePlane, encodePlane } from './png.ts';

export type { ShapePrompt, ShapeResult, ShapeService };
export type Rgba = { width: number; height: number; data: Uint8Array | Buffer };
type Rect = [number, number, number, number];

/** Below this score a shape is reported as uncertain, so the painter can give a tighter box or points. */
export const LOW_SCORE = 0.6;
export const SHAPE_POINTS = 16;
const CANVAS_SIDE = 4096;                    // the canvas view is decoded as it is (about 1024 px), never shrunk below this
/** Studied images kept per chat (the worker holds each one's encoding): the oldest is forgotten past this. */
export const SHAPE_STUDIES = 4;
/** Canvas shape files kept in a chat's .shapes: scratch for the passes and proposals of the last few moves. */
export const CANVAS_SHAPES = 8;

/** The painter's prompt for one element, in `where` pixels. */
export const shapeSchema = (where: string, description?: string) => Type.Union([
  Type.Object({ box: Type.Array(Type.Number({ minimum: 0, maximum: 100000 }), { minItems: 4, maxItems: 4,
    description: `[x,y,w,h] around the one element, ${where} pixels.` }) }, { additionalProperties: false }),
  Type.Object({ points: Type.Array(Type.Array(Type.Number({ minimum: -100000, maximum: 100000 }), { minItems: 3, maxItems: 3 }),
    { minItems: 1, maxItems: SHAPE_POINTS, description: `[x,y,label], ${where} pixels: label 1 on the element, 0 beside it.` }) },
  { additionalProperties: false }),
], { description: description ?? `One element’s shape (its exact pixels), from one box around it or a few points on it, ${where} pixels.` });

/** A checked prompt: a box with an area, points labelled 0 or 1 with at least one on the element. */
export function checkPrompt(given: unknown): ShapePrompt {
  const prompt = given as { box?: number[]; points?: number[][] };
  if (prompt?.box) {
    const [x = 0, y = 0, w = 0, h = 0] = prompt.box;
    if (!(w >= 1 && h >= 1)) throw new Error('A shape box needs a width and a height: [x,y,w,h].');
    return { box: [x, y, w, h] };
  }
  const points = prompt?.points ?? [];
  if (!points.length || points.some(p => p.length !== 3 || (p[2] !== 0 && p[2] !== 1)))
    throw new Error('Shape points are [x,y,label] with label 1 on the element or 0 beside it.');
  if (!points.some(p => p[2] === 1)) throw new Error('Put at least one shape point on the element (label 1).');
  return { points: points.map(([x = 0, y = 0, label]) => [x, y, label === 1 ? 1 : 0]) };
}

/** The prompt in another size's pixels, kept inside `limit` (the image it is found on): a box or point an epsilon past
 * the edge after scaling is clamped, not refused. */
export function scalePrompt(prompt: ShapePrompt, kx: number, ky: number, limit?: { width: number; height: number }): ShapePrompt {
  const cx = (x: number) => limit ? Math.min(limit.width, Math.max(0, x)) : x, cy = (y: number) => limit ? Math.min(limit.height, Math.max(0, y)) : y;
  if ('box' in prompt) {
    const [x, y, w, h] = prompt.box, left = cx(x * kx), top = cy(y * ky);
    return { box: [left, top, cx((x + w) * kx) - left, cy((y + h) * ky) - top] };
  }
  return { points: prompt.points.map(([x, y, label]) => [cx(x * kx), cy(y * ky), label]) };
}

/** The box around a prompt, for points the box around them. */
export function promptBox(prompt: ShapePrompt): Rect {
  if ('box' in prompt) return prompt.box;
  const xs = prompt.points.map(p => p[0]), ys = prompt.points.map(p => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
}

export type ShapeHost = { shapes?: ShapeService | null; shapeStudies?: Map<string, Promise<unknown>> };
export type Found = { result: ShapeResult; bounds: Rect; data: Uint8Array };

const hashes = new WeakMap<object, string>();
/** A key for an image: its kind (a reference id, or "canvas") and its decoded pixels' hash, remembered per pixels object. */
export function imageKey(kind: string, pixels: Rgba): string {
  let hash = hashes.get(pixels);
  if (!hash) { hash = createHash('sha256').update(pixels.data).digest('hex').slice(0, 24); hashes.set(pixels, hash); }
  return `${kind}:${hash}:${pixels.width}x${pixels.height}`;
}

/** Study `key` unless it is studied already: at most SHAPE_STUDIES kept (as the service and its worker keep), the oldest
 * forgotten. */
function studied(host: ShapeHost, service: ShapeService, key: string, pixels: Rgba): Promise<unknown> {
  const studies = host.shapeStudies ??= new Map();
  let study = studies.get(key);
  if (study) { studies.delete(key); studies.set(key, study); return study; }      // most recent last
  study = service.study(key, pixels.data instanceof Uint8Array ? pixels.data : new Uint8Array(pixels.data), pixels.width, pixels.height);
  studies.set(key, study);
  study.catch(() => { if (studies.get(key) === study) studies.delete(key); });   // a failed study is tried again next time
  while (studies.size > SHAPE_STUDIES) {
    const oldest = studies.keys().next().value as string;
    studies.delete(oldest);
    void Promise.resolve(service.forget?.(oldest)).catch(() => {});
  }
  return study;
}

/** One element's shape on an image: the image is studied once per key (reference or canvas, and its content), then the
 * shape is found from the prompt, in the image's pixels. A service that no longer holds the study (not_studied) is
 * asked to study again, once; any other failure propagates. The mask is read back at its bounds, never larger than
 * the image. */
export async function findShape(host: ShapeHost, base: string, pixels: Rgba, prompt: ShapePrompt): Promise<Found> {
  const service = host.shapes;
  if (!service) throw new Error('Finding shapes is not available in this companion. Give the element\u2019s source or lines instead.');
  const key = base;
  await studied(host, service, key, pixels);
  let result: ShapeResult;
  try { result = await service.shape(key, prompt); }
  catch (error) {
    if ((error as { code?: unknown }).code !== 'not_studied') throw error;
    host.shapeStudies?.delete(key);
    await studied(host, service, key, pixels);
    result = await service.shape(key, prompt);
  }
  const [x, y, w, h] = result.bounds.map(Math.round) as Rect;
  if (!(w > 0 && h > 0)) throw new Error(EMPTY_SHAPE);
  const plane = decodePlane(await readFile(result.mask_path), { width: pixels.width, height: pixels.height });
  let data = plane.data;
  if (plane.width !== w || plane.height !== h) {            // a mask at another size than its bounds: resampled to them
    data = new Uint8Array(w * h);
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++)
      data[j * w + i] = plane.data[Math.min(plane.height - 1, Math.floor((j + 0.5) * plane.height / h)) * plane.width
        + Math.min(plane.width - 1, Math.floor((i + 0.5) * plane.width / w))] ?? 0;
  }
  return { result, bounds: [x, y, w, h], data };
}

/** What the painter reads about a shape: its score, and a note when it is uncertain. */
export function shapeReport(found: Found, extra: Record<string, unknown> = {}) {
  const score = Math.round(found.result.score * 100) / 100;
  return { score, ...extra, ...(uncertain(found) ? { note: lowScoreNote(score) } : {}) };
}
/** The raw score against LOW_SCORE: 0.596 is uncertain though it shows as 0.6. */
export const uncertain = (found: Found) => !(found.result.score >= LOW_SCORE);
export const lowScoreNote = (score: number) => `The shape is uncertain (score ${score} < ${LOW_SCORE}): give a tighter box `
  + 'around the one element, or a few points on it (label 1) and beside it (label 0), and try again.';
/** Timings for diagnostics (element-shapes 1.9 reads them). */
export const shapeTimings = (found: Found) => ({ ms: found.result.ms, peak_mb: found.result.peak_mb, provider: found.result.provider, model: found.result.model });

export type CanvasHost = ShapeHost & {
  study: { directory: string };
  decisionObservation?: { width?: unknown; height?: unknown; image_path?: unknown; unguided_path?: unknown; region?: unknown;
    image_width?: unknown; image_height?: unknown } | null;
  callNative(operation: string, params: Record<string, unknown>, id?: string): Promise<any>;
  canvasPixels?: { sha: string; pixels: Rgba } | null;
};
export type CanvasShape = { mask_path: string; bounds: Rect; found: Found };

/** Keep the newest `keep` canvas shape files of a chat folder (0 at chat end). */
export async function pruneShapes(directory: string, keep = CANVAS_SHAPES): Promise<void> {
  const folder = join(directory, '.shapes');
  let names: string[];
  try { names = (await readdir(folder)).filter(name => /^canvas-[0-9a-f]+\.png$/.test(name)); } catch { return; }
  const dated = await Promise.all(names.map(async name => ({ name, time: await stat(join(folder, name)).then(info => info.mtimeMs, () => 0) })));
  dated.sort((a, b) => b.time - a.time || a.name.localeCompare(b.name));
  await Promise.all(dated.slice(keep).map(({ name }) => unlink(join(folder, name)).catch(() => {})));
}

/** One element's shape on the painting as the painter last saw it (the canvas view, without guide lines; a region
 * look is that region at its own scale), written at canvas resolution into the chat folder's .shapes for the plugin
 * (shape_mask.py): a mask file and its bounds. */
export async function canvasShape(host: CanvasHost, given: unknown): Promise<CanvasShape> {
  const prompt = checkPrompt(given);
  const seen = host.decisionObservation, width = Number(seen?.width), height = Number(seen?.height);
  const path = seen?.unguided_path ?? seen?.image_path;
  if (!(width > 0 && height > 0) || typeof path !== 'string')
    throw new Error('A shape on the painting is found on the canvas you last saw: look at the canvas first (observe).');
  const region = Array.isArray(seen?.region) && seen.region.length === 4 ? seen.region.map(Number) as Rect : null;
  const [ax, ay, aw, ah] = region ?? [0, 0, width, height];
  const corners = 'box' in prompt ? [[prompt.box[0], prompt.box[1]], [prompt.box[0] + prompt.box[2], prompt.box[1] + prompt.box[3]]] : prompt.points;
  if (corners.some(([x = 0, y = 0]) => x < ax || y < ay || x > ax + aw || y > ay + ah))
    throw new Error(region ? `The shape prompt lies outside the region you last looked at [${region.join(', ')}]: look at the canvas `
      + 'or a region holding the whole element first, then name it.' : `The shape prompt lies outside the canvas (${width} x ${height}).`);
  const file = await readFile(path), sha = createHash('sha256').update(file).digest('hex');
  let pixels = host.canvasPixels?.sha === sha ? host.canvasPixels.pixels : null;
  if (!pixels) {
    const decoded = await host.callNative('trace_reference', { image_base64: file.toString('base64'), sha256: sha, max_side: CANVAS_SIDE });
    if (decoded?.sha256 !== sha) throw new Error('Decoded canvas identity differs.');
    const expected = [Number(seen?.image_width), Number(seen?.image_height)];
    if (expected.every(n => n > 0) && (decoded.width !== expected[0] || decoded.height !== expected[1]))
      throw new Error(`The canvas view decoded at ${decoded.width} x ${decoded.height}, not its ${expected[0]} x ${expected[1]}: look at the canvas again.`);
    pixels = { width: decoded.width, height: decoded.height, data: Buffer.from(decoded.rgba_base64, 'base64') };
    host.canvasPixels = { sha, pixels };
  }
  // view = (canvas - area.xy) * k; canvas = area.xy + view / k.
  const kx = pixels.width / aw, ky = pixels.height / ah;
  const local: ShapePrompt = 'box' in prompt ? { box: [prompt.box[0] - ax, prompt.box[1] - ay, prompt.box[2], prompt.box[3]] }
    : { points: prompt.points.map(([x, y, label]) => [x - ax, y - ay, label]) };
  const found = await findShape(host, `canvas:${sha.slice(0, 24)}`, pixels, scalePrompt(local, kx, ky, pixels));
  // The view's bounds on the canvas, and the mask resampled to canvas pixels (bilinear, so its edge stays soft).
  const [vx, vy, vw, vh] = found.bounds;
  const left = Math.max(0, Math.floor(ax + vx / kx)), top = Math.max(0, Math.floor(ay + vy / ky));
  const right = Math.min(width, Math.ceil(ax + (vx + vw) / kx)), bottom = Math.min(height, Math.ceil(ay + (vy + vh) / ky));
  if (right <= left || bottom <= top) throw new Error(EMPTY_SHAPE);
  const w = right - left, h = bottom - top, data = new Uint8Array(w * h);
  const at = (i: number, j: number) => i < 0 || j < 0 || i >= vw || j >= vh ? 0 : found.data[j * vw + i] ?? 0;
  for (let y = 0; y < h; y++) {
    const sy = (top + y - ay + 0.5) * ky - vy - 0.5, j = Math.floor(sy), fy = sy - j;
    for (let x = 0; x < w; x++) {
      const sx = (left + x - ax + 0.5) * kx - vx - 0.5, i = Math.floor(sx), fx = sx - i;
      data[y * w + x] = Math.round((at(i, j) * (1 - fx) + at(i + 1, j) * fx) * (1 - fy) + (at(i, j + 1) * (1 - fx) + at(i + 1, j + 1) * fx) * fy);
    }
  }
  const folder = join(host.study.directory, '.shapes');
  await mkdir(folder, { recursive: true });
  const name = 'canvas-' + createHash('sha256').update(sha + JSON.stringify(region) + JSON.stringify(prompt)).digest('hex').slice(0, 24) + '.png';
  const mask_path = join(folder, name);
  await writeFile(mask_path, encodePlane({ width: w, height: h, data }));
  await pruneShapes(host.study.directory);
  return { mask_path, bounds: [left, top, w, h], found };
}

export type PaintHost = CanvasHost & { forkTools?: unknown };
/** A pass's inside_shape, checked before the canvas is read or the worker asked (fork only, one limit), then found;
 * an uncertain shape paints nothing. `label` prefixes a batch action's refusal. */
export async function passShape(host: PaintHost, args: { inside_shape?: unknown; region?: unknown; selection?: unknown }, label = ''): Promise<CanvasShape> {
  checkPassLimits(host, args, label);
  const shape = await canvasShape(host, args.inside_shape);
  if (uncertain(shape.found)) throw new Error(`${label}${lowScoreNote(shapeReport(shape.found).score)} Nothing was painted.`);
  return shape;
}
export function checkPassLimits(host: PaintHost, args: { region?: unknown; selection?: unknown }, label = ''): void {
  if (host.forkTools === false) throw new Error(`${label}Painting inside a shape needs our Krita. Nothing was painted.`);
  if (args.region !== undefined || args.selection !== undefined)
    throw new Error(`${label}Give a pass one limit: a region, a selection or inside_shape. Nothing was painted.`);
}

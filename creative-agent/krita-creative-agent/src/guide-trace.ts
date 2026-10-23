// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Guides from a reference (draw_guide from_reference; openspec sharper-guides goals 2 and 3): what the companion asks
// of the plugin's trace_edges, which traces the reference at full resolution with OpenCV (kritamcp/edge_trace.py) and
// returns lines in the reference's pixels; guide-tool.ts maps them onto the canvas and draws them as guide lines.
//
// - Caps grow with the element's size on the canvas (traceCaps): a moon keeps a handful of lines, a whole cityscape
//   gets dozens. Simplification and the shortest line are measured on the canvas in the plugin (`scale`).
// - Outlines come from shapes when the shapes model is allowed: one pointed element's shape (inside only), or for a
//   block-in the big shapes of the crop (sky, each building mass, ground, figures), found once (findBigShapes) and sent
//   as one label map (labelMap). Without shapes the plugin falls back to a brightness split, and the result says so.
//
// Ruling (big shapes): SAM answers prompts, it does not list objects. The crop is prompted with one positive point at
// the centre of each cell of a coarse grid (SHAPE_GRID cells on its long side), skipping points inside a smaller shape
// kept already (a point inside a big mass is still asked: a figure stands in front of it); a shape is kept when it is
// confident (LOW_SCORE), big enough (MIN_SHARE of the crop), not the whole crop, and not one kept already (SAME). The
// grid is the general choice: it needs no knowledge of the picture, and it stays a few dozen decoder calls (each about
// 15-50 ms once the image is studied; repeats come from the shapes cache).
import { encodePlane } from './shapes/png.ts';
import { LOW_SCORE, findShape, type Found, type Rgba, type ShapeHost } from './shapes/use.ts';

export type Detail = 'simple' | 'medium';
type Point = [number, number];
type Rect = [number, number, number, number];
export type TraceKind = 'outline' | 'structure' | 'light';
/** The shapes as the plugin reads them: an 8-bit PNG of ids (0 none) at `bounds` of an image of size `space`. */
export type Labels = { png_base64: string; bounds: Rect; space: [number, number]; inside: boolean };
/** source and the lines are in pixels of the reference at `size` (its listed size): the plugin maps them onto the file. */
export type TraceRequest = { reference_id: string; source: Rect; size: [number, number]; scale: number; detail: Detail; max_lines: number;
  lights: boolean; labels?: Labels };
/** The plugin's range for scale (canvas pixels a reference pixel). */
export const SCALE_RANGE = [0.01, 100] as const;
export type TraceReply = { lines: { kind: TraceKind; points: Point[] }[]; silhouette: 'shapes' | 'alpha' | 'brightness' | 'none'; ms: number;
  width: number; height: number; original_width: number; original_height: number };

/** Room left in one draw_guide call (guide-tool.ts GUIDE_LINES 128) for the plugin's up to 8 lights and a few lines. */
const MOST = { simple: 48, medium: 112 } as const;
const LEAST = { simple: 8, medium: 24 } as const;
const PER_LINE = { simple: 60, medium: 25 } as const;      // canvas pixels of the target's size for each line kept
/** Lines kept for an element drawn on `target` [x,y,w,h] canvas pixels: grows with its size, from the old caps. */
export function traceCaps(target: number[], detail: Detail): number {
  const span = Math.sqrt(Math.max(0, target[2] ?? 0) * Math.max(0, target[3] ?? 0));
  return Math.max(LEAST[detail], Math.min(MOST[detail], Math.round(span / PER_LINE[detail])));
}

export const SHAPE_GRID = 8;
export const BIG_SHAPES = 24;
const MIN_SHARE = 0.004;
const WHOLE_SHARE = 0.97;
const SAME = 0.7;                // intersection over union: a shape this like one kept already is that one again
const MASS_SHARE = 0.1;          // a point inside a kept shape this large is still asked: a figure in front of a mass

/** The big shapes inside `crop` [x,y,w,h] of `pixels` (see the ruling above), in the order found. A point with no
 * shape is skipped; any other failure of the shapes model propagates. */
export async function findBigShapes(host: ShapeHost, key: string, pixels: Rgba, crop: Rect, find = findShape, signal?: AbortSignal): Promise<Found[]> {
  const [cx, cy, cw, ch] = crop, step = Math.max(cw, ch) / SHAPE_GRID;
  const cols = Math.max(1, Math.round(cw / step)), rows = Math.max(1, Math.round(ch / step));
  const covered = new Uint8Array(cw * ch), kept: { found: Found; mask: Uint8Array; area: number }[] = [];
  for (let row = 0; row < rows && kept.length < BIG_SHAPES; row++) for (let col = 0; col < cols && kept.length < BIG_SHAPES; col++) {
    const px = Math.floor((col + 0.5) * cw / cols), py = Math.floor((row + 0.5) * ch / rows);
    signal?.throwIfAborted();                              // Stop ends the search between prompts
    if (covered[py * cw + px]) continue;
    let found: Found;
    try { found = await find(host, key, pixels, { points: [[cx + px + 0.5, cy + py + 0.5, 1]] }); }
    catch (error) { if ((error as { code?: unknown }).code === 'empty' || /No shape was found/.test(String((error as Error).message))) continue; throw error; }
    signal?.throwIfAborted();
    if (!(found.result.score >= LOW_SCORE)) continue;
    const [bx, by, bw, bh] = found.bounds, mask = new Uint8Array(cw * ch);
    let area = 0;
    for (let j = Math.max(by, cy); j < Math.min(by + bh, cy + ch); j++) for (let i = Math.max(bx, cx); i < Math.min(bx + bw, cx + cw); i++)
      if ((found.data[(j - by) * bw + i - bx] ?? 0) > 127) { mask[(j - cy) * cw + i - cx] = 1; area++; }
    if (area < MIN_SHARE * cw * ch || area > WHOLE_SHARE * cw * ch) continue;
    if (kept.some(other => { let both = 0; for (let k = 0; k < mask.length; k++) both += mask[k]! & other.mask[k]!; return both / (area + other.area - both) >= SAME; })) continue;
    kept.push({ found, mask, area });
    if (area < MASS_SHARE * cw * ch) for (let k = 0; k < mask.length; k++) covered[k] ||= mask[k]!;
  }
  return kept.map(entry => entry.found);
}

/** Shapes as one label map over `crop` of a width x height image: ids from 1, the largest painted first so a smaller
 * shape (a figure) keeps its own id over the mass behind it. */
export function labelMap(shapes: { bounds: number[]; data: Uint8Array }[], crop: Rect, width: number, height: number, inside = false): Labels {
  const [cx, cy, cw, ch] = crop, data = new Uint8Array(cw * ch);
  const area = (s: { data: Uint8Array }) => s.data.reduce((n, v) => n + (v > 127 ? 1 : 0), 0);
  const order = shapes.map((shape, index) => ({ shape, index, area: area(shape) })).sort((a, b) => b.area - a.area);
  order.forEach(({ shape }, rank) => {
    const [bx = 0, by = 0, bw = 0, bh = 0] = shape.bounds;
    for (let j = Math.max(by, cy); j < Math.min(by + bh, cy + ch); j++) for (let i = Math.max(bx, cx); i < Math.min(bx + bw, cx + cw); i++)
      if ((shape.data[(j - by) * bw + i - bx] ?? 0) > 127) data[(j - cy) * cw + i - cx] = Math.min(255, rank + 1);
  });
  return { png_base64: Buffer.from(encodePlane({ width: cw, height: ch, data })).toString('base64'), bounds: crop, space: [width, height], inside };
}

/** The crop to trace a shape on: its bounds and a margin (so its outline never lies on the crop's edge), on the image. */
export function shapeSource(bounds: number[], width: number, height: number): Rect {
  const [x = 0, y = 0, w = 0, h = 0] = bounds, margin = Math.ceil(0.03 * Math.max(w, h)) + 2;
  const left = Math.max(0, Math.floor(x - margin)), top = Math.max(0, Math.floor(y - margin));
  return [left, top, Math.min(width, Math.ceil(x + w + margin)) - left, Math.min(height, Math.ceil(y + h + margin)) - top];
}

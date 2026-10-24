// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Close-up crops for the painter (openspec eyes-and-history 2). The whole-canvas view of a large painting is shrunk to the
// view side, and the painter's provider may shrink it again (DeepSeek reads about 1.69 MP), so a larger view adds nothing
// where the painter works. When an Agent move works in an area (Paint only here, or the region or box its calls pass), each
// whole-canvas observe also carries up to MAX_CROPS crops of that area at canvas resolution, each at most the painter
// model's measured crop side (view-size.ts, default CROP_SIDE), labelled with its canvas rectangle and scale. They are
// read-only peeks of the revision just observed (a crop of another revision is dropped); older ones leave the history
// with the other images (keepRecentImages). Mechanism only: the studio says where the area is and reads the crops.

export type Rect = [number, number, number, number];
export const MAX_CROPS = 2;
export const CROP_SIDE = 1536;
/** A crop is at least this a side (or the canvas), so a small area still shows what is around it. */
export const MIN_CROP = 512;

const rect = (value: unknown): value is Rect => Array.isArray(value) && value.length === 4 && value.every(v => typeof v === 'number' && Number.isFinite(v)) && value[2] > 0 && value[3] > 0;
const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

/** The area a painting call names: its region, projection region, target, area box or inside_shape box (a paint_batch:
 * the union of its actions'), or null. Where its strokes land is not an area: crops only when the move names one. */
export function callArea(args: unknown): Rect | null {
  const a = record(args);
  if (Array.isArray(a.actions)) return union(a.actions.map(action => callArea(record(action).arguments)));
  for (const value of [a.region, a.projection_region, a.target, record(a.area).box, record(a.inside_shape).box]) if (rect(value)) return value;
  return null;
}

function union(areas: (Rect | null)[]): Rect | null {
  const valid = areas.filter((a): a is Rect => !!a);
  if (!valid.length) return null;
  const x0 = Math.min(...valid.map(a => a[0])), y0 = Math.min(...valid.map(a => a[1]));
  return [x0, y0, Math.max(...valid.map(a => a[0] + a[2])) - x0, Math.max(...valid.map(a => a[1] + a[3])) - y0];
}

/** The crops of `area` on the canvas: none when the area is missing or the whole view already shows actual pixels; one
 * window around it when it fits `side`; else up to MAX_CROPS windows along its long side (each at most `side`, shrunk by
 * the plugin past that, with the scale in the label). */
export function cropRects(area: unknown, canvas: { width: number; height: number }, side = CROP_SIDE): Rect[] {
  const { width, height } = canvas;
  if (!rect(area) || !(width > 0 && height > 0) || Math.max(width, height) <= side) return [];
  const x0 = Math.max(0, Math.floor(area[0])), y0 = Math.max(0, Math.floor(area[1]));
  const x1 = Math.min(width, Math.ceil(area[0] + area[2])), y1 = Math.min(height, Math.ceil(area[1] + area[3]));
  if (x1 <= x0 || y1 <= y0) return [];
  const window = (cx: number, cy: number, w: number, h: number): Rect => {
    const cw = Math.min(width, Math.max(Math.min(MIN_CROP, side), Math.ceil(w))), ch = Math.min(height, Math.max(Math.min(MIN_CROP, side), Math.ceil(h)));
    const place = (centre: number, span: number, total: number) => Math.max(0, Math.min(total - span, Math.round(centre - span / 2)));
    return [place(cx, cw, width), place(cy, ch, height), cw, ch];
  };
  const w = x1 - x0, h = y1 - y0;
  if (Math.max(w, h) <= side) return [window((x0 + x1) / 2, (y0 + y1) / 2, w, h)];
  const crops: Rect[] = [];
  for (let i = 0; i < MAX_CROPS; i++) crops.push(w >= h
    ? window(x0 + w * (2 * i + 1) / (2 * MAX_CROPS), (y0 + y1) / 2, Math.min(side, w / MAX_CROPS), Math.min(side, h))
    : window((x0 + x1) / 2, y0 + h * (2 * i + 1) / (2 * MAX_CROPS), Math.min(side, w), Math.min(side, h / MAX_CROPS)));
  return crops;
}

export type CropHost = {
  /** Where the move works now, or null. */
  area(): Rect | null;
  /** The longest side of one crop. */
  side(): number;
  /** A read-only view of `region` of the painting: its image, revision and scale, or null. */
  peek(region: Rect): Promise<{ image_path?: string; revision?: string; scale?: number } | null>;
  /** The model's image part for a view. */
  image(path: string): Promise<unknown>;
};

/** Add the close-ups of the move's area to an observation's content (text label, then image, a crop). Returns how many. */
export async function addCloseupCrops(host: CropHost, observation: { width?: number; height?: number; revision?: string }, content: unknown[]): Promise<number> {
  const crops = cropRects(host.area(), { width: observation.width ?? 0, height: observation.height ?? 0 }, host.side());
  let added = 0;
  for (const region of crops) {
    let view;
    try { view = await host.peek(region); } catch { continue; }
    if (!view?.image_path || view.revision !== observation.revision) continue;            // another revision: not this canvas
    let image;
    try { image = await host.image(view.image_path); } catch { continue; }
    const scale = typeof view.scale === 'number' ? view.scale : 1;
    content.push({ type: 'text', text: `CLOSE-UP ${added + 1} of the area you work in: canvas [${region.join(', ')}] (x, y, width, height), scale ${scale}${scale >= 1 ? ' (actual pixels)' : ''}.` }, image);
    added++;
  }
  return added;
}

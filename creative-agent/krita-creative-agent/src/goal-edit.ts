// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Use as the new goal (the canvas reference card; the artist, 2026-10-25): an approved canvas reference's change becomes
// part of the goal for the rest of the chat, so Refine, Finish, the likeness checks and Luna stop pulling it back out.
// Not the image model's whole picture: outside the change it is a softer copy of the canvas. The goal keeps its pixels,
// size, id and placement; only inside the difference area (canvas pixels, canvas-reference.ts canvasMask) the reference
// is pasted, through the goal's placement on the canvas and with a soft edge. The goal is swapped as Sharpen swaps it
// (goal-sharpen.ts use), the picture before remembered, and /original-goal goes back to the one the chat started from.
import type { Plane } from './shapes/png.ts';

export type Rect = [number, number, number, number];
export type Rgba = { width: number; height: number; data: Uint8Array };
/** The difference area on the canvas: the plane covers `bounds` (canvas pixels), 255 inside. */
export type Area = { bounds: Rect; plane: Plane };
/** Where the goal sits on the canvas: its `source` (goal pixels) shown at `target` (canvas pixels). */
export type Placement = { source: Rect; target: Rect };
/** The goal as it was before an edit: its picture, and its sharpening record and view as they were (restored exactly). */
export type GoalEdit = { from: { path: string; width?: number; height?: number; mimeType?: string; sharpened?: unknown; view_path?: string };
  canvas_reference: string; at: string };
type EditableGoal = { path: string; width?: number; height?: number; mimeType?: string; mass_map?: unknown; edits?: GoalEdit[];
  sharpened?: { from: { path: string } }; view_path?: string };

/** The picture the painter and Find it look at (studio.mjs modelImage, findGoalPixels): a sharpened goal is shown as the
 * picture it was (about the model's size), and an edited sharpened goal as that picture with the edit (`view_path`). The
 * sharpening record itself is left alone: transfers begun before sharpening map and resume through it (goalSourceFile). */
export function goalView(goal: Pick<EditableGoal, 'path' | 'sharpened' | 'view_path'>): string {
  return goal.view_path ?? goal.sharpened?.from?.path ?? goal.path;
}

/** The soft edge, as a share of the canvas's long side (about 24 px on a 6000 px canvas). */
export const FEATHER_SHARE = 0.004;

/** The area grown by `radius` and box-blurred by it: 0 to 255, in canvas pixels from `bounds`' corner minus `radius`. */
function soften({ bounds, plane }: Area, radius: number): { x: number; y: number; width: number; height: number; data: Float32Array } {
  const width = plane.width + 2 * radius, height = plane.height + 2 * radius, data = new Float32Array(width * height);
  for (let j = 0; j < plane.height; j++) for (let i = 0; i < plane.width; i++) data[(j + radius) * width + i + radius] = plane.data[j * plane.width + i]!;
  if (radius > 0) {
    const side = 2 * radius + 1, row = new Float32Array(Math.max(width, height));
    for (let j = 0; j < height; j++) {                       // horizontal, then vertical running sums
      for (let i = 0; i < width; i++) row[i] = data[j * width + i]!;
      let sum = 0;
      for (let i = -radius; i < width + radius; i++) {
        if (i + radius < width) sum += row[i + radius]!;
        if (i - radius - 1 >= 0) sum -= row[i - radius - 1]!;
        if (i >= 0 && i < width) data[j * width + i] = sum / side;
      }
    }
    for (let i = 0; i < width; i++) {
      for (let j = 0; j < height; j++) row[j] = data[j * width + i]!;
      let sum = 0;
      for (let j = -radius; j < height + radius; j++) {
        if (j + radius < height) sum += row[j + radius]!;
        if (j - radius - 1 >= 0) sum -= row[j - radius - 1]!;
        if (j >= 0 && j < height) data[j * width + i] = sum / side;
      }
    }
  }
  return { x: bounds[0] - radius, y: bounds[1] - radius, width, height, data };
}

/** The goal with the reference pasted inside the area: a new picture of the goal's size (the goal is not changed). The
 * reference covers the whole canvas (canvas-reference.ts: the image model's picture of the canvas, any size). */
export function blendIntoGoal(goal: Rgba, reference: Rgba, area: Area, [cw, ch]: [number, number], { source, target }: Placement,
  feather = Math.max(1, Math.round(FEATHER_SHARE * Math.max(cw, ch)))): Rgba {
  const out = { width: goal.width, height: goal.height, data: Uint8Array.from(goal.data) };
  const [sx, sy, sw, sh] = source, [tx, ty, tw, th] = target;
  if (!(sw > 0 && sh > 0 && tw > 0 && th > 0)) return out;
  const soft = soften(area, Math.max(0, Math.round(feather)));
  // Only the goal pixels under the softened area, and on the goal's placed part.
  const toGoalX = (cx: number) => sx + (cx - tx) * sw / tw, toGoalY = (cy: number) => sy + (cy - ty) * sh / th;
  const gx0 = Math.max(0, Math.floor(sx), Math.floor(toGoalX(soft.x))), gx1 = Math.min(goal.width, Math.ceil(sx + sw), Math.ceil(toGoalX(soft.x + soft.width)));
  const gy0 = Math.max(0, Math.floor(sy), Math.floor(toGoalY(soft.y))), gy1 = Math.min(goal.height, Math.ceil(sy + sh), Math.ceil(toGoalY(soft.y + soft.height)));
  const rx = reference.width / cw, ry = reference.height / ch, rw = reference.width, rh = reference.height, ref = reference.data;
  for (let gy = gy0; gy < gy1; gy++) {
    const cy = ty + (gy + 0.5 - sy) * th / sh, my = Math.floor(cy - soft.y);
    if (my < 0 || my >= soft.height) continue;
    // The reference, bilinear at the canvas point.
    const fy = Math.min(rh - 1, Math.max(0, cy * ry - 0.5)), y0 = Math.floor(fy), y1 = Math.min(rh - 1, y0 + 1), wy = fy - y0;
    for (let gx = gx0; gx < gx1; gx++) {
      const cx = tx + (gx + 0.5 - sx) * tw / sw, mx = Math.floor(cx - soft.x);
      if (mx < 0 || mx >= soft.width) continue;
      const a = soft.data[my * soft.width + mx]! / 255;
      if (a <= 0) continue;
      const fx = Math.min(rw - 1, Math.max(0, cx * rx - 0.5)), x0 = Math.floor(fx), x1 = Math.min(rw - 1, x0 + 1), wx = fx - x0;
      const p00 = (y0 * rw + x0) * 4, p01 = (y0 * rw + x1) * 4, p10 = (y1 * rw + x0) * 4, p11 = (y1 * rw + x1) * 4, o = (gy * goal.width + gx) * 4;
      for (let c = 0; c < 4; c++) {
        const r = (ref[p00 + c]! * (1 - wx) + ref[p01 + c]! * wx) * (1 - wy) + (ref[p10 + c]! * (1 - wx) + ref[p11 + c]! * wx) * wy;
        out.data[o + c] = Math.round(goal.data[o + c]! * (1 - a) + r * a);
      }
    }
  }
  return out;
}

/** The goal becomes the edited picture at `path` (same id, size and placement); the goal before is remembered. A sharpened
 * goal also gets `view`: the edit in the picture it was, which the painter is shown. */
export function adoptEditedGoal(goal: EditableGoal, path: string, canvasReference: string, at: string, view?: string): void {
  goal.edits = [...(goal.edits ?? []), { from: { path: goal.path, ...(goal.width ? { width: goal.width } : {}), ...(goal.height ? { height: goal.height } : {}),
    ...(goal.mimeType ? { mimeType: goal.mimeType } : {}), ...(goal.sharpened ? { sharpened: goal.sharpened } : {}),
    ...(goal.view_path ? { view_path: goal.view_path } : {}) }, canvas_reference: canvasReference, at }];
  goal.path = path; goal.mimeType = 'image/png';
  if (view) goal.view_path = view; else delete goal.view_path;
  delete goal.mass_map;
}

/** /original-goal: back to the picture the chat started from (or its sharpened copy). False when it was never edited. */
export function originalGoal(goal: EditableGoal): boolean {
  const first = goal.edits?.[0];
  if (!first) return false;
  goal.path = first.from.path;
  if (first.from.width && first.from.height) { goal.width = first.from.width; goal.height = first.from.height; }
  if (first.from.mimeType) goal.mimeType = first.from.mimeType; else delete goal.mimeType;
  // As it was: sharpened since the edit or not, the record goes back to the original's (none when it never had one).
  if (first.from.sharpened) goal.sharpened = first.from.sharpened as EditableGoal['sharpened']; else delete goal.sharpened;
  if (first.from.view_path) goal.view_path = first.from.view_path; else delete goal.view_path;
  delete goal.edits; delete goal.mass_map;
  return true;
}

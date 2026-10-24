// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Find it for me, by name (openspec element-scoped-painting goal 1; the artist, 2026-10-24): where on the painting is "the
// sky"? The shapes model finds an object's exact pixels from points on it, but it reads no names. A decision model that
// reads images (Luna by default, whichever the artist selected) answers one yes/no question a cell for the canvas view with
// a numbered grid drawn over it ("is cell 12 mostly the sky?"), all cells in one request; the confident yes cells become the
// shapes model's positive points and the confident no cells its negative points (find-it.ts). The cells are only where to
// point; the outline is the shapes model's.
//
// Measured on a copy of New Moscow's goal (2026-10-24): one request, 48 cells, about 0.8 s and 8,600 input tokens; drawn
// numbers placed the sky's cells far better than cells described in words (the second row of sky scored 0.07-0.45 in
// words, 0.85-0.96 numbered).
// The picture is at most LOCATE_PIXELS whatever the view's size (LIVE rehearsal 2, 2026-10-24): on a goal sharpened 4x the
// grid picture was 2309 x 1732 and 9.7 MB, and the model gave no answer; the cells only say where to point, so a smaller
// picture places them as well (the sharpened goal at 1155 x 866 and at 2309 x 1732 gave the same ten sky cells, 1.0 s
// against 2.5 s). When the model does not answer, the reason comes back (Unanswered) for the diagnostics.
// A thin part fills no cell (LIVE in Toska, 2026-10-24: "the bridge" on New Moscow's goal, a long low bridge about 7% of the
// height, scored at most 0.13 for "mostly the bridge" in every cell, and Find it said it could not see it). So each cell is
// also asked whether it shows any part of it (0.9-1.0 along the bridge); when no cell is mostly the part, the cells showing
// it are looked at again, cut from the view at its own pixels and with their own grid, until cells are mostly the part
// (the bridge's band, enlarged: one cell 0.82), at most LOOKS requests. Bridges, railings, rivers, power lines, any part
// thinner than a cell; a part that fills cells (the sky) takes one request as before.
// A small part fills no cell even enlarged (LIVE in Toska, 2026-10-24: "Domed church" on the same goal showed in six cells
// of the whole view and two of the enlarged look, mostly it at most 0.34, and the zoom ran on into a 272 x 181 cut the
// numbers covered). An enlarged look's cut is now grown to the picture size (fitRgba), and on an enlarged look where at
// most FEW cells show the part and none is mostly it, those cells come back as a small part (Cells.small): find-it.ts
// gives the shapes model one box around them instead of points at their centres.
// Mechanism only: the decision client comes in as a small interface; this module imports no .mjs.
import { encodeRgb } from './shapes/png.ts';
import { reduceRgba } from './bounded-image.ts';
import { resizeBilinear } from './shapes/image.ts';

export type Rgba = { width: number; height: number; data: Uint8Array };
/** The grid picture the model read: its size in pixels and PNG bytes. */
export type LocatePicture = { width: number; height: number; bytes: number };
/** A rectangle as proportions of the view: [left, top, right, bottom], each 0-1. */
export type Box = [number, number, number, number];
/** Probability per cell (row-major) that it is mostly the part, the grid's size, and what answering cost. The grid covers
 * `area` of the view (the whole view when absent: an enlarged look covers less). `guard`, when given, is where the part
 * is not (cells showing none of it), for the leak check; when absent, the cells at or below NEGATIVE are. `looks`: the
 * requests it took (more than one for a thin part). */
export type Cells = { cols: number; rows: number; p: number[]; ms: number; model?: string; picture?: LocatePicture;
  area?: Box; guard?: Box[]; looks?: number;
  /** A small part: `p` is whether each cell shows any of it (none was mostly it on an enlarged look). */
  small?: boolean };
/** No answer, and why: the decision client's fallback (not_connected, timeout, refused, service_or_response_error...), its
 * HTTP status or error name when it has one, how long it took, and the picture sent. */
export type Unanswered = { fallback: string; status?: number; error?: string; ms: number; picture?: LocatePicture };
export type Decider = { decide(request: { parts: unknown[]; questions: Record<string, unknown>; signal?: AbortSignal; purpose?: string }):
  Promise<{ answers?: Record<string, { type: string; noul?: number } | undefined>; fallback?: string; status?: number; error?: string; model?: string; elapsed_ms?: number }> };
export type PartLocator = (part: string, view: Rgba, signal?: AbortSignal) => Promise<Cells | Unanswered | null>;
/** Whether a locator's answer is no answer. */
export const unanswered = (cells: Cells | Unanswered | null): cells is Unanswered | null => !cells || 'fallback' in cells;

/** Cells in the grid: about 48, close to square on the canvas's proportions. */
export const GRID_CELLS = 48;
/** The grid picture is at most this many pixels (1024 x 1024): about 1 s and a few MB a request. */
export const LOCATE_PIXELS = 1024 * 1024;
/** A cell at or above this probability is the part (or shows it); at or below NEGATIVE it is not. */
export const POSITIVE = 0.6, NEGATIVE = 0.15;
/** Requests at most for one part: the whole view, then up to two enlarged looks at the cells showing a thin or small part. */
export const LOOKS = 3;
export const WHOLE: Box = [0, 0, 1, 1];
/** An enlarged look's picture is at most this many times the view's pixels a side. */
export const ENLARGE = 4;
/** On an enlarged look, at most this many cells showing a part and none mostly it: a small part, pointed at there. */
export const FEW = 4;
export function gridSize(width: number, height: number, cells = GRID_CELLS): { cols: number; rows: number } {
  const cols = Math.max(2, Math.round(Math.sqrt(cells * width / height)));
  return { cols, rows: Math.max(2, Math.round(cells / cols)) };
}
/** Cell `index` (row-major) as [x0, y0, x1, y1) in `width` x `height` pixels. */
export function cellRect(index: number, cols: number, rows: number, width: number, height: number): [number, number, number, number] {
  const c = index % cols, r = Math.floor(index / cols);
  return [Math.round(c * width / cols), Math.round(r * height / rows), Math.round((c + 1) * width / cols), Math.round((r + 1) * height / rows)];
}
/** Cell `index` of a grid over `area` of the view, as proportions of the view. */
export function cellBox(index: number, cols: number, rows: number, area: Box = WHOLE): Box {
  const c = index % cols, r = Math.floor(index / cols), w = area[2] - area[0], h = area[3] - area[1];
  return [area[0] + c * w / cols, area[1] + r * h / rows, area[0] + (c + 1) * w / cols, area[1] + (r + 1) * h / rows];
}
/** A box in `width` x `height` pixels: [x0, y0, x1, y1). */
export const boxPixels = (box: Box, width: number, height: number): [number, number, number, number] =>
  [Math.round(box[0] * width), Math.round(box[1] * height), Math.round(box[2] * width), Math.round(box[3] * height)];
/** The picture on its own proportions at most `pixels`: reduced when larger; enlarged (bilinear, 2-ENLARGE times a side)
 * when it fits twice a side or more, so an enlarged look at a small part is not a small picture under the grid's numbers
 * (New Moscow's domed church: a 272 x 181 cut). A picture that would grow less is sent as it is: the bridge's 1086 x 724
 * cut, grown 1.15 times, changed the model's answers for no more detail. */
export function fitRgba(image: Rgba, pixels: number): Rgba {
  if (image.width * image.height >= pixels) return reduceRgba(image, pixels);
  const k = Math.min(ENLARGE, Math.sqrt(pixels / (image.width * image.height)));
  if (k < 2) return image;
  const width = Math.max(1, Math.floor(image.width * k)), height = Math.max(1, Math.floor(image.height * k));
  if (width === image.width && height === image.height) return image;
  return { width, height, data: resizeBilinear(image.data, image.width, image.height, 4, width, height) };
}
/** `box` of the view, cut out at the view's own pixels. */
function cut(view: Rgba, box: Box): Rgba {
  const [x0, y0, x1, y1] = boxPixels(box, view.width, view.height), width = Math.max(1, x1 - x0), height = Math.max(1, y1 - y0);
  if (x0 === 0 && y0 === 0 && width === view.width && height === view.height) return view;
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) data.set(view.data.subarray(((y0 + y) * view.width + x0) * 4, ((y0 + y) * view.width + x0 + width) * 4), y * width * 4);
  return { width, height, data };
}

// A 5 x 7 bitmap of each digit, a row a string: enough to number the cells without a font.
const DIGITS: Record<string, string[]> = {
  0: ['01110', '10001', '10011', '10101', '11001', '10001', '01110'], 1: ['00100', '01100', '00100', '00100', '00100', '00100', '01110'],
  2: ['01110', '10001', '00001', '00010', '00100', '01000', '11111'], 3: ['11110', '00001', '00001', '01110', '00001', '00001', '11110'],
  4: ['00010', '00110', '01010', '10010', '11111', '00010', '00010'], 5: ['11111', '10000', '11110', '00001', '00001', '10001', '01110'],
  6: ['00110', '01000', '10000', '11110', '10001', '10001', '01110'], 7: ['11111', '00001', '00010', '00100', '01000', '01000', '01000'],
  8: ['01110', '10001', '10001', '01110', '10001', '10001', '01110'], 9: ['01110', '10001', '10001', '01111', '00001', '00010', '01100'],
};
const YELLOW = [255, 230, 0] as const, BLACK = [0, 0, 0] as const;

/** The view as RGB with the numbered grid drawn over it: yellow lines, and each cell's number (from 1) in yellow on a
 * black outline at its centre. */
export function gridPicture(view: Rgba, cols: number, rows: number): { width: number; height: number; data: Uint8Array } {
  const { width, height } = view, rgb = new Uint8Array(width * height * 3);
  for (let i = 0, j = 0; i < width * height; i++, j += 3) { rgb[j] = view.data[i * 4] ?? 0; rgb[j + 1] = view.data[i * 4 + 1] ?? 0; rgb[j + 2] = view.data[i * 4 + 2] ?? 0; }
  const put = (x: number, y: number, colour: readonly number[]) => {
    if (x < 0 || y < 0 || x >= width || y >= height) return;
    const k = (y * width + x) * 3; rgb[k] = colour[0]!; rgb[k + 1] = colour[1]!; rgb[k + 2] = colour[2]!;
  };
  const line = Math.max(1, Math.round(Math.max(width, height) / 512));
  for (let c = 1; c < cols; c++) { const x = Math.round(c * width / cols); for (let y = 0; y < height; y++) for (let t = 0; t < line; t++) put(x - (line >> 1) + t, y, YELLOW); }
  for (let r = 1; r < rows; r++) { const y = Math.round(r * height / rows); for (let x = 0; x < width; x++) for (let t = 0; t < line; t++) put(x, y - (line >> 1) + t, YELLOW); }
  const scale = Math.max(1, Math.round(Math.min(width / cols, height / rows) / 40));
  for (let index = 0; index < cols * rows; index++) {
    const [x0, y0, x1, y1] = cellRect(index, cols, rows, width, height), label = String(index + 1);
    const w = label.length * 6 * scale - scale, h = 7 * scale, left = Math.round((x0 + x1 - w) / 2), top = Math.round((y0 + y1 - h) / 2);
    for (const [colour, spread] of [[BLACK, scale], [YELLOW, 0]] as const)
      [...label].forEach((digit, d) => DIGITS[digit]!.forEach((row, gy) => [...row].forEach((bit, gx) => {
        if (bit !== '1') return;
        for (let sy = -spread; sy < scale + spread; sy++) for (let sx = -spread; sx < scale + spread; sx++)
          put(left + (d * 6 + gx) * scale + sx, top + gy * scale + sy, colour);
      })));
  }
  return { width, height, data: rgb };
}

/** A part's cells from a decision model that reads images: a request a look, two yes/no questions a cell (mostly the part;
 * any part of it), on the view reduced to at most `pixels` (the cells are proportions of the view, so they place on any size
 * of it). When no cell is mostly the part, the cells showing any of it are looked at again (a thin part), at most `looks`
 * requests; the enlarged look's cells come back with their area and a guard (the cells, on every look, showing none of it).
 * Unanswered (with the reason) when the model does not answer (not connected, text only, refused, timed out), so the caller
 * can say so. */
export function decisionLocator(client: () => Promise<Decider | null>, { cells = GRID_CELLS, pixels = LOCATE_PIXELS, looks = LOOKS }:
  { cells?: number; pixels?: number; looks?: number } = {}): PartLocator {
  return async (part, view, signal) => {
    const started = performance.now(), ms = () => Math.round(performance.now() - started);
    const decider = await client();
    if (!decider) return { fallback: 'not_connected', ms: ms() };
    const name = part.trim().replace(/[.?!]+$/, '');
    const guard: Box[] = [];
    let area = WHOLE;
    for (let look = 1; ; look++) {
      const seen = cut(view, area), { cols, rows } = gridSize(seen.width, seen.height, cells);
      const shown = area === WHOLE ? reduceRgba(seen, pixels) : fitRgba(seen, pixels), png = encodeRgb(gridPicture(shown, cols, rows));
      const picture = { width: shown.width, height: shown.height, bytes: png.length };
      const questions: Record<string, unknown> = {};
      for (let i = 1; i <= cols * rows; i++)
        questions['cell_' + i] = { type: 'noul', instructions: `Is cell ${i} (the yellow-outlined cell labelled ${i}) mostly ${name}?` };
      for (let i = 1; i <= cols * rows; i++)
        questions['any_' + i] = { type: 'noul', instructions: `Does cell ${i} (the yellow-outlined cell labelled ${i}) show any part of ${name}?` };
      const what = area === WHOLE ? 'The painting is' : 'An enlarged part of the painting is';
      let result: Awaited<ReturnType<Decider['decide']>>;
      try {
        result = await decider.decide({ purpose: 'find-it', signal,
          parts: [`${what} divided into a numbered grid of ${cols} columns and ${rows} rows.`, { data: png.toString('base64'), mimeType: 'image/png' }], questions });
      } catch (error) {
        if (signal?.aborted) throw error;
        return { fallback: 'service_or_response_error', error: (error as Error)?.name ?? 'Error', ms: ms(), picture };
      }
      if (!result.answers) return { fallback: result.fallback ?? 'service_or_response_error', ...(result.status ? { status: result.status } : {}),
        ...(result.error ? { error: result.error } : {}), ms: ms(), picture };
      const answer = (key: string) => {
        const given = result.answers?.[key];
        return given?.type === 'noul' && typeof given.noul === 'number' && Number.isFinite(given.noul) ? given.noul : 0.5;
      };
      const p = Array.from({ length: cols * rows }, (_, i) => answer('cell_' + (i + 1)));
      const any = Array.from({ length: cols * rows }, (_, i) => answer('any_' + (i + 1)));
      const earlier = guard.length;
      for (let i = 0; i < any.length; i++) if (any[i]! <= NEGATIVE) guard.push(cellBox(i, cols, rows, area));
      const found: Cells = { cols, rows, p, ms: ms(), picture, ...(result.model ? { model: result.model } : {}),
        ...(look > 1 ? { area, guard, looks: look } : {}) };
      if (p.some(value => value >= POSITIVE)) return found;
      const showing = any.flatMap((value, i) => value >= POSITIVE ? [cellBox(i, cols, rows, area)] : []);
      // A small part on an enlarged look: a few cells show it and none is mostly it. Those cells are where to point; the
      // guard is the earlier looks' only, since this look's neighbouring cells can hold the rest of it.
      if (look > 1 && showing.length && showing.length <= FEW)
        return { ...found, p: any, guard: guard.slice(0, earlier), small: true };
      if (look >= looks) return found;
      // No cell is mostly the part: the box around the cells showing it, unless that is no smaller than this look.
      if (!showing.length) return found;
      const next: Box = [Math.min(...showing.map(b => b[0])), Math.min(...showing.map(b => b[1])), Math.max(...showing.map(b => b[2])), Math.max(...showing.map(b => b[3]))];
      const [x0, y0, x1, y1] = boxPixels(next, view.width, view.height);
      if ((next[2] - next[0]) * (next[3] - next[1]) >= (area[2] - area[0]) * (area[3] - area[1]) - 1e-9 || x1 - x0 < 2 || y1 - y0 < 2) return found;
      area = next;
    }
  };
}

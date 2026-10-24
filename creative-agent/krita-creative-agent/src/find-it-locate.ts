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
// Mechanism only: the decision client comes in as a small interface; this module imports no .mjs.
import { encodeRgb } from './shapes/png.ts';

export type Rgba = { width: number; height: number; data: Uint8Array };
/** Probability per cell (row-major), the grid's size, and what answering cost. */
export type Cells = { cols: number; rows: number; p: number[]; ms: number; model?: string };
export type Decider = { decide(request: { parts: unknown[]; questions: Record<string, unknown>; signal?: AbortSignal; purpose?: string }):
  Promise<{ answers?: Record<string, { type: string; noul?: number } | undefined>; fallback?: string; model?: string; elapsed_ms?: number }> };
export type PartLocator = (part: string, view: Rgba, signal?: AbortSignal) => Promise<Cells | null>;

/** Cells in the grid: about 48, close to square on the canvas's proportions. */
export const GRID_CELLS = 48;
export function gridSize(width: number, height: number, cells = GRID_CELLS): { cols: number; rows: number } {
  const cols = Math.max(2, Math.round(Math.sqrt(cells * width / height)));
  return { cols, rows: Math.max(2, Math.round(cells / cols)) };
}
/** Cell `index` (row-major) as [x0, y0, x1, y1) in `width` x `height` pixels. */
export function cellRect(index: number, cols: number, rows: number, width: number, height: number): [number, number, number, number] {
  const c = index % cols, r = Math.floor(index / cols);
  return [Math.round(c * width / cols), Math.round(r * height / rows), Math.round((c + 1) * width / cols), Math.round((r + 1) * height / rows)];
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

/** A part's cells from a decision model that reads images: one request, a yes/no question a cell. Null when the model does
 * not answer (not connected, text only, refused, timed out), so the caller can ask the artist to click the part instead. */
export function decisionLocator(client: () => Promise<Decider | null>, { cells = GRID_CELLS }: { cells?: number } = {}): PartLocator {
  return async (part, view, signal) => {
    const decider = await client();
    if (!decider) return null;
    const { cols, rows } = gridSize(view.width, view.height, cells), started = performance.now();
    const picture = encodeRgb(gridPicture(view, cols, rows)).toString('base64');
    const name = part.trim().replace(/[.?!]+$/, '');
    const questions: Record<string, unknown> = {};
    for (let i = 1; i <= cols * rows; i++)
      questions['cell_' + i] = { type: 'noul', instructions: `Is cell ${i} (the yellow-outlined cell labelled ${i}) mostly ${name}?` };
    const result = await decider.decide({ purpose: 'find-it', signal,
      parts: [`The painting is divided into a numbered grid of ${cols} columns and ${rows} rows.`, { data: picture, mimeType: 'image/png' }], questions });
    if (!result.answers) return null;
    const p = Array.from({ length: cols * rows }, (_, i) => {
      const answer = result.answers?.['cell_' + (i + 1)];
      return answer?.type === 'noul' && typeof answer.noul === 'number' && Number.isFinite(answer.noul) ? answer.noul : 0.5;
    });
    return { cols, rows, p, ms: Math.round(performance.now() - started), ...(result.model ? { model: result.model } : {}) };
  };
}

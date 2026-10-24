// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The sharpening model's pixel side, apart from the model (core.ts) and the process (worker.ts):
// - tiles: the model takes a fixed 128-pixel tile, so the picture is cut into cores of (128 - 2 x pad) pixels, each read
//   with `pad` pixels of the picture around it (its window stays inside the picture; a picture smaller than a tile is
//   padded with its edge pixels). Only the core of each 4x result is kept, so nothing the model guesses near a tile's
//   edge reaches the picture, and no tile is blended (Real-ESRGAN's own tile_pad, without seams to hide). Memory stays
//   one tile in and out, plus the 4x picture;
// - the reference size: the largest picture of the same proportions the reference tools read (closeups.ts TRANSFER_PIXELS);
// - the side-by-side: the most detailed square of the original, enlarged plainly, beside the same square sharpened.
import { resizeBilinear } from '../shapes/image.ts';

export type Rect = [number, number, number, number];
/** core: the pixels this tile decides; window: the top-left of the 128-pixel square read around it. */
export type TileCell = { core: Rect; window: [number, number] };

export function tilePlan(width: number, height: number, { tile, pad }: { tile: number; pad: number }): TileCell[] {
  const stride = tile - 2 * pad;
  if (!(stride > 0) || !(width > 0 && height > 0)) throw new Error('Invalid tile plan.');
  const cells: TileCell[] = [];
  const start = (core: number, size: number) => Math.max(0, Math.min(core - pad, size - tile));
  for (let y = 0; y < height; y += stride) for (let x = 0; x < width; x += stride) {
    const w = Math.min(stride, width - x), h = Math.min(stride, height - y);
    cells.push({ core: [x, y, w, h], window: [start(x, width), start(y, height)] });
  }
  return cells;
}

/** The tile's window as the model's input: RGB channels first, 0..1, edge pixels repeated past the picture. */
export function tileInput(rgb: Uint8Array, width: number, height: number, cell: TileCell, tile: number): Float32Array {
  const [wx, wy] = cell.window, out = new Float32Array(3 * tile * tile), plane = tile * tile;
  for (let y = 0; y < tile; y++) {
    const sy = Math.min(height - 1, wy + y);
    for (let x = 0; x < tile; x++) {
      const at = (sy * width + Math.min(width - 1, wx + x)) * 3, i = y * tile + x;
      out[i] = (rgb[at] ?? 0) / 255; out[plane + i] = (rgb[at + 1] ?? 0) / 255; out[2 * plane + i] = (rgb[at + 2] ?? 0) / 255;
    }
  }
  return out;
}

const byte = (value: number) => { const v = Math.round(value * 255); return v < 0 ? 0 : v > 255 ? 255 : v; };

/** Writes the 4x core of one tile's result (channels first, 0..1) into the 4x RGB picture `out` of width `outWidth`. */
export function placeTile(out: Uint8Array, outWidth: number, result: Float32Array, cell: TileCell, tile: number, scale: number): void {
  const side = tile * scale, plane = side * side;
  if (result.length !== 3 * plane) throw new Error('The sharpening model gave a tile of the wrong size.');
  const [x, y, w, h] = cell.core, [wx, wy] = cell.window;
  for (let row = 0; row < h * scale; row++) {
    const ty = (y - wy) * scale + row, oy = y * scale + row;
    for (let col = 0; col < w * scale; col++) {
      const tx = (x - wx) * scale + col, i = ty * side + tx, o = (oy * outWidth + x * scale + col) * 3;
      out[o] = byte(result[i] ?? 0); out[o + 1] = byte(result[plane + i] ?? 0); out[o + 2] = byte(result[2 * plane + i] ?? 0);
    }
  }
}

/** RGBA to RGB, a transparent pixel over white (the goal is a picture; the model has no alpha). */
export function rgbFromRgba(rgba: Uint8Array, width: number, height: number): Uint8Array {
  if (rgba.length !== width * height * 4) throw new Error('Invalid pixels for their size.');
  const rgb = new Uint8Array(width * height * 3);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j += 3) {
    const a = (rgba[i + 3] ?? 255) / 255;
    for (let c = 0; c < 3; c++) rgb[j + c] = Math.round((rgba[i + c] ?? 0) * a + 255 * (1 - a));
  }
  return rgb;
}

/** The largest [width, height] of these proportions holding at most `maxPixels`; never larger than the picture. */
export function referenceSize(width: number, height: number, maxPixels: number): [number, number] {
  if (width * height <= maxPixels) return [width, height];
  const k = Math.sqrt(maxPixels / (width * height));
  let w = Math.floor(width * k), h = Math.floor(height * k);
  while (w * h > maxPixels) { if (w / h > width / height) w--; else h--; }
  return [w, h];
}

/** The picture resized (Pillow's antialiased bilinear, shapes/image.ts). */
export const resizeRgb = (rgb: Uint8Array, width: number, height: number, outWidth: number, outHeight: number): Uint8Array =>
  resizeBilinear(rgb, width, height, 3, outWidth, outHeight);

/** [x, y, side]: the side x side square (side capped at the picture) with the most local contrast, on a coarse grid. */
export function detailCrop(rgb: Uint8Array, width: number, height: number, side: number): [number, number, number] {
  const s = Math.max(1, Math.min(side, width, height)), step = Math.max(1, Math.floor(s / 8));
  const cols = Math.ceil(width / step), rows = Math.ceil(height / step), energy = new Float64Array(cols * rows);
  const luma = (x: number, y: number) => { const i = (y * width + x) * 3; return 0.299 * (rgb[i] ?? 0) + 0.587 * (rgb[i + 1] ?? 0) + 0.114 * (rgb[i + 2] ?? 0); };
  for (let y = 0; y + 1 < height; y++) for (let x = 0; x + 1 < width; x++)
    energy[Math.floor(y / step) * cols + Math.floor(x / step)]! += Math.abs(luma(x + 1, y) - luma(x, y)) + Math.abs(luma(x, y + 1) - luma(x, y));
  const span = Math.max(1, Math.round(s / step));
  let best = -1, at: [number, number] = [0, 0];
  for (let gy = 0; gy * step + s <= height; gy++) for (let gx = 0; gx * step + s <= width; gx++) {
    let sum = 0;
    for (let j = gy; j < Math.min(rows, gy + span); j++) for (let i = gx; i < Math.min(cols, gx + span); i++) sum += energy[j * cols + i] ?? 0;
    if (sum > best) { best = sum; at = [gx * step, gy * step]; }
  }
  return [at[0], at[1], s];
}

function crop(rgb: Uint8Array, width: number, [x, y, w, h]: Rect): Uint8Array {
  const out = new Uint8Array(w * h * 3);
  for (let row = 0; row < h; row++) out.set(rgb.subarray(((y + row) * width + x) * 3, ((y + row) * width + x + w) * 3), row * w * 3);
  return out;
}

/** The side-by-side the artist judges: the original square enlarged to `size` (plain bilinear, how the canvas would show
 * it), an 8-pixel white gap, then the same square of the sharpened picture at `size`. */
export function compareImage(original: Uint8Array, width: number, sharp: Uint8Array, scale: number, [x, y, side]: [number, number, number], size: number): { width: number; height: number; data: Uint8Array } {
  const gap = 8, outWidth = size * 2 + gap, out = new Uint8Array(outWidth * size * 3).fill(255);
  const left = resizeRgb(crop(original, width, [x, y, side, side]), side, side, size, size);
  const big = side * scale, right = resizeRgb(crop(sharp, width * scale, [x * scale, y * scale, big, big]), big, big, size, size);
  for (let row = 0; row < size; row++) {
    out.set(left.subarray(row * size * 3, (row + 1) * size * 3), row * outWidth * 3);
    out.set(right.subarray(row * size * 3, (row + 1) * size * 3), (row * outWidth + size + gap) * 3);
  }
  return { width: outWidth, height: size, data: out };
}

// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Element shapes, the pixel side: what goes into SAM 2.1 and what comes out of it, ported from the proven Python
// reference (scratch run_edgetam.py, 2026-10-21), which used Pillow and NumPy:
// - encoder input: the RGB image resized to 1024x1024 with Pillow's bilinear (squashing the aspect ratio), /255, then
//   normalised with ImageNet's mean and std, channels first;
// - prompts: a box [x,y,w,h] or points [x,y,label] in image pixels, scaled into the 1024 space;
// - output: the best mask's 256x256 logits thresholded at 0 (0/255), resized to the image with Pillow's bilinear and
//   thresholded at 127.
// resizeBilinear is Pillow's resampler (ImagingResample with the triangle filter and 8-bit fixed-point coefficients,
// horizontal pass first), so the masks and scores match the reference's; a plain bilinear moved the encoder input enough
// to change scores in the second decimal.

export const ENCODER_SIZE = 1024;
const MEAN = [0.485, 0.456, 0.406] as const;
const STD = [0.229, 0.224, 0.225] as const;
const PRECISION_BITS = 32 - 8 - 2;                   // Pillow's 8-bit coefficient precision

export type Box = [number, number, number, number];
export type Point = [number, number, number];
/** One element, as a rough box or a few points (label 1 = part of it, 0 = not), in the reference's pixels. */
export type ShapePrompt = { box: Box } | { points: Point[] };

type Coefficients = { bounds: Int32Array; weights: Int32Array; size: number };

/** Pillow's precompute_coeffs for the bilinear (triangle) filter, normalised and turned into fixed point. */
function coefficients(inSize: number, outSize: number): Coefficients {
  const scale = inSize / outSize, filterScale = Math.max(scale, 1), support = filterScale;
  const size = Math.ceil(support) * 2 + 1;
  const bounds = new Int32Array(outSize * 2), weights = new Int32Array(outSize * size), k = new Float64Array(size);
  for (let xx = 0; xx < outSize; xx++) {
    const center = (xx + 0.5) * scale, ss = 1 / filterScale;
    let xmin = Math.trunc(center - support + 0.5); if (xmin < 0) xmin = 0;
    let xmax = Math.trunc(center + support + 0.5); if (xmax > inSize) xmax = inSize;
    xmax -= xmin;
    let total = 0;
    for (let x = 0; x < xmax; x++) {
      const t = Math.abs((x + xmin - center + 0.5) * ss), w = t < 1 ? 1 - t : 0;
      k[x] = w; total += w;
    }
    for (let x = 0; x < xmax; x++) {
      const w = total !== 0 ? (k[x] ?? 0) / total : (k[x] ?? 0);
      weights[xx * size + x] = w < 0 ? Math.trunc(-0.5 + w * (1 << PRECISION_BITS)) : Math.trunc(0.5 + w * (1 << PRECISION_BITS));
    }
    bounds[xx * 2] = xmin; bounds[xx * 2 + 1] = xmax;
  }
  return { bounds, weights, size };
}

const clip8 = (value: number): number => { const v = Math.floor(value / (1 << PRECISION_BITS)); return v < 0 ? 0 : v > 255 ? 255 : v; };

/** Pillow's Image.resize(..., BILINEAR) on 8-bit interleaved pixels with `channels` channels. With `window` [x0,y0,x1,y1)
 * only those output pixels are computed and the rest are 0: exact when the source is 0 wherever it does not reach them. */
export function resizeBilinear(source: Uint8Array, width: number, height: number, channels: number, outWidth: number, outHeight: number,
  window: Box = [0, 0, outWidth, outHeight]): Uint8Array {
  if (source.length !== width * height * channels) throw new Error('Invalid pixels for their size.');
  const [wx0, wy0, wx1, wy1] = window;
  let pixels = source, w = width;
  if (outWidth !== width) {
    const c = coefficients(width, outWidth), out = new Uint8Array(outWidth * height * channels);
    for (let y = 0; y < height; y++) for (let xx = wx0; xx < wx1; xx++) {
      const xmin = c.bounds[xx * 2] ?? 0, xmax = c.bounds[xx * 2 + 1] ?? 0, base = xx * c.size;
      for (let ch = 0; ch < channels; ch++) {
        let sum = 1 << (PRECISION_BITS - 1);
        for (let x = 0; x < xmax; x++) sum += (pixels[(y * w + x + xmin) * channels + ch] ?? 0) * (c.weights[base + x] ?? 0);
        out[(y * outWidth + xx) * channels + ch] = clip8(sum);
      }
    }
    pixels = out; w = outWidth;
  }
  if (outHeight !== height) {
    const c = coefficients(height, outHeight), out = new Uint8Array(w * outHeight * channels);
    const [x0, x1] = w === outWidth ? [wx0, wx1] : [0, w];
    for (let yy = wy0; yy < wy1; yy++) {
      const ymin = c.bounds[yy * 2] ?? 0, ymax = c.bounds[yy * 2 + 1] ?? 0, base = yy * c.size;
      for (let x = x0; x < x1; x++) for (let ch = 0; ch < channels; ch++) {
        let sum = 1 << (PRECISION_BITS - 1);
        for (let y = 0; y < ymax; y++) sum += (pixels[((y + ymin) * w + x) * channels + ch] ?? 0) * (c.weights[base + y] ?? 0);
        out[(yy * w + x) * channels + ch] = clip8(sum);
      }
    }
    pixels = out;
  }
  return pixels === source ? source.slice() : pixels;
}

/** The reference squashed to the encoder's 1024x1024 as RGB (alpha dropped, as Pillow's convert('RGB') does): all the
 * encoder needs, so the service keeps this (3 MB) instead of the full-size pixels to study a reference again. */
export function squareRgb(rgba: Uint8Array, width: number, height: number): Uint8Array {
  if (rgba.length !== width * height * 4) throw new Error('Invalid reference pixels for their size.');
  const rgb = new Uint8Array(width * height * 3);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j += 3) { rgb[j] = rgba[i] ?? 0; rgb[j + 1] = rgba[i + 1] ?? 0; rgb[j + 2] = rgba[i + 2] ?? 0; }
  return resizeBilinear(rgb, width, height, 3, ENCODER_SIZE, ENCODER_SIZE);
}

/** pixel_values [1,3,1024,1024] from the 1024 square: /255, then ImageNet's mean and std, channels first. */
export function normalise(square: Uint8Array): Float32Array {
  const plane = ENCODER_SIZE * ENCODER_SIZE;
  if (square.length !== plane * 3) throw new Error('Invalid encoder square.');
  const out = new Float32Array(3 * plane);
  for (let i = 0; i < plane; i++) for (let ch = 0; ch < 3; ch++)
    out[ch * plane + i] = (Math.fround((square[i * 3 + ch] ?? 0) / 255) - (MEAN[ch] ?? 0)) / (STD[ch] ?? 1);
  return out;
}

/** The vision encoder's pixel_values [1,3,1024,1024] from RGBA pixels. */
export const encoderInput = (rgba: Uint8Array, width: number, height: number): Float32Array => normalise(squareRgb(rgba, width, height));

/** Refuses a prompt that is not one box or a few labelled points inside a width x height reference. */
export function checkPrompt(prompt: unknown, width: number, height: number): asserts prompt is ShapePrompt {
  const value = (prompt && typeof prompt === 'object' ? prompt : {}) as Record<string, unknown>;
  const hasBox = 'box' in value, hasPoints = 'points' in value;
  if (hasBox === hasPoints) throw new Error('A shape needs a box or points, not both.');
  const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
  if (hasBox) {
    const box = value.box;
    if (!Array.isArray(box) || box.length !== 4 || !box.every(finite)) throw new Error('A shape box is [x, y, width, height] in reference pixels.');
    const [x, y, w, h] = box as Box;
    if (!(w > 0 && h > 0)) throw new Error('A shape box needs a positive width and height.');
    if (x < 0 || y < 0 || x + w > width || y + h > height) throw new Error(`A shape box must lie inside the reference (${width}x${height}).`);
    return;
  }
  const points = value.points;
  if (!Array.isArray(points) || !points.length || points.length > 16) throw new Error('A shape needs 1-16 points [x, y, label].');
  for (const point of points) {
    if (!Array.isArray(point) || point.length !== 3 || !point.every(finite)) throw new Error('Each shape point is [x, y, label].');
    const [x, y, label] = point as Point;
    if (label !== 0 && label !== 1) throw new Error('A point label is 1 (part of the element) or 0 (not part of it).');
    if (x < 0 || y < 0 || x > width || y > height) throw new Error(`Shape points must lie inside the reference (${width}x${height}).`);
  }
}

/** The decoder's prompt inputs in 1024 space: input_points [1,1,N,2], input_labels [1,1,N] and input_boxes [1,1,4] or none. */
export function decoderPrompt(prompt: ShapePrompt, width: number, height: number): { points: Float32Array; labels: BigInt64Array; count: number; box: Float32Array | null } {
  const sx = ENCODER_SIZE / width, sy = ENCODER_SIZE / height;
  if ('box' in prompt) {
    const [x, y, w, h] = prompt.box;
    return { points: new Float32Array(0), labels: new BigInt64Array(0), count: 0, box: Float32Array.from([x * sx, y * sy, (x + w) * sx, (y + h) * sy]) };
  }
  const points = new Float32Array(prompt.points.length * 2), labels = new BigInt64Array(prompt.points.length);
  prompt.points.forEach(([x, y, label], i) => { points[i * 2] = x * sx; points[i * 2 + 1] = y * sy; labels[i] = BigInt(label); });
  return { points, labels, count: prompt.points.length, box: null };
}

/** The best mask's size x size logits as a width x height mask, 255 inside and 0 outside. */
export function maskFromLogits(logits: Float32Array, size: number, width: number, height: number): Uint8Array {
  if (logits.length !== size * size) throw new Error('Invalid mask logits for their size.');
  const low = new Uint8Array(size * size);
  for (let i = 0; i < low.length; i++) low[i] = (logits[i] ?? 0) > 0 ? 255 : 0;
  const inside = maskBounds(low, size, size);
  if (!inside) return new Uint8Array(width * height);
  // Only the output pixels the low-resolution shape can reach (a bilinear tap spans at most 2 source pixels when
  // enlarging, 2 x the scale when shrinking): the same bytes, about 10 times faster for one element of a large image.
  const reach = (start: number, end: number, out: number) => {
    const scale = size / out, margin = Math.max(1, scale) + 1;
    return [Math.max(0, Math.floor((start - margin) / scale) - 1), Math.min(out, Math.ceil((end + margin) / scale) + 1)];
  };
  const [ix, iy, iw, ih] = inside, [x0 = 0, x1 = width] = reach(ix, ix + iw, width), [y0 = 0, y1 = height] = reach(iy, iy + ih, height);
  const full = resizeBilinear(low, size, size, 1, width, height, [x0, y0, x1, y1]);
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) { const i = y * width + x; full[i] = (full[i] ?? 0) > 127 ? 255 : 0; }
  return full;
}

/** The smallest [x,y,w,h] holding every pixel of the mask, or null for an empty mask. */
export function maskBounds(mask: Uint8Array, width: number, height: number): Box | null {
  let x0 = width, y0 = height, x1 = -1, y1 = -1;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) if (mask[y * width + x]) {
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
  return x1 < 0 ? null : [x0, y0, x1 - x0 + 1, y1 - y0 + 1];
}

/** The mask cut to its bounds, row by row. */
export function cropMask(mask: Uint8Array, width: number, bounds: Box): Uint8Array {
  const [x, y, w, h] = bounds, out = new Uint8Array(w * h);
  for (let row = 0; row < h; row++) out.set(mask.subarray((y + row) * width + x, (y + row) * width + x + w), row * w);
  return out;
}

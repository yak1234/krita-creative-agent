// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// A bounded copy of a large picture, made in the companion (LIVE rehearsal 2, Toska, 2026-10-24): a goal sharpened 4x is
// 25 million pixels and a 38 MB PNG. The tools that only need a working size of it (Find it, the masses, the likeness grid,
// the accents finder) sent the whole file to Krita, whose plugin decoded it reduced on the GUI thread (about 4 s for
// trace_reference), and Find it then sent the decision model a 2309 x 1732 grid picture (9.7 MB). Here the file is read
// once (png-rgba.ts), reduced by averaging blocks of pixels to at most `maxPixels`, and kept in the chat folder's .bounded
// by content and size, so the next call reads a small file. The plugin's tools take the copy as they took the original:
// their `source` and `size` are in the pixels the companion lists the picture at, and they map them to what they decode.
//
//   const copy = await boundedImage(directory, goal.path, TRACE_PIXELS);   // { path, data, sha256, width, height, reduced }
//   const view = await boundedPixels(directory, goal.path, FIND_PIXELS);   // { sha, pixels } or null: Krita must read it
//
// A file already within bounds is used as it is. One this module does not read (JPEG, interlaced, a colour profile) is
// used as it is too, and boundedPixels returns null: the caller decodes it through the plugin as before.
// Mechanism only: no .mjs imports.
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, rename, stat, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { decodeRgba, pngSize } from './png-rgba.ts';
import { encodeRgba } from './shapes/png.ts';

export type Rgba = { width: number; height: number; data: Uint8Array };
export type BoundedImage = { path: string; data: Buffer; sha256: string; width: number; height: number;
  /** Whether this is a reduced copy (false: the file itself). */
  reduced: boolean; source_sha256: string };
/** Bounded copies kept in a chat's .bounded. */
export const BOUNDED_KEPT = 8;
const COPY = /^[0-9a-f]{32}-\d+\.png$/;

/** The picture reduced to at most `maxPixels` on its own proportions by area averaging (each output pixel the exact
 * area-weighted mean of the source pixels it covers, as Qt's smooth scaling and OpenCV's INTER_AREA reduce: the plugin's
 * own reduced decode), weighted by alpha so a clear pixel adds no colour; the picture itself when it is within bounds. */
export function reduceRgba(image: Rgba, maxPixels: number): Rgba {
  const { width, height, data } = image;
  if (width * height <= maxPixels) return image;
  const k = Math.sqrt(maxPixels / (width * height));
  let w = Math.max(1, Math.floor(width * k)), h = Math.max(1, Math.floor(height * k));
  while (w * h > maxPixels && (w > 1 || h > 1)) { if (w >= h && w > 1) w--; else h--; }
  // Each source pixel covers at most two output pixels on an axis (a reduction): the first, and its share of it.
  const split = (from: number, to: number) => {
    const scale = from / to, first = new Int32Array(from), share = new Float64Array(from);
    for (let x = 0; x < from; x++) {
      const o = Math.min(to - 1, Math.floor(x / scale)), edge = (o + 1) * scale;
      first[x] = o; share[x] = x + 1 <= edge || o === to - 1 ? 1 : edge - x;
    }
    return { first, share };
  };
  const cols = split(width, w), rows = split(height, h);
  const line = new Float64Array(w * 4), acc = new Float64Array(w * h * 4), out = new Uint8Array(w * h * 4);
  for (let y = 0; y < height; y++) {
    line.fill(0);
    for (let x = 0, p = y * width * 4; x < width; x++, p += 4) {
      const alpha = data[p + 3]!, o = cols.first[x]! * 4, a = cols.share[x]!, r = data[p]! * alpha, g = data[p + 1]! * alpha, b = data[p + 2]! * alpha;
      line[o] += r * a; line[o + 1] += g * a; line[o + 2] += b * a; line[o + 3] += alpha * a;
      if (a < 1) { const c = 1 - a; line[o + 4] += r * c; line[o + 5] += g * c; line[o + 6] += b * c; line[o + 7] += alpha * c; }
    }
    const o = rows.first[y]!, a = rows.share[y]!;
    for (let i = 0, t = o * w * 4; i < w * 4; i++) acc[t + i] += line[i]! * a;
    if (a < 1) for (let i = 0, t = (o + 1) * w * 4, c = 1 - a; i < w * 4; i++) acc[t + i] += line[i]! * c;
  }
  const area = (width / w) * (height / h);
  for (let i = 0; i < w * h; i++) {
    const t = i * 4, a = acc[t + 3]!;
    if (a > 0) { out[t] = Math.round(acc[t]! / a); out[t + 1] = Math.round(acc[t + 1]! / a); out[t + 2] = Math.round(acc[t + 2]! / a); }
    out[t + 3] = Math.min(255, Math.round(a / area));
  }
  return { width: w, height: h, data: out };
}

const sha256 = (data: Uint8Array) => createHash('sha256').update(data).digest('hex');
// The last copies made or read in this process, by file and size, so a call per batch reads nothing again.
const recent = new Map<string, Promise<BoundedImage & { pixels?: Rgba | null }>>();
const RECENT = 4;

async function prune(folder: string): Promise<void> {
  let names: string[];
  try { names = (await readdir(folder)).filter(name => COPY.test(name)); } catch { return; }
  const dated = await Promise.all(names.map(async name => ({ name, time: await stat(join(folder, name)).then(info => info.mtimeMs, () => 0) })));
  dated.sort((a, b) => b.time - a.time || a.name.localeCompare(b.name));
  await Promise.all(dated.slice(BOUNDED_KEPT).map(({ name }) => unlink(join(folder, name)).catch(() => {})));
}

async function make(directory: string, path: string, maxPixels: number): Promise<BoundedImage & { pixels?: Rgba | null }> {
  const file = await readFile(path), source_sha256 = sha256(file), size = pngSize(file);
  const itself = { path, data: file, sha256: source_sha256, width: size?.width ?? 0, height: size?.height ?? 0, reduced: false, source_sha256 };
  if (!size || size.width * size.height <= maxPixels) return itself;
  const folder = join(directory, '.bounded'), copy = join(folder, `${source_sha256.slice(0, 32)}-${maxPixels}.png`);
  try {
    const data = await readFile(copy), known = pngSize(data);
    if (known) return { path: copy, data, sha256: sha256(data), width: known.width, height: known.height, reduced: true, source_sha256 };
  } catch { /* not made yet */ }
  const decoded = decodeRgba(file);
  if (!decoded) return { ...itself, pixels: null };
  const pixels = reduceRgba(decoded, maxPixels), data = encodeRgba(pixels);
  await mkdir(folder, { recursive: true });
  const temporary = copy + '.' + process.pid;
  await writeFile(temporary, data); await rename(temporary, copy);
  await prune(folder);
  return { path: copy, data, sha256: sha256(data), width: pixels.width, height: pixels.height, reduced: true, source_sha256, pixels };
}

async function bounded(directory: string, path: string, maxPixels: number): Promise<BoundedImage & { pixels?: Rgba | null }> {
  const info = await stat(path), key = [directory, path, info.size, info.mtimeMs, maxPixels].join(':');
  let known = recent.get(key);
  if (!known) {
    known = make(directory, path, maxPixels);
    recent.set(key, known); known.catch(() => recent.delete(key));
    while (recent.size > RECENT) recent.delete(recent.keys().next().value!);
  }
  return known;
}

/** The picture at `path` as a file of at most `maxPixels`: a reduced copy in `directory`/.bounded, made once per content
 * and size; the file itself when it is within bounds or not a plain PNG this module reads. */
export async function boundedImage(directory: string, path: string, maxPixels: number): Promise<BoundedImage> {
  const { pixels: _pixels, ...image } = await bounded(directory, path, maxPixels);
  return image;
}

/** The pixels of boundedImage (RGBA, not premultiplied) and their file's hash; null when only Krita can read the file. */
export async function boundedPixels(directory: string, path: string, maxPixels: number): Promise<{ sha: string; pixels: Rgba; image: BoundedImage } | null> {
  const known = await bounded(directory, path, maxPixels);
  const { pixels: kept, ...image } = known;
  if (kept === null) return null;
  const pixels = kept ?? decodeRgba(image.data, Math.max(maxPixels, image.width * image.height));
  if (!pixels) { known.pixels = null; return null; }
  known.pixels = pixels;
  return { sha: image.sha256, pixels, image };
}

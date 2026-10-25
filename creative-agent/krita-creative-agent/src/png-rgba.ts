// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// A large reference decoded in the companion instead of Krita (reference-tool.mjs): a goal sharpened 4x is 25 million
// pixels, and the plugin's decode_reference holds it on Krita's GUI thread for about 0.7 s and some 700 MB, then sends
// 134 MB of base64 back. A plain PNG is read here, bounded: 8-bit grey, grey+alpha, RGB or RGBA, not interlaced, and with
// no colour profile, gamma or chromaticities (those are left to the plugin, which converts them to sRGB as Qt does);
// anything else returns null and goes to the plugin as before. Out: RGBA, not premultiplied (Qt's Format_RGBA8888).
import { inflateSync } from 'node:zlib';
import { REFERENCE_PIXELS } from './reference-limits.ts';

const SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const CHANNELS: Record<number, number> = { 0: 1, 2: 3, 4: 2, 6: 4 };
const COLOUR_CHUNKS = new Set(['iCCP', 'gAMA', 'cHRM']);

/** The PNG's declared size from its header, or null when it is not a PNG. */
export function pngSize(file: Uint8Array): { width: number; height: number } | null {
  const data = Buffer.from(file.buffer, file.byteOffset, file.byteLength);
  if (data.length < 33 || !data.subarray(0, 8).equals(SIGNATURE) || data.toString('latin1', 12, 16) !== 'IHDR') return null;
  return { width: data.readUInt32BE(16), height: data.readUInt32BE(20) };
}

/** `ignoreColour`: read a PNG with a colour profile, gamma or chromaticities as if it were sRGB (a canvas reference compares
 * an image model's PNG with the canvas view, both sRGB in practice; canvas-reference.ts). */
export function decodeRgba(file: Uint8Array, maxPixels = REFERENCE_PIXELS, { ignoreColour = false }: { ignoreColour?: boolean } = {}): { width: number; height: number; data: Buffer } | null {
  const data = Buffer.from(file.buffer, file.byteOffset, file.byteLength), size = pngSize(data);
  if (!size || !size.width || !size.height || size.width * size.height > maxPixels) return null;
  const { width, height } = size, colour = data[25] ?? -1, channels = CHANNELS[colour];
  if (data[24] !== 8 || data[28] !== 0 || !channels) return null;
  const parts: Buffer[] = [];
  for (let at = 33; ;) {
    if (at + 12 > data.length) return null;
    const length = data.readUInt32BE(at), kind = data.toString('latin1', at + 4, at + 8);
    if (at + 12 + length > data.length) return null;
    if (COLOUR_CHUNKS.has(kind) && !ignoreColour) return null;
    if (kind === 'IDAT') parts.push(data.subarray(at + 8, at + 8 + length));
    if (kind === 'IEND') break;
    at += 12 + length;
  }
  const stride = width * channels, expected = height * (stride + 1);
  let raw: Buffer;
  try { raw = inflateSync(Buffer.concat(parts), { maxOutputLength: expected }); } catch { return null; }
  if (raw.length !== expected) return null;
  const rows = new Uint8Array(stride * height);
  for (let y = 0; y < height; y++) {
    const kind = raw[y * (stride + 1)], src = y * (stride + 1) + 1, row = y * stride, up = row - stride;
    if (kind === 0) { rows.set(raw.subarray(src, src + stride), row); continue; }
    for (let i = 0; i < stride; i++) {
      const x = raw[src + i]!, a = i >= channels ? rows[row + i - channels]! : 0, b = y ? rows[up + i]! : 0;
      let p: number;
      if (kind === 1) p = a; else if (kind === 2) p = b; else if (kind === 3) p = (a + b) >> 1;
      else if (kind === 4) {
        const c = y && i >= channels ? rows[up + i - channels]! : 0, q = a + b - c;
        const pa = q > a ? q - a : a - q, pb = q > b ? q - b : b - q, pc = q > c ? q - c : c - q;
        p = pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      } else return null;
      rows[row + i] = (x + p) & 255;
    }
  }
  if (channels === 4) return { width, height, data: Buffer.from(rows.buffer, rows.byteOffset, rows.byteLength) };
  const out = Buffer.alloc(width * height * 4);
  for (let i = 0, j = 0; i < out.length; i += 4, j += channels) {
    const grey = channels <= 2;
    out[i] = rows[j]!; out[i + 1] = grey ? rows[j]! : rows[j + 1]!; out[i + 2] = grey ? rows[j]! : rows[j + 2]!;
    out[i + 3] = channels === 2 ? rows[j + 1]! : channels === 4 ? rows[j + 3]! : 255;
  }
  return { width, height, data: out };
}

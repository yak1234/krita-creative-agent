// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Tests only: an unbounded PNG reader to RGBA (the opt-in benchmark reads a reference copy, the tests read masks) and a
// writer of grey, RGB and RGBA PNGs. The companion reads and writes shape files with src/shapes/png.ts (bounded).
import { deflateSync, inflateSync } from 'node:zlib';

const SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; table[n] = c >>> 0; }
  return table;
})();

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (const byte of bytes) c = (CRC_TABLE[(c ^ byte) & 0xff] ?? 0) ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Uint8Array): Buffer {
  const out = Buffer.alloc(12 + data.length);
  out.writeUInt32BE(data.length, 0); out.write(type, 4, 'latin1'); out.set(data, 8);
  out.writeUInt32BE(crc32(out.subarray(4, 8 + data.length)), 8 + data.length);
  return out;
}

const COLOUR_TYPE: Record<number, number> = { 1: 0, 2: 4, 3: 2, 4: 6 };

/** An 8-bit PNG of grey (1), grey+alpha (2), RGB (3) or RGBA (4) pixels. */
export function encodePng({ width, height, channels, data }: { width: number; height: number; channels: 1 | 2 | 3 | 4; data: Uint8Array }): Buffer {
  if (data.length !== width * height * channels) throw new Error('Invalid pixels for their size.');
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = COLOUR_TYPE[channels] ?? 0;
  const stride = width * channels, raw = Buffer.alloc((stride + 1) * height);
  for (let y = 0; y < height; y++) raw.set(data.subarray(y * stride, (y + 1) * stride), y * (stride + 1) + 1);   // filter 0 (none)
  return Buffer.concat([SIGNATURE, chunk('IHDR', header), chunk('IDAT', deflateSync(raw)), chunk('IEND', new Uint8Array(0))]);
}

const paeth = (a: number, b: number, c: number): number => {
  const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
};

/** RGBA pixels from an 8-bit, non-interlaced grey, grey+alpha, RGB, RGBA or palette PNG. */
export function decodePng(file: Uint8Array): { width: number; height: number; data: Uint8Array } {
  const bytes = Buffer.from(file.buffer, file.byteOffset, file.byteLength);
  if (bytes.length < 8 || !bytes.subarray(0, 8).equals(SIGNATURE)) throw new Error('Not a PNG file.');
  let width = 0, height = 0, type = -1, palette: Uint8Array | null = null, transparency: Uint8Array | null = null;
  const parts: Buffer[] = [];
  for (let at = 8; at + 8 <= bytes.length;) {
    const length = bytes.readUInt32BE(at), name = bytes.toString('latin1', at + 4, at + 8), data = bytes.subarray(at + 8, at + 8 + length);
    if (name === 'IHDR') {
      width = data.readUInt32BE(0); height = data.readUInt32BE(4); type = data[9] ?? -1;
      if (data[8] !== 8 || data[12] !== 0) throw new Error('Only 8-bit, non-interlaced PNG files are read here.');
    } else if (name === 'PLTE') palette = data;
    else if (name === 'tRNS') transparency = data;
    else if (name === 'IDAT') parts.push(data);
    else if (name === 'IEND') break;
    at += 12 + length;
  }
  const channels = ({ 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 } as Record<number, number>)[type];
  if (!channels || !width || !height) throw new Error('Unsupported PNG file.');
  const raw = inflateSync(Buffer.concat(parts)), stride = width * channels, pixels = new Uint8Array(stride * height);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)], row = y * stride, src = y * (stride + 1) + 1;
    for (let x = 0; x < stride; x++) {
      const value = raw[src + x] ?? 0, left = x >= channels ? pixels[row + x - channels] ?? 0 : 0, up = y ? pixels[row - stride + x] ?? 0 : 0;
      const corner = y && x >= channels ? pixels[row - stride + x - channels] ?? 0 : 0;
      pixels[row + x] = (value + (filter === 1 ? left : filter === 2 ? up : filter === 3 ? (left + up) >> 1 : filter === 4 ? paeth(left, up, corner) : 0)) & 0xff;
    }
  }
  const out = new Uint8Array(width * height * 4);
  for (let i = 0; i < width * height; i++) {
    const p = i * channels, o = i * 4;
    if (type === 3) {
      const index = pixels[p] ?? 0;
      out[o] = palette?.[index * 3] ?? 0; out[o + 1] = palette?.[index * 3 + 1] ?? 0; out[o + 2] = palette?.[index * 3 + 2] ?? 0;
      out[o + 3] = transparency?.[index] ?? 255;
    } else if (channels <= 2) {
      out[o] = out[o + 1] = out[o + 2] = pixels[p] ?? 0; out[o + 3] = channels === 2 ? pixels[p + 1] ?? 255 : 255;
    } else {
      out[o] = pixels[p] ?? 0; out[o + 1] = pixels[p + 1] ?? 0; out[o + 2] = pixels[p + 2] ?? 0; out[o + 3] = channels === 4 ? pixels[p + 3] ?? 255 : 255;
    }
  }
  return { width, height, data: out };
}

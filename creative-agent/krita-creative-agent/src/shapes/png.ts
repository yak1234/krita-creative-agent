// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// One-byte-a-pixel PNGs for element shapes: the shape service's mask files are read here, and a shape used on the
// painting is written for the plugin (shape_mask.py) as grey rows with filter 0, which it reads at zlib's speed.
import { deflateSync, inflateSync } from 'node:zlib';

export type Plane = { width: number; height: number; data: Uint8Array };
const SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const CHANNELS: Record<number, number> = { 0: 1, 2: 3, 4: 2, 6: 4 };
const CRC = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
const crc32 = (bytes: Uint8Array) => { let c = 0xffffffff; for (const b of bytes) c = CRC[(c ^ b) & 255]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };

const LARGEST = 16384;                       // a side no shape file is larger than, when no limit is given
const damaged = () => new Error('The shape file is damaged.');

/** An 8-bit, non-interlaced PNG as one byte a pixel: grey, or the first channel times alpha. A file larger than
 * `limit` (or LARGEST a side) is refused from its header, and the inflate never makes more than its rows. */
export function decodePlane(file: Uint8Array, limit?: { width: number; height: number }): Plane {
  const data = Buffer.from(file.buffer, file.byteOffset, file.byteLength);
  if (data.length < 8 || !data.subarray(0, 8).equals(SIGNATURE)) throw new Error('The shape file is not a PNG.');
  if (data.length < 33 || data.readUInt32BE(8) !== 13 || data.toString('latin1', 12, 16) !== 'IHDR') throw damaged();
  const width = data.readUInt32BE(16), height = data.readUInt32BE(20), colour = data[25] ?? -1;
  if (data[24] !== 8 || data[28] !== 0 || !(colour in CHANNELS) || !width || !height) throw new Error('A shape is an 8-bit PNG.');
  const most = limit ?? { width: LARGEST, height: LARGEST };
  if (width > most.width || height > most.height)
    throw new Error(`The shape file is ${width} x ${height}, larger than the ${most.width} x ${most.height} image it was found on.`);
  let position = 33;
  const parts: Buffer[] = [];
  for (;;) {
    if (position + 12 > data.length) throw damaged();
    const length = data.readUInt32BE(position), kind = data.toString('latin1', position + 4, position + 8);
    if (position + 12 + length > data.length || kind === 'IHDR') throw damaged();
    if (kind === 'IDAT') parts.push(data.subarray(position + 8, position + 8 + length));
    else if (kind === 'IEND') break;
    position += 12 + length;
  }
  const channels = CHANNELS[colour];
  if (!channels) throw damaged();
  const stride = width * channels, size = height * (stride + 1);
  let raw: Buffer;
  try { raw = inflateSync(Buffer.concat(parts), { maxOutputLength: size }); } catch { throw damaged(); }
  if (raw.length !== size) throw damaged();
  const pixels = new Uint8Array(stride * height);
  for (let y = 0; y < height; y++) {
    const kind = raw[y * (stride + 1)], row = y * stride;
    for (let i = 0; i < stride; i++) {
      const x = raw[y * (stride + 1) + 1 + i]!, a = i >= channels ? pixels[row + i - channels]! : 0;
      const b = y ? pixels[row - stride + i]! : 0, c = y && i >= channels ? pixels[row - stride + i - channels]! : 0;
      let predicted = 0;
      if (kind === 1) predicted = a; else if (kind === 2) predicted = b; else if (kind === 3) predicted = (a + b) >> 1;
      else if (kind === 4) { const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c); predicted = pa <= pb && pa <= pc ? a : pb <= pc ? b : c; }
      else if (kind !== 0) throw new Error('The shape file is damaged.');
      pixels[row + i] = (x + predicted) & 255;
    }
  }
  if (channels === 1) return { width, height, data: pixels };
  const out = new Uint8Array(width * height), alpha = channels === 2 || channels === 4;
  for (let k = 0; k < out.length; k++) {
    const value = pixels[k * channels]!;
    out[k] = alpha ? Math.floor(value * pixels[k * channels + channels - 1]! / 255) : value;
  }
  return { width, height, data: out };
}

/** A grey 8-bit PNG, every row filter 0. */
export function encodePlane({ width, height, data }: Plane): Buffer {
  if (data.length !== width * height || !width || !height) throw new Error('A shape plane needs width x height bytes.');
  const raw = Buffer.alloc(height * (width + 1));
  for (let y = 0; y < height; y++) raw.set(data.subarray(y * width, (y + 1) * width), y * (width + 1) + 1);
  const chunk = (kind: string, body: Buffer) => {
    const head = Buffer.alloc(8); head.writeUInt32BE(body.length, 0); head.write(kind, 4, 'latin1');
    const tail = Buffer.alloc(4); tail.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), body])), 0);
    return Buffer.concat([head, body, tail]);
  };
  const header = Buffer.alloc(13); header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8;
  return Buffer.concat([SIGNATURE, chunk('IHDR', header), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

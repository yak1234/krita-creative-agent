// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// 8-bit RGB PNGs for the sharpened goal: each row takes the filter (none, Sub, Up, Average, Paeth) whose bytes sum
// smallest as signed values (the PNG specification's suggested heuristic, on a sample of a long row), then zlib.
import { crc32, deflateSync } from 'node:zlib';

const SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

function chunk(kind: string, body: Buffer): Buffer {
  const head = Buffer.alloc(8); head.writeUInt32BE(body.length, 0); head.write(kind, 4, 'latin1');
  const tail = Buffer.alloc(4); tail.writeUInt32BE(crc32(body, crc32(head.subarray(4))), 0);
  return Buffer.concat([head, body, tail]);
}

const predict = (kind: number, a: number, b: number, c: number) => {
  if (kind === 1) return a; if (kind === 2) return b; if (kind === 3) return (a + b) >> 1;
  if (kind === 4) { const q = a + b - c, pa = Math.abs(q - a), pb = Math.abs(q - b), pc = Math.abs(q - c); return pa <= pb && pa <= pc ? a : pb <= pc ? b : c; }
  return 0;
};

/** One row filtered by `kind`, a loop per kind (no call per byte: this is most of the time for a large picture). */
function filterRow(kind: number, row: Uint8Array, prev: Uint8Array, out: Uint8Array): void {
  const n = row.length;
  if (kind === 0) { out.set(row); return; }
  if (kind === 2) { for (let i = 0; i < n; i++) out[i] = (row[i]! - prev[i]!) & 255; return; }
  for (let i = 0; i < 3; i++) out[i] = (row[i]! - (kind === 1 ? 0 : kind === 3 ? prev[i]! >> 1 : prev[i]!)) & 255;
  if (kind === 1) { for (let i = 3; i < n; i++) out[i] = (row[i]! - row[i - 3]!) & 255; return; }
  if (kind === 3) { for (let i = 3; i < n; i++) out[i] = (row[i]! - ((row[i - 3]! + prev[i]!) >> 1)) & 255; return; }
  for (let i = 3; i < n; i++) {
    const a = row[i - 3]!, b = prev[i]!, c = prev[i - 3]!, q = a + b - c;
    const pa = q > a ? q - a : a - q, pb = q > b ? q - b : b - q, pc = q > c ? q - c : c - q;
    out[i] = (row[i]! - (pa <= pb && pa <= pc ? a : pb <= pc ? b : c)) & 255;
  }
}

/** `level`: zlib's (1 is several times faster than the default 6 on a large picture, for a file about a tenth larger). */
export function encodeRgb(width: number, height: number, rgb: Uint8Array, level = 6): Buffer {
  const stride = width * 3;
  if (!width || !height || rgb.length !== stride * height) throw new Error('An RGB picture needs width x height x 3 bytes.');
  const raw = Buffer.alloc(height * (stride + 1)), zero = new Uint8Array(stride);
  // Each row's filter is chosen from every SAMPLE-th byte (the costs differ by far more than the sample misses), then the
  // row is filtered once: a fifth of the work of trying all five on every byte, for nearly the same file.
  const SAMPLE = stride > 3000 ? 7 : 1;
  for (let y = 0; y < height; y++) {
    const row = rgb.subarray(y * stride, (y + 1) * stride), prev = y ? rgb.subarray((y - 1) * stride, y * stride) : zero;
    let best = 0, bestCost = Infinity;
    for (let kind = 0; kind < 5; kind++) {
      let cost = 0;
      for (let i = 0; i < stride && cost < bestCost; i += SAMPLE) {
        const v = (row[i]! - predict(kind, i >= 3 ? row[i - 3]! : 0, prev[i]!, i >= 3 ? prev[i - 3]! : 0)) & 255;
        cost += v < 128 ? v : 256 - v;
      }
      if (cost < bestCost) { bestCost = cost; best = kind; }
    }
    const at = y * (stride + 1);
    raw[at] = best;
    filterRow(best, row, prev, raw.subarray(at + 1, at + 1 + stride));
  }
  const header = Buffer.alloc(13); header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 2;
  return Buffer.concat([SIGNATURE, chunk('IHDR', header), chunk('IDAT', deflateSync(raw, { level })), chunk('IEND', Buffer.alloc(0))]);
}

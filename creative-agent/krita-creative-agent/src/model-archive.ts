// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The members of a zip, for a model its publisher ships as one (the sharpening model, src/upscale/model.ts): the central
// directory is read from the end of the file, and a member is streamed through zlib's raw inflate into a file, never
// writing more than the size the directory lists. Stored and deflated members only; ZIP64 and encrypted members are
// refused. The caller checks each extracted file against its pinned SHA-256.
import { createReadStream, createWriteStream } from 'node:fs';
import { open } from 'node:fs/promises';
import { Transform, type TransformCallback } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { createInflateRaw } from 'node:zlib';

export type ZipEntry = { name: string; method: number; compressed: number; size: number; offset: number; flags: number };

const END = 0x06054b50, CENTRAL = 0x02014b50, LOCAL = 0x04034b50;
const notZip = () => new Error('The model download is not a zip archive it can read.');

/** The archive's members, in the order its central directory lists them. */
export async function zipEntries(path: string): Promise<ZipEntry[]> {
  const handle = await open(path, 'r');
  try {
    const { size } = await handle.stat();
    const tail = Math.min(size, 22 + 65535), buffer = Buffer.alloc(tail);
    await handle.read(buffer, 0, tail, size - tail);
    let at = -1;
    for (let i = tail - 22; i >= 0; i--) if (buffer.readUInt32LE(i) === END) { at = i; break; }
    if (at < 0) throw notZip();
    const count = buffer.readUInt16LE(at + 10), length = buffer.readUInt32LE(at + 12), start = buffer.readUInt32LE(at + 16);
    if (count === 0xffff || length === 0xffffffff || start === 0xffffffff || start + length > size) throw notZip();
    const directory = Buffer.alloc(length);
    await handle.read(directory, 0, length, start);
    const entries: ZipEntry[] = [];
    let p = 0;
    for (let n = 0; n < count; n++) {
      if (p + 46 > directory.length || directory.readUInt32LE(p) !== CENTRAL) throw notZip();
      const nameLength = directory.readUInt16LE(p + 28), extra = directory.readUInt16LE(p + 30), comment = directory.readUInt16LE(p + 32);
      entries.push({ name: directory.toString('utf8', p + 46, p + 46 + nameLength), flags: directory.readUInt16LE(p + 8), method: directory.readUInt16LE(p + 10),
        compressed: directory.readUInt32LE(p + 20), size: directory.readUInt32LE(p + 24), offset: directory.readUInt32LE(p + 42) });
      p += 46 + nameLength + extra + comment;
    }
    return entries;
  } finally { await handle.close(); }
}

/** Passes bytes through, failing once more than `limit` went by. */
function capped(limit: number): Transform {
  let seen = 0;
  return new Transform({
    transform(chunk: Buffer, _encoding: BufferEncoding, done: TransformCallback) {
      seen += chunk.length;
      if (seen > limit) done(new Error(`A file in the model download is larger than its archive says (${limit} bytes): refused.`));
      else done(null, chunk);
    },
  });
}

/** Writes one member to `target` (created or replaced). */
export async function extractEntry(path: string, entry: ZipEntry, target: string): Promise<void> {
  if (entry.flags & 1) throw new Error(`${entry.name} in the model download is encrypted.`);
  if (entry.method !== 0 && entry.method !== 8) throw new Error(`${entry.name} in the model download uses a compression it cannot read.`);
  const handle = await open(path, 'r'), header = Buffer.alloc(30);
  let start: number;
  try {
    await handle.read(header, 0, 30, entry.offset);
    if (header.readUInt32LE(0) !== LOCAL) throw notZip();
    start = entry.offset + 30 + header.readUInt16LE(26) + header.readUInt16LE(28);
  } finally { await handle.close(); }
  const source = createReadStream(path, { start, end: start + entry.compressed - 1 });
  const steps = entry.method === 8 ? [source, createInflateRaw(), capped(entry.size)] : [source, capped(entry.size)];
  await pipeline([...steps, createWriteStream(target)]);
}

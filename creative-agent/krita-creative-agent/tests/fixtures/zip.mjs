// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// A tiny zip writer for the tests of models published as a zip (model-archive.test.mjs, upscale-model.test.mjs).
import { crc32, deflateRawSync } from 'node:zlib';

/** A zip of `files` ({name: Buffer}), deflated unless `stored`; `lie` makes one member claim a smaller size. */
export function makeZip(files, { stored = false, lie = null } = {}) {
  const locals = [], central = [];
  let offset = 0;
  for (const [name, data] of Object.entries(files)) {
    const body = stored ? data : deflateRawSync(data), nameBytes = Buffer.from(name), method = stored ? 0 : 8;
    const size = lie === name ? Math.max(0, data.length - 10) : data.length;
    const local = Buffer.alloc(30); local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(method, 8);
    local.writeUInt32LE(crc32(data), 14); local.writeUInt32LE(body.length, 18); local.writeUInt32LE(size, 22); local.writeUInt16LE(nameBytes.length, 26);
    locals.push(local, nameBytes, body);
    const entry = Buffer.alloc(46); entry.writeUInt32LE(0x02014b50, 0); entry.writeUInt16LE(20, 4); entry.writeUInt16LE(20, 6); entry.writeUInt16LE(method, 10);
    entry.writeUInt32LE(crc32(data), 16); entry.writeUInt32LE(body.length, 20); entry.writeUInt32LE(size, 24); entry.writeUInt16LE(nameBytes.length, 28);
    entry.writeUInt32LE(offset, 42);
    central.push(entry, nameBytes);
    offset += 30 + nameBytes.length + body.length;
  }
  const directory = Buffer.concat(central), end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(Object.keys(files).length, 8); end.writeUInt16LE(Object.keys(files).length, 10);
  end.writeUInt32LE(directory.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// A model that is published as a zip (src/model-archive.ts): its central directory is read and one member is inflated to
// a file, streamed, never more than its listed size. The zips are written here by a tiny writer, in a temporary folder
// that is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomBytes } from 'node:crypto';
import { zipEntries, extractEntry } from '../src/model-archive.ts';
import { makeZip } from './fixtures/zip.mjs';

async function folder(t) {
  const dir = await mkdtemp(join(tmpdir(), 'model-archive-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}

test('the members of a zip are listed and one is inflated to a file, deflated or stored', async t => {
  const dir = await folder(t), model = randomBytes(300000), data = Buffer.from('{"a":1}');
  for (const stored of [false, true]) {
    const zip = join(dir, `m-${stored}.zip`);
    await writeFile(zip, makeZip({ 'pack/': Buffer.alloc(0), 'pack/model.onnx': model, 'pack/meta.json': data }, { stored }));
    const entries = await zipEntries(zip);
    assert.deepEqual(entries.map(e => [e.name, e.size]), [['pack/', 0], ['pack/model.onnx', 300000], ['pack/meta.json', 7]]);
    const target = join(dir, `model-${stored}.onnx`);
    await extractEntry(zip, entries[1], target);
    assert.ok((await readFile(target)).equals(model));
  }
});

test('a member that inflates past its listed size is refused, and a file that is not a zip says so', async t => {
  const dir = await folder(t), zip = join(dir, 'lying.zip');
  await writeFile(zip, makeZip({ 'model.onnx': randomBytes(5000) }, { lie: 'model.onnx' }));
  const [entry] = await zipEntries(zip);
  await assert.rejects(extractEntry(zip, entry, join(dir, 'out')), /larger than/);
  await writeFile(join(dir, 'not.zip'), randomBytes(100));
  await assert.rejects(zipEntries(join(dir, 'not.zip')), /not a zip/);
});

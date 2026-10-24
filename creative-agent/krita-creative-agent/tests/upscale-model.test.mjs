// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The sharpening model's download (src/upscale/model.ts through shapes/model.ts downloadModel): one pinned zip, then each
// file out of it checked against its own pin; the zip goes once the files are in. A local fake server stands in for the
// asset bucket: no real network. Files go to a temporary folder that is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createHash, randomBytes } from 'node:crypto';
import { mkdtemp, readFile, readdir, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { UPSCALE_MODEL } from '../src/upscale/model.ts';
import { downloadModel, downloadBytes, modelDirectory, modelReady } from '../src/shapes/model.ts';
import { makeZip } from './fixtures/zip.mjs';
import { SHAPES_MODEL } from '../src/shapes/model.ts';

const sha = data => createHash('sha256').update(data).digest('hex');
const GRAPH = randomBytes(4000), DATA = randomBytes(150000);

function spec(base, zip, files = { 'm.onnx': GRAPH, 'm.data': DATA }) {
  return { name: 'fake-upscaler', repo: 'someone/fake', revision: 'r1', licence: 'BSD-3-Clause', label: 'the sharpening model',
    archive: { url: base + '/models/fake.zip', size: zip.length, sha256: sha(zip), folder: 'pack/' },
    files: Object.entries(files).map(([name, data]) => ({ name, size: data.length, sha256: sha(data) })) };
}

async function bucket(t, zip, { cut = false } = {}) {
  const log = [];
  let cutOnce = cut;
  const server = createServer((req, res) => {
    log.push({ url: req.url, range: req.headers.range ?? null });
    if (req.url !== '/models/fake.zip') { res.statusCode = 404; res.end(); return; }
    const range = /^bytes=(\d+)-$/.exec(req.headers.range ?? ''), from = range ? Number(range[1]) : 0, body = zip.subarray(from);
    res.writeHead(range ? 206 : 200, { 'Content-Length': body.length, ...(range ? { 'Content-Range': `bytes ${from}-${zip.length - 1}/${zip.length}` } : {}) });
    if (cutOnce) { cutOnce = false; res.write(body.subarray(0, body.length >> 1)); setTimeout(() => res.socket.destroy(), 20); return; }
    res.end(body);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  return { base: `http://127.0.0.1:${server.address().port}`, log };
}

async function folder(t) {
  const dir = await mkdtemp(join(tmpdir(), 'upscale-model-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}

test('the sharpening model is pinned: Real-ESRGAN x4plus, BSD-3-Clause, one zip and two files with their sizes and SHA-256', () => {
  assert.equal(UPSCALE_MODEL.licence, 'BSD-3-Clause');
  assert.match(UPSCALE_MODEL.archive.url, /^https:\/\/qaihub-public-assets\.s3\.us-west-2\.amazonaws\.com\/.*\/releases\/v0\.65\.0\/real_esrgan_x4plus-onnx-float\.zip$/);
  assert.deepEqual(UPSCALE_MODEL.files.map(f => f.name), ['real_esrgan_x4plus.onnx', 'real_esrgan_x4plus.data']);
  for (const pin of [UPSCALE_MODEL.archive, ...UPSCALE_MODEL.files]) { assert.match(pin.sha256, /^[0-9a-f]{64}$/); assert.ok(pin.size > 0); }
  assert.equal(Math.round(downloadBytes(UPSCALE_MODEL) / 1e6), 62);
  assert.equal(modelDirectory('/data', UPSCALE_MODEL), '/data/models/real-esrgan-x4plus/qai-hub-models-v0.65.0');
});

test('first use downloads the zip, takes each pinned file out of it, removes the zip and marks the folder ready', async t => {
  const zip = makeZip({ 'pack/': Buffer.alloc(0), 'pack/m.onnx': GRAPH, 'pack/m.data': DATA, 'pack/metadata.json': Buffer.from('{}') });
  const dir = await folder(t), hub = await bucket(t, zip), model = spec(hub.base, zip), directory = modelDirectory(dir, model), progress = [];
  await downloadModel({ directory, spec: model, onProgress: (done, total) => progress.push([done, total]) });
  assert.equal(await modelReady(directory, model), true);
  assert.ok((await readFile(join(directory, 'm.onnx'))).equals(GRAPH));
  assert.ok((await readFile(join(directory, 'm.data'))).equals(DATA));
  assert.deepEqual((await readdir(directory)).sort(), ['m.data', 'm.onnx', 'verified.json'], 'the zip and anything unpinned in it are gone');
  assert.deepEqual(progress.at(-1), [zip.length, zip.length]);
  assert.ok(progress.every(([done, total]) => total === zip.length && done <= total));
  await downloadModel({ directory, spec: model });
  assert.equal(hub.log.length, 1, 'a ready model is not downloaded again');
});

test('a broken zip download resumes from its part; a zip or a file that differs from its pin is refused and removed', async t => {
  const zip = makeZip({ 'pack/m.onnx': GRAPH, 'pack/m.data': DATA });
  const dir = await folder(t), hub = await bucket(t, zip, { cut: true }), model = spec(hub.base, zip), directory = modelDirectory(dir, model);
  await assert.rejects(downloadModel({ directory, spec: model }));
  const part = await stat(join(directory, 'download.zip.part'));
  await downloadModel({ directory, spec: model });
  assert.equal(hub.log.at(-1).range, `bytes=${part.size}-`);
  assert.equal(await modelReady(directory, model), true);

  const other = makeZip({ 'pack/m.onnx': randomBytes(4000), 'pack/m.data': DATA });
  const wrong = await bucket(t, other), pinned = { ...spec(wrong.base, other), files: spec(wrong.base, zip).files };
  const second = modelDirectory(await folder(t), pinned);
  await assert.rejects(downloadModel({ directory: second, spec: pinned }), /m\.onnx does not match its pinned checksum/);
  assert.ok(!(await readdir(second)).some(name => name.startsWith('m.onnx')));
  assert.equal(await modelReady(second, pinned), false);
  const tampered = { ...pinned, archive: { ...pinned.archive, sha256: '0'.repeat(64) } };
  await assert.rejects(downloadModel({ directory: modelDirectory(await folder(t), tampered), spec: tampered }), /does not match its pinned checksum/);
});

test('too little free disk for the zip and its files is refused before anything is fetched, naming the sharpening model', async t => {
  const zip = makeZip({ 'pack/m.onnx': GRAPH, 'pack/m.data': DATA });
  const dir = await folder(t), hub = await bucket(t, zip), model = spec(hub.base, zip);
  await assert.rejects(downloadModel({ directory: modelDirectory(dir, model), spec: model, freeBytes: async () => 1000 }),
    error => error.code === 'space' && /sharpening model needs about 1 MB free/.test(error.message));
  assert.equal(hub.log.length, 0);
});

test('downloaded-models.json, which the app\u2019s notices read, names each downloadable model as its spec does', async () => {
  const listed = JSON.parse(await readFile(new URL('../src/downloaded-models.json', import.meta.url), 'utf8')).models;
  assert.deepEqual(listed.map(m => [m.name, m.licence]), [SHAPES_MODEL, UPSCALE_MODEL].map(m => [m.name, m.licence]));
  assert.ok(listed[0].download.includes(SHAPES_MODEL.repo) && listed[0].download.includes(SHAPES_MODEL.revision));
  assert.ok(listed[1].download.includes(UPSCALE_MODEL.repo) && UPSCALE_MODEL.archive.url.includes('v0.65.0') && listed[1].download.includes('v0.65.0'));
});

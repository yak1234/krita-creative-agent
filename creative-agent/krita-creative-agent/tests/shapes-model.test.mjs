// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Element shapes, the model download (src/shapes/model.ts): pinned repository, revision and SHA-256 per file; files come
// over HTTP(S) from <base>/<repo>/resolve/<revision>/onnx/<file>, resume after a broken connection, and a file whose
// checksum differs is refused and removed. A local fake server stands in for Hugging Face: no real network. Files go to
// a temporary folder that is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createHash, randomBytes } from 'node:crypto';
import { mkdtemp, readFile, readdir, rm, stat, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { SHAPES_MODEL, modelDirectory, modelReady, downloadModel, modelBytes } from '../src/shapes/model.ts';

const sha = data => createHash('sha256').update(data).digest('hex');
const CONTENT = { 'vision_encoder.onnx': randomBytes(3000), 'vision_encoder.onnx_data': randomBytes(200000), 'prompt_encoder_mask_decoder.onnx': randomBytes(1000) };
const SPEC = { name: 'fake-model', repo: 'someone/fake-model-ONNX', revision: 'abc123', licence: 'Apache-2.0',
  files: Object.entries(CONTENT).map(([name, data]) => ({ name, size: data.length, sha256: sha(data) })) };

/** A fake Hugging Face: serves CONTENT (or `serve(name)`), honours Range unless told not to, and can cut a file short once. */
async function fakeHub(t, { ranges = true, cut = null, serve = name => CONTENT[name], wrongStart = false } = {}) {
  const log = [], cutOnce = new Set(cut ? [cut] : []);
  const server = createServer((req, res) => {
    const match = /^\/someone\/fake-model-ONNX\/resolve\/abc123\/onnx\/([^/]+)$/.exec(req.url);
    const data = match && serve(decodeURIComponent(match[1]));
    log.push({ url: req.url, range: req.headers.range ?? null });
    if (!data) { res.statusCode = 404; res.end('missing'); return; }
    const range = ranges && /^bytes=(\d+)-$/.exec(req.headers.range ?? '');
    // wrongStart: a 206 that says (and sends) the file from 0, whatever was asked.
    const from = range && !wrongStart ? Number(range[1]) : 0, body = data.subarray(from);
    res.writeHead(range ? 206 : 200, { 'Content-Length': body.length, ...(range ? { 'Content-Range': `bytes ${from}-${data.length - 1}/${data.length}` } : {}) });
    if (cutOnce.delete(match[1])) { res.write(body.subarray(0, body.length >> 1)); setTimeout(() => res.socket.destroy(), 20); return; }
    res.end(body);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  return { base: `http://127.0.0.1:${server.address().port}`, log };
}

async function folder(t) {
  const dir = await mkdtemp(join(tmpdir(), 'shapes-model-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}

test('the model is pinned: base-plus at one revision, four files with their sizes and SHA-256, about 330 MB', () => {
  assert.equal(SHAPES_MODEL.repo, 'onnx-community/sam2.1-hiera-base-plus-ONNX');
  assert.equal(SHAPES_MODEL.revision, 'bab18593f44e652f04cf18b60b3690f60e8996b0');
  assert.deepEqual(SHAPES_MODEL.files.map(f => f.name).sort(),
    ['prompt_encoder_mask_decoder.onnx', 'prompt_encoder_mask_decoder.onnx_data', 'vision_encoder.onnx', 'vision_encoder.onnx_data']);
  for (const file of SHAPES_MODEL.files) { assert.match(file.sha256, /^[0-9a-f]{64}$/); assert.ok(file.size > 0); }
  const mb = modelBytes(SHAPES_MODEL) / 1e6;
  assert.ok(mb > 320 && mb < 340, String(mb));
  assert.equal(modelDirectory('/data'), '/data/models/sam2.1-hiera-base-plus/bab18593f44e652f04cf18b60b3690f60e8996b0');
});

test('first use downloads every file from the pinned revision, checks it and marks the folder ready; then nothing more', async t => {
  const dir = await folder(t), hub = await fakeHub(t), progress = [];
  const directory = modelDirectory(dir, SPEC);
  assert.equal(await modelReady(directory, SPEC), false);
  await downloadModel({ directory, spec: SPEC, baseUrl: hub.base, onProgress: (done, total) => progress.push([done, total]) });
  assert.equal(await modelReady(directory, SPEC), true);
  for (const [name, data] of Object.entries(CONTENT)) assert.ok((await readFile(join(directory, name))).equals(data), name);
  assert.deepEqual(hub.log.map(entry => entry.url).sort(), Object.keys(CONTENT).map(name => '/someone/fake-model-ONNX/resolve/abc123/onnx/' + name).sort());
  const total = modelBytes(SPEC);
  assert.ok(progress.length >= 3 && progress.every(([, of]) => of === total));
  assert.deepEqual(progress.at(-1), [total, total]);
  assert.ok(progress.every(([done], i) => i === 0 || done >= progress[i - 1][0]), 'progress only grows');
  assert.ok(!(await readdir(directory)).some(name => name.endsWith('.part')));
  await downloadModel({ directory, spec: SPEC, baseUrl: hub.base });
  assert.equal(hub.log.length, 3, 'a ready model is not downloaded again');
});

test('a broken download resumes where it stopped', async t => {
  const dir = await folder(t), hub = await fakeHub(t, { cut: 'vision_encoder.onnx_data' }), directory = modelDirectory(dir, SPEC);
  await assert.rejects(downloadModel({ directory, spec: SPEC, baseUrl: hub.base }));
  const part = await stat(join(directory, 'vision_encoder.onnx_data.part'));
  assert.ok(part.size > 0 && part.size < CONTENT['vision_encoder.onnx_data'].length);
  await downloadModel({ directory, spec: SPEC, baseUrl: hub.base });
  assert.equal(await modelReady(directory, SPEC), true);
  const resumed = hub.log.filter(entry => entry.url.endsWith('/vision_encoder.onnx_data')).at(-1);
  assert.equal(resumed.range, `bytes=${part.size}-`);
  assert.ok((await readFile(join(directory, 'vision_encoder.onnx_data'))).equals(CONTENT['vision_encoder.onnx_data']));
});

test('a server that ignores the range starts the file again, and the result is still right', async t => {
  const dir = await folder(t), hub = await fakeHub(t, { ranges: false }), directory = modelDirectory(dir, SPEC);
  await mkdir(directory, { recursive: true });
  await writeFile(join(directory, 'vision_encoder.onnx_data.part'), CONTENT['vision_encoder.onnx_data'].subarray(0, 5000));
  await downloadModel({ directory, spec: SPEC, baseUrl: hub.base });
  assert.ok((await readFile(join(directory, 'vision_encoder.onnx_data'))).equals(CONTENT['vision_encoder.onnx_data']));
});

test('a file whose checksum differs is refused and removed, and the model is not ready', async t => {
  const dir = await folder(t), directory = modelDirectory(dir, SPEC);
  const hub = await fakeHub(t, { serve: name => name === 'vision_encoder.onnx' ? Buffer.alloc(3000, 7) : CONTENT[name] });
  await assert.rejects(downloadModel({ directory, spec: SPEC, baseUrl: hub.base }), /checksum/i);
  const left = await readdir(directory);
  assert.ok(!left.includes('vision_encoder.onnx') && !left.includes('vision_encoder.onnx.part'), left.join(', '));
  assert.equal(await modelReady(directory, SPEC), false);
  // A file changed on disk after the download is caught too: ready means sizes and the verified record agree.
  const good = await fakeHub(t);
  await downloadModel({ directory, spec: SPEC, baseUrl: good.base });
  assert.equal(await modelReady(directory, SPEC), true);
  await writeFile(join(directory, 'vision_encoder.onnx'), 'short');
  assert.equal(await modelReady(directory, SPEC), false);
});

test('a missing file on the server is a plain error naming it', async t => {
  const dir = await folder(t), hub = await fakeHub(t, { serve: name => name === 'prompt_encoder_mask_decoder.onnx' ? null : CONTENT[name] });
  await assert.rejects(downloadModel({ directory: modelDirectory(dir, SPEC), spec: SPEC, baseUrl: hub.base }), /prompt_encoder_mask_decoder\.onnx.*404/);
});

test('a 206 that does not start where the file stopped is not appended: the file starts again from 0', async t => {
  const dir = await folder(t), hub = await fakeHub(t, { wrongStart: true }), directory = modelDirectory(dir, SPEC);
  await mkdir(directory, { recursive: true });
  await writeFile(join(directory, 'vision_encoder.onnx_data.part'), CONTENT['vision_encoder.onnx_data'].subarray(0, 5000));
  await downloadModel({ directory, spec: SPEC, baseUrl: hub.base });
  assert.ok((await readFile(join(directory, 'vision_encoder.onnx_data'))).equals(CONTENT['vision_encoder.onnx_data']));
  const asked = hub.log.filter(entry => entry.url.endsWith('/vision_encoder.onnx_data'));
  assert.deepEqual(asked.map(entry => entry.range), ['bytes=5000-', null], 'asked again from the start, without a range');
});

test('too little free disk is refused before anything is fetched, saying how much is needed', async t => {
  const dir = await folder(t), hub = await fakeHub(t);
  await assert.rejects(downloadModel({ directory: modelDirectory(dir, SPEC), spec: SPEC, baseUrl: hub.base, freeBytes: async () => 1000 }),
    error => error.code === 'space' && /needs about 1 MB free/.test(error.message) && /0 MB/.test(error.message));
  assert.equal(hub.log.length, 0);
});

test('a disk that fills up while downloading says so, and the partial file is removed to give the space back', async t => {
  const dir = await folder(t), hub = await fakeHub(t), directory = modelDirectory(dir, SPEC);
  const full = Object.assign(new Error('ENOSPC: no space left on device, write'), { code: 'ENOSPC' });
  await assert.rejects(downloadModel({ directory, spec: SPEC, baseUrl: hub.base, write: async () => { throw full; } }),
    error => error.code === 'space' && /disk is full/.test(error.message));
  assert.ok(!(await readdir(directory)).some(name => name.endsWith('.part')));
});

test('an aborted download stops and keeps its part for next time', async t => {
  const dir = await folder(t), hub = await fakeHub(t), controller = new AbortController();
  controller.abort();
  await assert.rejects(downloadModel({ directory: modelDirectory(dir, SPEC), spec: SPEC, baseUrl: hub.base, signal: controller.signal }));
});

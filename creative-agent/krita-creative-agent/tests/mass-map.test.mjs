// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The mass map on attach (mass-map.ts): which references get one (the whole picture only), computed once per content
// and kept on disk in the chat folder, its colours and sentence for the artist (the panel) and its summary for the painter. A fake plugin; the
// chat folder is a temporary one, removed after each test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { wantsMassMap, ensureMassMaps, massContext, MASS_MAP_VERSION } from '../src/mass-map.ts';

const canvas = { width: 1600, height: 1200 };
const night = () => {
  const w = 240, h = 180, data = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4, moon = Math.hypot(x - 180, y - 35) <= 16;
    const [r, g, b] = moon ? [250, 240, 200] : x >= 20 && x < 110 && y >= 60 && y < 130 ? [110, 70, 40] : y >= 130 ? [40, 90, 50] : [20, 30, 80];
    data[i] = r; data[i + 1] = g; data[i + 2] = b; data[i + 3] = 255;
  }
  return { w, h, data };
};

test('only the whole picture gets a mass map: the goal of a project folder, or a general reference shaped like the canvas', () => {
  const ref = extra => ({ id: 'r', role: 'reference', purpose: 'general', width: 800, height: 600, ...extra });
  assert.equal(wantsMassMap(ref(), canvas), true, 'the canvas’s proportions');
  assert.equal(wantsMassMap(ref({ purpose: 'composition' }), canvas), true);
  assert.equal(wantsMassMap(ref({ width: 600, height: 800 }), canvas), false, 'other proportions: an element');
  assert.equal(wantsMassMap(ref({ purpose: 'palette' }), canvas), false, 'a colour reference');
  assert.equal(wantsMassMap(ref({ purpose: 'material' }), canvas), false, 'a style reference');
  assert.equal(wantsMassMap(ref({ purpose: 'likeness' }), canvas), false, 'a close-up');
  assert.equal(wantsMassMap(ref({ role: 'asset' }), canvas), false);
  assert.equal(wantsMassMap(ref({ part_kind: 'crop' }), canvas), false);
  assert.equal(wantsMassMap(ref(), null), false, 'no canvas yet: proportions unknown');
  assert.equal(wantsMassMap(ref({ source: 'folder', width: 600, height: 800 }), null), true, 'the project folder’s goal image');
  assert.equal(wantsMassMap(ref({ source: 'folder', role: 'asset' }), canvas), false, 'a folder element');
});

test('computed once per content, kept in the chat folder, read back by a resumed chat; summary, colours and sentence', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'mass-map-'));
  try {
    await writeFile(join(folder, 'goal.png'), 'goal image bytes');
    await writeFile(join(folder, 'palette.png'), 'palette bytes');
    const calls = [];
    const host = () => ({
      study: { directory: folder, references: [
        { id: 'goal', role: 'reference', purpose: 'general', path: join(folder, 'goal.png'), width: 480, height: 360 },
        { id: 'colours', role: 'reference', purpose: 'palette', path: join(folder, 'palette.png'), width: 480, height: 360 }] },
      decisionObservation: canvas,
      async callNative(operation, params) {
        calls.push(operation);
        const { w, h, data } = night();
        return { status: 'ok', width: w, height: h, source: [0, 0, 480, 360], sha256: params.sha256, ms: 3, rgba_base64: Buffer.from(data).toString('base64') };
      } });
    const first = host();
    let changed = 0;
    await ensureMassMaps(first, () => { changed++; });
    assert.deepEqual(calls, ['mass_reference'], 'the goal only, once');
    const goal = first.study.references[0], map = goal.mass_map;
    assert.ok(map && !first.study.references[1].mass_map);
    assert.equal(changed, 1, 'the panel is told');
    assert.match(map.summary, /^\d+ masses/);
    assert.ok(map.masses >= 3 && map.ms >= 0 && map.peak_mb > 0);
    assert.equal(map.thumbnail, undefined, 'no outline picture: it looked like a tracing');
    assert.ok(map.colours.length >= 3 && map.colours.every(c => /^#[0-9a-f]{6}$/.test(c.colour) && c.share > 0 && c.share <= 1));
    assert.ok(map.colours.every((c, i) => !i || c.share <= map.colours[i - 1].share), 'largest first');
    assert.ok(Math.abs(map.colours.reduce((n, c) => n + c.share, 0) - 1) < 0.01, 'the bar\u2019s proportions');
    assert.match(map.overview, /^Mostly [a-z ]+ (at the|on the|in the) [a-z ]+/, 'one plain sentence for the artist');
    assert.doesNotMatch(map.overview, /[%\[\]\d]/, 'no numbers or coordinates');
    assert.equal(map.version, MASS_MAP_VERSION);
    await ensureMassMaps(first, () => { changed++; });
    assert.equal(calls.length, 1, 'not again for the same reference');
    const resumed = host();
    await ensureMassMaps(resumed, () => {});
    assert.equal(calls.length, 1, 'a resumed chat reads it from the chat folder');
    assert.equal(resumed.study.references[0].mass_map.summary, map.summary);
    assert.deepEqual(massContext(resumed.study.references), { goal: map.summary }, 'the painter reads the summary by reference id');
    await writeFile(join(folder, 'goal.png'), 'another goal image');
    const changedFile = host();
    await ensureMassMaps(changedFile, () => {});
    assert.equal(calls.length, 2, 'new content, a new mass map');
    assert.ok((await readdir(join(folder, '.masses'))).length >= 2);
  } finally { await rm(folder, { recursive: true, force: true }); }
});

test('a failure leaves no mass map and does not throw (a hint must never stop a chat)', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'mass-map-'));
  try {
    await writeFile(join(folder, 'goal.png'), 'goal image bytes');
    const runtime = { study: { directory: folder, references: [{ id: 'goal', role: 'reference', purpose: 'general', path: join(folder, 'goal.png'), width: 480, height: 360, source: 'folder' }] },
      decisionObservation: null, async callNative() { throw new Error('old plugin: unknown operation'); } };
    await ensureMassMaps(runtime, () => {});
    assert.equal(runtime.study.references[0].mass_map, undefined);
    assert.deepEqual(massContext(runtime.study.references), {});
  } finally { await rm(folder, { recursive: true, force: true }); }
});

const smoothed = params => { const { w, h, data } = night(); return { status: 'ok', width: w, height: h, source: [0, 0, 480, 360], sha256: params.sha256, ms: 3, rgba_base64: Buffer.from(data).toString('base64') }; };
const goalStudy = folder => ({ directory: folder, references: [{ id: 'goal', role: 'reference', purpose: 'general', path: join(folder, 'goal.png'), width: 480, height: 360, source: 'folder' }] });

test('a failure is not retried on every message: only when the content changes or the chat reopens', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'mass-map-'));
  try {
    await writeFile(join(folder, 'goal.png'), 'goal image bytes');
    let calls = 0;
    const host = { study: goalStudy(folder), decisionObservation: null, async callNative() { calls++; throw new Error('Unknown operation: mass_reference'); } };
    await ensureMassMaps(host, () => {}); await ensureMassMaps(host, () => {}); await ensureMassMaps(host, () => {});
    assert.equal(calls, 1, 'one try per content in this chat');
    await writeFile(join(folder, 'goal.png'), 'another goal image');
    await ensureMassMaps(host, () => {});
    assert.equal(calls, 2, 'new content: tried again');
    host.study = goalStudy(folder);                              // the chat reopens
    await ensureMassMaps(host, () => {});
    assert.equal(calls, 3);
  } finally { await rm(folder, { recursive: true, force: true }); }
});

test('a run that outlives its chat writes nothing and tells nobody', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'mass-map-'));
  try {
    await writeFile(join(folder, 'goal.png'), 'goal image bytes');
    const old = goalStudy(folder), next = { directory: join(folder, 'next'), references: [] };
    const host = { study: old, decisionObservation: null, async callNative(_o, params) { host.study = next; return smoothed(params); } };
    let changed = 0;
    await ensureMassMaps(host, () => { changed++; });
    assert.equal(changed, 0);
    assert.equal(old.references[0].mass_map, undefined);
    await assert.rejects(readdir(join(folder, '.masses')), /ENOENT/, 'nothing written for the closed chat');
  } finally { await rm(folder, { recursive: true, force: true }); }
});

test('the cache is versioned: a mass map of another version counts as missing', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'mass-map-'));
  try {
    await writeFile(join(folder, 'goal.png'), 'goal image bytes');
    const study = goalStudy(folder);
    study.references[0].mass_map = { version: MASS_MAP_VERSION - 1, sha256: 'x', summary: 'old', masses: 1, thumbnail: '/nonexistent.png', ms: 0, peak_mb: 0 };
    let calls = 0;
    const host = { study, decisionObservation: null, async callNative(_o, params) { calls++; return smoothed(params); } };
    await ensureMassMaps(host, () => {});
    assert.equal(calls, 1, 'recomputed');
    const map = study.references[0].mass_map;
    assert.equal(map.version, MASS_MAP_VERSION);
    assert.ok(map.colours.length && map.overview, 'with the artist\u2019s colours and sentence');
    assert.ok((await readdir(join(folder, '.masses'))).every(name => name.includes(`.v${MASS_MAP_VERSION}.`)));
  } finally { await rm(folder, { recursive: true, force: true }); }
});

// LIVE rehearsal 2 (Toska, 2026-10-24): a goal sharpened 4x is 25 million pixels; the plugin decoded all of it on Krita's
// GUI thread for a 720-pixel copy. A large goal goes to it as a bounded copy (bounded-image.ts), its size still listed.
test('a large goal goes to the plugin as a bounded copy, listed at its own size; the record is kept by the goal\'s content', async () => {
  const { encodeRgba } = await import('../src/shapes/png.ts');
  const { pngSize } = await import('../src/png-rgba.ts');
  const { WORKING_PIXELS } = await import('../src/reference-limits.ts');
  const { createHash } = await import('node:crypto');
  const folder = await mkdtemp(join(tmpdir(), 'mass-map-'));
  try {
    const W = 2600, H = 1950, file = encodeRgba({ width: W, height: H, data: new Uint8Array(W * H * 4).fill(200) });   // 5 million pixels
    await writeFile(join(folder, 'goal.png'), file);
    const sent = [];
    const host = {
      study: { directory: folder, references: [{ id: 'goal', role: 'reference', purpose: 'general', path: join(folder, 'goal.png'), width: W, height: H }] },
      decisionObservation: { width: W, height: H },
      async callNative(operation, params) {
        sent.push({ operation, size: params.size, picture: pngSize(Buffer.from(params.image_base64, 'base64')),
          hashed: createHash('sha256').update(Buffer.from(params.image_base64, 'base64')).digest('hex') === params.sha256 });
        const { w, h, data } = night();
        return { status: 'ok', width: w, height: h, source: [0, 0, W, H], sha256: params.sha256, ms: 3, rgba_base64: Buffer.from(data).toString('base64') };
      } };
    await ensureMassMaps(host, () => {});
    assert.equal(sent.length, 1);
    assert.deepEqual(sent[0].size, [W, H], 'listed at the goal\'s own size');
    assert.ok(sent[0].picture.width * sent[0].picture.height <= WORKING_PIXELS, JSON.stringify(sent[0].picture));
    assert.equal(sent[0].hashed, true, 'the copy goes with its own hash');
    assert.ok(host.study.references[0].mass_map);
    const sha = createHash('sha256').update(file).digest('hex');
    assert.ok((await readdir(join(folder, '.masses'))).includes(`${sha}.v${MASS_MAP_VERSION}.json`), 'kept by the goal\'s content');
  } finally { await rm(folder, { recursive: true, force: true }); }
});

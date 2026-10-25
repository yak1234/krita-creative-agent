// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The texture library (src/texture-library.ts): the committed catalogue, each material's pinned download (an ambientCG zip
// with only three maps kept, or Poly Haven maps one by one), and which parts are architecture. Downloads go through a fake
// fetch serving small synthetic files: never the network. Every file goes to a temporary folder that is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { mkdtemp, readdir, rm, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { makeZip } from './fixtures/zip.mjs';
import { CATALOGUE, readCatalogue, materialSpec, textureDirectory, ensureMaterial, partKind, allowedMaterials, PART_KINDS, SNOW_KINDS }
  from '../src/texture-library.ts';

const sha = data => createHash('sha256').update(data).digest('hex');
const folder = async t => { const dir = await mkdtemp(join(tmpdir(), 'texture-library-')); t.after(() => rm(dir, { recursive: true, force: true })); return dir; };
const response = (body, status = 200) => new Response(body, { status, headers: { 'Content-Length': String(body.length) } });

test('the committed catalogue: 50 CC0 materials, each pinned, with the three maps where the source has them', () => {
  assert.equal(CATALOGUE.length, 50);
  const ids = new Set(CATALOGUE.map(m => m.id));
  for (const id of ['PavingStones046', 'Bricks085', 'RoofingTiles001', 'Snow013', 'Metal048C', 'Facade009', 'ph_castle_brick_02_red', 'ph_grey_roof_tiles_02'])
    assert.ok(ids.has(id), id);
  for (const m of CATALOGUE) {
    assert.ok(m.metres > 0 && m.metres <= 100, m.id);
    assert.ok(m.kinds.length && m.kinds.every(k => PART_KINDS.includes(k)), m.id);
    assert.ok(m.maps.color && m.maps.displacement, m.id);
    for (const map of Object.values(m.maps)) assert.match(map.sha256, /^[0-9a-f]{64}$/);
    if (m.source === 'ambientcg') assert.match(m.archive.url, /^https:\/\/ambientcg\.com\/get\?file=\w+_1K-JPG\.zip$/);
    else for (const map of Object.values(m.maps)) assert.match(map.url, /^https:\/\/dl\.polyhaven\.org\//);
  }
  // Snow only lies on architecture where snow lies: streets, railings, roofs and ledges.
  for (const m of CATALOGUE.filter(m => m.tags.includes('snow'))) assert.ok(m.kinds.every(k => SNOW_KINDS.includes(k)), m.id);
});

test('a catalogue with a broken entry is refused', () => {
  const good = structuredClone(CATALOGUE[0]);
  assert.throws(() => readCatalogue({ materials: [{ ...good, metres: 0 }] }), /metres/);
  assert.throws(() => readCatalogue({ materials: [{ ...good, kinds: ['sky'] }] }), /kind/);
  assert.throws(() => readCatalogue({ materials: [{ ...good, maps: { color: good.maps.color } }] }), /displacement/);
  assert.throws(() => readCatalogue({ materials: [good, good] }), /twice/);
  assert.equal(readCatalogue({ materials: [good] }).length, 1);
});

test('architectural parts by name; sky, water, people, vehicles and trees never', () => {
  assert.equal(partKind('Historic buildings'), 'wall');
  assert.equal(partKind('the church'), 'church');
  assert.equal(partKind('Kremlin towers'), 'tower');
  assert.equal(partKind('onion domes'), 'dome');
  assert.equal(partKind('Moscow City skyscrapers'), 'skyscraper');
  assert.equal(partKind('modern skyline'), 'skyscraper');
  assert.equal(partKind('Bridge'), 'bridge');
  assert.equal(partKind('cobbled street'), 'street');
  assert.equal(partKind('iron railing'), 'railing');
  assert.equal(partKind('snowy roofs'), 'roof');
  for (const name of ['Moonlit sky', 'river', 'people walking', 'red car', 'trees', 'Moon', 'clouds', 'boats on the river', 'street with people'])
    assert.equal(partKind(name), null, name);
});

test('the materials a part may get: its kind only, snow never on walls', () => {
  const street = allowedMaterials('street').map(m => m.id);
  assert.ok(street.includes('PavingStones046') && street.includes('Snow013'));
  const wall = allowedMaterials('wall').map(m => m.id);
  assert.ok(wall.includes('Bricks085') && !wall.some(id => id.startsWith('Snow')));
  assert.ok(allowedMaterials('dome').map(m => m.id).includes('RoofingTiles001'));
  assert.ok(allowedMaterials('skyscraper').map(m => m.id).includes('Facade001'));
  assert.ok(!allowedMaterials('church').some(m => m.id.startsWith('Facade')));
});

test('an ambientCG material: its zip pinned, only its maps kept, each checked, in the data folder', async t => {
  const dir = await folder(t);
  const maps = { color: randomBytes(3000), displacement: randomBytes(2000), ao: randomBytes(1000) };
  const zip = makeZip({ 'X_1K-JPG_Color.jpg': maps.color, 'X_1K-JPG_Displacement.jpg': maps.displacement, 'X_1K-JPG_AmbientOcclusion.jpg': maps.ao,
    'X_1K-JPG_NormalGL.jpg': randomBytes(500), 'X.blend': randomBytes(800) }, { stored: true });
  const material = { id: 'X', source: 'ambientcg', material: 'test brick', tags: ['brick'], kinds: ['wall'], metres: 2, pixels: [64, 32],
    archive: { url: 'https://ambientcg.com/get?file=X_1K-JPG.zip', sha256: sha(zip), bytes: zip.length },
    maps: { color: { file: 'X_1K-JPG_Color.jpg', bytes: maps.color.length, sha256: sha(maps.color) },
      displacement: { file: 'X_1K-JPG_Displacement.jpg', bytes: maps.displacement.length, sha256: sha(maps.displacement) },
      ao: { file: 'X_1K-JPG_AmbientOcclusion.jpg', bytes: maps.ao.length, sha256: sha(maps.ao) } } };
  const asked = [];
  const fetch = async url => { asked.push(String(url)); return response(zip); };
  const paths = await ensureMaterial({ dataDir: dir, material, fetch, freeBytes: async () => 1e12 });
  assert.deepEqual(asked, ['https://ambientcg.com/get?file=X_1K-JPG.zip']);
  assert.equal(paths.color, join(textureDirectory(dir, material), 'X_1K-JPG_Color.jpg'));
  const kept = (await readdir(textureDirectory(dir, material))).sort();
  assert.deepEqual(kept, ['X_1K-JPG_AmbientOcclusion.jpg', 'X_1K-JPG_Color.jpg', 'X_1K-JPG_Displacement.jpg', 'verified.json']);
  await ensureMaterial({ dataDir: dir, material, fetch, freeBytes: async () => 1e12 });     // second use: nothing fetched
  assert.equal(asked.length, 1);
  assert.equal(materialSpec(material).licence, 'CC0-1.0');
});

test('a zip that does not match its pin is refused and nothing is kept', async t => {
  const dir = await folder(t);
  const material = structuredClone(CATALOGUE.find(m => m.source === 'ambientcg'));
  await assert.rejects(ensureMaterial({ dataDir: dir, material, fetch: async () => response(randomBytes(material.archive.bytes)), freeBytes: async () => 1e12 }), /checksum/);
  assert.deepEqual((await readdir(textureDirectory(dir, material))).filter(f => !f.endsWith('.part')), []);
});

test('a Poly Haven material: each map from its own url, checked', async t => {
  const dir = await folder(t);
  const color = randomBytes(1500), disp = randomBytes(900);
  const material = { id: 'ph_x', source: 'polyhaven', material: 'test granite', tags: ['granite'], kinds: ['bridge'], metres: 2, pixels: [32, 32],
    maps: { color: { file: 'ph_x_Color.jpg', bytes: color.length, sha256: sha(color), url: 'https://dl.polyhaven.org/x_diff_1k.jpg' },
      displacement: { file: 'ph_x_Displacement.jpg', bytes: disp.length, sha256: sha(disp), url: 'https://dl.polyhaven.org/x_disp_1k.jpg' } } };
  const fetch = async url => response(String(url).includes('diff') ? color : disp);
  const paths = await ensureMaterial({ dataDir: dir, material, fetch, freeBytes: async () => 1e12 });
  assert.equal(paths.displacement, join(textureDirectory(dir, material), 'ph_x_Displacement.jpg'));
  assert.equal(paths.ao, undefined);
});

test('a test folder gives the maps as they are, without any download', async t => {
  const dir = await folder(t), material = CATALOGUE.find(m => m.id === 'Bricks085');
  await mkdir(join(dir, 'Bricks085'), { recursive: true });
  await writeFile(join(dir, 'Bricks085', material.maps.color.file), 'c');
  await writeFile(join(dir, 'Bricks085', material.maps.displacement.file), 'd');
  const paths = await ensureMaterial({ dataDir: '/nowhere', material, testFolder: dir, fetch: async () => { throw new Error('no network in tests'); } });
  assert.equal(paths.color, join(dir, 'Bricks085', material.maps.color.file));
  assert.equal(paths.ao, undefined);
});

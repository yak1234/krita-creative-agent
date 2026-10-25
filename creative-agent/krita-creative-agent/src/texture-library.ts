// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The texture library of the architecture texture pass (openspec architecture-texture goal 1, approved by the artist
// 2026-10-25: "i don't know how to create textures"; "download the materials now"). 50 CC0 materials: ambientCG 1K-JPG
// sets (a zip each) and Poly Haven 1K maps (a file each), listed in texture-catalogue.json with each one's material, tags,
// the part kinds it suits, its tile width in metres (estimated from its courses, stones or grain), and every download's
// size and SHA-256. Nothing but the catalogue ships: a material downloads on first use into the companion's data folder
// (textures/<id>/1K-JPG, beside models/ where goal-sharpen keeps its model) through the same pinned download as the models
// (shapes/model.ts downloadModel): a zip is checked, only its Color, Displacement and AmbientOcclusion maps are taken out
// and each checked, the zip removed; a Poly Haven map is fetched from its url and checked. A changed upload is refused.
//
// Which parts are architecture (goal 4) is decided here, by the part's name: buildings, church, towers, domes, skyscrapers,
// bridge, street, railing, walls, roofs, ledges. Sky, water, people, vehicles and trees never get texture, even named
// together with architecture ("street with people"): a mixed part is left alone. Snow lies only where snow lies on
// architecture: streets, railings, roofs and ledges (the artist, 2026-10-25).
// This module imports no .mjs.
import { readFileSync } from 'node:fs';
import { access } from 'node:fs/promises';
import { join } from 'node:path';
import { downloadModel, type ModelSpec } from './shapes/model.ts';

export const PART_KINDS = ['wall', 'church', 'tower', 'dome', 'skyscraper', 'bridge', 'street', 'railing', 'roof', 'ledge'] as const;
export type PartKind = typeof PART_KINDS[number];
export const SNOW_KINDS: readonly PartKind[] = ['street', 'railing', 'roof', 'ledge'];
export const MAP_KEYS = ['color', 'displacement', 'ao'] as const;
export type MapKey = typeof MAP_KEYS[number];
export type MapFile = { file: string; bytes: number; sha256: string; url?: string };
export type Material = { id: string; source: 'ambientcg' | 'polyhaven'; material: string; tags: string[]; kinds: PartKind[]; metres: number;
  pixels: [number, number]; archive?: { url: string; sha256: string; bytes: number }; detail_from?: MapKey[]; max_strength?: number;
  maps: { color: MapFile; displacement: MapFile; ao?: MapFile } };
export type MapPaths = { color: string; displacement: string; ao?: string };
export const REVISION = '1K-JPG';

const fail = (why: string): never => { throw new Error('Texture catalogue: ' + why); };
const SHA = /^[0-9a-f]{64}$/, ID = /^[A-Za-z0-9_]{1,60}$/, FILE = /^[A-Za-z0-9_.-]{1,120}\.jpg$/;
const HOSTS: Record<Material['source'], RegExp> = { ambientcg: /^https:\/\/ambientcg\.com\/get\?file=[A-Za-z0-9_-]+\.zip$/, polyhaven: /^https:\/\/dl\.polyhaven\.org\/[\w./-]+\.jpg$/ };

function readMap(raw: unknown, id: string, key: string, source: Material['source']): MapFile {
  const map = raw as Partial<MapFile> | undefined;
  if (!map || typeof map !== 'object') return fail(`${id} has no ${key} map`);
  if (typeof map.file !== 'string' || !FILE.test(map.file)) fail(`${id} ${key}: file`);
  if (!Number.isInteger(map.bytes) || (map.bytes ?? 0) <= 0) fail(`${id} ${key}: bytes`);
  if (typeof map.sha256 !== 'string' || !SHA.test(map.sha256)) fail(`${id} ${key}: sha256`);
  if (source === 'polyhaven' && (typeof map.url !== 'string' || !HOSTS.polyhaven.test(map.url))) fail(`${id} ${key}: url`);
  return { file: map.file!, bytes: map.bytes!, sha256: map.sha256!, ...(map.url ? { url: map.url } : {}) };
}

/** The catalogue's materials, every field checked (a broken entry refuses the whole catalogue). */
export function readCatalogue(raw: unknown): Material[] {
  const list = (raw as { materials?: unknown })?.materials;
  if (!Array.isArray(list) || !list.length) return fail('no materials');
  const seen = new Set<string>();
  return list.map((value: any): Material => {
    const id = String(value?.id ?? '');
    if (!ID.test(id)) fail('an id');
    if (seen.has(id)) fail(`${id} is listed twice`);
    seen.add(id);
    const source = value.source;
    if (source !== 'ambientcg' && source !== 'polyhaven') fail(`${id}: source`);
    if (typeof value.material !== 'string' || !value.material) fail(`${id}: material`);
    if (!Array.isArray(value.tags) || !value.tags.every((t: unknown) => typeof t === 'string')) fail(`${id}: tags`);
    if (!Array.isArray(value.kinds) || !value.kinds.length || !value.kinds.every((k: unknown) => (PART_KINDS as readonly unknown[]).includes(k))) fail(`${id}: kinds (a part kind)`);
    if (!(typeof value.metres === 'number' && value.metres > 0 && value.metres <= 100)) fail(`${id}: metres`);
    if (!Array.isArray(value.pixels) || value.pixels.length !== 2 || !value.pixels.every((n: unknown) => Number.isInteger(n) && (n as number) > 0)) fail(`${id}: pixels`);
    let archive: Material['archive'];
    if (source === 'ambientcg') {
      const a = value.archive;
      if (!a || typeof a.url !== 'string' || !HOSTS.ambientcg.test(a.url) || !SHA.test(String(a.sha256)) || !Number.isInteger(a.bytes) || a.bytes <= 0) fail(`${id}: archive`);
      archive = { url: a.url, sha256: a.sha256, bytes: a.bytes };
    }
    const maps = value.maps ?? {};
    const detail = value.detail_from;
    if (detail !== undefined && (!Array.isArray(detail) || !detail.length || !detail.every((k: unknown) => (MAP_KEYS as readonly unknown[]).includes(k)))) fail(`${id}: detail_from`);
    if (value.max_strength !== undefined && !(typeof value.max_strength === 'number' && value.max_strength > 0 && value.max_strength <= 1)) fail(`${id}: max_strength`);
    return { id, source, material: value.material, tags: [...value.tags], kinds: [...value.kinds], metres: value.metres, pixels: [value.pixels[0], value.pixels[1]],
      ...(archive ? { archive } : {}), ...(detail ? { detail_from: [...detail] } : {}), ...(value.max_strength ? { max_strength: value.max_strength } : {}),
      maps: { color: readMap(maps.color, id, 'color', source), displacement: readMap(maps.displacement, id, 'displacement', source),
        ...(maps.ao ? { ao: readMap(maps.ao, id, 'ao', source) } : {}) } };
  });
}

export const CATALOGUE: readonly Material[] = Object.freeze(readCatalogue(JSON.parse(readFileSync(new URL('./texture-catalogue.json', import.meta.url), 'utf8'))));
export const materialById = (id: string): Material | undefined => CATALOGUE.find(m => m.id === id);

/** The pinned download of one material, as shapes/model.ts takes it. */
export function materialSpec(material: Material): ModelSpec {
  const files = MAP_KEYS.flatMap(key => { const map = material.maps[key]; return map ? [{ name: map.file, size: map.bytes, sha256: map.sha256, ...(map.url ? { url: map.url } : {}) }] : []; });
  return { name: 'texture-' + material.id, repo: material.source, revision: REVISION, licence: 'CC0-1.0', label: `the ${material.material} texture`, files,
    ...(material.archive ? { archive: { url: material.archive.url, size: material.archive.bytes, sha256: material.archive.sha256, folder: '' } } : {}) };
}
/** Where a material's maps are kept: the companion's data folder, one folder per material and revision. */
export const textureDirectory = (dataDir: string, material: Pick<Material, 'id'>): string => join(dataDir, 'textures', material.id, REVISION);

type Download = typeof downloadModel;
export type EnsureOptions = { dataDir: string; material: Material; signal?: AbortSignal; download?: Download;
  fetch?: typeof globalThis.fetch; freeBytes?: (directory: string) => Promise<number>;
  /** Tests only: a folder holding <id>/<map file>, used as it is (no download, no checksum). */
  testFolder?: string };

/** The material's map files on this computer, downloaded and verified first when they are not there yet. */
export async function ensureMaterial({ dataDir, material, signal, download = downloadModel, fetch, freeBytes, testFolder }: EnsureOptions): Promise<MapPaths> {
  const paths = (directory: string): MapPaths => ({ color: join(directory, material.maps.color.file), displacement: join(directory, material.maps.displacement.file),
    ...(material.maps.ao ? { ao: join(directory, material.maps.ao.file) } : {}) });
  if (testFolder) {
    const found = paths(join(testFolder, material.id));
    const there = async (path?: string) => !!path && await access(path).then(() => true, () => false);
    if (!(await there(found.color)) || !(await there(found.displacement))) throw new Error(`The test textures have no ${material.id}.`);
    return { color: found.color, displacement: found.displacement, ...(await there(found.ao) ? { ao: found.ao! } : {}) };
  }
  const directory = textureDirectory(dataDir, material);
  await download({ directory, spec: materialSpec(material), ...(signal ? { signal } : {}), ...(fetch ? { fetch } : {}), ...(freeBytes ? { freeBytes } : {}) });
  return paths(directory);
}

// Part kinds by name (see the header). Never-words win over everything; then the first kind whose words match, most
// specific first (an onion dome is a dome before it is a church; "Kremlin towers" are towers).
const NEVER = /\b(?:sky|skies|moon|moonlight|clouds?|stars?|water|river|sea|lake|reflections?|people|person|figures?|man|men|woman|women|child(?:ren)?|crowds?|pedestrians?|cars?|vehicles?|bus(?:es)?|trams?|trucks?|taxis?|boats?|ships?|trees?|foliage|bush(?:es)?|forest|grass|horses?|birds?|characters?)\b/i;
const KINDS: [PartKind, RegExp][] = [
  ['skyscraper', /\b(?:skyscrapers?|skyline|high-?rises?|tower blocks?|office (?:towers?|buildings?)|moscow city|glass towers?)\b/i],
  ['dome', /\b(?:domes?|cupolas?|onions?)\b/i],
  ['church', /\b(?:church(?:es)?|cathedrals?|chapels?|monaster(?:y|ies)|basilicas?|temples?)\b/i],
  ['tower', /\b(?:towers?|spires?|belfr(?:y|ies)|turrets?|steeples?)\b/i],
  ['bridge', /\b(?:bridges?|viaducts?|piers?|arches)\b/i],
  ['railing', /\b(?:railings?|fences?|balustrades?|lamps?|lampposts?|street ?lights?|parapets?|bollards?)\b/i],
  ['roof', /\b(?:roofs?|rooftops?|roofing)\b/i],
  ['street', /\b(?:streets?|roads?|pavements?|sidewalks?|squares?|cobbles?(?:tones?)?|cobbled|embankments?|quays?|promenades?|paths?|plazas?)\b/i],
  ['ledge', /\b(?:ledges?|cornices?|steps|stairs|sills?)\b/i],
  ['wall', /\b(?:buildings?|walls?|facades?|façades?|houses?|kremlin|palaces?|castles?|architecture|apartments?|mansions?)\b/i],
];
/** The architectural kind of a part by its name, or null: not architecture (or mixed with something that never is). */
export function partKind(name: string): PartKind | null {
  const said = String(name ?? '');
  if (NEVER.test(said)) return null;
  return KINDS.find(([, words]) => words.test(said))?.[0] ?? null;
}

/** The materials a part of this kind may get (snow only where snow lies: the catalogue's kinds keep it there). */
export const allowedMaterials = (kind: PartKind): Material[] => CATALOGUE.filter(m => m.kinds.includes(kind));

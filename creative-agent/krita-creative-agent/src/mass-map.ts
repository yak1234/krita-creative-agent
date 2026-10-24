// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The mass map on attach: when the whole picture is attached (a project folder's goal image, or a general or
// composition reference with the canvas's proportions), its masses are found once (the plugin smooths it, guide-masses.ts
// traces it) and kept in the chat folder by content and version (.masses/<sha256>.v<version>.json). The reference then
// carries mass_map: a short summary the painter reads in its study context, and for the artist (the panel) the masses'
// own colours and shares, drawn as a flat colour bar, with one plain sentence. No outline picture: outlines over the
// reference looked like the tracing the artist removed. Style, colour and close-up references get none. A failure only
// means no mass map: it never stops a chat.
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { traceMasses, describeMasses, massColours, describeMassesForArtist, type MassPixels } from './guide-masses.ts';

/** summary: the painter's line; colours and overview: the artist's bar and sentence (the panel). */
export type MassMapRecord = { version: number; sha256: string; summary: string; masses: number; colours: { colour: string; share: number }[];
  overview: string; ms: number; peak_mb: number };
export type MassReference = { id: string; role?: string; purpose?: string; path: string; width?: number; height?: number;
  part_kind?: string; source?: string; mass_map?: MassMapRecord };
export type MassHost = {
  study?: { directory: string; references: MassReference[] } | null;
  decisionObservation?: { width?: unknown; height?: unknown } | null;
  canvasContext?: { canvas?: { width?: unknown; height?: unknown } | null } | null;
  callNative(operation: string, params: Record<string, unknown>): Promise<unknown>;
};

/** The mass map's version: a record or file of another version counts as missing (the tracing or smoothing changed). */
export const MASS_MAP_VERSION = 2;          // 2: colours and overview for the panel, no outline thumbnail
const ASPECT_TOLERANCE = 0.03;              // reference-tool.mjs: the canvas's proportions, within this
const MAX_BYTES = 12 * 1024 * 1024;         // reference-tool.mjs TRACE_REFERENCE_MB

/** Whether a reference is the whole picture: the project folder's goal image, or a general or composition reference
 * with the canvas's proportions (an element, a colour, style or close-up reference is not). */
export function wantsMassMap(reference: MassReference, canvas: { width?: unknown; height?: unknown } | null | undefined): boolean {
  if ((reference.role ?? 'reference') !== 'reference' || reference.part_kind) return false;
  if (reference.source === 'folder') return true;
  if (!['general', 'composition'].includes(reference.purpose ?? 'general')) return false;
  const cw = Number(canvas?.width), ch = Number(canvas?.height), rw = Number(reference.width), rh = Number(reference.height);
  if (!(cw > 0 && ch > 0 && rw > 0 && rh > 0)) return false;
  return Math.abs(rw / rh / (cw / ch) - 1) <= ASPECT_TOLERANCE;
}

/** The masses' summaries the painter reads, by reference id. */
export function massContext(references: readonly MassReference[] | undefined): Record<string, string> {
  return Object.fromEntries((references ?? []).filter(r => r.mass_map?.summary).map(r => [r.id, r.mass_map!.summary]));
}

/** Per chat (its study object, so a reopened chat starts afresh): the content hash of each reference file by its size
 * and modification time (hashing up to 12 MB on every message is not free), and the id:sha256 that failed, which is not
 * tried again until the content changes or the chat reopens. */
type ChatState = { hashes: Map<string, { stamp: string; sha256: string }>; failed: Set<string>; pending: Set<string> };
const chats = new WeakMap<object, ChatState>();

/** Finds the mass map of every whole-picture reference that has none of this version yet, one at a time; `changed` is
 * called after each one is set (so the panel can show it). Stops, writing nothing, once the chat it started for is no
 * longer the host's. Never throws. */
export async function ensureMassMaps(host: MassHost, changed: () => void): Promise<void> {
  const study = host.study;
  if (!study) return;
  let state = chats.get(study);
  if (!state) chats.set(study, state = { hashes: new Map(), failed: new Set(), pending: new Set() });
  const live = () => host.study === study;
  const canvas = host.decisionObservation ?? host.canvasContext?.canvas ?? null;
  for (const reference of [...study.references]) {
    if (!live()) return;
    if (reference.mass_map?.version === MASS_MAP_VERSION || state.pending.has(reference.id) || !wantsMassMap(reference, canvas)) continue;
    state.pending.add(reference.id);
    let key = '';
    try {
      const file = await stat(reference.path), stamp = `${file.size}:${file.mtimeMs}`;
      if (file.size > MAX_BYTES) continue;
      let known = state.hashes.get(reference.path);
      if (known?.stamp !== stamp) {
        known = { stamp, sha256: createHash('sha256').update(await readFile(reference.path)).digest('hex') };
        state.hashes.set(reference.path, known);
      }
      key = `${reference.id}:${known.sha256}`;
      if (state.failed.has(key)) continue;
      const record = await massMap(host, study.directory, reference, known.sha256, live);
      if (record && live() && study.references.includes(reference)) { reference.mass_map = record; changed(); }
    } catch {
      // No mass map: the painter works without its summary, as before. Not again for this content in this chat.
      if (key) state.failed.add(key);
    } finally { state.pending.delete(reference.id); }
  }
}

async function massMap(host: MassHost, directory: string, reference: MassReference, sha256: string, live: () => boolean): Promise<MassMapRecord | null> {
  const data = await readFile(reference.path);
  if (createHash('sha256').update(data).digest('hex') !== sha256) throw new Error('The reference changed while its masses were found.');
  const folder = join(directory, '.masses'), name = `${sha256}.v${MASS_MAP_VERSION}`;
  const json = join(folder, name + '.json');
  try {
    const kept = JSON.parse(await readFile(json, 'utf8')) as MassMapRecord;
    if (kept.version === MASS_MAP_VERSION) return kept;
  } catch { /* not computed yet */ }
  const started = performance.now(), rss = process.memoryUsage().rss;
  const decoded = await host.callNative('mass_reference', { image_base64: data.toString('base64'), sha256,
    ...(Number(reference.width) > 0 && Number(reference.height) > 0 ? { size: [reference.width, reference.height] } : {}) }) as
    { width: number; height: number; rgba_base64: string; sha256: string; ms?: number; source?: number[] };
  if (decoded?.sha256 !== sha256) throw new Error('Decoded reference identity differs.');
  if (!live()) return null;
  const pixels: MassPixels = { width: decoded.width, height: decoded.height, data: Buffer.from(decoded.rgba_base64, 'base64'),
    ...(decoded.source ? { source: decoded.source } : {}), ...(decoded.ms !== undefined ? { ms: decoded.ms } : {}) };
  const traced = await traceMasses(pixels);
  const record: MassMapRecord = { version: MASS_MAP_VERSION, sha256, summary: describeMasses(traced.masses), masses: traced.masses.length,
    colours: massColours(traced.masses), overview: describeMassesForArtist(traced.masses), ms: Math.round(performance.now() - started), peak_mb: Math.round(Math.max(process.memoryUsage().rss, rss) / 1e6) };
  if (!live()) return null;                                 // the chat closed meanwhile: nothing is written for it
  await mkdir(folder, { recursive: true });
  await writeFile(json, JSON.stringify(record) + '\n');
  return record;
}

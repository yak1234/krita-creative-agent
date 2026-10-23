// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The mass map on attach: when the whole picture is attached (a project folder's goal image, or a general or
// composition reference with the canvas's proportions), its masses are found once (the plugin smooths it, guide-masses.ts
// traces it) and kept in the chat folder by content and version (.masses/<sha256>.v<version>.json and .png). The reference then carries
// mass_map: a short summary the painter reads in its study context, and a small thumbnail the panel shows beside the
// reference. Style, colour and close-up references get none. A failure only means no mass map: it never stops a chat.
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { deflateSync, crc32 } from 'node:zlib';
import { traceMasses, describeMasses, type MassLine, type MassPixels } from './guide-masses.ts';

export type MassMapRecord = { version: number; sha256: string; summary: string; masses: number; thumbnail: string; ms: number; peak_mb: number };
export type MassReference = { id: string; role?: string; purpose?: string; path: string; width?: number; height?: number;
  part_kind?: string; source?: string; mass_map?: MassMapRecord };
export type MassHost = {
  study?: { directory: string; references: MassReference[] } | null;
  decisionObservation?: { width?: unknown; height?: unknown } | null;
  canvasContext?: { canvas?: { width?: unknown; height?: unknown } | null } | null;
  callNative(operation: string, params: Record<string, unknown>): Promise<unknown>;
};

/** The mass map's version: a record or file of another version counts as missing (the tracing or smoothing changed). */
export const MASS_MAP_VERSION = 1;
export const MASS_THUMB = 160;              // the panel's thumbnail, long side
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
  const json = join(folder, name + '.json'), thumbnail = join(folder, name + '.png');
  try {
    const kept = JSON.parse(await readFile(json, 'utf8')) as MassMapRecord;
    await stat(thumbnail);
    if (kept.version === MASS_MAP_VERSION) return { ...kept, thumbnail };
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
    thumbnail, ms: Math.round(performance.now() - started), peak_mb: Math.round(Math.max(process.memoryUsage().rss, rss) / 1e6) };
  if (!live()) return null;                                 // the chat closed meanwhile: nothing is written for it
  await mkdir(folder, { recursive: true });
  await writeFile(thumbnail, encodeRgb(renderThumbnail(pixels, traced.lines)));
  await writeFile(json, JSON.stringify(record) + '\n');
  return record;
}

type Rgb = { width: number; height: number; data: Uint8Array };
const LINE = [143, 211, 255], LIGHT = [255, 179, 71];     // the guide's light blue and warm light-shape colour

/** The smoothed copy reduced to MASS_THUMB, dimmed, with the masses' boundaries over it. */
function renderThumbnail(image: MassPixels, lines: MassLine[]): Rgb {
  const k = Math.min(1, MASS_THUMB / Math.max(image.width, image.height));
  const width = Math.max(1, Math.round(image.width * k)), height = Math.max(1, Math.round(image.height * k));
  const out = new Uint8Array(width * height * 3);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const x0 = Math.floor(x / k), x1 = Math.max(x0 + 1, Math.floor((x + 1) / k)), y0 = Math.floor(y / k), y1 = Math.max(y0 + 1, Math.floor((y + 1) / k));
    const sum = [0, 0, 0]; let n = 0;
    for (let yy = y0; yy < Math.min(y1, image.height); yy++) for (let xx = x0; xx < Math.min(x1, image.width); xx++) {
      const i = (yy * image.width + xx) * 4;
      for (let c = 0; c < 3; c++) sum[c]! += image.data[i + c] ?? 0;
      n++;
    }
    for (let c = 0; c < 3; c++) out[(y * width + x) * 3 + c] = Math.round(0.6 * sum[c]! / Math.max(1, n));
  }
  for (const line of lines) {
    const colour = line.light ? LIGHT : LINE;
    for (let i = 1; i < line.points.length; i++) {
      const [ax, ay] = line.points[i - 1]!, [bx, by] = line.points[i]!;
      const steps = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) * k));
      for (let s = 0; s <= steps; s++) {
        const x = Math.min(width - 1, Math.max(0, Math.floor((ax + (bx - ax) * s / steps) * k)));
        const y = Math.min(height - 1, Math.max(0, Math.floor((ay + (by - ay) * s / steps) * k)));
        out.set(colour, (y * width + x) * 3);
      }
    }
  }
  return { width, height, data: out };
}

/** An 8-bit RGB PNG, every row filter 0. */
function encodeRgb({ width, height, data }: Rgb): Buffer {
  const raw = Buffer.alloc(height * (width * 3 + 1));
  for (let y = 0; y < height; y++) raw.set(data.subarray(y * width * 3, (y + 1) * width * 3), y * (width * 3 + 1) + 1);
  const chunk = (kind: string, body: Buffer) => {
    const head = Buffer.alloc(8); head.writeUInt32BE(body.length, 0); head.write(kind, 4, 'latin1');
    const tail = Buffer.alloc(4); tail.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), body])), 0);
    return Buffer.concat([head, body, tail]);
  };
  const header = Buffer.alloc(13); header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

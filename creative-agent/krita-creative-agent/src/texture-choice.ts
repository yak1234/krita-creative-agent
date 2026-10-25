// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The decision of the architecture texture pass (openspec architecture-texture goal 2, the artist 2026-10-25: "shouldn't
// we have our qwen vl do that"): the planner model (Qwen3 VL by default, studio.plannerModel) looks at the canvas and, for
// each architectural part, answers in a typed result: one or two materials from the ones its kind may get, the tile width
// in canvas px near and far (the far side smaller in perspective), the direction the courses or rows run (toward the
// vanishing point when there is one), and the strength. The reply is JSON read leniently (a code fence or words around it
// are fine); the host validates and clamps every field (clampPart), so the model can only ever choose within the limits
// below. A part the reply leaves out, or every part when there is no model, it fails or it answers nothing usable, gets
// the default for its kind (defaultPart): buildings first (the artist, 2026-10-25: "it's buildings that it struggles with").
// The model reads the same picture the painter sees (the canvas view); it is called the way the folder study calls it
// (folder-study.ts piReader). This module imports no .mjs.
import type { StudyReader, Picture } from './folder-study.ts';
import { allowedMaterials, materialById, type Material, type PartKind } from './texture-library.ts';

/** The strength range (the share of the Overlay or Soft Light detail), the artist's 10-30%. */
export const STRENGTH: readonly [number, number] = [0.10, 0.30];
export const DEFAULT_STRENGTH = 0.18;
/** The smallest tile in canvas px: below it a 1K texture's detail is finer than the painting's strokes. */
export const TILE_MIN = 48;
/** The far tile is at least this share of the near one (a steeper perspective is a vanishing point's job). */
export const FAR_SHARE = 0.2;
export const BLENDS = ['soft_light', 'overlay'] as const;
export type Blend = typeof BLENDS[number];
export type Rect = [number, number, number, number];
export type TexturePart = { name: string; kind: PartKind; bounds: number[]; note?: string };
export type PartChoice = { part: string; kind: PartKind; materials: { id: string; weight: number }[]; tile_px: { near: number; far: number };
  direction_deg: number; vanishing: [number, number] | null; strength: number; blend: Blend; source: 'model' | 'default' };
export type Choice = { parts: PartChoice[]; model?: string; cost?: number; ms: number; fallback?: string };

// Buildings first: what reads as each kind when the model says nothing (plaster facades of classical buildings, Kremlin
// brick on towers, the cream sandstone of a Stalinist high-rise is the planner's to choose among the skyscraper's).
const DEFAULT_MATERIAL: Record<PartKind, string> = { wall: 'Concrete012', church: 'Bricks008', tower: 'ph_castle_brick_02_red', dome: 'RoofingTiles001',
  skyscraper: 'Facade001', bridge: 'ph_granite_wall', street: 'PavingStones046', railing: 'Metal027', roof: 'ph_grey_roof_tiles_02', ledge: 'ph_granite_tile_03' };
/** A part of this kind is about this many metres along its bounds' long side: how a tile in metres becomes canvas px. */
const PART_METRES: Record<PartKind, number> = { wall: 40, church: 40, tower: 50, dome: 12, skyscraper: 250, bridge: 120, street: 60, railing: 20, roof: 30, ledge: 10 };
/** Ground goes away from the viewer: the street is drawn in perspective by default (its far side up the canvas). */
const RECEDES: readonly PartKind[] = ['street'];

const round = (v: number) => Math.round(v * 100) / 100;
const clamp = (v: number, low: number, high: number) => Math.min(high, Math.max(low, v));
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'string' && v.trim() && Number.isFinite(Number(v)) ? Number(v) : null);
const longSide = (b: readonly number[]) => Math.max(Number(b[2]) || 0, Number(b[3]) || 0);
const tileLimits = (part: TexturePart, canvas: { width: number; height: number }) => {
  const canvasLong = Math.max(canvas.width, canvas.height), low = Math.max(TILE_MIN, Math.round(canvasLong / 125));
  return { low, high: Math.max(low, Math.round(Math.min(Math.max(longSide(part.bounds), low), canvasLong / 3))) };
};
const strengthCap = (materials: readonly { id: string }[]) =>
  Math.max(STRENGTH[0], Math.min(STRENGTH[1], ...materials.map(m => materialById(m.id)?.max_strength ?? STRENGTH[1])));

/** The default for a part: its kind's material, a tile from the material's metres over the part's size, flat (or receding). */
export function defaultPart(part: TexturePart, canvas: { width: number; height: number }): PartChoice {
  const material = materialById(DEFAULT_MATERIAL[part.kind]) ?? allowedMaterials(part.kind)[0]!;
  const limits = tileLimits(part, canvas), near = Math.round(clamp(material.metres * longSide(part.bounds) / PART_METRES[part.kind], limits.low, limits.high));
  const recedes = RECEDES.includes(part.kind);
  return { part: part.name, kind: part.kind, materials: [{ id: material.id, weight: 1 }], tile_px: { near, far: recedes ? Math.max(Math.round(near * 0.45), Math.round(near * FAR_SHARE)) : near },
    direction_deg: recedes ? -90 : 0, vanishing: null, strength: Math.min(DEFAULT_STRENGTH, strengthCap([material])), blend: 'soft_light', source: 'default' };
}

/** What the model chose for one part, made safe: anything it got wrong falls back to the default's value. */
export function clampPart(raw: any, part: TexturePart, canvas: { width: number; height: number }): PartChoice {
  const fallback = defaultPart(part, canvas), allowed = new Set(allowedMaterials(part.kind).map((m: Material) => m.id));
  const picked: { id: string; weight: number }[] = [];
  for (const m of Array.isArray(raw?.materials) ? raw.materials : []) {
    const id = typeof m === 'string' ? m : m?.id;
    if (typeof id !== 'string' || !allowed.has(id) || picked.some(p => p.id === id) || picked.length >= 2) continue;
    picked.push({ id, weight: clamp(num(m?.weight) ?? 1, 0.2, 1) });
  }
  if (!picked.length) return fallback;
  const total = picked.reduce((sum, m) => sum + m.weight, 0);
  const materials = picked.map(m => ({ id: m.id, weight: m.weight / total }));
  const limits = tileLimits(part, canvas);
  const near = Math.round(clamp(num(raw?.tile_px?.near) ?? fallback.tile_px.near, limits.low, limits.high));
  const far = Math.round(clamp(num(raw?.tile_px?.far) ?? near, Math.max(1, near * FAR_SHARE), near));
  let direction = num(raw?.direction_deg) ?? fallback.direction_deg;
  direction = ((direction % 360) + 540) % 360 - 180;                 // into [-180, 180)
  const long = Math.max(canvas.width, canvas.height), [bx = 0, by = 0, bw = 0, bh = 0] = part.bounds.map(Number);
  let vanishing: [number, number] | null = null;
  if (Array.isArray(raw?.vanishing) && raw.vanishing.length === 2) {
    const [vx, vy] = raw.vanishing.map(num);
    const fair = vx !== null && vy !== null && vx! >= -2 * long && vx! <= canvas.width + 2 * long && vy! >= -2 * long && vy! <= canvas.height + 2 * long;
    const inside = fair && vx! >= bx && vx! <= bx + bw && vy! >= by && vy! <= by + bh;
    if (fair && !inside) vanishing = [Math.round(vx!), Math.round(vy!)];
  }
  const strength = round(clamp(num(raw?.strength) ?? DEFAULT_STRENGTH, STRENGTH[0], strengthCap(materials)));
  const blend: Blend = (BLENDS as readonly unknown[]).includes(raw?.blend) ? raw.blend : 'soft_light';
  return { part: part.name, kind: part.kind, materials, tile_px: { near, far }, direction_deg: round(direction), vanishing, strength, blend, source: 'model' };
}

/** The JSON object in a reply with a `parts` list, or null. */
export function readChoice(text: string): { parts: any[] } | null {
  const said = String(text ?? ''), fenced = /```(?:json)?\s*([\s\S]*?)```/i.exec(said)?.[1];
  for (const candidate of [fenced, said.slice(said.indexOf('{'), said.lastIndexOf('}') + 1)]) {
    if (!candidate?.trim()) continue;
    try { const value = JSON.parse(candidate); if (value && Array.isArray(value.parts)) return value; } catch { /* the next candidate */ }
  }
  return null;
}

/** The request: the canvas, each part with its bounds, folder note and allowed materials, and the reply's exact form. */
export function texturePrompt({ canvas, parts }: { canvas: { width: number; height: number }; parts: readonly TexturePart[] }): string {
  const lines = parts.map((p, i) => {
    const materials = allowedMaterials(p.kind).map(m => `${m.id} (${m.material}; ${m.metres} m a tile)`).join(', ');
    return `${i + 1}. "${p.name}" (${p.kind}), bounds [${p.bounds.map(n => Math.round(Number(n))).join(',')}]${p.note ? `; the folder note says: ${p.note.slice(0, 400)}` : ''}. Materials it may get: ${materials}.`;
  });
  return `CANVAS is a painting of ${canvas.width} x ${canvas.height} px (the image is the painting, smaller). A subtle photo texture pass will add `
    + 'surface detail (stone grain, brick courses, cobbles, weathering) to its architectural parts: the detail only, blended at low strength over the '
    + 'painting’s own colours, never a photo pasted on. For each part below choose, from what you see in the picture:\n'
    + '- materials: one material id from its list (two only when the surface really mixes, e.g. brick with rust streaks), with weights;\n'
    + '- tile_px: the width of one tile in canvas px on the part’s near side and far side (equal for a wall seen front on; the far side smaller '
    + 'when the surface recedes). Work it out from the tile’s metres and the part’s real size: a 20 m facade 1000 px wide makes 50 px a metre;\n'
    + '- direction_deg: the angle the courses or rows run on the canvas (0 is horizontal, -90 up the canvas), toward the vanishing point when there is one;\n'
    + '- vanishing: [x, y] in canvas px where the courses converge, or null for a surface seen front on;\n'
    + `- strength: ${STRENGTH[0]}-${STRENGTH[1]} (lower on smooth or far surfaces, higher on rough near stone);\n`
    + '- blend: "soft_light" (gentle, the default) or "overlay" (crisper).\n'
    + 'Parts:\n' + lines.join('\n') + '\n'
    + 'Answer with JSON only, no other words: {"parts":[{"part":"<the part’s name as given>","materials":[{"id":"<id>","weight":1}],'
    + '"tile_px":{"near":<px>,"far":<px>},"direction_deg":<deg>,"vanishing":null,"strength":<0.1-0.3>,"blend":"soft_light"}]}';
}

const key = (name: string) => String(name ?? '').trim().toLowerCase();
/** The planner's choice for these parts, clamped; defaults where it gives nothing usable. Never throws for the model. */
export async function chooseTextures({ reader, view, canvas, parts, signal }: { reader: StudyReader | null; view: { label: string; picture: Picture } | null;
  canvas: { width: number; height: number }; parts: readonly TexturePart[]; signal: AbortSignal }): Promise<Choice> {
  const started = Date.now();
  const defaults = (fallback: string): Choice => ({ parts: parts.map(p => defaultPart(p, canvas)), ms: Date.now() - started, fallback });
  if (!reader || !view) return defaults('no_model');
  let reply;
  try { reply = await reader({ prompt: texturePrompt({ canvas, parts }), images: [view], signal }); }
  catch (error) { signal.throwIfAborted(); return defaults((error as Error)?.message === 'timeout' ? 'timeout' : 'provider_error'); }
  const read = readChoice(reply.text);
  const byName = new Map((read?.parts ?? []).map((p: any) => [key(p?.part), p]));
  const chosen = parts.map((p, i) => { const raw = byName.get(key(p.name)) ?? (read && read.parts.length === parts.length ? read.parts[i] : undefined);
    return raw ? clampPart(raw, p, canvas) : defaultPart(p, canvas); });
  return { parts: chosen, model: reply.model, cost: reply.cost, ms: Date.now() - started, ...(read ? {} : { fallback: 'unreadable_reply' }) };
}

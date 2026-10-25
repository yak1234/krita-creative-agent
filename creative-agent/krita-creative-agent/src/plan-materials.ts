// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Materials chosen in the plan (openspec architecture-texture goal 7; the artist, 2026-10-25: "make that part of the
// planning prompt, qwen 3vl picks the krita patterns for each aspect"). While planning, the planner model already views
// each part's image; for an architectural "Refine: <group>" step it writes `materials`: per aspect (walls, roofs and domes,
// windows, ground, trim) one catalogue material with a scale and a receding hint. The host checks them here (an id or a
// material's name, against texture-catalogue.json; unknown ones are dropped and reported, one per aspect), the plan card
// shows them in plain words (materialsLine), and the texture pass takes a part's planned material (plannedChoice) instead
// of asking the model at paint time. This module imports no .mjs.
import { Type } from 'typebox';
import { CATALOGUE, allowedMaterials, materialById, partKind, type Material, type PartKind } from './texture-library.ts';
import { clampPart, tileFor, RECEDING, type PartChoice, type TexturePart } from './texture-choice.ts';

export const ASPECTS = ['walls', 'roofs', 'windows', 'ground', 'trim'] as const;
export type Aspect = typeof ASPECTS[number];
export const SCALES = { fine: 0.6, medium: 1, coarse: 1.6 } as const;
export type Scale = keyof typeof SCALES;
export type PlannedMaterial = { aspect: Aspect; id: string; material?: string; scale?: Scale; recedes?: boolean };
/** The part kinds each aspect covers. */
const ASPECT_KINDS: Record<Aspect, readonly PartKind[]> = { walls: ['wall', 'church', 'tower', 'bridge', 'skyscraper'], roofs: ['roof', 'dome'],
  windows: ['skyscraper'], ground: ['street'], trim: ['railing', 'ledge'] };
export const aspectOf = (kind: PartKind): Aspect => (ASPECTS.find(a => a !== 'windows' && ASPECT_KINDS[a].includes(kind)) ?? 'walls');

/** propose_plan's schema for a step's materials. */
export const plannedMaterialsSchema = Type.Array(Type.Object({
  aspect: Type.String({ maxLength: 20, description: 'walls, roofs (roofs and domes), windows, ground or trim.' }),
  id: Type.String({ minLength: 1, maxLength: 80, description: 'A texture library id (painting_tool_help name "materials").' }),
  material: Type.Optional(Type.String({ maxLength: 120 })),
  scale: Type.Optional(Type.Union([Type.Literal('fine'), Type.Literal('medium'), Type.Literal('coarse')])),
  recedes: Type.Optional(Type.Boolean({ description: 'The surface goes away from the viewer (a street): smaller toward its far side.' })),
}, { additionalProperties: false }), { maxItems: 8, description: 'An architectural "Refine: <parts>" step only: its texture materials, one per aspect.' });

const resolve = (given: string): Material | undefined => {
  const said = String(given ?? '').trim().toLowerCase();
  return materialById(String(given ?? '').trim()) ?? CATALOGUE.find(m => m.id.toLowerCase() === said || m.material.toLowerCase() === said);
};

/** The step's planned materials, checked: known ids (or names), a known aspect each, the material fit for it, one per aspect. */
export function cleanMaterials(list: unknown): { materials: PlannedMaterial[]; dropped: string[] } {
  const materials: PlannedMaterial[] = [], dropped: string[] = [];
  for (const raw of Array.isArray(list) ? list.slice(0, 12) : []) {
    const entry = (raw ?? {}) as Record<string, unknown>, aspect = String(entry.aspect ?? '').trim().toLowerCase().replace(/^domes?$/, 'roofs').replace(/^roofs?( and domes)?$/, 'roofs');
    const said = String(entry.id ?? entry.material ?? '');
    if (!(ASPECTS as readonly string[]).includes(aspect)) { dropped.push(`${said || '?'} (aspect "${String(entry.aspect ?? '')}" is not walls, roofs, windows, ground or trim)`); continue; }
    const material = resolve(said);
    if (!material) { dropped.push(`${said || '?'} (not in the texture library)`); continue; }
    if (!material.kinds.some(k => ASPECT_KINDS[aspect as Aspect].includes(k))) { dropped.push(`${material.id} (not a ${aspect} material)`); continue; }
    if (materials.some(m => m.aspect === aspect)) { dropped.push(`${material.id} (a second ${aspect} material)`); continue; }
    const scale = typeof entry.scale === 'string' && entry.scale in SCALES ? entry.scale as Scale : undefined;
    materials.push({ aspect: aspect as Aspect, id: material.id, material: material.material, ...(scale ? { scale } : {}), ...(entry.recedes === true ? { recedes: true } : {}) });
  }
  return { materials, dropped };
}

/** A plan's steps with their materials checked; a step that is not an architectural refine step keeps none. */
export function cleanPlanSteps<S extends { title: string; materials?: unknown }>(steps: readonly S[], refinePart: (step: S) => boolean): { steps: S[]; dropped: string[] } {
  const dropped: string[] = [];
  const cleaned = steps.map((step, i) => {
    const { materials: given, ...rest } = step;
    if (given === undefined) return step;
    if (!refinePart(step)) { if (Array.isArray(given) && given.length) dropped.push(`step ${i + 1}: materials belong to a "Refine: <parts>" step`); return rest as S; }
    // A step of people, vehicles, sky, water or trees only gets no texture, so its plan card names none.
    const parts = String(step.title).replace(/^Refine:\s*/i, '').split(/\s*(?:,|\band\b|&)\s*/i).filter(Boolean);
    if (!parts.some(part => partKind(part) !== null)) {
      if (Array.isArray(given) && given.length) dropped.push(`step ${i + 1}: no architecture in "${step.title}", so no materials`);
      return rest as S;
    }
    const { materials, dropped: lost } = cleanMaterials(given);
    dropped.push(...lost.map(d => `step ${i + 1}: ${d}`));
    return (materials.length ? { ...rest, materials } : rest) as S;
  });
  return { steps: cleaned, dropped };
}

/** "walls: old red brick; roofs: rusty green metal" for the plan card. */
export const materialsLine = (materials: readonly PlannedMaterial[] | undefined): string =>
  (materials ?? []).map(m => `${m.aspect}: ${materialById(m.id)?.material ?? m.material ?? m.id}`).join('; ');

/** The library for the planner (painting_tool_help name "materials"): one short line a material. */
export function materialCatalogue(): { aspects: string; materials: string[] } {
  return { aspects: 'walls (walls, church, towers, bridge, skyscrapers), roofs (roofs and domes), windows (skyscraper window grids), ground (street), trim (railings, ledges)',
    materials: CATALOGUE.map(m => `${m.id}: ${m.material} [${m.tags.join(' ')}] (${m.kinds.join(', ')}; ${m.metres} m)`) };
}

/** A part's choice from the plan: the planned material of its aspect (and a skyscraper's window grid), when its kind may get
 * it; null when the plan has none for it (the model chooses at paint time). */
export function plannedChoice(part: TexturePart, planned: readonly PlannedMaterial[] | undefined, canvas: { width: number; height: number }): PartChoice | null {
  const aspects: Aspect[] = [aspectOf(part.kind), ...(part.kind === 'skyscraper' ? ['windows' as const] : [])];
  const allowed = new Set(allowedMaterials(part.kind).map(m => m.id));
  const picked = aspects.flatMap(a => (planned ?? []).filter(m => m.aspect === a && allowed.has(m.id)));
  if (!picked.length) return null;
  const first = picked[0]!, material = materialById(first.id)!;
  const near = tileFor(material, part, canvas, SCALES[first.scale ?? 'medium']);
  const recedes = first.recedes ?? part.kind === 'street';
  const choice = clampPart({ materials: picked.map((m, i) => ({ id: m.id, weight: i ? 0.5 : 1 })), tile_px: { near, far: recedes ? near * RECEDING.far : near },
    direction_deg: recedes ? RECEDING.direction_deg : 0, vanishing: null }, part, canvas);
  return { ...choice, source: 'plan' };
}

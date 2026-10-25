// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Luna picks each building part's texture material by looking (architecture-texture goal 7, approved by the artist
// 2026-10-25). Live, the planner (Qwen3 VL, free choice from the catalogue's lines) chose by name, not by look: red factory
// brick for cream stucco buildings, rusty white metal for the Kremlin's green tower roofs, even with tags and a prompt to
// match colour and build. So at the step's first paint, when Find it has outlined each part, Luna sees the goal cropped to
// the part and a swatch of each material the part may get (its Color map, SWATCH_PX square), each under its letter, and
// answers one choice: which surface matches (structure first: courses, blocks, scales, grid, plain; then tone). One
// decision a part. The swatches go as labelled images rather than one drawn sheet: the letters are exact text, nothing is
// drawn, and the plugin's existing comparison_crop makes them.
//
// Every material the part's kind may get is a candidate (25 at most, letters A-Z): measured live on New Moscow's goal
// (2026-10-25) 128 px swatches cost little (about 900-1200 input tokens and $0.0001 a part with 17-25 swatches, 0.4 s), and a
// cap of 12 cut exactly the materials that mattered (the castle brick, the cream sandstones).
// A pick counts when its probability is at least PICK_CONFIDENCE and PICK_MARGIN clear of the second: more on one surface
// than on all the others together, and not a split between two look-alikes. Live, Luna spreads its probability over
// look-alikes (four bricks share most of it), so that rule alone seldom fires; what matters is whether the planner's pick
// looks wrong. So a pick also counts when it is PICK_OVER_PLANNED times as likely as the planner's pick and at least
// PICK_OVER_CHANCE times chance (1 / candidates): live, the Kremlin towers' dark weathered brick 0.47 against the planned
// red brick's 0.11 replaces it; the cream buildings' yellow brick 0.21 against red brick 0.08 (chance 0.04) replaces it; a
// look-alike of the plan's (0.30 against 0.24) does not. Then it replaces the planner's pick for the
// part's aspect (source 'luna'; a part's own entry when two parts of one aspect look different); otherwise the planner's
// pick stays, marked unsure. Luna offline, failing or late changes nothing, and nothing here throws. The artist's own
// materials (source 'artist') are never asked about. Mechanism only: the studio gives the client, crops and swatches
// (studio.mjs lunaStepMaterials). This module imports no .mjs.
import type { ChoiceQuestion, DecisionImage, DecisionMaker, DecisionPart } from './decisions/types.ts';
import { allowedMaterials, materialById, type Material, type PartKind } from './texture-library.ts';
import { aspectOf, type Aspect, type PlannedMaterial } from './plan-materials.ts';

export const PICK_CONFIDENCE = 0.5;
export const PICK_MARGIN = 0.2;
/** Against the planner's pick: Luna's top replaces it when at least this many times as likely as the planner's... */
export const PICK_OVER_PLANNED = 2;
/** ...and at least this many times chance (1 / the number of candidates). */
export const PICK_OVER_CHANCE = 3;
export const MAX_CANDIDATES = 26;
export const SWATCH_PX = 128;
/** The goal crop's long side at most (never enlarged). */
export const PART_CROP_SIDE = 384;
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

export type LookPart = { part: string; kind: PartKind; crop: DecisionImage | null };
export type LunaPick = { part: string; kind: PartKind; aspect: Aspect; planned: string | null; candidates: string[]; probabilities: Record<string, number>;
  top: string | null; p: number; second: number; confident: boolean; cost: number; input_tokens: number; elapsed_ms: number; fallback?: string };
type Swatch = (material: Material) => Promise<DecisionImage>;

/** The materials a part may get (every one: the catalogue gives a kind 25 at most), at most MAX_CANDIDATES: the planner's pick first, then those made for this kind before
 * those it shares (a material's kinds list its main use first). */
export function candidatesFor(kind: PartKind, planned?: string | null): Material[] {
  const allowed = allowedMaterials(kind), rank = (m: Material) => m.kinds.indexOf(kind);
  const sorted = allowed.map((m, i) => ({ m, i })).sort((a, b) => rank(a.m) - rank(b.m) || a.i - b.i).map(e => e.m);
  const first = sorted.find(m => m.id === planned);
  return [...(first ? [first] : []), ...sorted.filter(m => m !== first)].slice(0, MAX_CANDIDATES);
}

/** The goal crop's output size for a goal rect: the long side at most PART_CROP_SIDE, never enlarged, at least 16 a side. */
export function cropOut([, , w, h]: number[]): [number, number] {
  const k = Math.min(1, PART_CROP_SIDE / Math.max(w!, h!, 1));
  return [Math.max(16, Math.round(w! * k)), Math.max(16, Math.round(h! * k))];
}

const question = (part: string, kind: PartKind, letters: string[]): ChoiceQuestion => ({ type: 'choice',
  criteria: Object.fromEntries(letters.map(l => [l, `The surface in swatch ${l}.`])),
  instructions: `PART is the goal painting cropped to ${part} (a ${kind}). Each lettered swatch is a texture material. Which swatch’s surface best `
    + 'matches the surface of the PART? Judge its structure first: brick courses, cut stone blocks, roof scales or tiles, a window grid, metal sheet, '
    + 'or plain render or plaster; then its tone and colour (light cream, red, green, grey, dark). Ignore the painting’s lighting and brushwork.' });

const round = (v: number) => Math.round(v * 1000) / 1000;

/** One part's pick: one decision over its candidates. Never throws: a failure is a fallback. */
export async function pickMaterial({ client, part, planned, swatch, signal }: { client: DecisionMaker | null; part: LookPart; planned: string | null;
  swatch: Swatch; signal?: AbortSignal }): Promise<LunaPick> {
  const list = candidatesFor(part.kind, planned), aspect = aspectOf(part.kind);
  const base: LunaPick = { part: part.part, kind: part.kind, aspect, planned, candidates: list.map(m => m.id), probabilities: {}, top: null, p: 0, second: 0,
    confident: false, cost: 0, input_tokens: 0, elapsed_ms: 0 };
  if (!client) return { ...base, fallback: 'not_connected' };
  if (!part.crop) return { ...base, fallback: 'no_crop' };
  let swatches: DecisionImage[];
  try { swatches = await Promise.all(list.map(m => swatch(m))); } catch { return { ...base, fallback: 'no_swatches' }; }
  const letters = list.map((_, i) => LETTERS[i]!);
  const parts: DecisionPart[] = [`PART (the goal, ${part.part}):`, part.crop, 'SWATCHES:'];
  letters.forEach((l, i) => parts.push(l + ':', swatches[i]));
  let result;
  try { result = await client.decide({ parts, questions: { material: question(part.part, part.kind, letters) }, purpose: 'material-by-look', ...(signal ? { signal } : {}) }); }
  catch { return { ...base, fallback: 'service_or_response_error' }; }
  if (result.fallback) return { ...base, elapsed_ms: result.elapsed_ms, fallback: result.fallback };
  const usage = { cost: result.usage.cost, input_tokens: result.usage.input_tokens, elapsed_ms: result.elapsed_ms };
  const answer = result.answers.material;
  if (answer?.type !== 'choice' || !letters.includes(answer.choice)) return { ...base, ...usage, fallback: 'service_or_response_error' };
  const given = answer.probabilities ?? { [answer.choice]: answer.confidence ?? 0 };
  const probabilities = Object.fromEntries(letters.map((l, i) => { const v = Number(given[l]); return [list[i]!.id, Number.isFinite(v) ? round(Math.min(1, Math.max(0, v))) : 0]; }));
  const ranked = Object.entries(probabilities).sort((a, b) => b[1] - a[1]);
  const [top, p] = ranked[0]!, second = ranked[1]?.[1] ?? 0;
  const sure = p >= PICK_CONFIDENCE && p - second >= PICK_MARGIN;
  const plannedP = planned && planned in probabilities ? probabilities[planned]! : null;
  const overPlan = plannedP !== null && top !== planned && p >= PICK_OVER_CHANCE / list.length && p >= PICK_OVER_PLANNED * plannedP;
  return { ...base, ...usage, probabilities, top, p, second, confident: sure || overPlan };
}

const slotOf = (m: PlannedMaterial) => m.aspect + '|' + (m.part ?? '').toLowerCase();
const named = (id: string) => materialById(id)?.material ?? id;

/** The step's materials with Luna's picks applied (see the header). A fallback changes nothing; unsure marks the aspect's
 * planned entry; confident picks of one aspect that agree replace its entry (its hints kept), ones that differ become each
 * part's own entry. */
export function applyPicks(materials: readonly PlannedMaterial[] | undefined, picks: readonly LunaPick[]): PlannedMaterial[] {
  const out: PlannedMaterial[] = (materials ?? []).map(m => ({ ...m }));
  const answered = picks.filter(p => !p.fallback);
  for (const aspect of [...new Set(answered.map(p => p.aspect))]) {
    const mine = answered.filter(p => p.aspect === aspect), sure = mine.filter(p => p.confident && p.top), unsure = mine.filter(p => !p.confident);
    const entry = out.find(m => m.aspect === aspect && !m.part) ?? null;
    const hints = entry ? { ...(entry.scale ? { scale: entry.scale } : {}), ...(entry.recedes ? { recedes: true } : {}) } : {};
    // Earlier picks of these parts are replaced.
    for (const p of mine) { const i = out.findIndex(m => m.aspect === aspect && m.part?.toLowerCase() === p.part.toLowerCase() && m.source !== 'artist'); if (i >= 0) out.splice(i, 1); }
    const ids = [...new Set(sure.map(p => p.top!))];
    if (sure.length && !unsure.length && ids.length === 1) {
      const pick: PlannedMaterial = { aspect, id: ids[0]!, material: named(ids[0]!), ...hints, source: 'luna' };
      const i = out.findIndex(m => m.aspect === aspect && !m.part);
      if (i >= 0) out[i] = pick; else out.push(pick);
      continue;
    }
    const own = sure.map((p): PlannedMaterial => ({ aspect, part: p.part, id: p.top!, material: named(p.top!), ...hints, source: 'luna' }));
    const i = out.findIndex(m => m.aspect === aspect && !m.part);
    if (i >= 0) {
      out.splice(i, 1, ...own, ...(unsure.length ? [{ ...out[i]!, unsure: true }] : []));
    } else out.push(...own);
  }
  return out;
}

/** Luna's look at each architectural part of a step, applied to its materials. The artist's materials are kept and their
 * parts not asked. Never throws. */
export async function chooseByLook({ client, parts, materials, crops, swatch, signal }: { client: DecisionMaker | null;
  parts: readonly { name: string; kind: PartKind; bounds: number[] }[]; materials: readonly PlannedMaterial[] | undefined;
  crops: (parts: { name: string; kind: PartKind; bounds: number[] }[]) => Promise<(DecisionImage | null)[]>; swatch: Swatch; signal?: AbortSignal }): Promise<{ materials: PlannedMaterial[]; picks: LunaPick[] }> {
  const given = materials ?? [];
  const artists = (part: { name: string; kind: PartKind }) => given.some(m => m.source === 'artist' && m.aspect === aspectOf(part.kind)
    && (!m.part || m.part.toLowerCase() === part.name.toLowerCase()));
  const asked = parts.filter(p => !artists(p));
  if (!asked.length) return { materials: [...given], picks: [] };
  let images: (DecisionImage | null)[];
  try { images = await crops([...asked]); } catch { images = asked.map(() => null); }
  const plannedFor = (p: { name: string; kind: PartKind }) => (given.find(m => slotOf(m) === aspectOf(p.kind) + '|' + p.name.toLowerCase())
    ?? given.find(m => m.aspect === aspectOf(p.kind) && !m.part))?.id ?? null;
  const picks = await Promise.all(asked.map((p, i) => pickMaterial({ client, part: { part: p.name, kind: p.kind, crop: images[i] ?? null }, planned: plannedFor(p), swatch, ...(signal ? { signal } : {}) })));
  return { materials: applyPicks(given, picks), picks };
}

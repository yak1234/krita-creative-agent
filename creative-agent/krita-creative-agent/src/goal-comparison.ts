// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Luna's goal comparison (openspec luna-goal-reviewer goal 1, approved by the artist 2026-10-23). On 2026-10-23 Luna's
// move review reported "no regressions" while hand strokes damaged a finished underpainting: it judges how strokes look,
// never whether the painting moved away from the goal; and the goal-likeness check (goal-likeness.ts, CIE ΔE on a grid of
// about 94 px cells) misses structure and style damage in the right colours, blobs over the towers in the towers' own
// colours. So after each painting batch with a goal reference Luna sees the goal's crop and the canvas's crops before and
// after the batch (the same area, at the same scale) and answers one question for each: is AFTER closer to the goal than
// BEFORE, the same, or further from it? "Further" with good confidence counts as clearly worse beside the ΔE rule, under the
// same exemptions and the same per-move undo cap (extensions/goal-likeness.ts); Luna never undoes alone and never paints.
//
// The crops are cut from the canvas views the painter already has (the plugin's comparison_crop, which decodes the views'
// JPEGs), at the views' own scale, so BEFORE and AFTER have the same pixels a canvas pixel and nothing is invented by
// enlarging. The view grows to the size the painter's model reads (goal 3, view-size.ts), and a crop is at most the size
// Luna reads 1:1 (the resolution probe, resolution-probe.ts): an area larger than one crop becomes several, at most
// MAX_CROPS, reduced only when it is larger than that. One decision call a batch, one question a crop.
// Mechanism only: the studio fetches the crops (studio.mjs goalComparison); this module imports no .mjs.
import type { DecisionMaker, DecisionPart, ChoiceQuestion, Questions, FallbackReason } from './decisions/types.ts';

export type Rect = [number, number, number, number];
export type Verdict = 'closer' | 'same' | 'further';
export type CropPlan = { rect: Rect; out: [number, number] };
export type CropImages = { goal: DecisionPart; before: DecisionPart; after: DecisionPart };
export type Comparison = { verdict: Verdict | null; confidence: number; crops: number; per_crop: { verdict: Verdict; confidence: number }[];
  elapsed_ms: number; cost: number; input_tokens: number; fallback?: FallbackReason | 'no_crops'; area?: Rect };

/** The longest side of a crop when no probe has measured the decision model (resolution-probe.ts records what it reads). */
export const CROP_SIDE = 768;
/** Crops a batch at most: an area larger than this many crops is cut into fewer, reduced ones (one call, bounded cost). */
export const MAX_CROPS = 3;
/** "Further" counts as clearly worse from this confidence: below it the answer is recorded, never acted on. */
export const FURTHER_CONFIDENCE = 0.75;
/** A crop Luna finds closer at this confidence keeps the batch whatever the other crops say. */
export const CLOSER_VETO = 0.6;
/** Context around the batch's area, a share of its size on each side: Luna judges a passage against its surroundings. */
const PAD = 0.1;
/** A crop is never smaller than this, so a tiny area is still a picture. */
const MIN_OUT = 16;

const finite = (v: unknown): v is number[] => Array.isArray(v) && v.length === 4 && v.every(Number.isFinite);

/** Where to compare, in canvas pixels: the union of the batch's pass areas, else the cells the batch changed (the
 * likeness grid's), else the goal's whole target; padded by PAD of its size each side and kept inside the target.
 * Null when it lies outside the goal (nothing of the goal to compare with). */
export function comparisonArea(areas: (number[] | null | undefined)[], changed: Rect | null, target: Rect): Rect | null {
  const known = areas.filter(finite).filter(a => a[2]! > 0 && a[3]! > 0);
  let x0: number, y0: number, x1: number, y1: number;
  if (known.length) {
    x0 = Math.min(...known.map(a => a[0]!)); y0 = Math.min(...known.map(a => a[1]!));
    x1 = Math.max(...known.map(a => a[0]! + a[2]!)); y1 = Math.max(...known.map(a => a[1]! + a[3]!));
  } else if (changed) [x0, y0, x1, y1] = [changed[0], changed[1], changed[0] + changed[2], changed[1] + changed[3]];
  else return [...target];
  const px = Math.round((x1 - x0) * PAD), py = Math.round((y1 - y0) * PAD);
  const [tx, ty, tw, th] = target;
  const left = Math.max(tx, x0 - px), top = Math.max(ty, y0 - py), right = Math.min(tx + tw, x1 + px), bottom = Math.min(ty + th, y1 + py);
  return right > left && bottom > top ? [left, top, right - left, bottom - top] : null;
}

/** The crops of `area` (canvas px) at the views' `scale` (view px a canvas px, at most 1), each at most `cropSide` px: one
 * when it fits, else tiles; past `maxCrops` tiles the fewest, least reduced arrangement, reduced to fit. */
export function cropPlan(area: Rect, scale: number, cropSide = CROP_SIDE, maxCrops = MAX_CROPS): CropPlan[] {
  const [x, y, w, h] = area, s = Math.min(1, Math.max(1e-6, scale)), per = cropSide / s;
  let cols = Math.max(1, Math.ceil(w / per)), rows = Math.max(1, Math.ceil(h / per));
  if (cols * rows > maxCrops) {
    let best: [number, number] = [1, 1], side = Infinity;
    for (let c = 1; c <= maxCrops; c++) for (let r = 1; c * r <= maxCrops; r++) {
      const longest = Math.max(w / c, h / r);
      if (longest < side - 1e-9) { side = longest; best = [c, r]; }       // ties keep the fewer tiles found first
    }
    [cols, rows] = best;
  }
  const cuts = (start: number, size: number, n: number) => Array.from({ length: n }, (_, i) => {
    const a = start + Math.floor(size * i / n), b = start + Math.floor(size * (i + 1) / n); return [a, b - a] as const; });
  const plans: CropPlan[] = [];
  for (const [ty, th] of cuts(y, h, rows)) for (const [tx, tw] of cuts(x, w, cols)) {
    const k = Math.min(s, cropSide / Math.max(tw, th));
    plans.push({ rect: [tx, ty, tw, th], out: [Math.max(MIN_OUT, Math.round(tw * k)), Math.max(MIN_OUT, Math.round(th * k))] });
  }
  return plans;
}

/** The goal's pixels (its listed size) under a canvas rect, by the mapping that placed the goal on the canvas; with the
 * goal's `size`, kept inside it as likenessGrid keeps its crops (the plugin refuses a crop past the edge). */
export function goalSource(rect: Rect, { source, target }: { source: Rect | number[]; target: Rect | number[] }, size?: [number, number] | number[]): Rect {
  const kx = source[2]! / target[2]!, ky = source[3]! / target[3]!;
  const out: Rect = [Math.round(source[0]! + (rect[0] - target[0]!) * kx), Math.round(source[1]! + (rect[1] - target[1]!) * ky),
    Math.max(1, Math.round(rect[2] * kx)), Math.max(1, Math.round(rect[3] * ky))];
  if (!size) return out;
  const [w, h] = [Math.max(1, Math.round(size[0]!)), Math.max(1, Math.round(size[1]!))];
  const x = Math.min(w - 1, Math.max(0, out[0])), y = Math.min(h - 1, Math.max(0, out[1]));
  return [x, y, Math.max(1, Math.min(w - x, out[0] + out[2] - x)), Math.max(1, Math.min(h - y, out[1] + out[3] - y))];
}

/** Context for a small batch (review, 2026-10-24): the area grown about its centre to at least MIN_CONTEXT view pixels a
 * side at the views' `scale`, kept inside the target; a larger area is left as it is. */
export const MIN_CONTEXT = 256;
export function withContext(area: Rect, scale: number, target: Rect): Rect {
  const least = Math.ceil(MIN_CONTEXT / Math.min(1, Math.max(1e-6, scale)));
  const grow = (start: number, size: number, lo: number, span: number): [number, number] => {
    if (size >= least) return [start, size];
    const want = Math.min(least, span), from = Math.min(lo + span - want, Math.max(lo, Math.round(start + size / 2 - want / 2)));
    return [from, want];
  };
  const [x, w] = grow(area[0], area[2], target[0], target[2]), [y, h] = grow(area[1], area[3], target[1], target[3]);
  return [x, y, w, h];
}

const CRITERIA: Record<Verdict, string> = {
  closer: 'AFTER looks more like GOAL than BEFORE did.',
  same: 'AFTER and BEFORE are about as close to GOAL: little changed, or it got as much better as worse.',
  further: 'AFTER looks less like GOAL than BEFORE did: forms, edges, detail or the paint’s style that BEFORE shared with GOAL were damaged, blurred or covered.',
};
const question = (n: number): ChoiceQuestion => ({ type: 'choice', criteria: { ...CRITERIA },
  instructions: `In CROP ${n}: GOAL is the reference image the painting is made from; BEFORE and AFTER show the same area of the painting at the same scale, before and after one batch of brushwork. `
    + 'Compared with GOAL, is AFTER closer to GOAL than BEFORE (shapes, structure, edges, values, colours and the style of the paint), about the same, or further from it? '
    + 'Blobs, smears, stripes or flat patches over forms that BEFORE had like GOAL make AFTER further, even in the right colours.' });

const VERDICTS: readonly Verdict[] = ['closer', 'same', 'further'];
const confidenceOf = (answer: { choice?: unknown; confidence?: unknown; probabilities?: Record<string, unknown> }, verdict: Verdict): number => {
  const p = answer.probabilities?.[verdict] ?? answer.confidence;
  return typeof p === 'number' && Number.isFinite(p) ? Math.round(Math.min(1, Math.max(0, p)) * 100) / 100 : 0;
};

/** Luna's verdict on the crops: one decision, one question a crop. Overall (review, 2026-10-24): further only when most
 * crops are further and no crop is closer at CLOSER_VETO or more; closer likewise; else the same. A fallback is no verdict. */
export async function compareWithGoal({ client, crops, signal }: { client: DecisionMaker; crops: CropImages[]; signal?: AbortSignal }): Promise<Comparison> {
  const empty = { verdict: null, confidence: 0, crops: crops.length, per_crop: [], cost: 0, input_tokens: 0 };
  if (!crops.length) return { ...empty, elapsed_ms: 0, fallback: 'no_crops' };
  const parts: DecisionPart[] = [], questions: Questions = {};
  crops.forEach((c, i) => {
    parts.push(`CROP ${i + 1} GOAL (the reference):`, c.goal, `CROP ${i + 1} BEFORE (the painting before the batch):`, c.before, `CROP ${i + 1} AFTER (the painting after the batch):`, c.after);
    questions['crop_' + i] = question(i + 1);
  });
  const started = Date.now();
  let result;
  try { result = await client.decide({ signal, purpose: 'compare-with-goal', parts, questions }); }
  catch { return { ...empty, elapsed_ms: Date.now() - started, fallback: 'service_or_response_error' }; }
  if (result.fallback) return { ...empty, elapsed_ms: result.elapsed_ms, fallback: result.fallback };
  const per_crop: Comparison['per_crop'] = [];
  for (let i = 0; i < crops.length; i++) {
    const answer = result.answers['crop_' + i];
    if (answer?.type !== 'choice' || !VERDICTS.includes(answer.choice as Verdict))
      return { ...empty, elapsed_ms: result.elapsed_ms, cost: result.usage.cost, input_tokens: result.usage.input_tokens, fallback: 'service_or_response_error' };
    const verdict = answer.choice as Verdict;
    per_crop.push({ verdict, confidence: confidenceOf(answer, verdict) });
  }
  const said = (v: Verdict) => per_crop.filter(c => c.verdict === v);
  const vetoed = (v: Verdict) => per_crop.some(c => c.verdict === v && c.confidence >= CLOSER_VETO);
  const most = (v: Verdict) => said(v).length * 2 > per_crop.length;
  const verdict: Verdict = most('further') && !vetoed('closer') ? 'further' : most('closer') && !vetoed('further') ? 'closer' : 'same';
  const confidence = Math.max(0, ...said(verdict).map(c => c.confidence));
  return { verdict, confidence, crops: crops.length, per_crop, elapsed_ms: result.elapsed_ms, cost: result.usage.cost, input_tokens: result.usage.input_tokens };
}

/** Whether Luna's comparison counts as clearly worse: further, with good confidence. */
export function furtherFromGoal(c: Comparison | null | undefined): boolean {
  return c?.verdict === 'further' && c.confidence >= FURTHER_CONFIDENCE;
}

/** What got worse by Luna's comparison, for the painter and the artist. */
export function describeFurther(c: Comparison): string {
  return `Luna compared the batch’s area${c.area ? ` [${c.area.join(',')}]` : ''} with the goal image: further from it than before (confidence ${c.confidence.toFixed(2)}), in its forms, edges or detail`;
}

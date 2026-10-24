// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// refine_to_goal (openspec finish-stage goal 8; the artist, 2026-10-24: "i want the end result where our accents and finishes
// make it move eventually to the final. Right now we just have a very crisp underpainting"). A host-driven loop, not the
// painter guessing areas: the plugin ranks the canvas in REGION squares by what is left to do at full size, against the
// placed goal (sharpened when it is): colour (ΔE of both blurred 2 px) plus edges (the difference of their gradient
// magnitudes), so crispness counts (area_compare.py refine_map). Each round takes the regions still above DONE_SCORE, worst
// first, and runs paint_finish at the region's next level (fine, then finer: fine again paints the same strokes) and then
// the accents the canvas still lacks there at full size (area_accents, then the plugin's accents operation), measuring the
// region before and after. It ends when every region is at or under DONE_SCORE, when a region has had every level (as close
// as the strokes get), or at a budget (BUDGET_MINUTES, MAX_STROKES), between regions; Stop ends it there too and keeps what
// is done. Every finish and accents pass is the plugin's own reversible pass under this call's id in the move's group, so
// the move's Undo removes them all; Krita keeps every write out of the protected areas (and accents in them are skipped);
// goal likeness measures it and never undoes it (goal-likeness.ts exemption, as paint_finish). The Now card shows
// "Refine: round N, region M of K, difference X → Y".
//
// Numbers, measured offline on the New Moscow 6000 x 4500 canvas export and its 4x-sharpened goal (finish-stage tasks 2):
// regions scored 3.8-15 after the whole-picture Finish (median 7.7); the church went 8.5 -> 4.9 (fine) -> 2.7 (finer).
// DONE_SCORE 4 is a little under what one fine pass leaves on a building, and what the soft sky already scores.
// The studio's native calls come in as dependencies, so this module imports no .mjs.
import { Type, type Static } from 'typebox';
import type { AgentToolResult, ToolDefinition } from '@earendil-works/pi-coding-agent';
import { goalSpec, type GoalSpec, type PlacedGoal } from './goal-spec.ts';
import { chooseAccents, accentAdjustments, speckSize, type Accent, type AccentKind, ACCENT_KINDS } from './accents-tool.ts';
import { loadAreaMask } from './paint-only-here.ts';
import { encodePlane } from './shapes/png.ts';
import { mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { refineRequested } from './goal-sharpen.ts';
import { SURE, type Reading } from './message-reading.ts';
import { NOT_UNDERPAINTED, NO_GOAL } from './finish-tool.ts';

/** colour + edges at full size (area_compare.py) at or under which a region is close to the goal. */
export const DONE_SCORE = 4;
/** The levels a region goes through, one a round (finish_pass.py DETAILS). */
export const LEVELS = ['fine', 'finer'] as const;
/** A region's side at 6000 px on the long side (scaled with the canvas): about 1% of New Moscow's canvas, ~2 s fine. */
export const REGION = 512;
export const BUDGET_MINUTES = 15;
export const MAX_STROKES = 12_000_000;
/** Accents a region at most (the paint_accents default count). */
export const REGION_ACCENTS = 40;
/** Squares a finish pass takes at most, as a share of the canvas (finish_pass.py allows fine on 15%), and accents a pass
 * (accent_adjust.py MOST): on New Moscow a pass a square made ~300 passes and ~1,000 layers (review finding); a round is
 * now a few finish passes and one accents pass. */
export const BATCH_SHARE = 0.14;
export const ACCENTS_A_PASS = 400;

type Rect = [number, number, number, number];
type Result = AgentToolResult<unknown>;
type Cell = { rect: Rect; colour: number; edges: number; score: number };
export type RegionRecord = { rect: Rect; detail: string; before: number; after: number; strokes: number; accents: number };
export type RoundRecord = { round: number; seconds: number; regions: RegionRecord[] };

const rect = (description: string) => Type.Array(Type.Integer({ minimum: 0, maximum: 100000 }), { minItems: 4, maxItems: 4, description });
const refineSchema = Type.Object({
  area: Type.Optional(Type.Union([Type.Literal('whole'), Type.Object({ box: rect('[x,y,w,h] on the canvas.') }, { additionalProperties: false })],
    { description: 'whole (default; the artist’s Paint only here area while it is set) or a box.' })),
  budget_minutes: Type.Optional(Type.Integer({ minimum: 1, maximum: 30, description: `Time budget (default ${BUDGET_MINUTES}).` })),
  max_strokes: Type.Optional(Type.Integer({ minimum: 10000, maximum: 30_000_000, description: `Stroke budget (default ${MAX_STROKES.toLocaleString('en-US')}).` })),
}, { additionalProperties: false });
export type RefineArgs = Static<typeof refineSchema>;

export type RefineRuntime = {
  study: { directory: string };
  decisionObservation?: unknown;
  emit(event: Record<string, unknown>): void;
  callNative(operation: string, params: Record<string, unknown>, id?: string): Promise<any>;
  paintOnlyArea?(): { mask_path: string; bounds: number[] } | null;
  /** Milliseconds for the budget (tests); Date.now by default. */
  refineClock?(): number;
};
export type RefineDependencies = {
  /** The chat's placed goal and whether the whole picture is underpainted (studio.mjs finishGoal). */
  goal(canvas: { width: number; height: number }): Promise<{ goal: PlacedGoal | null; underpainted: boolean }>;
  /** The studio's Sharpen-first refusal, as paint_finish's (finish-tool.ts). */
  sharpenFirst?(goal: PlacedGoal): Promise<string | null>;
  /** The plugin's reversible passes: `finish` and `accents`. */
  native(operation: 'finish' | 'accents', id: string, params: Record<string, unknown>, signal?: AbortSignal): Promise<any>;
};

// The whole picture, or a word that names it: "refine the painting", "closer to the final", "add more detail".
const WHOLE = new Set(['painting', 'picture', 'image', 'canvas', 'whole', 'final', 'goal', 'reference', 'original', 'result', 'scene', 'artwork', 'piece', 'work', 'thing', 'rest', 'end']);
const NEGATED = /\b(?:no|not|don['’]?t|do not|never|without|stop|avoid)\b[^.!?\n]{0,30}$/i;
/** The part a refine request names ("the church windows" -> "church"), or null for the whole picture. */
export function namedPart(text: string): string | null {
  for (const found of String(text ?? '').matchAll(/\b(?:the|its|those|these|that|this)\s+([a-z][\w-]*)/gi)) {
    const word = found[1]!.toLowerCase();
    if (!WHOLE.has(word) && !['more', 'most', 'same', 'other', 'detail', 'details'].includes(word)) return word;
  }
  return null;
}

/** A refine request after the whole-picture Finish with no area set (goal 8): for the whole picture, the note that runs
 * refine_to_goal; naming a part (review, 2026-10-24: "add more detail to the church windows" refined the whole canvas),
 * the note that asks for its area and refines it fine there; nothing when the request is negated ("don't add detail"). */
/** `reading`: Luna's reading of the message (message-reading.ts, luna-review), which decides a named part and a negation
 * when it answered them; the keyword rules otherwise. */
export function refineToGoalNote({ text, area, finished, reading }: { text: string; area: boolean; finished: boolean; reading?: Reading | null }): string {
  const said = String(text ?? ''), found = refineRequested(said);
  if (area || !finished || !found) return '';
  const luna = reading && !reading.fallback ? reading : null;
  const negated = typeof luna?.negation === 'number' ? luna.negation >= SURE : NEGATED.test(said.slice(0, said.toLowerCase().indexOf(found.toLowerCase())));
  if (negated) return '';
  const element = luna?.element?.name && luna.element.confidence >= SURE ? luna.element.name : null;
  const part = element ?? (typeof luna?.one_part === 'number' ? (luna.one_part >= SURE ? namedPart(said) ?? 'the part named' : null) : namedPart(said));
  if (part) return `REFINE A PART: the artist names a part (${part}) with no area set. Ask for its area first (ask_for_selection, or Find it), `
    + 'then paint_finish with detail "fine" in it and paint_accents there. Do not run refine_to_goal over the whole canvas and do not add typed strokes.';
  return 'REFINE TO THE GOAL: the whole picture is finished and the artist asks to refine it with no area set. Call refine_to_goal once: '
    + 'the host finds the regions still furthest from the goal at full size and refines them (a fine finish, then accents; finer where '
    + 'needed) until they are close or its budget is spent. Do not pick areas yourself and do not add typed strokes.';
}

const round1 = (v: number) => Math.round(v * 10) / 10;
const json = (value: unknown): Result['content'][number] => ({ type: 'text', text: JSON.stringify(value) });
type AreaMask = { data: Uint8Array; width: number; bounds: number[] };
const maskAt = (m: AreaMask, x: number, y: number) => (m.data[Math.floor(y - m.bounds[1]!) * m.width + Math.floor(x - m.bounds[0]!)] ?? 0) > 127;
const overlap = (a: number[], b: number[]) => Math.max(0, Math.min(a[0]! + a[2]!, b[0]! + b[2]!) - Math.max(a[0]!, b[0]!))
  * Math.max(0, Math.min(a[1]! + a[3]!, b[1]! + b[3]!) - Math.max(a[1]!, b[1]!));
/** The share of square `r` inside the area mask (1 without one), sampled every 8 px. */
function share(r: Rect, m: AreaMask | null): number {
  if (!m) return 1;
  let hit = 0, all = 0;
  for (let y = r[1] + 4; y < r[1] + r[3]; y += 8) for (let x = r[0] + 4; x < r[0] + r[2]; x += 8) {
    all++; if (inside(x, y, m.bounds) && maskAt(m, x, y)) hit++;
  }
  return all ? hit / all : 0;
}
/** One finish pass's area: the batch's squares (cut to the Paint only here area) as a mask file in the chat's .shapes. */
async function batchMask(directory: string, key: string, rects: Rect[], area: AreaMask | null): Promise<{ mask_path: string; bounds: number[] }> {
  const x0 = Math.min(...rects.map(r => r[0])), y0 = Math.min(...rects.map(r => r[1]));
  const width = Math.max(...rects.map(r => r[0] + r[2])) - x0, height = Math.max(...rects.map(r => r[1] + r[3])) - y0;
  const data = new Uint8Array(width * height);
  for (const r of rects) for (let y = r[1]; y < r[1] + r[3]; y++) for (let x = r[0]; x < r[0] + r[2]; x++)
    if (!area || (inside(x, y, area.bounds) && maskAt(area, x, y))) data[(y - y0) * width + (x - x0)] = 255;
  const folder = join(directory, '.shapes'), mask_path = join(folder, `refine-${createHash('sha256').update(key).digest('hex').slice(0, 24)}.png`);
  await mkdir(folder, { recursive: true });
  await writeFile(mask_path, encodePlane({ width, height, data }));
  return { mask_path, bounds: [x0, y0, width, height] };
}
const inside = (x: number, y: number, r: number[]) => x >= (r[0] ?? 0) && y >= (r[1] ?? 0) && x < (r[0] ?? 0) + (r[2] ?? 0) && y < (r[1] ?? 0) + (r[3] ?? 0);

export function refineTools(runtime: RefineRuntime, dependencies: RefineDependencies): ToolDefinition<any, unknown>[] {
  return [{
    name: 'refine_to_goal', label: 'Refining to the goal', executionMode: 'sequential', parameters: refineSchema,
    description: 'After the whole-picture paint_finish: brings the painting to the goal image region by region, host-driven. The host '
      + 'compares the canvas with the goal at full size, takes the regions still furthest from it (colour and crispness), worst first, '
      + 'and runs a fine finish then accents on each, a finer finish where fine was not enough, until every region is close or the '
      + `budget is spent (${BUDGET_MINUTES} minutes by default). One call; the move's Undo removes it all. Use it for "refine", "closer `
      + 'to the final", "finish it" on the whole picture; for one part with an area use paint_finish detail fine and paint_accents there.',
    execute: async (id: string, args: RefineArgs, signal?: AbortSignal): Promise<Result> => {
      signal?.throwIfAborted();
      const clock = () => (runtime.refineClock ? runtime.refineClock() : Date.now());
      const began = clock(), started = Date.now();
      const seen = await runtime.callNative('observe', {}) as { width: number; height: number; protected_areas?: { bounds: number[] }[]; [key: string]: unknown };
      runtime.decisionObservation = seen;
      const canvas = { width: Number(seen.width), height: Number(seen.height) };
      if (!(canvas.width > 0 && canvas.height > 0)) throw new Error('Open the painting first: there is no canvas to refine.');
      const { goal, underpainted } = await dependencies.goal(canvas);
      if (!underpainted) throw new Error(NOT_UNDERPAINTED);
      if (!goal) throw new Error(NO_GOAL);
      const first = await dependencies.sharpenFirst?.(goal);
      if (first) throw new Error(first);
      const spec: GoalSpec = await goalSpec(goal);
      const scoped = args.area === undefined ? runtime.paintOnlyArea?.() ?? null : null;
      const areaMask = scoped ? await loadAreaMask(scoped, runtime.study.directory) : null;
      const area = (scoped ? scoped.bounds : args.area && typeof args.area === 'object' ? args.area.box : [0, 0, canvas.width, canvas.height]) as Rect;
      const side = Math.max(128, Math.round(REGION * Math.max(canvas.width, canvas.height) / 6000));
      // A batch of squares is one finish pass: at most BATCH_SHARE of the canvas (under finish_pass.py's 15% for fine).
      const batchSize = Math.max(1, Math.floor(BATCH_SHARE * canvas.width * canvas.height / (side * side)));
      const budget = (args.budget_minutes ?? BUDGET_MINUTES) * 60000, maxStrokes = args.max_strokes ?? MAX_STROKES;
      const protectedAreas = seen.protected_areas ?? [];
      // A square mostly in protected areas or outside the Paint only here area is left (Krita keeps those pixels anyway).
      const usable = (r: Rect) => share(r, areaMask) >= 0.5 && protectedAreas.every(p => overlap(r, p.bounds) <= 0.5 * r[2] * r[3]);
      const speck = speckSize(side, 1);
      const levels = new Map<string, number>(), rounds: RoundRecord[] = [], after = new Map<string, number>();
      let strokes = 0, passes = 0, ended = '', last: Cell[] = [];
      const measure = async (r: Rect) => { const m = await runtime.callNative('area_likeness', { goal: spec, rect: r }); return round1(Number(m.colour) + Number(m.edges)); };
      const stopped = () => `Stopped by the artist after ${passes} regions: what is refined is kept.`;
      rounds: for (let round = 1; ; round++) {
        const map = await runtime.callNative('refine_map', { goal: spec, rect: area, cell: side }) as { cells: Cell[] };
        last = map.cells; after.clear();
        const todo = map.cells.filter(c => c.score > DONE_SCORE && (levels.get(c.rect.join(',')) ?? 0) < LEVELS.length && usable(c.rect));
        if (!todo.length) break;
        const record: RoundRecord = { round, seconds: 0, regions: [] }, roundStart = Date.now(), done: { cell: Cell; detail: string }[] = [];
        rounds.push(record);
        // Close what was painted: the accents the canvas still lacks in the squares done, then each square measured.
        const close = async () => {
          const found: Accent[] = [];
          for (const { cell } of done) {
            const reply = await runtime.callNative('area_accents', { goal: spec, rect: cell.rect, kinds: [...ACCENT_KINDS], strength: 'medium', max_accents: 3 * REGION_ACCENTS + 20 }) as { accents?: Accent[] };
            const kept = (reply.accents ?? []).filter(a => inside(a.x, a.y, cell.rect) && !protectedAreas.some(p => inside(a.x, a.y, p.bounds))
              && (a.kind !== 'darks' || a.size >= speck || a.strength >= 0.8) && (!areaMask || maskAt(areaMask, a.x, a.y)));
            found.push(...chooseAccents(kept, ACCENT_KINDS as readonly AccentKind[], REGION_ACCENTS));
          }
          for (let k = 0; k * ACCENTS_A_PASS < found.length; k++)
            await dependencies.native('accents', `${id}/r${round}-accents-${k + 1}`, { name: `Refine ${round} accents`,
              accents: accentAdjustments(found.slice(k * ACCENTS_A_PASS, (k + 1) * ACCENTS_A_PASS), (x, y) => [x, y], 1, canvas) }, signal);
          for (const [index, { cell, detail }] of done.entries()) {
            const score = await measure(cell.rect);
            after.set(cell.rect.join(','), score);
            record.regions.push({ rect: cell.rect, detail, before: round1(cell.score), after: score, strokes: 0, accents: found.filter(a => inside(a.x, a.y, cell.rect)).length });
            runtime.emit({ type: 'status', phase: 'painting', message: `Refine: round ${round}, region ${index + 1} of ${todo.length}, difference ${cell.score.toFixed(1)} → ${score.toFixed(1)}` });
          }
        };
        try {
          for (let b = 0; b * batchSize < todo.length; b++) {
            if (signal?.aborted) { ended = stopped(); break; }
            if (clock() - began >= budget) { ended = `The time budget (${Math.round(budget / 60000)} minutes) is spent.`; break; }
            if (strokes >= maxStrokes) { ended = `The stroke budget (${maxStrokes.toLocaleString('en-US')}) is spent.`; break; }
            const batch = todo.slice(b * batchSize, (b + 1) * batchSize);
            for (const level of [...new Set(batch.map(c => levels.get(c.rect.join(',')) ?? 0))]) {
              const cells = batch.filter(c => (levels.get(c.rect.join(',')) ?? 0) === level), detail = LEVELS[level]!;
              const inside_shape = await batchMask(runtime.study.directory, `${id}/${round}/${b}/${level}`, cells.map(c => c.rect), areaMask);
              runtime.emit({ type: 'status', phase: 'painting', message: `Refine: round ${round}, ${cells.length} region${cells.length === 1 ? '' : 's'} (${detail})…` });
              const painted = await dependencies.native('finish', `${id}/r${round}-${b + 1}-${detail}`, { name: `Refine ${round}`, goal: spec, inside_shape, detail }, signal);
              const result = painted?.details ?? painted ?? {};
              strokes += Number(result.finish?.strokes ?? 0);
              for (const cell of cells) { levels.set(cell.rect.join(','), level + 1); done.push({ cell, detail }); }
              passes += cells.length;
              if (result.stopped || signal?.aborted) { ended = stopped(); break; }
            }
            if (ended) break;
          }
          await close();
        } catch (error) {
          // Stop, the painting allowance or a failed pass: what is done stays, the run reports it.
          const aborted = signal?.aborted || (error as Error)?.name === 'AbortError';
          ended = aborted ? stopped() : `Ended after ${passes} regions: ${(error as Error)?.message ?? error}`;
          await close().catch(() => {});
        }
        record.seconds = Math.round((Date.now() - roundStart) / 100) / 10;
        const mean = (key: 'before' | 'after') => round1(record.regions.reduce((sum, r) => sum + r[key], 0) / Math.max(1, record.regions.length));
        runtime.emit({ type: 'action', seconds: record.seconds, message: `Refine round ${round}: ${record.regions.length} regions, difference ${mean('before')} → ${mean('after')} on average.` });
        if (ended) break rounds;
      }
      // What is left: the last map, with the squares refined since it was made at their measured scores.
      const above = last.map(c => after.get(c.rect.join(',')) ?? c.score).filter(score => score > DONE_SCORE).length;
      const converged = !ended && above === 0;
      const message = converged ? `Every region is within ${DONE_SCORE} of the goal at full size.`
        : ended || `${above} region${above === 1 ? ' is' : 's are'} still above ${DONE_SCORE} after every level: as close as the strokes get there.`;
      const view = await runtime.callNative('observe', {}).catch(() => null);
      if (view) runtime.decisionObservation = view;
      const report = { converged, rounds, regions: rounds.reduce((n, r) => n + r.regions.length, 0), strokes, left_above: above, done_score: DONE_SCORE, ms: Date.now() - started,
        ...(ended ? { ended } : {}), message, next: 'Look at the canvas; tell the artist what changed and what is left.' };
      return { content: [json(report)], details: { ...(view ?? {}), refine: report } };
    },
  }];
}

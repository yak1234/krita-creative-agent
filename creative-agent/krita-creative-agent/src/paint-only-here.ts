// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Paint only here (openspec element-scoped-painting, goals 1, 5 and 6; the artist, 2026-10-23): the artist selects an area
// in Krita with any selection tool and presses Paint only here in the panel (or types "paint only in my selection"). The
// panel captures the selection's pixels and the plugin protects everything outside it (paint_only_here.py), so Krita
// itself blocks every agent write there: that is the guarantee. This module is the companion's side:
//
// - the area the chat keeps (goal.paint_only_here, so it survives resume), adopted from the panel's mask file into the chat
//   folder's .shapes, where the plugin reads shapes (shape_mask.py); one area at a time, a new one replaces it;
// - the painter's context: where it is, a short description, what the host does there, and the line its reply starts with;
// - the scoped transfer (goal 5): the same plan, only the dabs whose centre lies inside the area (scopePlan), and the share
//   the transfer rules measure (goal 6, reference-tool.mjs);
// - ask_for_selection (and the studio's element steps, askForArea): for work on one part with no area set, a question card
//   in Agent, proposing the shapes model's outline when it has one (Use this, Adjust with Freehand, Paint everywhere), else
//   Find it for me, Select with Freehand, Use my selection, Paint everywhere; Autopilot never stops for it, and uses the
//   found outline as the area when there is one.
// The studio's calls come in as a small host, so this module imports no .mjs.
import { mkdir, readFile, unlink, writeFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { basename, dirname, isAbsolute, join, resolve } from 'node:path';
import { Type, type Static } from 'typebox';
import type { AgentToolResult, ToolDefinition } from '@earendil-works/pi-coding-agent';
import { decodePlane, encodePlane } from './shapes/png.ts';
import { elementsNamed } from './project-folder.ts';

export type Rect = [number, number, number, number];
export type PaintOnlyArea = { name: string | null; bounds: Rect; mask_path: string; sha256: string; share: number; canvas: [number, number]; set_at: string };
export type PaintOnlyCommand = { action?: string; mask_path?: unknown; bounds?: unknown; canvas?: unknown; name?: unknown };
export type AreaMask = { width: number; height: number; data: Uint8Array; bounds: Rect };

/** A mask value from which a pixel is inside (as protection_raster.INSIDE). */
const INSIDE = 128;
/** The companion's copy of an area's mask, in the chat folder's .shapes; the panel's waiting file, in its pasted folder. */
const MASK_FILE = /^paint-only-[0-9a-f]{24}\.png$/;
const PANEL_FILE = /^creative-paint-only-[0-9a-f]{32}\.png$/, PANEL_FOLDER = 'creative-agent-pasted';
/** Whether `path` is an area mask of the chat folder `directory`: <directory>/.shapes/paint-only-<24 hex>.png. */
export const areaMaskPath = (directory: string, path: unknown): path is string =>
  typeof path === 'string' && isAbsolute(path) && MASK_FILE.test(basename(path)) && dirname(path) === resolve(directory, '.shapes');
const NAME_LIMIT = 60;

export const areaLabel = (area: { name?: string | null }): string => area.name?.trim() || 'your selection';
/** The line the panel's chip, the host and the painter's reply use. */
export const chipLine = (area: { name?: string | null }): string =>
  'Painting only inside your selection' + (area.name?.trim() ? ': ' + area.name.trim() : '');

const integers = (value: unknown, count: number): number[] | null =>
  Array.isArray(value) && value.length === count && value.every(v => Number.isInteger(v) && v >= 0) ? value as number[] : null;

/** The panel's mask file (one byte a pixel, the selection cropped to its bounds) as the chat's area: re-encoded into the
 * chat folder's .shapes, measured, and named when the artist named it. The panel's file is removed afterwards. */
export async function adoptArea(directory: string, command: PaintOnlyCommand): Promise<PaintOnlyArea> {
  const bounds = integers(command.bounds, 4), canvas = integers(command.canvas, 2);
  if (!bounds || !canvas || !(bounds[2]! > 0 && bounds[3]! > 0 && canvas[0]! > 0 && canvas[1]! > 0))
    throw new Error('Paint only here needs the selection’s bounds and the canvas size.');
  const [x, y, w, h] = bounds as Rect, [cw, ch] = canvas as [number, number];
  if (x + w > cw || y + h > ch) throw new Error('The selection lies outside the canvas.');
  const path = command.mask_path;
  if (typeof path !== 'string' || !isAbsolute(path) || !path.endsWith('.png')) throw new Error('Paint only here needs the selection’s mask file.');
  const plane = decodePlane(await readFile(path), { width: w, height: h });
  if (plane.width !== w || plane.height !== h) throw new Error(`The selection mask has another size (${plane.width} x ${plane.height}) than its bounds (${w} x ${h}).`);
  let inside = 0;
  for (const value of plane.data) if (value >= INSIDE) inside++;
  if (!inside) throw new Error('The selection is empty: select the area first.');
  const sha256 = createHash('sha256').update(JSON.stringify(bounds)).update(plane.data).digest('hex');
  const folder = join(directory, '.shapes');
  await mkdir(folder, { recursive: true });
  const mask_path = join(folder, 'paint-only-' + sha256.slice(0, 24) + '.png');
  await writeFile(mask_path, encodePlane(plane));
  // Only the panel's own waiting file goes (its pasted folder, its name): never a file the command merely names.
  if (basename(dirname(path)) === PANEL_FOLDER && PANEL_FILE.test(basename(path))) await unlink(path).catch(() => {});
  const name = typeof command.name === 'string' && command.name.trim() ? command.name.trim().slice(0, NAME_LIMIT) : null;
  return { name, bounds: [x, y, w, h], mask_path, sha256, share: inside / (cw * ch), canvas: [cw, ch], set_at: new Date().toISOString() };
}

export type PaintOnlyHost = {
  study: { directory: string } | null;
  goal: { paint_only_here?: PaintOnlyArea | null } | null;
  persist(): Promise<void>;
  publish(): void;
  /** One line beside the chat (an action event). */
  say(message: string): void;
};
/** The panel's paint_only_here command (set or clear), alone or with a prompt. Nothing without one. */
export async function applyPaintOnlyCommand(host: PaintOnlyHost, command: PaintOnlyCommand | undefined | null): Promise<void> {
  if (!command) return;
  if (!host.goal || !host.study) throw new Error('Start a chat first: Paint only here belongs to a chat.');
  if (command.action === 'clear') {
    if (!host.goal.paint_only_here) return;
    host.goal.paint_only_here = null;
    host.say('Painting everywhere again: the area was cleared.');
  } else if (command.action === 'set') {
    host.goal.paint_only_here = await adoptArea(host.study.directory, command);
    host.say(chipLine(host.goal.paint_only_here));
  } else throw new Error('Paint only here is set or clear.');
  await host.persist(); host.publish();
}

/** The painter's context while an area is set (studio.mjs context()). */
export function areaContext(area: PaintOnlyArea | null | undefined) {
  if (!area) return undefined;
  const percent = Math.max(1, Math.round(area.share * 100));
  return {
    name: areaLabel(area), bounds: area.bounds,
    description: `The artist's own selection (${percent}% of the canvas), the pixels they drew around inside bounds [${area.bounds.join(', ')}].`,
    rules: 'Paint only inside it: Krita blocks every write outside it, and its edge is softened a few pixels. paint_from_reference, '
      + 'continue_reference_painting and the edges and surface tools paint only the dabs inside it, so transfer the whole reference over '
      + 'the whole canvas (or the reference area that lies under it) and the area may be the first transfer; paint_finish and paint_accents '
      + 'work in it by default. To refine, sharpen or add detail here after the whole-picture finish: paint_finish with detail "fine" '
      + '(2-4 px strokes from the goal, its real detail size), then paint_accents. Do not paint elsewhere; to work outside it the artist '
      + 'clears it in the panel.',
    reply: chipLine(area) + '. Start your reply with this line.',
  };
}

/** The area's mask, read back from the chat folder `directory` for a scoped transfer or accents: only its own
 * .shapes/paint-only-*.png. */
export async function loadAreaMask(area: { mask_path: string; bounds: number[] }, directory: string): Promise<AreaMask> {
  if (!areaMaskPath(directory, area.mask_path)) throw new Error('A Paint only here mask is read only from this chat folder\u2019s .shapes.');
  let file: Buffer;
  try { file = await readFile(area.mask_path); } catch { throw new Error('The Paint only here area’s mask is no longer there: the artist can press Paint only here again.'); }
  const [x = 0, y = 0, w = 0, h = 0] = area.bounds;
  const plane = decodePlane(file, { width: w, height: h });
  if (plane.width !== w || plane.height !== h) throw new Error('The Paint only here mask does not match its bounds.');
  return { ...plane, bounds: [x, y, w, h] };
}

/** Whether a canvas point lies inside the area (mask >= 128). */
export function insideTest(mask: AreaMask): (x: number, y: number) => boolean {
  const [bx, by, bw, bh] = mask.bounds;
  return (x, y) => {
    const i = Math.floor(x - bx), j = Math.floor(y - by);
    return i >= 0 && j >= 0 && i < bw && j < bh && (mask.data[j * mask.width + i] ?? 0) >= INSIDE;
  };
}

type Stroke = { start: number[]; segments?: number[][] };
type Plan = { total: number; passes: { strokes: Stroke[] }[] };
/** A dab's centre: halfway between its start and the end of its last segment. */
const dabCentre = (stroke: Stroke): [number, number] => {
  const end = stroke.segments?.at(-1), [sx = 0, sy = 0] = stroke.start;
  return end && end.length >= 6 ? [(sx + end[4]!) / 2, (sy + end[5]!) / 2] : [sx, sy];
};
/** The plan with only the dabs whose centre lies inside the area; a pass left with none goes. Deterministic, so a resume
 * rebuilds the same plan from the job's own area. */
export function scopePlan<P extends Plan>(plan: P, mask: AreaMask): P {
  const inside = insideTest(mask);
  const passes = plan.passes.map(pass => ({ ...pass, strokes: pass.strokes.filter(stroke => inside(...dabCentre(stroke))) })).filter(pass => pass.strokes.length);
  return { ...plan, passes, total: passes.reduce((n, pass) => n + pass.strokes.length, 0) };
}

/** The share of the canvas a transfer to `target` paints inside the area: the area's share, times the part of its bounds
 * under the target (a transfer is measured by its element, goal 6). */
export function scopedShare(area: { bounds: number[]; share: number }, target: number[]): number {
  const [ax = 0, ay = 0, aw = 0, ah = 0] = area.bounds, [tx = 0, ty = 0, tw = 0, th = 0] = target;
  const overlap = Math.max(0, Math.min(ax + aw, tx + tw) - Math.max(ax, tx)) * Math.max(0, Math.min(ay + ah, ty + th) - Math.max(ay, ty));
  return aw * ah ? area.share * overlap / (aw * ah) : 0;
}

// ----- asking the artist to select ------------------------------------------------------------------------------------------
// Find it for me (find-it.ts; the artist, 2026-10-24): the card also offers the shapes model's outline. When it can be had
// without asking anything (the model allowed and downloaded, a decision model to locate the part), the card proposes it,
// loaded in the painting as the selection: "Is this the sky?" Use this / Adjust with Freehand / Paint everywhere. Otherwise
// Find it for me is the first option (it may ask once for the model download: the artist pressed it). Autopilot uses the
// found outline as the area by itself and says so.
export const SELECT_OPTIONS = ['Find it for me', 'Select with Freehand', 'Use my selection', 'Paint everywhere'];
export const PROPOSAL_OPTIONS = ['Use this', 'Adjust with Freehand', 'Paint everywhere'];
/** A found outline as the card and the panel see it (find-it.ts FoundArea, the fields that cross). */
export type Proposal = { mask_path: string; bounds: number[]; canvas: number[]; share: number; score?: number; ms?: unknown; cached?: boolean; note?: string };
const selectSchema = Type.Object({
  part: Type.String({ minLength: 1, maxLength: NAME_LIMIT, description: 'The part the artist asked about, as they said it: "the sky", "the hair", "the car".' }),
}, { additionalProperties: false });
type Result = AgentToolResult<unknown>;
const reply = (text: string, details: Record<string, unknown> = {}): Result => ({ content: [{ type: 'text', text }], details });

export type SelectionHost = {
  mode: string;
  goal: { status?: string; question?: unknown; paint_only_here?: PaintOnlyArea | null } | null;
  emit(event: Record<string, unknown>): void;
  persist(): Promise<void>;
  publish(): void;
  /** End the turn after this call (the studio's yieldRequested). */
  yieldTurn(): void;
  /** The artist's latest message, for a negated part ("don't paint the sky"). */
  latestRequest?(): string;
  /** The shapes model's outline of `part` on the painting, only when it needs no question to the artist; null otherwise. */
  propose?(part: string): Promise<Proposal | null>;
  /** Autopilot: the found outline becomes the chat's area (and is protected on the painting at once). */
  adopt?(proposal: Proposal, part: string): Promise<PaintOnlyArea>;
};
export type AskOutcome = { asked: boolean; adopted?: PaintOnlyArea; negated?: boolean; reply: string };

/** Ask the artist for the area of `part` (Agent: the card, proposing the found outline when there is one), or in Autopilot
 * use the found outline by itself. ask_for_selection and the studio's element steps both come here. */
export async function askForArea(host: SelectionHost, given: string, { request }: { request?: string } = {}): Promise<AskOutcome> {
  const goal = host.goal, part = given.trim().slice(0, NAME_LIMIT);
  if (!goal) throw new Error('There is no chat to ask in.');
  if (goal.paint_only_here) return { asked: false, reply: `An area is already set. ${chipLine(goal.paint_only_here)}: paint there.` };
  if (partNegated(host.latestRequest?.() ?? '', part))
    return { asked: false, negated: true, reply: `The artist said not to work on ${part}: do not ask for it and leave it alone.` };
  let proposal: Proposal | null = null;
  try { proposal = (await host.propose?.(part)) ?? null; } catch { proposal = null; }    // no outline: the plain card
  if (host.mode !== 'agent') {
    let failed = '';
    if (proposal && host.adopt) {
      try {
        const area = await host.adopt(proposal, part), percent = Math.max(1, Math.round(area.share * 100));
        const message = `Autopilot found ${part} with the shapes model (${percent}% of the canvas) and paints only inside it until this step ends. Clear it in the panel to paint everywhere.`;
        host.emit({ type: 'action', seconds: 0, message });
        return { asked: false, adopted: area, reply: `${chipLine(area)}. The shapes model found ${part}: paint it inside this area (Krita keeps every write there) and say so in your reply.` };
      } catch (error) { failed = ` (${(error as Error).message})`; }      // the area could not be protected: none at all
    }
    host.emit({ type: 'action', seconds: 0, message: `Autopilot does not stop to ask for a selection: painting ${part} without an area${failed}.` });
    return { asked: false, reply: `Autopilot does not stop for this: paint ${part} without an area, keep to it carefully, and say in your reply that no area was selected.` };
  }
  const question = proposal
    ? `Is this ${part}? It is selected on your painting now. Adjust it with Freehand (Shift adds, Alt subtracts) if needed, then press Use this.`
    : `Select ${part}: Find it for me outlines it with the shapes model, or draw around it with the Freehand Selection tool (the Magnetic one snaps to edges), then press Use my selection.`;
  goal.question = { id: randomUUID(), question, options: [...(proposal ? PROPOSAL_OPTIONS : SELECT_OPTIONS)], asked_in: 'agent',
    select_area: { part, ...(request ? { request: request.slice(0, 500) } : {}), ...(proposal ? { proposal } : {}) } };
  goal.status = 'needs_input'; host.yieldTurn();
  await host.persist(); host.publish();
  host.emit({ type: 'question', ...(goal.question as object) });
  return { asked: true, reply: 'Question displayed: the artist selects the part, or paints everywhere. Stop now and wait for their answer.' };
}
/** Whether the message mentions the part only where it says not to work on it (project-folder.ts elementsNamed's rule). */
export function partNegated(text: string, part: string): boolean {
  const head = part.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean).at(-1);
  if (!head || !new RegExp(`(?<![\\p{L}\\p{N}])${head.replace(/s$/, '')}`, 'u').test(text.toLowerCase())) return false;
  return !elementsNamed(text, [{ name: part, guess: part.replace(/^(the|a|an)\s+/i, '') }]).length;
}
export function selectionTools(host: SelectionHost): ToolDefinition<any, unknown>[] {
  return [{
    name: 'ask_for_selection', label: 'Asking for a selection', executionMode: 'sequential', parameters: selectSchema,
    description: 'Before work on one part of the painting ("paint the sky", "only the hair", "fix the car") when no Paint only here area '
      + 'is set: ask the artist for its area instead of guessing where it is (never a colour selection or a magic wand for it). The panel '
      + 'shows the question, with the shapes model\u2019s outline of the part already selected when it can find it ("Is this the sky?"), '
      + 'or Find it for me and Select with Freehand; stop after this call and wait. In Autopilot it does not stop: the found outline '
      + 'becomes the area, or you paint without one; say which. Not for the whole picture, nor for a part the artist said to leave '
      + 'alone ("don\u2019t paint the sky").',
    execute: async (_id: string, args: Static<typeof selectSchema>): Promise<Result> => {
      const outcome = await askForArea(host, args.part, { request: host.latestRequest?.() ?? '' });
      return reply(outcome.reply, { asked: outcome.asked, ...(outcome.negated ? { negated: true } : {}), ...(outcome.adopted ? { area: areaLabel(outcome.adopted) } : {}) });
    },
  }];
}

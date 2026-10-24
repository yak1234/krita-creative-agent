// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// paint_finish (openspec finish-stage; approved by the artist 2026-10-24 after the offline spike): the stage between the
// whole-picture underpainting and the accents. On New Moscow the underpainting matched the goal (goal likeness ΔE 1.7) yet
// still read as an underpainting: every area the same small round dabs, the sky confetti, the buildings ragged; accents
// add lights and darks only. Finish treats areas as a painter does: where the goal is soft (sky, mist, water) the canvas's
// own paint is blended by an edge-preserving filter; where it is hard (buildings, towers, a bridge) short strokes follow
// the goal's form, coloured from the goal, each ending where the goal's colour changes (never along outlines). The plugin's
// `finish` operation (finish_pass.py) does the work per tile and bakes it into one Finish group of two plain layers inside
// the move's group (one Undo); this module finds the goal and where it sits, and the area.
//
// - The goal is the chat's whole-picture goal where its kept whole transfer placed it (goal-likeness.ts goalMapping), else
//   a goal of the canvas's proportions over the whole canvas; its sharpened copy when the chat has one (goal-sharpen.ts:
//   the reference itself becomes it). The plugin reads the file from the chat folder; nothing is sent as base64.
// - Refused before the whole picture is underpainted (a kept whole-picture transfer, or a painting the chat started on):
//   Finish refines an underpainting, it is not one.
// - The area: the whole picture by default (the artist's Paint only here area while it is set), a box, a saved selection
//   or features, or an element's shape. Protected areas: Krita keeps the writes out of them.
// - A goal enlarged more than 2x and not sharpened: the first call is refused so the painter offers Sharpen (the card) first,
//   unless the artist kept the original or chose Never (review, 2026-10-24: Finish from such a goal mostly blurs).
// - detail fine (goal 6, the artist 2026-10-24: "yess we need both"): on New Moscow the whole-picture Finish's 5-9 px strokes
//   were blobby beside the church's 2-4 px windows; fine paints 2-4 px strokes for one part (the plugin refuses it on more
//   than 15% of the canvas: finish_pass.py FINE_SHARE). The refine step after the whole-picture Finish: fine, then accents.
// - Measured by goal likeness, never undone by it (goal-likeness.ts exemption 'finish'); the Now card shows the tile.
// The studio's native calls come in as dependencies, so this module imports no .mjs.
import { Type, type Static } from 'typebox';
import type { AgentToolResult, ToolDefinition } from '@earendil-works/pi-coding-agent';
import { canvasShape, shapeSchema, type CanvasHost } from './shapes/use.ts';
import { loadAreaMask } from './paint-only-here.ts';
import { shapesAllowed } from './accents-tool.ts';
import { goalSpec, type PlacedGoal } from './goal-spec.ts';

const rect = (description: string) => Type.Array(Type.Integer({ minimum: 0, maximum: 100000 }), { minItems: 4, maxItems: 4, description });
const finishSchema = Type.Object({
  area: Type.Optional(Type.Union([
    Type.Literal('whole'),
    Type.Object({ box: rect('[x,y,w,h] on the canvas.') }, { additionalProperties: false }),
    Type.Object({ selection: Type.String({ minLength: 1, maxLength: 2000, description: 'A saved selection, or feature names and expressions such as "Sky - Moon".' }) }, { additionalProperties: false }),
    Type.Object({ shape: shapeSchema('canvas') }, { additionalProperties: false }),
  ], { description: 'Where: whole (the default), a box, a named selection, or one element’s shape (only when the shapes model is already allowed).' })),
  detail: Type.Optional(Type.Union([Type.Literal('normal'), Type.Literal('fine')], { description: 'normal (default): the whole-picture '
    + 'finish. fine: strokes about half as wide, for refining one part (an area of at most 15% of the canvas) to the goal’s real detail size.' })),
}, { additionalProperties: false });
export type FinishArgs = Static<typeof finishSchema>;

type Result = AgentToolResult<unknown>;
export type FinishGoal = PlacedGoal;
export type FinishParams = { name: string; goal: { path: string; sha256: string; size: [number, number]; source: number[]; target: number[] };
  box?: number[]; selection?: string; inside_shape?: { mask_path: string; bounds: number[] }; detail?: 'fine' };
export type FinishRuntime = CanvasHost & {
  study: { directory: string; shapes_declined?: boolean };
  decisionObservation?: unknown;
  emit(event: Record<string, unknown>): void;
  /** The artist's Paint only here area (paint-only-here.ts), the default area while it is set. */
  paintOnlyArea?(): { mask_path: string; bounds: number[] } | null;
  /** A finish painted: whole when it covered the whole picture at the default detail (element steps then refine fine). */
  finishDone?(scope: { whole: boolean }): void;
};
export type FinishDependencies = {
  /** The chat's whole-picture goal and where it sits on `canvas` (studio.mjs goalPlacement), and whether the whole picture is
   * underpainted (a kept whole transfer, or a painting the chat started on). */
  goal(canvas: { width: number; height: number; [key: string]: unknown }): Promise<{ goal: FinishGoal | null; underpainted: boolean }>;
  /** Before painting from an unsharpened goal enlarged more than 2x (Finish would mostly blur it): the studio's refusal, once,
   * that shows the Sharpen goal card and tells the painter to offer it; null to paint (sharpened, declined, Never, asked). */
  sharpenFirst?(goal: FinishGoal): Promise<string | null>;
  /** The plugin's `finish` operation (finish_pass.py) through the studio's native call: one reversible pass. */
  finish(id: string, params: FinishParams, signal?: AbortSignal): Promise<Result>;
};

export const NOT_UNDERPAINTED = 'Nothing was painted: Finish refines a whole-picture underpainting, and this canvas has none yet. '
  + 'Underpaint the whole picture from the goal image first (paint_from_reference, all of it onto the whole canvas), then finish it.';
export const sharpenFirstMessage = (enlargement: number) => `Nothing was painted: the goal image is drawn ${enlargement.toFixed(1)}x larger `
  + 'than it is and not sharpened, so Finish would mostly blur it. The host showed the artist the Sharpen goal card: tell them, and offer to '
  + 'sharpen it first. Call paint_finish again after they answer (with the original goal it then runs as it is).';
export const NO_GOAL = 'Nothing was painted: Finish repaints from the goal image, and this chat has none placed on the canvas. Attach the goal '
  + 'image (with the canvas’s proportions) or underpaint the whole picture from it first.';

/** How many times larger the goal's crop is drawn onto the canvas. */
export const goalEnlargement = (goal: Pick<FinishGoal, 'source' | 'target'>): number =>
  (goal.source[2] ?? 0) > 0 ? (goal.target[2] ?? 0) / (goal.source[2] ?? 1) : 0;

const json = (value: unknown): Result['content'][number] => ({ type: 'text', text: JSON.stringify(value) });

export function finishTools(runtime: FinishRuntime, dependencies: FinishDependencies): ToolDefinition<any, unknown>[] {
  return [{
    name: 'paint_finish', label: 'Finishing the painting', executionMode: 'sequential', parameters: finishSchema,
    description: 'Stage two after the whole-picture underpainting, before paint_accents: turns the underpainting’s even dabs into a '
      + 'finished painting. Where the goal image is soft (sky, mist, water) the canvas’s own paint is blended into smooth gradients, '
      + 'edges kept; where it is hard (buildings, towers, figures) short strokes follow the forms, coloured from the goal image, each '
      + 'ending where its colour changes. The host uses the goal where the underpainting placed it (sharpened when the chat has a '
      + 'sharpened goal). Name the area: whole (default; the artist’s Paint only here area while it is set), a box, a selection or '
      + 'an element’s shape. One Finish group of two layers (one Undo); about a minute for a whole large canvas. Call it once per '
      + 'area, after the underpainting and before paint_accents; never before an underpainting. To refine, sharpen or add detail to one '
      + 'part after the whole-picture finish (Paint only here, Find it, an element step): detail fine in that area, then paint_accents there '
      + '(a few seconds for a building).',
    execute: async (id: string, args: FinishArgs, signal?: AbortSignal): Promise<Result> => {
      signal?.throwIfAborted();
      const started = Date.now();
      if (args.area && typeof args.area === 'object' && 'shape' in args.area && !(await shapesAllowed(runtime)))
        throw new Error('Finishing inside an element’s shape needs the shapes model, which is not allowed in this chat: give a box or a selection around it instead.');
      const seen = await runtime.callNative('observe', {}) as { width: number; height: number; [key: string]: unknown };
      runtime.decisionObservation = seen;
      const canvas = { ...seen, width: Number(seen.width), height: Number(seen.height) };
      if (!(canvas.width > 0 && canvas.height > 0)) throw new Error('Open the painting first: there is no canvas to finish.');
      const { goal, underpainted } = await dependencies.goal(canvas);
      if (!underpainted) throw new Error(NOT_UNDERPAINTED);
      if (!goal) throw new Error(NO_GOAL);
      const first = await dependencies.sharpenFirst?.(goal);
      if (first) throw new Error(first);
      const reference = goal.reference;
      // The area: the plugin reads a selection or a shape's file itself; the box goes as it is.
      let limit: Pick<FinishParams, 'box' | 'selection' | 'inside_shape'> = {};
      const scoped = args.area === undefined ? runtime.paintOnlyArea?.() ?? null : null;
      if (scoped) {
        const plane = await loadAreaMask(scoped, runtime.study.directory);
        limit = { inside_shape: { mask_path: scoped.mask_path, bounds: plane.bounds } };
      } else if (args.area && typeof args.area === 'object' && 'box' in args.area) limit = { box: args.area.box };
      else if (args.area && typeof args.area === 'object' && 'selection' in args.area) limit = { selection: args.area.selection };
      else if (args.area && typeof args.area === 'object' && 'shape' in args.area) {
        const shape = await canvasShape(runtime, args.area.shape);
        limit = { inside_shape: { mask_path: shape.mask_path, bounds: shape.bounds } };
      }
      signal?.throwIfAborted();
      const params: FinishParams = { name: 'Finish', goal: await goalSpec(goal), ...limit,
        ...(args.detail === 'fine' ? { detail: 'fine' as const } : {}) };
      runtime.emit({ type: 'status', phase: 'painting', message: args.detail === 'fine' ? 'Finish (fine): restroking the forms at the goal’s detail size…'
        : 'Finish: blending the soft areas and restroking the forms…' });
      const result = await dependencies.finish(id, params, signal);
      const details = (result.details ?? {}) as { layer_id?: string; finish?: { detail?: string; tiles?: number; of_tiles?: number; strokes?: number; soft_share?: number; ms?: number }; stopped?: string };
      const ms = Date.now() - started, done = details.finish ?? {};
      if (!details.stopped) runtime.finishDone?.({ whole: !Object.keys(limit).length && args.detail !== 'fine' });
      runtime.emit({ type: 'action', seconds: Math.round(ms / 100) / 10, message: details.stopped ? `Finish stopped: ${done.tiles ?? 0} of ${done.of_tiles ?? 0} squares done.`
        : `Finished ${done.of_tiles ?? 0} squares${done.detail === 'fine' ? ' in fine detail' : ''}: soft areas blended (${Math.round((done.soft_share ?? 0) * 100)}% of the area), ${(done.strokes ?? 0).toLocaleString('en-US')} form strokes from the goal.` });
      const report = { layer_id: details.layer_id ?? null, goal: { id: reference.id, sharpened: !!reference.sharpened, placed_by: goal.from,
        enlargement: Math.round(goalEnlargement(goal) * 100) / 100 }, ...done, ms,
        next: 'Look at the canvas; then paint_accents for the lights, glints, darks and lines.' };
      return { content: [...(result.content ?? []), json(report)], details: { ...(details as object), finish_report: report } };
    },
  }];
}

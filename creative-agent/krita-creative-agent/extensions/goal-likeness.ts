// Goal likeness: after each painting batch of an Agent move with a goal reference, the host measures how close the canvas
// is to the goal before and after it (src/goal-likeness.ts, on the plugin's blurred Lab grids). A batch that made it
// clearly less like the goal is undone through the pass review, as Luna's undo, and the painter is told what got worse
// and where. The cap is per move and shared with Luna review (UNDO_CAP undos in all), then the move stops for the artist.
// Measured, never undone: accents, the finish, colour transfers, layer settings, a departure the artist asked for; and every batch
// when the studio says measure only (Reference colours off, a message Luna could not classify) or the goal has no kept
// whole-picture transfer to protect (frame.protect). A project folder's element step is judged like any other batch once
// its goal is underpainted (the artist, 2026-10-23). Runs before Luna review, which skips a batch this undid or capped
// (host_undone).
// Luna's goal comparison (luna-goal-reviewer goal 1, src/goal-comparison.ts): when ΔE does not find the batch clearly worse
// and nothing exempts it, Luna compares the goal's crop with the canvas's before and after it. With Luna on Guide its
// "further" (good confidence) counts as clearly worse: the same undo, the same note and the same shared cap. With Evaluate
// it is recorded after the result (compared), never delaying the painter. Luna is not asked when its answer could not
// change what happens: ΔE already decided, an exemption, measure only, or no goal underpainting to protect.
// A shipped Pi extension registered inline (src/extensions.mjs). It knows the studio only through LikenessHost.
import type { ExtensionAPI, ToolResultEvent, ToolResultEventResult } from '@earendil-works/pi-coding-agent';
import type { BatchPass, Undone } from './luna-review.ts';
import { measure, clearlyWorse, describeWorse, exemption, type Grid, type Measure, type Exemption, type Rect } from '../src/goal-likeness.ts';
import { furtherFromGoal, describeFurther, type Comparison } from '../src/goal-comparison.ts';

export type LikenessMode = 'off' | 'measure' | 'protect';
export type GoalFrame = { goal: Grid; target: Rect; protect: boolean };
/** The move's undo counter, shared with Luna review (extensions/luna-review.ts). */
export type UndoCounter = { count(move: number): number; add(move: number): void };
export type LikenessRecord = { move: number; call_id: string; tool: string; status: 'kept' | 'undone' | 'worse_kept' | 'fallback';
  exempt?: Exemption; whole?: Measure['whole']; area?: Measure['area']; worse?: Measure['worse']; ms: number;
  undone_pass_ids?: string[]; partial?: boolean; reason?: string; summary?: string;
  luna?: Comparison; by?: 'delta_e' | 'luna' };       // Luna's goal comparison when it was asked; which check found it worse
export type ComparisonInput = { before: string; after: string; passes: BatchPass[]; measure: Measure; target: Rect };
/** What the studio provides (studio.mjs likenessHost). */
export interface LikenessHost {
  active(): LikenessMode;               // read on every call: the artist may change the setting between moves
  why?(): string | null;                // why this move is measured only, when active() is 'measure'
  undos?: UndoCounter;                  // shared with Luna review; a counter of this extension's own when absent
  move(): number | null;                // the Agent move in progress; null outside an Agent move
  painting(toolName: string): boolean;  // the paced painting tools
  frame(): Promise<GoalFrame | null>;   // the goal's grid and where it sits on the canvas; null without a goal
  grid(imagePath: string, target: Rect): Promise<Grid>;    // a canvas view's grid over the goal's target
  batch(toolCallId: string, toolName: string, input: Record<string, any>, details: any): BatchPass[];
  departure(): string | null;           // the artist's latest message asks to depart from the reference: its phrase
  undo(passes: BatchPass[]): Promise<Undone | null>;
  record(entry: LikenessRecord): void;
  stop(message: string): void;          // end the move after this turn
  lunaMode?(): 'off' | 'evaluate' | 'guide';   // the Decision checks setting, read on every call
  compare?(input: ComparisonInput): Promise<Comparison | null>;      // Luna's goal comparison of this batch (goal-comparison.ts)
  compared?(entry: { move: number; call_id: string; luna: Comparison }): void;   // Evaluate's comparison, after the result
}
/** Automatic undos per move: past this a worse batch is reported and the move stops, so a move is never undone empty. */
export const UNDO_CAP = 2;
const line = (value: Record<string, unknown>) => ({ type: 'text' as const, text: JSON.stringify({ goal_likeness: value }) });
const WHY: Record<Exemption, string> = { accents: 'accents are small by design',
  finish: 'the finish repaints the underpainting from the goal by design (the artist approved its look)', transfer: 'it is a colour transfer from a reference',
  departure: 'the artist asked for a change from the reference', layer_settings: 'it changes layer settings, not only paint' };
const UNPROTECTED = 'this chat has no kept whole-picture transfer of the goal to protect';
/** ΔE finds the batch clearly better (review, 2026-10-24): its changed area got closer to the goal by a just-noticeable
 * difference or more, or more of its cells got clearly better than clearly worse. Luna is not asked: never undone. */
const clearlyBetter = (m: Measure): boolean => m.area.change <= -1 || m.area.better_cells > m.area.worse_cells;
/** A comparison that could not be made (the host threw or had nothing): no verdict, never an undo. */
const FAILED: Comparison = { verdict: null, confidence: 0, crops: 0, per_crop: [], elapsed_ms: 0, cost: 0, input_tokens: 0, fallback: 'service_or_response_error' };

export default function goalLikeness(host: LikenessHost): (pi: ExtensionAPI) => void {
  const own = new Map<number, number>();
  const counter = (): UndoCounter => host.undos ?? { count: move => own.get(move) ?? 0, add: move => { own.set(move, (own.get(move) ?? 0) + 1); } };
  return pi => {
    pi.on('tool_result', async (event: ToolResultEvent): Promise<ToolResultEventResult | undefined> => {
      const toolName = (event as { toolName: string }).toolName;
      const mode = host.active(), move = host.move();
      if (event.isError || mode === 'off' || move === null || !host.painting(toolName)) return undefined;
      const details = ((event as { details?: unknown }).details ?? {}) as { image_path?: string; unguided_path?: string };
      const passes = host.batch(event.toolCallId, toolName, event.input, details);
      const after = details.unguided_path ?? details.image_path;
      if (!passes.length || !after) return undefined;
      const started = Date.now(), base = { move, call_id: event.toolCallId, tool: toolName };
      let m: Measure, frame: GoalFrame | null;
      try {
        frame = await host.frame();
        if (!frame) return undefined;
        const [b, a] = await Promise.all([host.grid(passes[0].before_path, frame.target), host.grid(after, frame.target)]);
        m = measure(frame.goal, b, a, frame.target);
      } catch (error) {                                   // a measurement must never fail a painting call
        host.record({ ...base, status: 'fallback', ms: Date.now() - started, reason: error instanceof Error ? error.message : String(error) });
        return undefined;
      }
      const measured = { ...base, whole: m.whole, area: m.area, worse: m.worse, ms: Date.now() - started };
      const exempt = exemption(toolName, event.input as Record<string, any>, { departure: host.departure() }) ?? undefined;
      const why = exempt ? WHY[exempt] : mode === 'measure' ? host.why?.() ?? 'the artist\u2019s Reference colours setting is off' : !frame.protect ? UNPROTECTED : null;
      let what: string, by: 'delta_e' | 'luna', luna: Comparison | undefined;
      if (clearlyWorse(m)) { what = describeWorse(m); by = 'delta_e'; }
      else {
        // ΔE keeps it: Luna's comparison may still find it further from the goal (structure, style), when that could count.
        const luna_mode = host.lunaMode?.() ?? 'off';
        const ask = (): Promise<Comparison> => Promise.resolve().then(() => host.compare!({ before: passes[0].before_path, after, passes, measure: m, target: frame!.target }))
          .then(c => c ?? FAILED).catch(() => FAILED);
        if (why || !host.compare || luna_mode === 'off' || clearlyBetter(m)) { host.record({ ...measured, status: 'kept' }); return undefined; }
        if (luna_mode === 'evaluate') {
          host.record({ ...measured, status: 'kept' });
          void ask().then(c => { if (c !== FAILED) host.compared?.({ move, call_id: event.toolCallId, luna: c }); });
          return undefined;
        }
        luna = await ask();
        if (!furtherFromGoal(luna)) { host.record({ ...measured, status: 'kept', luna }); return undefined; }
        what = describeFurther(luna); by = 'luna';
      }
      const found = { ...measured, by, ...(luna ? { luna } : {}) };
      if (why) {
        host.record({ ...found, status: 'worse_kept', ...(exempt ? { exempt } : {}), summary: what, reason: why });
        return { content: [...event.content, line({ note: `This batch made the canvas less like the goal image (${what}); it is kept because ${why}.`, ...m })] };
      }
      const undos = counter();
      if (undos.count(move) >= UNDO_CAP) {
        host.record({ ...found, status: 'worse_kept', summary: what, reason: 'undo cap' });
        host.stop(`The host undid ${UNDO_CAP} batches in this move; this one also made the canvas less like the goal (${what}).`);
        return { content: [...event.content, line({ note: `This batch made the canvas less like the goal image (${what}), but the host already undid ${UNDO_CAP} batches in this move, so this one stays. Stop here: the artist decides.`, ...m })],
          details: { ...details, host_undone: 'goal_likeness_cap' } };
      }
      const undone = await host.undo(passes).catch(() => null);
      if (!undone) {
        host.record({ ...found, status: 'worse_kept', reason: 'undo failed', summary: what });
        return { content: [...event.content, line({ note: `This batch made the canvas less like the goal image (${what}); it could not be undone. Repair it in the next batch.`, ...m })] };
      }
      undos.add(move);                                    // a partial undo counts too: the host acted on this batch
      const left = passes.map(p => p.id).filter(id => !undone.pass_ids.includes(id));
      host.record({ ...found, status: 'undone', undone_pass_ids: undone.pass_ids, ...(left.length ? { partial: true } : {}), summary: what });
      const reason = by === 'luna' ? what : `it made the canvas clearly less like the goal image, ${what}`;
      const note = (left.length
        ? `The host undid part of this batch: ${reason}. ${left.join(', ')} could not be undone; repair what remains. `
        : `The host undid this batch: ${reason}. `) + 'The attached image is the canvas now. '
        + 'Keep to the goal’s colours and values there: refine what the underpainting already has rather than repainting it, '
        + 'and if the artist wants a change from the reference, they say so.';
      return {
        content: [...event.content.filter(c => c.type !== 'image'), line({ note, undone_pass_ids: undone.pass_ids, ...m }), ...(undone.image ? [undone.image] : [])],
        details: { ...details, host_undone: 'goal_likeness', ...(undone.image_path ? { image_path: undone.image_path } : {}), ...(undone.revision ? { revision: undone.revision } : {}) },
      };
    });
  };
}

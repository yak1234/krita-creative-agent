// Luna review: after each painting batch of an Agent move, Luna compares the canvas before and after it
// (src/visual-checks.ts moveCheck): the pass artifacts, texture laid over forms, and focal features (protected
// areas, kept or proposed) covered. With Luna on Guide a batch with a finding is undone and the painter is told what
// was lost; at most UNDO_CAP times per move, then the move stops for the artist. Evaluate only records.
// A shipped Pi extension registered inline (src/extensions.mjs). It knows the studio only through ReviewHost.
import type { ExtensionAPI, ToolResultEvent, ToolResultEventResult } from '@earendil-works/pi-coding-agent';
import type { MoveCheckResult, MoveFinding } from '../src/visual-checks.ts';

export type LunaMode = 'off' | 'evaluate' | 'guide';
export type BatchPass = { id: string; before_path: string; title?: string; layer_id?: string; area?: number[] | null };
export type Verdict = { move: number; call_id: string; status: 'kept' | 'undone' | 'warned' | 'fallback';
  findings: MoveFinding[]; undone_pass_ids?: string[]; partial?: boolean; reason?: string; scope?: unknown };
type Image = { type: 'image'; data: string; mimeType: string };
export type Undone = { pass_ids: string[]; image?: Image; image_path?: string; revision?: string };
/** What the studio provides (studio.mjs reviewHost). */
export interface ReviewHost {
  mode(): LunaMode;                     // read on every call: the artist may change it between moves
  move(): number | null;                // the Agent move in progress; null outside an Agent move
  scope?(): unknown;                    // the chat this call belongs to, carried to review and record (a late verdict is dropped)
  painting(toolName: string): boolean;  // the paced painting tools
  batch(toolCallId: string, toolName: string, input: Record<string, any>, details: any): BatchPass[];   // painted passes, not layer settings
  canvas?(): string | undefined;        // the latest canvas image, for a batch whose result has none (it stopped early)
  features(): Promise<string[]>;        // kept and proposed protected-area names
  review(input: { before: string; after: string; features: string[]; scope?: unknown }): Promise<MoveCheckResult>;
  undo(passes: BatchPass[]): Promise<Undone | null>;
  record(verdict: Verdict): void;
  stop(message: string): void;         // end the move after this turn
}
/** Automatic undos per move: past this a finding is reported and the move stops, so Luna never undoes a move empty. */
export const UNDO_CAP = 2;

const lost = (findings: MoveFinding[]): string => findings.map(f => f.location ? `${f.label} (${f.location})` : f.label).join('; ');
const line = (review: Record<string, unknown>) => ({ type: 'text' as const, text: JSON.stringify({ luna_review: review }) });

export default function lunaReview(host: ReviewHost): (pi: ExtensionAPI) => void {
  const undos = new Map<number, number>();

  const check = async (move: number, callId: string, passes: BatchPass[], after: string, scope: unknown): Promise<Verdict> => {
    const base = { move, call_id: callId, ...(scope === undefined ? {} : { scope }) };
    try {
      const result = await host.review({ before: passes[0].before_path, after, features: await host.features(), ...(scope === undefined ? {} : { scope }) });
      if (!('findings' in result)) return { ...base, status: 'fallback', findings: [], reason: result.fallback };
      return { ...base, status: result.findings.length ? 'warned' : 'kept', findings: result.findings };
    } catch (error) {
      return { ...base, status: 'fallback', findings: [], reason: error instanceof Error ? error.message : String(error) };
    }
  };

  return pi => {
    pi.on('tool_result', async (event: ToolResultEvent): Promise<ToolResultEventResult | undefined> => {
      const toolName = (event as { toolName: string }).toolName;
      const mode = host.mode(), move = host.move();
      if (event.isError || mode === 'off' || move === null || !host.painting(toolName)) return undefined;
      const details = ((event as { details?: unknown }).details ?? {}) as { image_path?: string };
      const passes = host.batch(event.toolCallId, toolName, event.input, details);
      const after = details.image_path ?? host.canvas?.();
      if (!passes.length || !after) return undefined;
      const scope = host.scope?.();
      if (mode === 'evaluate') {                       // record only, never delay the painter
        void check(move, event.toolCallId, passes, after, scope).then(verdict => host.record(verdict)).catch(() => {});
        return undefined;
      }
      const verdict = await check(move, event.toolCallId, passes, after, scope);
      if (verdict.status !== 'warned') { host.record(verdict); return undefined; }
      const what = lost(verdict.findings);
      if ((undos.get(move) ?? 0) >= UNDO_CAP) {
        host.record(verdict);
        host.stop(`Luna undid ${UNDO_CAP} batches in this move; this one also has ${what}.`);
        return { content: [...event.content, line({ note: `Luna found ${what}, but it already undid ${UNDO_CAP} batches in this move, so this one stays. Stop here: the artist decides.`, findings: verdict.findings })] };
      }
      const undone = await host.undo(passes).catch(() => null);
      if (!undone) {
        host.record(verdict);
        return { content: [...event.content, line({ note: `Luna found ${what} in this batch; it could not be undone. Repair it in the next batch.`, findings: verdict.findings })] };
      }
      undos.set(move, (undos.get(move) ?? 0) + 1);       // a partial undo counts too: Luna acted on this batch
      const left = passes.map(p => p.id).filter(id => !undone.pass_ids.includes(id));
      host.record({ ...verdict, status: 'undone', undone_pass_ids: undone.pass_ids, ...(left.length ? { partial: true } : {}) });
      const feature = verdict.findings.find(f => f.feature)?.feature;
      const note = (left.length
        ? `Luna undid part of this batch: ${what}. ${left.join(', ')} could not be undone; repair what remains.`
        : `Luna undid this batch: ${what}.`)
        + ' The attached image is the canvas now. Reach the same goal another way: keep what already works and refine it.'
        + (feature ? ` If the ${feature} is in the way, propose_protection for it first.` : '');
      return {
        content: [...event.content.filter(c => c.type !== 'image'), line({ note, findings: verdict.findings, undone_pass_ids: undone.pass_ids }), ...(undone.image ? [undone.image] : [])],
        details: { ...details, ...(undone.image_path ? { image_path: undone.image_path } : {}), ...(undone.revision ? { revision: undone.revision } : {}) },
      };
    });
  };
}

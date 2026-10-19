// Seam check: seams baked into the painting (straight joins of pasted panels or upscaling tiles), confirmed by Luna.
// Every look carries the plugin's candidates (found once a chat) with a close-up of each (seams.py); this asks Luna about
// each close-up on the painter's first look and adds the confirmed ones to what it sees, so it repairs them before painting near them.
// A wash or stamp over a baked-in join keeps the line, and Luna's batch review then undoes it as a flat block
// (New Moscow, runs 10-13). The painter never sees an unconfirmed candidate. Follows the Luna setting: off, nothing.
// A shipped Pi extension registered inline (src/extensions.mjs). It knows the studio only through SeamHost.
import type { ExtensionAPI, ToolResultEvent, ToolResultEventResult } from '@earendil-works/pi-coding-agent';
import type { LunaMode } from './luna-review.ts';

export type SeamCandidate = { axis: 'h' | 'v'; at: number; from: number; to: number; step?: number; crop: string };
/** What the studio provides (studio.mjs seamHost). */
export interface SeamHost {
  mode(): LunaMode;
  confirm(candidates: SeamCandidate[]): Promise<(number | null)[]>;   // Luna's probability per close-up, null when unanswered
  record(entry: { candidates: number; confirmed: number; scores: (number | null)[] }): void;
}
/** Luna's probability from which a candidate is told to the painter (calibrated: no object edge above 0.05). */
export const SEAM_THRESHOLD = 0.5;
const NOTE = 'Seams baked into the painting: straight joins of pasted panels or tiles, in canvas pixels. Repair each before painting ' +
  'over or near it: low-opacity soft strokes or smudges across the join, short and varied, until it is gone. A wash, fill or stamp over ' +
  'it keeps the line and Luna undoes the batch as a flat block. Never select up to a seam either: extend the selection across it.';

export default function seamCheck(host: SeamHost): (pi: ExtensionAPI) => void {
  const asked = new Set<string>();                  // candidate sets already put to Luna: once a chat (crops live in the chat folder)
  return pi => {
    pi.on('tool_result', async (event: ToolResultEvent): Promise<ToolResultEventResult | undefined> => {
      if (event.isError || (event as { toolName: string }).toolName !== 'observe_canvas' || host.mode() === 'off') return undefined;
      const details = ((event as { details?: unknown }).details ?? {}) as { seam_candidates?: SeamCandidate[] };
      const candidates = details.seam_candidates ?? [];
      const key = candidates.map(c => c.crop).join('|');
      if (!candidates.length || asked.has(key)) return undefined;
      asked.add(key);
      let scores: (number | null)[];
      try { scores = await host.confirm(candidates); } catch { return undefined; }   // a hint must never fail a look
      const seams = candidates.filter((_, i) => (scores[i] ?? 0) >= SEAM_THRESHOLD)
        .map(c => ({ axis: c.axis === 'h' ? 'horizontal' : 'vertical', at: c.at, from: c.from, to: c.to }));
      host.record({ candidates: candidates.length, confirmed: seams.length, scores });
      if (!seams.length) return undefined;
      return { content: [...event.content, { type: 'text', text: JSON.stringify({ baked_in_seams: seams, note: NOTE }) }] };
    });
  };
}

// Painting weight: tells the painter what makes the painting heavy for Krita, from the `weight` every observation
// carries (krita-mcp painting_weight.py: layer metadata only). A painting with 147 groups and live noise-reducer filter
// masks made one observe take 909 s, and the painter only saw slow, failing calls. One line when the level rises, and
// one when a call was slow on a heavy painting, naming the likely cause. Never blocks. Registered inline (src/extensions.mjs).
import type { ExtensionAPI, ToolResultEvent, ToolResultEventResult } from '@earendil-works/pi-coding-agent';

export type Weight = { level: 'ok' | 'heavy' | 'too_heavy'; reasons: string[]; fixes: string[] };
/** A call slower than this on a heavy painting gets the cause named. */
export const SLOW_MS = 60_000;
const RANK = { ok: 0, heavy: 1, too_heavy: 2 } as const;
const FIXES: Record<string, string> = { merge_kept: 'merge kept moves', bake_filters: 'bake the filter masks', tidy: 'tidy leftover layers' };

export default function paintingWeight({ now = Date.now }: { now?: () => number } = {}): (pi: ExtensionAPI) => void {
  return pi => {
    let weight: Weight | null = null;
    let told = 0;                                        // the highest level the painter has heard about
    const causes = new Set<string>();                   // slow-call causes already named
    const started = new Map<string, number>();

    pi.on('tool_execution_start', event => { started.set(event.toolCallId, now()); });
    pi.on('tool_result', async (event: ToolResultEvent): Promise<ToolResultEventResult | undefined> => {
      const toolName = (event as { toolName: string }).toolName;
      const begun = started.get(event.toolCallId); started.delete(event.toolCallId);
      const details = ((event as { details?: unknown }).details ?? {}) as { weight?: Weight | null };
      if (details.weight?.level) weight = details.weight;
      if (!weight || weight.level === 'ok') return undefined;
      let line: string | null = null;
      if (RANK[weight.level] > told) {
        told = RANK[weight.level];
        const fixes = weight.fixes.map(f => FIXES[f] ?? f).join(', ');
        line = `This painting is ${weight.level === 'too_heavy' ? 'too heavy' : 'heavy'} for Krita: ${weight.reasons.slice(0, 2).join('; ')}. `
          + 'Every canvas refresh recomposites it, so calls can take minutes. Work in fewer, larger batches and do not add filter masks.'
          + (fixes ? ` Tell the artist they can ${fixes}.` : '');
      } else if (begun !== undefined && now() - begun > SLOW_MS && weight.reasons[0] && !causes.has(weight.reasons[0])) {
        causes.add(weight.reasons[0]);
        line = `That ${toolName} took ${Math.round((now() - begun) / 1000)} s: ${weight.reasons[0]}.`;
      }
      return line ? { content: [...event.content, { type: 'text', text: JSON.stringify({ painting_weight: line }) }] } : undefined;
    });
  };
}

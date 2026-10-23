// Ask when it may be done (after-the-underpainting goal 4). Two traced New Moscow chats: after an excellent
// whole-picture underpainting the next-layer decision (layer-need.mjs) fell from 0.97 to 0.12-0.22, spread over texture,
// accents and done (done 0.23-0.27), and the painter spent about 18 minutes inventing strokes on one head. When the
// decision ranks "done" in its top two, or is unsure (confidence under DONE_CONFIDENCE), the move ends after at most
// one painting call and the painter asks the artist what to work on next instead. Only after a whole-picture underpainting
// (the studio checks): before it, a thin decision is no reason to stop. Mechanism only: the studio decides
// which elements to offer and enforces the end of the move.

export const DONE_CONFIDENCE = 0.3;
// "done" in the top two counts only from this probability: a confident flat at 0.97 has done second at 0.008.
export const DONE_FLOOR = 0.15;

/** A next-layer check as layerNeedCheck returns it (or its fallback). */
export type NeedCheck = { need?: string; confidence?: number | null; probabilities?: Record<string, number> | null; fallback?: string };
/** done: "done" is the choice or the runner-up; unsure: no choice reaches DONE_CONFIDENCE. */
export type DoneReason = 'done' | 'unsure';

export function mayBeDone(check: NeedCheck | null | undefined): DoneReason | null {
  if (!check?.need) return null;
  if (check.need === 'done') return 'done';
  const probabilities = check.probabilities;
  if (probabilities && Number.isFinite(probabilities.done) && probabilities.done >= DONE_FLOOR) {
    // Top two: at most one other choice at or above it (a tie counts against done).
    const above = Object.entries(probabilities).filter(([need, p]) => need !== 'done' && Number.isFinite(p) && p >= probabilities.done).length;
    if (above <= 1) return 'done';
  }
  return typeof check.confidence === 'number' && check.confidence < DONE_CONFIDENCE ? 'unsure' : null;
}

/** What the painter is told: end the move and ask, offering `elements` (or the ones it sees) still lacking detail. */
export function askWhenDoneNote(reason: DoneReason, area: string, elements: readonly string[]): string {
  const why = reason === 'done' ? `ranks "done" among its top two choices for "${area}"` : `is unsure what "${area}" needs next`;
  const offer = elements.length ? `offering the elements still lacking detail (${elements.join(', ')})` : 'offering the elements you see still lacking detail';
  return `\nASK WHEN IT MAY BE DONE: Luna's next-layer check ${why}, so this area may already be as finished as the references allow. `
    + 'Do not invent detail. Paint at most one call for what the artist asked (or nothing, if it is already there), then call finish_move '
    + `and, in your reply, ask the artist what to work on next, ${offer}. The move ends after that one call.\n`;
}

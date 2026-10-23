// The underpainting move ends when the transfer finishes (crisp-accents goal 7, the artist's fix 1). Live chat 34deca0e:
// after a clean 39,918-stroke whole-picture transfer, the painter added about 177 typed strokes in the same move until
// the move's size limit stopped it, and Luna saw no regression in any batch. A move in which a whole-picture transfer
// (paint_from_reference over most of the canvas) completes is closed by the host there, as finish_move closes it: the
// folder plan's step 1, a reference-first first move, or any move that finishes one (a continuation included). A stopped
// transfer keeps the move open, and only continue_reference_painting of that job paints in it. This module recognises
// the job and words the rules; the studio decides what is whole (studio.mjs wholeTransfers) and keeps the state.
import { createHash } from 'node:crypto';

export type UnderpaintingState = { job: string; status: string; closed: boolean };

/** The reference job a transfer call paints (reference-tool.mjs: a new job's id is its call id's sha256), else null. */
export function transferJobId(tool: string, callId: string, args: { job_id?: unknown } = {}): string | null {
  if (tool === 'paint_from_reference') return createHash('sha256').update(callId).digest('hex').slice(0, 32);
  if (tool === 'continue_reference_painting' && typeof args?.job_id === 'string') return args.job_id;
  return null;
}

/** The move's underpainting after a transfer call: closed when a whole transfer completed. Null when it was not one. */
export function underpaintingState({ job, whole, status }: { job: string | null; whole: boolean; status: unknown }): UnderpaintingState | null {
  if (!job || !whole) return null;
  return { job, status: String(status ?? 'unknown'), closed: status === 'complete' };
}

/** Why a painting call may not run in this move, or null. */
export function underpaintingRefusal(state: UnderpaintingState | undefined | null, tool: string, args: { job_id?: unknown } = {}, move?: number): string | null {
  if (!state) return null;
  if (state.closed) return `Move ${move ?? ''} ended when the whole-picture underpainting completed: nothing more is painted in it. `
    + 'Stop now; the artist keeps it, undoes it or corrects it, and refining (accents, your own strokes) is the next move.';
  if (tool === 'continue_reference_painting' && args?.job_id === state.job) return null;
  return `This move’s underpainting stopped before it finished: continue it first with continue_reference_painting with job_id "${state.job}". `
    + 'The move ends when it completes; nothing else is painted in it.';
}

/** Appended to the transfer's result when it closes the move. */
export function closedNote(): string {
  return 'The whole-picture underpainting is complete, so the host closed this move here for the artist to keep, undo or correct. Stop now: no more painting in this move.';
}

/** Added to a move's instructions when its step is the whole-picture underpainting. */
export const UNDERPAINTING_MOVE_NOTE = 'UNDERPAINTING MOVE: the whole-picture transfer is this move, and the move ends when it completes (the host closes it); '
  + 'nothing else is painted in it, and refining comes in the next move.';

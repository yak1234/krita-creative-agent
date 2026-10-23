// Reference first: when the artist attaches a goal reference, an Agent move starts from the reference's colours.
// A live chat with final_goal.png and "trace the outline" (a small Qwen painter) drew decent guides, then flat-filled
// them as grey blocks, painted the moon dark and never used the reference tools; the skills that say how were only
// listed for it to read. Until the chat has a reference colour pass, and while the artist's reference_first setting
// is on (settings-schema.mjs), the studio (studio.mjs) puts these skills into the chat's moves and nudges the first
// flat fill of a move. The reference tools themselves (reference-tool.mjs) are unchanged.
//
// Only paint_from_reference lays the reference's colours: paint_reference_surface smudges the paint already on the
// canvas, and paint_reference_edges sharpens it. So "transfer" below says whether a whole transfer would be accepted
// now (the studio asks transferRefusal, reference-tool.mjs); where it would be refused (an established painting, or a
// transfer that ran and was undone), the text points to surface and edges over what is there, never to another transfer.
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';

/** The skills a move gets: lay the colours. Guides are not a default (the artist, 2026-10-23: traced lines were
 * distracting next to the solid underpainting); guided-trace comes only with a request for guides (/trace). */
export const REFERENCE_FIRST_SKILLS = ['reference-transfer'] as const;

const NUDGE_START = 'This painting has a reference.';
const NUDGE_END = 'Call fill_region again if a flat fill is really intended.';

/** The tool result of a move's first fill_region before any reference colour pass. The next fill runs. */
export function fillNudge(transfer: boolean): string {
  return NUDGE_START + (transfer
    ? ' Lay its colours first with paint_from_reference (the whole picture on a fresh canvas), then refine; '
    : ' Bring its colours in with paint_reference_surface and paint_reference_edges over the paint already there, plus your own strokes, then refine; ')
    + 'guides show where things go and are not shapes to fill flat. ' + NUDGE_END;
}

/** A tool error that is the nudge, not a failure (the panel words it calmly). */
export function isFillNudge(text: string | undefined): boolean {
  return !!text && text.includes(NUDGE_START) && text.includes(NUDGE_END);
}

/** The move's batch guidance for masses, in place of "lay it in with fill_region". */
export function massGuidance(transfer: boolean): string {
  return 'This chat has a goal reference and no reference colour pass yet: ' + (transfer
    ? 'lay the sky, background and large masses from the reference first with paint_from_reference (the whole picture on a fresh canvas), then refine'
    : 'a whole transfer is not available here, so bring the reference\'s colours into the masses with paint_reference_surface and paint_reference_edges over the paint already there, plus your own strokes')
    + '; use fill_region only for flat design areas.';
}

export type Reference = { role?: string; purpose?: string; part_kind?: string };

/** A goal or general reference: an attached picture (not an asset, a construction map or a cut-out part) that the
 * painting should look like. Palette, likeness and material references guide one aspect, not the whole picture. */
export function hasGoalReference(references: readonly Reference[] | undefined): boolean {
  return (references ?? []).some(r => (r.role ?? 'reference') === 'reference' && !r.part_kind
    && ['general', 'composition'].includes(r.purpose ?? 'general'));
}

export type Job = { id?: string; completed?: number; recipe?: { mode?: string }; scope?: string | null };

// As reference-tool.mjs sameScope: a job belongs to a plan revision.
function sameScope(job: Job, revision: unknown): boolean {
  const known = revision !== undefined && revision !== null;
  if ((job.scope ?? null) === (known ? JSON.stringify([revision]) : null)) return true;
  try { return known && JSON.parse(job.scope ?? 'null')[0] === revision; } catch { return false; }
}

/** The transfers (paint_from_reference jobs, no mode) of this plan revision that painted, as reference-tool.mjs counts
 * them for its refusals: an undone one included, since its job file stays. Jobs are saved in the chat's folder. */
export async function paintedTransfers(directory: string, { revision }: { revision?: unknown } = {}): Promise<Job[]> {
  let names: string[];
  try { names = await readdir(join(directory, 'reference-paintings')); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return []; throw error; }
  const jobs: Job[] = [];
  for (const name of names.filter(n => /^[a-f0-9]{32}\.json$/.test(n))) {
    try {
      const job = JSON.parse(await readFile(join(directory, 'reference-paintings', name), 'utf8')) as Job;
      if ((job.completed ?? 0) > 0 && !job.recipe?.mode && sameScope(job, revision)) jobs.push({ ...job, id: job.id ?? name.slice(0, 32) });
    } catch { /* a job being written: the next check reads it */ }
  }
  return jobs;
}

/** A reference colour pass: a painted transfer whose move the artist did not undo (undone: those job ids). */
export async function referenceColourPassMade(directory: string, { revision, undone = new Set<string>() }: { revision?: unknown; undone?: ReadonlySet<string> } = {}): Promise<boolean> {
  return (await paintedTransfers(directory, { revision })).some(job => !undone.has(job.id ?? ''));
}

/** What the move adds: the skills in full (once a chat, and again after an Undo of its colour pass), else a one-line
 * reminder. Each skill at most once, and none the artist's message already expanded (/colour). */
export function referenceFirstContext(text: string, skillBlock: (name: string) => string, { transfer = true, full = true }: { transfer?: boolean; full?: boolean } = {}): string {
  const lead = '\nREFERENCE FIRST (the artist\'s setting): this chat has a goal reference and no reference colour pass yet. '
    + (transfer ? 'Lay the reference\'s colours first with paint_from_reference' : 'Bring the reference\'s colours in with paint_reference_surface and paint_reference_edges over the paint already there')
    + ', then refine in your own strokes. Draw guides only when the artist asks for them.';
  if (!full) return lead + ' Follow the reference-transfer skill given earlier in this chat.\n';
  const blocks = REFERENCE_FIRST_SKILLS.filter(name => !text.includes(`<skill name="${name}"`)).map(skillBlock);
  return lead + (blocks.length ? ' Follow these skills:\n' + blocks.join('\n') : '') + '\n';
}

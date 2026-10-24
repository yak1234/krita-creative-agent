// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// What an element step may use (openspec element-scoped-painting; the artist, 2026-10-24). In the live chat 385b4a4f the
// artist named "Moonlit sky"; the painter selected three times, split the canvas by colour, made a material and sent typed
// paint_batch strokes that the typed-stroke cap refused. An element step has one good sequence: a scoped reference transfer
// of the goal inside the element's area (the underpainting engine, only the dabs inside it), then paint_finish and
// paint_accents in the area (finish-stage, 2026-10-24: the finish between them, as on the whole picture). After the
// whole-picture Finish (finish-stage goal 6, the artist 2026-10-24: "yess we need both"; on New Moscow every refine move
// called paint_accents alone, which found nothing at the reduced view while the church stayed blobby at full size) the
// part is not underpainted again: paint_finish with detail fine in the area (2-4 px strokes from the goal), then paint_accents.
// In an element step the studio (studio.mjs) refuses, before anything runs:
//   - split_by_color, and selections made from colour (a magic-wand seed, a colour range; bucket_fill's "similar" mode),
//   - make_material and stamp_material,
//   - typed strokes (paint_pass, painting_toolbox marks, paint_contours, paint_recipe; inside a paint_batch too),
// unless the artist's latest message asks for that kind of work. The refusal points to the scoped transfer and accents.
// Mechanism only: the studio decides what an element step is; this module imports no .mjs.
import { typedMarks, handPaintingRequested } from './typed-strokes.ts';

export type Call = { tool: string; args?: Record<string, unknown> };
export type Kind = 'colour_split' | 'colour_selection' | 'material' | 'typed_strokes' | 'whole_refine';

const record = (value: unknown): Record<string, unknown> => (value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {});
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

/** Selection steps that pick pixels by colour: a seed (magic wand) or a colour (colour range). */
const colourSteps = (steps: unknown): boolean => list(steps).some(step => { const s = record(step); return s.seed !== undefined || s.color !== undefined; });

/** The kinds of element-step trouble one call (or one batch action) holds. */
export function callKinds({ tool, args = {} }: Call): Kind[] {
  const kinds = new Set<Kind>();
  if (tool === 'split_by_color') kinds.add('colour_split');
  // refine_to_goal with no box: the whole picture (or the Paint only here area, when it is set: elementStepRefusal).
  if (tool === 'refine_to_goal' && !record(args.area).box) kinds.add('whole_refine');
  if (tool === 'make_material' || tool === 'stamp_material') kinds.add('material');
  if (tool === 'select' && colourSteps(args.steps)) kinds.add('colour_selection');
  // A selection given inline to a fill, a filter or a tool (area, enclose_area), and the fill tool's similar-colour mode.
  if (tool !== 'select' && (colourSteps(args.area) || colourSteps(args.enclose_area))) kinds.add('colour_selection');
  if (tool === 'bucket_fill' && record(args.options).mode === 'similar') kinds.add('colour_selection');
  if (tool === 'paint_batch') for (const action of list(args.actions)) {
    const a = record(action);
    for (const kind of callKinds({ tool: String(a.tool), args: record(a.arguments) })) kinds.add(kind);
  } else if (tool !== 'stamp_material') {
    const marks = typedMarks({ tool, args });
    if (marks && (marks.marks > 0 || marks.broad.length)) kinds.add('typed_strokes');
  }
  return [...kinds];
}

const ASKED: Record<Kind, RegExp> = {
  colour_split: /\bsplit\w*\b[^.!?\n]{0,30}\bcolou?rs?\b|\bcolou?r[- ]split/i,
  colour_selection: /\bmagic[- ]?wand\b|\bwand\b|\bcolou?r (?:range|selection|select)\b|\bselect\w*\b[^.!?\n]{0,30}\bby colou?r\b|\bsimilar colou?r/i,
  material: /\bmaterials?\b|\bstamp\w*\b/i,
  typed_strokes: /$^/,                                   // handPaintingRequested decides
  whole_refine: /$^/,                                    // never in an element step: the part is refined in its area
};
const NOT = /\b(?:no|not|don['’]?t|do not|never|without|stop|avoid)\b[^.!?\n]{0,30}$/i;
/** Whether the artist's message asks for this kind of work (a refusal of it does not). */
export function askedFor(kind: Kind, text: string): boolean {
  const said = String(text ?? '');
  if (kind === 'typed_strokes') return !!handPaintingRequested(said);
  const found = ASKED[kind].exec(said);
  return !!found && !NOT.test(said.slice(0, found.index));
}

const WHAT: Record<Kind, string> = {
  colour_split: 'split_by_color', colour_selection: 'a selection made from colour (a magic wand or a colour range)',
  material: 'materials (make_material, stamp_material)', typed_strokes: 'typed strokes', whole_refine: 'refine_to_goal over the whole picture',
};
/** The sequence for one part: with its area set or not, before or after the whole-picture Finish (`finished`). */
export function refineSequence({ area, finished = false }: { area: boolean; finished?: boolean }): string {
  if (finished) return area
    ? 'paint_finish with detail "fine" in the area (it works there by default: 2-4 px strokes from the goal; for an area of more than 15% of the canvas, refine_to_goal instead, which works in it by default), then paint_accents, which works in the area by default'
    : 'ask the artist for its area (ask_for_selection), then paint_finish with detail "fine" in it, then paint_accents there';
  return area
    ? `paint_from_reference of the goal image, the whole goal over the whole canvas: only the dabs inside the area are painted; then paint_finish and paint_accents, which work in the area by default`
    : `ask the artist for its area (ask_for_selection), then paint_from_reference of the goal image inside it, then paint_finish and paint_accents there`;
}

/** Why this call is refused in an element step, or null. `part` names the element ("Moonlit sky"); `area` says whether
 * its Paint only here area is set; `finished` whether the whole picture has had its Finish. `handPainting`, when known, is
 * whether the artist's latest message asked for hand-painted work as the studio read it (Luna's reading, else the phrases:
 * luna-goal-reviewer goal 2); it decides typed strokes. */
export function elementStepRefusal(call: Call, { part, area, request, finished = false, handPainting }: { part: string; area: boolean; request: string; finished?: boolean; handPainting?: boolean }): string | null {
  const refused = callKinds(call).filter(kind => !(kind === 'typed_strokes' && handPainting !== undefined ? handPainting : askedFor(kind, request))
    && !(kind === 'whole_refine' && area));
  if (!refused.length) return null;
  const sequence = refineSequence({ area, finished });
  return `Nothing was painted: ${refused.map(kind => WHAT[kind]).join(' and ')} ${refused.length > 1 ? 'are' : 'is'} not used in an element step `
    + `(${part}) unless the artist asks for it. Paint the element with ${finished ? 'the fine finish and accents' : 'the scoped transfer, the finish and accents'} instead: ${sequence}.`;
}

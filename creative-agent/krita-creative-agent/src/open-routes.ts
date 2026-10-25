// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Open routes: one line in each Agent move's context saying which painting routes the host allows now and which it will
// refuse, and why. In the artist's chats of 2026-10-23/24 about 25 calls in 10 chats were refused by rules that overlap
// (a flat fill while reference first holds, typed strokes over the cap after the underpainting, a second unify pass,
// live filter masks, the artist's layers, a whole transfer late in the plan), and the painter found the allowed route one
// refusal at a time. The studio (studio.mjs openRoutes) computes the state once per move from the same checks the calls
// meet; this module only words it. Mechanism only, no I/O.

export type RouteState = {
  /** Reference first holds: the move's first fill_region is answered with the reference tools (studio.mjs fillNudge). */
  fillNudge: boolean;
  /** Why a whole-canvas paint_from_reference would be refused now (reference-tool.mjs transferRefusal), or null. */
  wholeTransfer: string | null;
  /** Why a patch transfer (a region of at most 20% of the canvas) would be refused now, or null. */
  patchTransfer: string | null;
  /** The typed-stroke cap after the underpainting (typed-strokes.ts), or null when it does not hold this move. */
  typedCap: { marks: number; px: number } | null;
  /** What used the chat's one whole-canvas softening pass (unify-pass.ts), or null when it is still free. */
  unifyUsed: string | null;
  /** An Agent move adds no live filter masks or filter layers (studio.mjs callNative). */
  liveFilters: boolean;
};

/** "(off from step 3 of 3)": the first clause of a refusal, short enough for the line. */
function why(refusal: string): string {
  const off = /off from step \d+ of \d+/.exec(refusal)?.[0];
  if (off) return off;
  if (/already exists/.test(refusal)) return 'the painting already exists';
  if (/already has a reference transfer/.test(refusal)) return 'this plan already has one';
  if (/not known yet/.test(refusal)) return refusal;
  return refusal.split(/[.:;]/)[0].slice(0, 90);
}

export function openRoutesLine(state: RouteState): string {
  const allowed: string[] = [], not: string[] = [];
  (state.wholeTransfer ? not : allowed).push('a whole-canvas paint_from_reference' + (state.wholeTransfer ? ` (${why(state.wholeTransfer)})` : ''));
  (state.patchTransfer ? not : allowed).push('paint_from_reference on a region of at most 20% of the canvas' + (state.patchTransfer ? ` (${why(state.patchTransfer)})` : ''));
  allowed.push('paint_reference_surface and paint_reference_edges on an area', 'paint_finish', 'paint_accents');
  if (state.fillNudge) not.push('fill_region before a reference colour pass (the host answers it with the reference tools)');
  else allowed.push('fill_region');
  if (state.typedCap) not.push(`typed strokes over ${state.typedCap.marks} small marks a call or wider than ${state.typedCap.px} px (the whole-picture underpainting is down; the artist lifts this by asking for hand-painted work)`);
  else allowed.push('typed strokes (paint_pass, paint_contours, stamp_material)');
  if (state.unifyUsed) not.push(`another whole-canvas softening pass (${state.unifyUsed} used the chat's one; soften an element or a region instead)`);
  else allowed.push('one whole-canvas softening pass');
  if (state.liveFilters) not.push('apply_filter as a live mask or filter layer (use mode copy)');
  not.push("the artist's own layers are never filtered or repainted (clip to them, clone them or select from them)");
  return `OPEN ROUTES this move (the host's own checks, made now; a call outside them is refused):\nAllowed now: ${allowed.join('; ')}.\nNot now: ${not.join('; ')}.`;
}

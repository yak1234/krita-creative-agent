# Luna as a goal-aware reviewer and a reader of the artist's messages

Status: APPROVED by the artist (2026-10-23: "1 and 2 build after paint here lands"). Builds after Paint only here.

## Why

On 2026-10-23 Luna's move review reported "no regressions" while hand strokes damaged a finished underpainting: it
judges how strokes look (flat blocks, stripes, ellipses), never whether the painting moved away from the goal. The
colour check (goal-likeness, CIE ΔE on a coarse grid) catches colour drift but not structure or style damage (blobs in
the right colour). Element names in the artist's messages are matched by keywords, which added and painted elements on
"don't paint the sky" or "the light is too harsh" until a negation patch.

## Goals

1. **Goal comparison.** After each painting batch with a goal reference, Luna sees the reference crop and the canvas
   crops before and after the batch (same area, same scale) and answers one question: is the after-crop closer to the
   reference than the before-crop (choice: closer / same / further, with confidence)? "Further" with good confidence
   counts as clearly worse alongside the ΔE rule, under the same exemptions (artist departures, accents, element steps
   only with a goal underpainting) and the shared per-move undo cap. Recorded on the move card and in lessons.
2. **Reading the artist's messages.** One Luna decision on each typed message (any language) replaces keyword
   matching: is it about one part of the picture (and which element, if a folder names elements), is it a change from
   the reference or a return to it, is it a negation ("don't", "leave alone"), does it ask for hand painting? Answers
   drive: adding/targeting element steps, asking for Paint only here when a part is named without a selected area,
   departures, the typed-stroke exemption. The keyword rules stay as the offline fallback; when Luna is off or
   unsure, the host does nothing irreversible (no step added, no undo).

## Non-goals

- Luna never paints and never decides alone to restart or repaint; it judges and routes.
- No new model or provider; the existing decision client and its consent/cost settings.

## Done when

On a copy of New Moscow: a hand-stroke batch that blobs the underpainting in the right colours is undone by the goal
comparison; "don't paint the sky", "leave the towers alone", "the light is too harsh" add nothing; "work on the Kremlin
towers" and a French or German equivalent target the towers; "paint the sky" without a selection asks for Paint only
here. Costs and latency per batch measured.

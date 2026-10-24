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

3. **Sharper eyes** (the artist, 2026-10-24; both models have ~1M-token windows, so size is about speed/cost, not
   space). The painter's observe view grows from about 1024 px to up to 2048 px on the long side, and Luna's goal
   comparison uses 1:1 crops (canvas pixels, the batch's area; several crops when the area is larger than one crop).
   Not assumed, measured: many vision models shrink large images internally, so a resolution probe per model
   (a synthetic image with fine detail — small numbers and dot counts — at 1024/1536/2048/2560 px and as 1:1 crops)
   finds the size each model actually reads; the view size is set to the smallest size that keeps the detail, and a
   larger view is not sent where the model would throw it away. Latency and cost per call are measured and reported.

## Non-goals

- Luna never paints and never decides alone to restart or repaint; it judges and routes.
- No new model or provider; the existing decision client and its consent/cost settings.

## Done when

On a copy of New Moscow: a hand-stroke batch that blobs the underpainting in the right colours is undone by the goal
comparison; "don't paint the sky", "leave the towers alone", "the light is too harsh" add nothing; "work on the Kremlin
towers" and a French or German equivalent target the towers; "paint the sky" without a selection asks for Paint only
here. Costs and latency per batch measured.

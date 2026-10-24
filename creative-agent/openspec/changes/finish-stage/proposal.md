# Finish: the stage that turns the underpainting into a finished painting

Status: APPROVED by the artist (2026-10-24: "yes please 1,2 then 3"; the offline spike judged first, its before/afters
sent the same night). Fixes 4-5 approved earlier the same night ("yes" to sharpening any attached goal).

## Why

On New Moscow the whole-picture underpainting matches the goal (goal likeness ΔE 1.7) yet still reads as an
underpainting: every area is the same small round dabs, the sky is confetti, buildings have ragged edges. Accents add
lights and darks only, hand strokes are capped small, so chat "Creative painting 22" spent 20 passes changing nothing
visible (mean change 1.7/255 on the left buildings). A finished painting treats areas differently: soft, blended
atmosphere; crisp, form-following strokes on the subject; sharp highlights last.

## Goals

1. **Blend the soft areas.** Where the goal has little structure (sky, mist, water), the canvas's own pixels are
   smoothed by an edge-preserving filter so the dabs melt into gradients while edges stay.
2. **Repaint the hard areas** (buildings, towers, bridge) with strokes that follow the form (structure-tensor field of
   the goal), coloured from the goal, each ending where the goal's colour changes. Never along outlines (no tracing).
   Uses the sharpened goal when there is one.
3. **Order:** underpainting -> finish -> accents. The default folder plan gains the Finish step between them.
4. **Sharpen any goal**, not only a project folder's: an attached goal enlarged more than 2x gets the same Sharpen card.
5. **Say so instead of inventing strokes:** when the artist asks to refine an area the canvas already matches at the
   goal's resolution and the goal is not sharpened, the painter says the goal has no more detail there and offers
   Sharpen.

## Spike (offline, 2026-10-24, scratchpad finish/finish.py)

On a copy of the 6000x4500 canvas with the 4x-sharpened goal: soft mask from the goal's gradient magnitude blurred
(sigma 40 px), soft where under 0.014 (ramp 0.006); self-guided filter r 10, eps 0.004; strokes 5-9 px wide,
10-34 px long, seeds every 4 px, end at Lab distance 26. 1.28 M strokes in 93 s (OpenCV), blur 1.5 s; difference to
the goal 7.1 -> 4.6. The artist judged the before/afters.

## Non-goals

- No live filter masks (they stalled New Moscow before); everything is baked into plain paint layers.
- No change to the artist's own layers.

## Done when

Live in Toska on a copy of New Moscow: underpainting -> Finish -> accents gives a picture comparable to the spike, in
a few minutes, the panel shows progress, Undo removes it, Paint only here limits it.

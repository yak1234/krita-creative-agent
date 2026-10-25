---
name: canvas-reference
description: Paint toward a canvas reference the artist approved (/canvas-edit-ref): an image model's picture of the canvas with one change (more ghosts, ghost-like light, more snow), used as the move's target only where it differs from the canvas. Use when the move's instructions name a CANVAS REFERENCE.
---

# Canvas reference

The artist typed `/canvas-edit-ref <change>` (or a plan's Add step previewed itself). An image model made the
canvas as it would look with that change, the artist saw it beside the canvas and pressed **Use as the target**.
The host measured where the picture differs from the canvas and set that as the move's Paint only here area:
Krita blocks every write outside it, so faces, figures and everything the change does not touch stay as painted.

The reference is a target, never pixels: it is never pasted into the painting.

1. `paint_from_reference` with the reference id, source the whole reference and target the whole canvas (the
   move's instructions give the exact arguments). Only the dabs inside the area are painted, so the transfer
   brings the change and nothing else.
2. `paint_accents` in the area: the reference's crisp lights, darks and edges (snow highlights, a ghost's glow).
3. Look at the canvas. If a part of the change is still missing inside the area, paint it with the reference
   tools again (a smaller target over that part, its source the same rectangle of the reference scaled to it).
4. `finish_move`.

Do not use `refine_to_goal` for this: its goal is the plan's picture, not the reference. Do not try to paint
outside the area; to change more, the artist makes another canvas reference.

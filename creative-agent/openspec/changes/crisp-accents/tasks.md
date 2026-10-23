# Crisp accents: tasks

## 1. Accents and tracing removed — branch agent/accents
- [ ] 1.1 Plugin: accent finder (lights, glints, darks from local contrast; lines from trace_edges interior structure chains), bounded like trace_edges
- [ ] 1.2 Companion: paint_accents (area, kinds, count, strength), colour by role, sizes, strongest first, cap; one accents layer per move; skip where the canvas no longer resembles the reference; never in protected areas; >150 asks first; exempt from the 2x stretch limit
- [ ] 1.3 Remove visible tracing: draw_guide from_reference, traced block-in, /trace and its menu entry, guided-trace tracing guidance; keep hand lines/perspective on request; update sharper-guides/element-shapes specs and layer-need accents hint
- [ ] 1.4 Painter guidance: stage two is accents
- [ ] 1.5 Tests; New Moscow copy + portrait + landscape renders; timings

## 2. Protect the underpainting — branch agent/protect-underpainting
- [x] 2.1 The underpainting move ends when the whole transfer completes (host-enforced)
- [x] 2.2 Goal-likeness check before/after every batch; clearly worse batches undone by the host with a message; accents and artist-requested departures exempt from undo
- [x] 2.3 Tests incl. a replay of chat 34deca0e's shape (transfer then hand strokes)

Builder's notes (section 2): `underpainting-move.ts` closes an Agent move when a whole-picture transfer (over 60% of the
canvas) completes in it, and refuses every later painting call in that move; a stopped transfer may only be continued.
`goal-likeness.ts` + `extensions/goal-likeness.ts` measure each Agent batch on the plugin's `likeness_grid`
(`goal_likeness.py`: the goal's crop and the same canvas area, 64 cells on the long side, blurred one cell, CIE Lab;
CIE76 delta E in the companion). Clearly worse = the cells made 6 or more worse, net of those made 6 or more better,
reach 0.65% of the grid (20 of 3072 cells); or the changed cells' mean rose by 4 over at least 16 cells; or the whole
canvas's by 1. The tail rule is what catches 34deca0e's move 2 (mean +1.1, net 49 cells); normal brushwork over the
same view stays at 12 or less. A transfer is measured from the view before it and recorded, never undone. Undone through
the pass review; the cap (2 a move) is shared with Luna's review, then the move stops. Undone only when the chat has a
kept, completed whole transfer of a goal reference (the most recent one places the goal) or the goal is the project
folder's. Measured, never undone: `paint_accents`, colour transfers, batches with a layer setting, folder element steps,
Reference colours off, and departures. A departure holds until a later artist message points back to the reference;
phrases decide first (additions, recolouring, "make it ...", atmosphere, grade, style, "than the reference"), then Luna
classifies the message (any language); with Luna off or unanswered the move is measured only. About 10-25 ms a batch
(one plugin call of about 5-9 ms when the view before is cached).

## 3. Release
- [ ] 3.1 Reviews, merge, CI, publish, package, install; live check on a copy of the New Moscow folder

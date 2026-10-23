# Crisp accents: tasks

## 1. Accents and tracing removed — branch agent/accents
- [ ] 1.1 Plugin: accent finder (lights, glints, darks from local contrast; lines from trace_edges interior structure chains), bounded like trace_edges
- [ ] 1.2 Companion: paint_accents (area, kinds, count, strength), colour by role, sizes, strongest first, cap; one accents layer per move; skip where the canvas no longer resembles the reference; never in protected areas; >150 asks first; exempt from the 2x stretch limit
- [ ] 1.3 Remove visible tracing: draw_guide from_reference, traced block-in, /trace and its menu entry, guided-trace tracing guidance; keep hand lines/perspective on request; update sharper-guides/element-shapes specs and layer-need accents hint
- [ ] 1.4 Painter guidance: stage two is accents
- [ ] 1.5 Tests; New Moscow copy + portrait + landscape renders; timings

## 2. Protect the underpainting — branch agent/protect-underpainting
- [ ] 2.1 The underpainting move ends when the whole transfer completes (host-enforced)
- [ ] 2.2 Goal-likeness check before/after every batch; clearly worse batches undone by the host with a message; accents and artist-requested departures exempt from undo
- [ ] 2.3 Tests incl. a replay of chat 34deca0e's shape (transfer then hand strokes)

## 3. Release
- [ ] 3.1 Reviews, merge, CI, publish, package, install; live check on a copy of the New Moscow folder

---
name: repaint-area
description: Repaint, regrade or relight an area already on the canvas (a sky behind buildings, lit windows, a street to darken, a wall, a coat) with Krita's selections, fill layers and filter masks instead of stroke passes. Use when the area exists and should change while everything around it stays.
---

# Repaint an existing area

## Refine or replace

Decide first. "Finish", "soften", "add light to", "give volume to" mean **refine**: the area already has form worth
keeping (cloud shapes, a moon, a face), so add to it on clipped layers at low opacity, or grade it with a filter mask,
and never fill over it. "Repaint", "replace", "change the sky to" mean **replace**: fill or regrade the selection.
When unsure, refine: it can be undone layer by layer, and a flat fill over good forms destroys them.

The rule: select the area with Krita, change it with a fill or a filter, and keep strokes for texture on top.
Never measure an outline from close-ups, and never cover an area with a stroke pass.

## 1. Select it

- **One connected area** (the sky between towers, a wall): `select` with a seed step, one point inside it:
  `{seed: [x, y], tolerance: 24-40}`. It stops at every edge. Add `bounds` to keep it out of a similar colour
  elsewhere.
- **Several areas of one colour** or an unclear edge: `split_by_color` on `"visible"` (or a `region`), then pick
  the saved selection whose colour and share match the area (the largest blue near the top is the sky).
- Combine with `select` steps: `{saved: "Split 1 1a2440"}` plus `mode: add` for a second region, or subtract
  a subject. Feather about 1-2% of the area's smaller side so the change blends.

## 2. Change it

First propose_protection for any focal feature inside the area (the moon, a figure), named; Luna checks it after the batch.

- **Repaint a sky:** `sample_canvas_colors` at the top and at the horizon first, then `fill_region` with
  `selection` = the saved sky and a linear `gradient` from the top colour to the horizon colour, on a new layer
  with `clip_base: true`. (Over a plain rectangular band, `create_layer` `type: fill` gives a live gradient.) Clouds: `paint_recipe` on a layer with `clip_to`
  that sky layer, `blend_mode: soft_light` or `overlay`, `layer_opacity` 0.3-0.5. Soften with an `apply_filter`
  blur as a mask (`mode: copy` in an Agent move).
- **Refine with the area's own texture** (volume in clouds, foam on water, a foliage mass): `make_material`
  `kind: light` from the area's selection, then `stamp_material` into the same selection, 300-800 dabs at low
  opacity, `tint` toward the light. The tips are cut from the painting itself, so the new paint keeps its
  texture; follow with strokes for crisp edges.
- **Make windows glow:** `split_by_color` on the building's `region` with 12-16 colours, or `select` with
  `color` steps at the window colour; `fill_region` a warm light colour in that selection on a new layer with
  `blend_mode: add` or `screen`; `set_layer` style `outer_glow` on that layer.
- **Darken a street:** select the street (seed, or the split region), then `apply_filter` with a curves or
  HSV filter as a `mask` on your layer covering it (`mode: copy` in an Agent move), or a `fill_region` in a dark colour, `blend_mode:
  multiply`, `opacity` 0.3-0.6. Lights stay crisp: subtract them from the selection.

## 3. Check

`observe_canvas` once. Look at the seams where the area meets what stays: a hard edge wants more feather, a
halo wants less tolerance. Fix with `set_layer` opacity or a new selection, not by painting over.

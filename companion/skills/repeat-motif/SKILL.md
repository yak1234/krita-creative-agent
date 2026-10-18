---
name: repeat-motif
description: Repeat or mirror a painted motif (lamp posts, windows, trees, fence posts) or make a reflection, with Krita's clone layers, transform masks and menu actions instead of painting each copy. Use when the same shape appears more than once or is reflected.
---

# Repeat a motif

Paint the motif once, on its own layer, then let Krita copy it.

1. **One motif, one layer:** paint the first lamp post (or window, tree) on its own layer, finished.
2. **Copies that follow it:** `clone_layer` with `source` = that layer and `offset: [dx, dy]` for each copy
   ("Lamp post 2" at `[400, 0]`). A clone follows later edits to the first one, so finish details once.
3. **Size and perspective:** `transform_layer` on a clone (`scale` below 1 for a farther post, `move` to
   place it). Farther copies also get a low-opacity fog fill clipped to them.
4. **Mirrored:** `transform_layer` with `scale [-1, 1]` on a clone keeps the original too; `krita_action`
   `mirrorNodeX` (or `mirrorNodeY`) flips one of your paint layers itself. `krita_capabilities` lists the
   actions this Krita offers.
5. **Reflection in water or a wet street:** `clone_layer` the motif, `transform_layer` with `scale [1, -1]` (a negative
   factor flips) and `move` to put it below the base line, `opacity` 0.3-0.5, then `apply_filter` a blur as a `mask` on the
   clone. Ripples: a horizontal `paint_recipe` clipped to the reflection in `overlay`.
6. **Vary them:** identical copies look stamped. Change opacity, scale or a few accents per copy.

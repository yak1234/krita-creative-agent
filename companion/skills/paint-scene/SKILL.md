---
name: paint-scene
description: Paint a whole scene from a description on an empty or early canvas, back to front, using the paint-sky, place-subject and fix-region workflows. Use when the artist asks for a complete picture (a Christmas scene, a city at night, a landscape) rather than one part.
---

# Paint a scene

1. **Plan the layout** before painting: horizon line height, the sky band, the ground, and each subject's
   target rectangle (size by distance), plus the light source. Say it in one or two lines.
2. **Back to front** — each step is its own skill and its own reject-able transfer:
   1. Sky: `paint-sky` (generate, since nothing is painted yet).
   2. Distant background (hills, a skyline): a background band asset, like the sky, `anchor: fill`.
   3. Ground (snow, a street, water): `make_asset` generate a ground band, fit to the ground area.
   4. Subjects, largest and furthest first: `place-subject` for each.
   5. Light effects last: glows (`set_layer` style `outer_glow` on light layers), falling snow
      (`paint_recipe` small dabs), reflections.
3. **Unify:** `observe_canvas` the whole picture. Fix anything wrong with `fix-region`; do not regenerate
   a step that is mostly right.

Keep one consistent style phrase in every asset prompt (for example *"oil painting, visible impasto
brushstrokes, cool blue night with warm gold lights"*) so the parts belong together.

---
name: guided-trace
description: Sketch construction lines by hand with draw_guide on a guide layer (eye level, vanishing points, a few placement lines), then paint over them and finish_guide. Use only when the artist asks for guides or perspective, or an approved plan step names guides. Nothing is traced from a reference.
---

# Guides: an underdrawing by hand

A guide is a painter's underdrawing on its own guide layer, never the painting: never merged, never judged,
hidden when finished. The guide gives **placement**; the reference tools give **colour and light**; `paint_accents`
and your own strokes give **crispness, detail and finish**. Nothing is traced: outlines traced from a reference never
helped a painting, and silhouettes come from paint, not lines.

## Only when asked, after the underpainting

Guides are drawn **only when the artist asks** (guides, perspective, a construction) or an approved plan step names
them. With a goal reference the work goes:

1. **Reference first:** on a fresh canvas, lay the reference's colours and light with `paint_from_reference` (the
   whole picture). On an established painting, bring them in with `paint_reference_surface` over the paint already there.
2. **When asked, a guides move (nothing painted):** what the artist named: the eye level, vanishing points, a few
   lines that place the big shapes. Then `finish_move`.
3. **Your own strokes, one element per move:** with a guide, tighten it (`replace: true`), paint the element following
   it, then `finish_guide` and `finish_move`. Make it crisp with `paint_accents` on its area. After a whole-picture
   underpainting the host allows at most 12 small marks a call unless the artist asks for hand-painted work.

With no goal reference, guides give placement and your own strokes the colour, from the element reference or
the artist's description.

Never fill a guide shape flat: a guide marks where a form goes, not its colour. Keep the
light sources bright: a moon or a lamp is the lightest value in the picture, and the brightest element stays the
brightest; never paint it dark or mid-grey.

## Which reference decides what

The **goal image** decides **placement** (where and how big, the eye level, the vanishing points); an **element
reference** decides **proportions**. When they disagree, fit the element's proportions to the goal's placement.

## Measure, then draw

View the goal image (`view_reference`). Note where the eye level and each big mass sit as a **fraction of
the canvas**: canvas boxes.

1. **Eye level and vanishing points first:** `draw_guide` with `perspective: {eye_level_y, vanishing_points, rays}`
   draws the eye level and rays from each vanishing point.
2. **Placement lines by hand:** a few `lines` per element (its top, its base, its centre line, a roofline), in canvas
   pixels, or in reference pixels with `reference_id`, `source` and `target` (same proportions) so the points you
   measured in the reference land in place. A few dozen lines at most; never an outline of every edge.
3. **Light shapes:** mark where a light source sits with a line of `weight: 'light'`, so it is painted light.
4. **Tighten before painting:** when an element's own photo shows it better, draw it again with `replace: true`.

Weights: `construction` thin, `contour` (the default) stronger, `light` warm.

## Check after each stage

- **Perspective:** do the receding lines (railings, kerbs, roof lines, window rows) meet at the vanishing point?
- **Placement:** does each big shape sit at the same fraction of the canvas as in the reference (its top, bottom and
  centre)?
- **Proportions:** does each element have the reference's height to width?
- **Light:** is every light source marked warm?

If a check fails, redraw that element's lines with `replace: true` before you paint it.

## More

- `example-harbour-dusk.md`: the three kinds of move as real calls; read it before a scene's first guide.
- `subject-architecture.md`, `subject-vehicles.md`, `subject-figures.md`, `subject-landscape.md`: what to place and
  the common errors; read only one.
- `project-folder.md`: a project folder's plan moves.

`finish_guide` hides an element's guide; undo of a move removes its guide with its paint.

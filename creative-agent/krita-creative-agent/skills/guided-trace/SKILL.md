---
name: guided-trace
description: Sketch an element's construction lines from a reference with draw_guide before painting it (an underdrawing on its own guide layer), then paint over it in your own strokes and finish_guide. Use when placing or shaping an element (a building, a figure, a car, the horizon) from a goal image or an element reference.
---

# Guided trace: an underdrawing from a reference

A guide is a painter's underdrawing on the element's own guide layer, never the painting: never merged, never judged,
hidden when the element is finished. The guide gives **placement and shape**; the reference tools give **colour and light**; your own strokes
give **edges, detail and finish**.

## Reference first, then guides, then your strokes

With a goal reference, work in three kinds of move:

1. **Construction (a guides move, nothing painted):** the whole scene's eye level, vanishing points, big silhouettes
   and light shapes, then `finish_move`.
2. **Reference first:** on a fresh canvas, lay the reference's colours and light with `paint_from_reference` (the
   whole picture). On an established painting, bring them in with `paint_reference_surface` and
   `paint_reference_edges` over the paint already there.
3. **Guides, then your own strokes, one element per move:** tighten that element's guide (`replace: true`), paint it
   in your own strokes following the guide (`inside_shape` keeps a pass inside it), then `finish_guide` and `finish_move`.

With no goal reference (an element reference only, or none), guides give placement and your own strokes give the
colour, from the element reference or the artist's description.

Never fill a guide shape flat: a guide marks where a form goes, not its colour. Keep the
light sources bright: a moon or a lamp is the lightest value in the picture, and the brightest element stays the
brightest; never paint it dark or mid-grey.

## Which reference decides what

The **goal image** decides **placement** (where and how big, the eye level, the vanishing points); an **element
reference** decides **shape and proportions**. When they disagree, fit the element's proportions to the goal's placement.

## Measure, then draw

View the goal image (`view_reference`). Note where the eye level and each big mass sit as a **fraction of
the canvas**, and turn those into canvas boxes.

1. **Eye level and vanishing points first:** `draw_guide` with `perspective: {eye_level_y, vanishing_points, rays}`
   draws a thin eye-level line and rays fanning from each vanishing point.
2. **Silhouettes from the reference:** `from_reference: {reference_id, shape: {box: [x,y,w,h]}, target, detail}`
   outlines one element's exact shape on `target` (the box's proportions: crop, never stretch), never the clutter
   around it. Give one box or a few points per element (`points: [[x,y,1]]` on it, `0` beside it; points are fitted into `target`);
   a group is one box per member: each tower of a skyline, not the cluster. A score under 0.6 is uncertain: a tighter
   box or points.
   `'medium'` adds inner structure. Without `shape`, the big shapes (sky, masses, figures) get outlines; a `trace.note`
   means outlines by brightness: give a blue tower on blue sky a `shape`. Add missing `lines`.
3. **Light shapes:** outline every light source and the brightest areas warm, with `lights: true` or lines with
   `weight: 'light'`. A shape outlined warm is painted light.
4. **Tighten before painting:** when an element's own photo shows it better, draw it again with `replace: true`.

Weights: `construction` thin, `contour` (the default) stronger, `light` warm.

## Check after each stage

- **Perspective:** do the receding lines (railings, kerbs, roof lines, window rows) meet at the vanishing point?
- **Placement:** does each big shape sit at the same fraction of the canvas as in the reference (its top, bottom and
  centre)?
- **Silhouettes:** does each silhouette say what it is (tiers and a spire, not a box; arches as curves)?
- **Light:** is every light source outlined warm?

If a check fails, redraw that element with `replace: true` before you paint it.

## More

- `example-harbour-dusk.md`: the three kinds of move as real calls; read it before a scene's first guide.
- `subject-architecture.md`, `subject-vehicles.md`, `subject-figures.md`, `subject-landscape.md`: what to guide and
  the common errors; read only one.
- `project-folder.md`: a project folder's plan moves.

`finish_guide` hides an element's guide (the artist can show it again); undo of a move removes its guide with its paint.

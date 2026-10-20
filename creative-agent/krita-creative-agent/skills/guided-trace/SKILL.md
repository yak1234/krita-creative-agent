---
name: guided-trace
description: Sketch an element's construction lines from a reference with draw_guide before painting it (an underdrawing on its own guide layer), then paint over it in your own strokes and finish_guide. Use when placing or shaping an element (a building, a figure, a car, the horizon) from a goal image or an element reference.
---

# Guided trace: an underdrawing from a reference

A guide is a painter's underdrawing: a few construction lines on the element's own guide layer, thin and light blue.
It is never the painting. It is never merged, Luna and the review never see it, and it is hidden when the element is
finished. The guide gives **placement and shape**; the reference tools give **colour and light**; your own strokes
give **edges, detail and finish**.

## When to guide

- Before painting an element whose placement or shape comes from a reference: a building, a figure, a vehicle, a
  skyline, the horizon of a scene.
- Not for texture, a sky gradient or a correction to paint that is already right.

## Which reference decides what

- The **goal image** (the composition reference) decides **placement**: where the element sits, how big it is, where
  the horizon and the vanishing points are.
- An **element reference** (a photo of the one thing) decides the element's **shape and proportions**.
- When an element reference's angle disagrees with the goal image, the goal image wins: take the element's
  proportions, but fit them to the placement the goal image gives.

## What to draw

A few dozen lines at most, never outlines of every detail:

1. **Horizon and perspective:** the horizon line, two or three vanishing lines along the main edges (roof lines,
   kerbs, window rows).
2. **Block-in:** the element's silhouette as a few straight segments: its outer extents, the main masses (a tower's
   shaft, its tent roof, its spire), the ground line it stands on.
3. **Key proportions:** a centre line, the height of a storey, where a figure's head, waist and feet fall.

## How

1. `view_reference` the goal image and the element reference; decide the element's target rectangle on the canvas
   from the goal image (canvas pixels).
2. `draw_guide` with `element` (the name its layer and the plan use) and `lines` (polylines of 2-64 points, 1-128
   lines). Points are canvas pixels; or give `reference_id` with `target` (and `source`, a crop of the reference,
   default the whole reference) and the points are that reference's pixels, mapped onto the target exactly as the
   reference tools map them (same aspect ratio: crop, never stretch). Draw again for the same element to add lines.
3. Look at the returned image: the guide shows over the painting. Paint the element **under** it in your own strokes
   (`paint_contours`, `paint_pass`, fills in a selection); `paint_from_reference` and its finishing tools may lay the
   colour and light. The guide is for placement: follow it, do not trace its lines as the final linework.
4. When the element is painted, `finish_guide` with the same `element`. Its guide is hidden; the artist can show it
   again. Then move on to the next element.

In Agent mode one move paints one element: draw its guide, paint it, finish its guide. Undo of the move removes the
guide with the paint.

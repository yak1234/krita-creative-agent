# Stroke generators: one decision, many good strokes, painted by Krita's own engines

Status: APPROVED by the artist (2026-10-23: "1, maybe make sure not literal tracing as models suck for traces"). Starts with a throwaway render spike on a copy of New Moscow; the tool is built only after the artist judges the spike.

## Why

After the underpainting the painter places hand strokes by typing coordinates (`paint_batch`). In New Moscow chat
9f8202e8 that went on for about 18 minutes on one head; Luna flagged flat_block 1.0, hard_graphic 1.0, stripes 0.94
and ellipses 0.78. A language model decides well ("follow the hair's form, darker at the nape") and places geometry
badly. Toska already has one generator that works: the surface pass (`generateSurfacePlan` in
`reference-generator.mjs`): a structure-tensor flow field from the reference, jittered seeds, streamlines traced both
ways, stops at edges, busy detail and 45-degree turns, painted with a real preset through `Node.paintStrokes`.

Krita's brush engine (studied 2026-10-23, `plugins/paintops/`, `libs/image/brushengine/`) already renders brushwork
better than any web library: 17 engines (pixel, Color Smudge with paint thickness, Hairy bristles, Hatching, Sketch,
Experiment, MyPaint...) whose options are driven by sensors (pressure, tilt, speed, rotation, drawing angle, fuzzy per
dab or stroke, distance, time, fade). What is missing is planning where the strokes go.

## Libraries considered (Context7 and npm, 2026-10-23)

No maintained JavaScript library generates painterly stroke paths for an external engine.
- p5.js (LGPL-2.1) / p5.brush (MIT): render their own pixels on a web canvas; useful ideas (vector fields, hatching,
  bleed fills), not a dependency: Krita's engines render.
- perfect-freehand (MIT): turns pen points into an outline polygon for drawing apps; Krita does this itself.
- geometrize / geometrizejs (MIT port, last released 2022): approximates an image by optimised shapes (lines, quadratic
  curves, ellipses) — stroke placement by error minimisation. A possible later experiment for "strokes optimised
  against the reference", but it only reproduces the reference and is slow.
- simplex-noise (MIT): small, maintained; useful for natural jitter of seeds and directions.
- Stroke-based rendering research (Hertzmann's curved-stroke painterly rendering, neural stroke predictors such as Paint
  Transformer) is mostly Python/PyTorch; Toska avoids PyTorch. Hertzmann's method is close to what the reference
  transfer and surface pass already do.

So the generators are our own code (extending the surface pass), with simplex-noise as the only candidate dependency.

## Goals

1. **`paint_generated_strokes`**, one tool: an `area` (selection, element shape, mass from the mass map, or box), a
   `field` (`reference` flow, `angle` N degrees, `around` the area's centre, `noise`), a preset,
   size, length, density, colour (`sample canvas`, `sample reference`, or a hex, with a small variation), and a pressure
   shape (`taper`, `swell`, `even`). The host generates the strokes (seeds inside the area, streamlines, stopping rules:
   area boundary, strong edges, sharp turns, spacing from earlier strokes), shuffles them and paints them with the
   preset on its own layer.
2. **Hatching** by `field: angle` plus a crosshatch option (a second angle), and a pointer to Krita's own Hatching
   engine presets where they suit.
3. **Soft area fill**: strokes that fade at the area's edge (pressure and opacity toward the boundary).
4. **Pen dynamics on generated strokes**: per-point pressure, speed and time, so presets with drawing-angle and fuzzy
   sensors respond; documented per preset in the brush cards.
5. **Guidance**: the painter uses generators for brushwork after the underpainting instead of long `paint_batch` runs;
   `paint_batch` stays for a few deliberate marks.

## Not tracing (the artist's rule)

Generated strokes fill and model **areas** along the form's flow; they never follow edges or outlines. Strokes start
inside an area and stop before strong edges (as the surface pass does); no stroke runs along a contour, silhouette or
mass boundary, and there is no "along the outline" field (removed from goal 1). Edges and silhouettes come from the
paint itself (the underpainting) and crispness from accents.

## Non-goals

- No pixels rendered outside Krita; no image layers.
- No invented detail beyond the references (close-ups or an upscaled goal remain the way to sharper detail).
- The reference transfers are unchanged.

## Done when

On a copy of New Moscow: hair and sky refined with one or two generator calls each, Luna's move checks clean (no
stripes/ellipses/flat blocks), no long `paint_batch` runs; checked on a portrait and a landscape; time and stroke counts
measured.

## Left to the builder

Field maths for `around`/`along` (distance transform of the area), seed spacing and collision checks, defaults per
preset, whether simplex-noise is worth a dependency, and the exact schema names.

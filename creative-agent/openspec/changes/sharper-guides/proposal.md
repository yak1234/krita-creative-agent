# Sharper guides: real perspective assistants, full-resolution tracing, outlines by shape

Status: PROPOSED (2026-10-23). The artist picked all three ("1,2,3"); waiting for approval of this write-up.

## Why

In the New Moscow test, `draw_guide from_reference` gave thin, wrong guides beside an excellent underpainting:

- **The spire and tiers vanished.** `guide-trace.ts` works on the reference shrunk to 360 cells on its long side
  (`WORK`), keeps at most 8 lines ("simple") or 24 ("medium") of at most 64 points, and drops short or curvy chains.
- **The blue-glass towers had no outline.** The silhouette is a brightness split (Otsu); towers the colour of the sky
  fall on the sky's side.
- **The perspective "star"** is rays painted on a guide layer: fixed, unrelated to Krita's own perspective tools, and
  (until aa514e8e) counted as paint.

Krita has no auto-trace (nothing like Illustrator's Image Trace). It does have perspective assistants, which the
artist already knows, and Toska already ships OpenCV (`seams.py`) and the SAM 2.1 shapes model.

## Goals

1. **Perspective as Krita assistants.** `draw_guide perspective` (eye level, up to three vanishing points) creates
   real Krita painting assistants (Vanishing Point / 2-Point / Perspective, plus the eye level as an Infinite Ruler)
   instead of painted rays. The artist sees, moves and snaps to them with the Assistant Tool as usual. They are a
   canvas decoration, so they are never paint, never in the observed image, and saved in the `.kra`. libkis has no
   assistant API; the fork adds a small one (`Document.addAssistant` / `assistants()` / `removeAssistant`, built on
   `KisPaintingAssistantsDecoration`), with C++ tests. The agent's own strokes do not snap to assistants. The painted
   rays stay available as a fallback only where the API is missing (never for the fork build).
2. **Trace at full resolution.** The tracer moves from the 360-cell copy to OpenCV at the reference's resolution
   (bounded by `TRACE_PIXELS`): edge-preserving smoothing (bilateral) to drop texture, Canny edges, contours,
   simplification relative to the canvas, not to the grid. The line and point caps grow with the element (a whole
   cityscape gets more lines than a moon), and thin tall parts (spires, masts, poles) are kept, not dropped as short.
   It runs in the plugin, where cv2 already lives; the companion keeps the mapping and drawing.
3. **Outlines by shape, not brightness.** When the painter traces a named or pointed element, its outline comes from
   the shapes model (SAM 2.1 base-plus, existing consent, timings and cache), so a blue tower on a blue sky still gets
   its outline. For a whole-reference block-in, the big shapes (sky, each building mass, ground, figures) are found
   once and each gets its outline; edges inside a shape become structure lines. Brightness splitting stays only as
   the fallback when the artist has not allowed the shapes model.

## Non-goals

- No reference pixels on the canvas: no edge-filter layer, no low-opacity reference layer. Guides stay lines.
- Guides stay a construction sketch (block-in), not a finished line drawing; the underpainting still comes from the
  reference transfer.
- No change to stock Krita 5.3.3 support (frozen).

## Done when

- On a copy of the New Moscow folder, the block-in shows the spire, the tower tiers, the blue towers' outlines and
  the foreground masses, with Krita perspective assistants the artist can drag, and the underpainting still runs.
- Tested on two other references (a portrait and a landscape) for the general case.
- Time and memory of a full-resolution trace measured in tests and live.

## Left to the builder

Canny thresholds and smoothing, the caps' growth with element size, the exact libkis signatures, and how the eye
level is shown. Order: 3 and 2 together (they share the tracer), then 1 (needs a fork rebuild).

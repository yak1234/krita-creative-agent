# Sharper guides: tasks

Amended by crisp-accents (2026-10-23): the visible guide lines of sections 1 and 2 (1.3, 1.4, 2.3 and 2.5's "block-in
move draws the masses by default") are REMOVED; the tracer and the mass map remain as analysis (accents' line finder,
masses summary, thumbnail). Section 3 is parked.

Amended by the panel tidy (2026-10-23, the artist's panel layout B): the panel's outline thumbnail is REMOVED (it looked like
the tracing the artist removed); the mass map now carries the masses' colours and shares, shown as a flat colour bar, and
one plain sentence for the artist (mass map version 2). The painter's summary is unchanged.

## 1. Full-resolution tracing and outlines by shape (goals 2, 3) — branch agent/sharper-trace
- [x] 1.1 Plugin: OpenCV edge trace of a reference crop at full resolution (bounded by TRACE_PIXELS): edge-preserving smoothing, Canny, contours, simplification in canvas terms; thin tall parts kept
- [x] 1.2 Line/point caps grow with the element's size on the canvas
- [x] 1.3 (removed by crisp-accents) Element outlines from the shapes model when allowed (existing consent, cache, timings); brightness split only as the fallback
- [x] 1.4 (removed by crisp-accents) Whole-reference block-in: big shapes found once, each outlined; edges inside a shape become structure lines
- [x] 1.5 Tests (plugin + companion), time and memory measured; three references (New Moscow copy, a portrait, a landscape)

## 2. Mass map with VTracer (goal 4) — branch agent/mass-map
- [x] 2.1 Plugin: smoothed copy (bilateral + mean shift, at most ~720 px long side): mass_reference (creative_masses.py),
  on guided trace's decode and listed-size mapping; three bilateral passes (9, 40, 7), mean shift (10, 20)
- [x] 2.2 Companion: @visioncortex/vtracer pinned 1.0.0-alpha.4, convertPixels, SVG path parsing to guide polylines
  (guide-masses.ts; filterSpeckle 12 at 720 px, the lead's 24 at 1440); shipped outside the bundle, listed in the notices
- [x] 2.3 (removed by crisp-accents) draw_guide option for masses (from_reference masses: true); shapes' outlines win; light masses in the
  light-shape colour; never fill
- [x] 2.4 Tests, time and memory; three references (New Moscow copy, a painted portrait, Starry Night)
- [x] 2.5 (added by the artist) On attach: the whole-picture reference's mass map once per content (mass-map.ts), its
  summary in the study context, a thumbnail in the panel; the block-in move draws the masses by default (that part removed by crisp-accents)

## 3. Perspective as Krita assistants (goal 1) — PARKED (crisp-accents)
- [ ] 3.1 libkis: Document assistant API on KisPaintingAssistantsDecoration; C++ tests
- [ ] 3.2 Plugin + companion: draw_guide perspective creates assistants (eye level as an infinite ruler)
- [ ] 3.3 Rebuild, CI, live check on a copy

## 4. Release
- [ ] 4.1 Review, merge, CI, publish, package, install; live check on a copy of the New Moscow folder

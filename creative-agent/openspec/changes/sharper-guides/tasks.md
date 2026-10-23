# Sharper guides: tasks

## 1. Full-resolution tracing and outlines by shape (goals 2, 3) — branch agent/sharper-trace
- [x] 1.1 Plugin: OpenCV edge trace of a reference crop at full resolution (bounded by TRACE_PIXELS): edge-preserving smoothing, Canny, contours, simplification in canvas terms; thin tall parts kept
- [x] 1.2 Line/point caps grow with the element's size on the canvas
- [x] 1.3 Element outlines from the shapes model when allowed (existing consent, cache, timings); brightness split only as the fallback
- [x] 1.4 Whole-reference block-in: big shapes found once, each outlined; edges inside a shape become structure lines
- [x] 1.5 Tests (plugin + companion), time and memory measured; three references (New Moscow copy, a portrait, a landscape)

## 2. Mass map with VTracer (goal 4) — branch agent/mass-map
- [ ] 2.1 Plugin: smoothed copy (bilateral + mean shift, at most ~720 px long side)
- [ ] 2.2 Companion: @visioncortex/vtracer pinned 1.0.0-alpha.4, convertPixels, SVG path parsing to guide polylines
- [ ] 2.3 draw_guide option for masses; shapes' outlines win; light masses in the light-shape colour; never fill
- [ ] 2.4 Tests, time and memory; three references

## 3. Perspective as Krita assistants (goal 1) — after 1 and 2 merge, main checkout
- [ ] 3.1 libkis: Document assistant API on KisPaintingAssistantsDecoration; C++ tests
- [ ] 3.2 Plugin + companion: draw_guide perspective creates assistants (eye level as an infinite ruler)
- [ ] 3.3 Rebuild, CI, live check on a copy

## 4. Release
- [ ] 4.1 Review, merge, CI, publish, package, install; live check on a copy of the New Moscow folder

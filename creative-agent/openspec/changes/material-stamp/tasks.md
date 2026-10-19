## 1. Plugin (`krita-mcp/krita-plugin/kritamcp/material_stamp.py`)
- [x] 1.1 Tip cutting, pure Python on pixel buffers, with unit tests:
  - `light` tips from a cloud-like buffer: smoothed, normalised, round falloff, at most `count`;
  - `shape` tips from an alpha cut-out;
  - a patch overlapping a protected rectangle is never chosen.
- [x] 1.2 `make_material` native operation:
  - sources: area, layer and reference;
  - writes `materials/<id>/` (tips and `material.json`) and returns a contact sheet image;
  - test: the document's pixels are unchanged.
- [x] 1.3 `stamp` native operation:
  - one `QPainter` pass, premultiplied, masked by the area, written once to one new agent layer, recorded as a pass;
  - tests: nothing lands outside the area; a dab at 0.2 opacity changes a pixel by about 20%, not 100% (the spike's
    bug); the same seed gives the same layer; protection erases a protected area.

## 2. Companion (`krita-creative-agent/extensions/material-stamp.ts`)
- [x] 2.1 The extension registers `make_material` and `stamp_material` with TypeBox schemas, through the
  `MaterialHost` port. Tests with a fake host:
  - dab planning is seeded and deterministic;
  - at most 2000 dabs;
  - sizes and opacities stay in range;
  - a missing material is refused.
- [x] 2.2 Registered inline in `extensions.mjs`. The studio provides `materialHost()` through `callNative`, so
  revision, `stage_id`, protection and pass history apply. Test: a stamp in an Agent move is one pass, Luna reviews
  its batch, and Undo rejects it with the move.
- [x] 2.3 Skill text in `paint-sky` and `repaint-area`: make a material from the painting's own texture, stamp into a
  selection, then strokes for edges.

## 3. Verify
- [ ] 3.1 Suites and typecheck; build, install, reload.
- [ ] 3.2 A live clouds test on a copy of merged New Moscow (Luna guide): it should take minutes, not ten, with Luna
  verdicts and before/after images. Then two more paintings (foliage, water), per build-for-the-general-case.

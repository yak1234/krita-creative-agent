# How Krita paints a scripted stroke, and what can make it faster

**Date:** 19 October 2026
**Source read:** Krita at `858d352` (tag v6.0.3), the source of the installed Krita 5.3.3 (the same tree built with Qt5).
**Measured on:** merged New Moscow (6000×4500, 13 nodes), M-series Mac with 14 cores and 36 GB, Krita 5.3.3.

## 1. The path of one scripted stroke

What `Node.paintPath(path, 'ForegroundColor', 'None')` does, in order:

1. **`PaintingResources::createHelper`** (`libs/libkis/PaintingResources.cpp`):
   - looks up the active window's view and its canvas resource manager;
   - builds a `KisFigurePaintingToolHelper`.
2. **The helper's constructor** (`libs/ui/tool/kis_figure_painting_tool_helper.cpp`):
   - snapshots the current brush preset, colours, size and opacity (`KisResourcesSnapshot`);
   - creates a `FreehandStrokeStrategy`;
   - **starts a stroke job** on the image (`startStroke`).
3. **`paintPainterPath`** adds one job carrying the path.
4. **The helper's destructor**, at the end of `paintPath`, adds an update job and **ends the stroke**. The stroke becomes **one undo step**, which keeps a copy of every tile it changed.
5. **The strategy runs on Krita's stroke threads** (`libs/ui/tool/strokes/freehand_stroke.cpp`). `KisPainter::paintPainterPath` (`libs/image/kis_painter.cc`) walks the path and paints each segment with `paintLine`/`paintBezierCurve`. **Every point is `KisPaintInformation(pt)`: full pressure, no tilt, no speed.**
6. **The brush engine (paintop)** places dabs along each segment:
   - only the **Pixel brush** (`plugins/paintops/defaultpaintops/brush/kis_brushop.cpp`) renders its dabs on several threads (`KisDabRenderingExecutor`);
   - Color Smudge, Bristle and MyPaint render on one thread.
7. **Updates:** changed areas are merged into the projection by the update scheduler, on all cores. `Document.refreshProjection()` instead recomposites the **whole** image and waits (`libs/libkis/Document.cpp`).

The plugin adds this per stroke (`precision_tools.cmd_curve_stroke`): `_apply_brush_state` (size, opacity, flow and colour pushed onto the view) before every `paintPath`. It waits once per chunk, not per stroke.

## 2. Measurements

**One chunk of 256 strokes at 40 px** (`stroke_probe`, on a copy):

| Part | ms |
|---|---|
| brush state, 256× | 437 |
| `paintPath` calls (queueing) | 172 |
| Krita painting the dabs | 1,722 |
| full recomposite after | 128 |
| **total** | **~2,460** |

**Whole runs** (`timings_ms` per canvas step):

- **Runs 5–8** (92 slow steps, 232 s):
  - apply 49%;
  - checkpoint 36%, of which 12 saves of 5–6.5 s made up 26% of all time;
  - observation 8%.
- **Run 9**, after saving by time: 1 save instead of 12.
- **One observation** (`observe_probe`), about 0.2 s:
  - refresh 25–95 ms;
  - read 25 ms;
  - revision hash 55 ms;
  - view 40 ms;
  - painted share 22 ms;
  - the rest 0–18 ms, even with 150 extra layers.

**Hashing** 108 MB with SHA-256 takes 0.036 s, using Apple Silicon's SHA hardware, so it was never the slow part.

## 3. What this means

- **Krita's brush engine is the real painting cost**, about 70% of a chunk. No Python package changes that, because it's C++ inside Krita. It can only be made cheaper by painting **fewer dabs**:
  - larger, more meaningful marks;
  - stamps (`stamp_material`: 2000 dabs in 0.6 s with QPainter).
- **Per-stroke overhead is about 25% of a chunk.** That's the brush state pushed to the UI 256 times, plus 256 resource snapshots, stroke jobs and **undo steps**. Your Krita keeps 200 undo steps (`undoStackLimit=200`), so every chunk turns the whole stack over. **The native helper's batched strokes remove this:** one stroke job, one undo step per chunk, with the brush set once per group of strokes that share it.
- **Scripted strokes have no pressure.** Every pressure-driven brush (taper, opacity, flow) paints scripted strokes at full pressure, which is a likely cause of Luna's "hard graphic look". The helper can build `KisPaintInformation` with pressure, tilt and speed per point on Krita 5.3.3 too. Krita master's `paintPolylineStroke` does the same upstream.
- **Saves were the largest fixable cost:** now by time, and in the background during the model's turn (`save-timing.ts`).

## 4. Python packages

- **Shipped for Krita's Python** (`python-packages.txt`):
  - numpy, for pixel maths;
  - OpenCV headless, for blur, regions, k-means and Lab;
  - psutil, for real memory figures;
  - xxhash, for hashing.

  They speed up **our** work (tips, masks, analysis), not Krita's brush engine.
- **skia-python** (33 MB, works with Krita's Python 3.13): 2000 dabs of 220 px over 6000×1350 took 0.77 s with `drawAtlas`, no faster than QPainter's 0.6 s. Worth it later only for its effects (blur masks, more blend modes), not for speed.
- **No package can call Krita's internals.** Batched strokes, pressure, area refresh and background saves need the C++ helper.

## 5. Measured with the helper loaded (later, 19 October)

**Strokes:** the same 256 seeded strokes, through the Python API and through the helper's `paintStrokes`, on merged New Moscow (`stroke_probe` with `compare`):

| Preset | Python API | Helper | Pixels |
|---|---|---|---|
| b) Basic-5 Size Opacity | 432 ms | 404 ms | identical |
| f) Bristles-3 Large Smooth | 883 ms | 868 ms | identical |
| b) Basic-6 Details | 1,159 ms | 1,137 ms | identical |

**Batching strokes does not make painting faster** (1.02–1.07×). The 437 ms of "brush state" in section 2 did not repeat with a set preset. Krita's brush engine is nearly all of the time. The helper's stroke path is therefore off by default (`agent_accel.NATIVE_STROKES`). Its value is pressure per point, once the painter can send pressure.

**Area refresh:** 5 ms for an 800×600 area, against 67 ms for the full image.

**A probe pitfall:** the New Moscow copy carries a saved selection, which clips every stroke. Probes clear and restore it, as `paint_pass` does.

## 6. Helper priorities, from this study

1. **Pressure through to the painter** (the helper paints it already): the quality gain.
2. **Background save with job status,** to go with `save-timing.ts`.
3. **Area refresh** (built and working) and a scaled view read, for heavy paintings.

**Speed itself** comes from fewer dabs (stamps, larger marks) and fewer, hidden saves, not from C++.

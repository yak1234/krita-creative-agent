## Context

- **Krita release lines** (checked live on 18 October 2026, report section 9):
  - 5.3.x is Qt5;
  - 6.0.x is Qt6, without `paintPolylineStroke`;
  - master (5.4.0-prealpha on Qt5, 6.1.0-prealpha on Qt6) is the only line with `paintPolylineStroke`;
  - the installed version is 5.3.3.
- **Krita-Revamp** (github.com/10zindraws/Krita-Revamp) is a GPL-3.0 fork of Krita, branch `revamp-5.2.14`. Its
  changes:
  - brush stroke previews; a welcome screen without the news, so more recent images show;
  - horizontal scrubby zoom; the line tool only with the freehand brush;
  - short groups with folder thumbnails; clipping masks;
  - an instant overview;
  - resizable vertical toolbar icons and spacer actions; a toolbar smoothing slider;
  - brush presets that keep changed settings until "Reload";
  - bundled plugins: krita-redesign, krita_ui_tweaks, dockerundercursor, super_docker-lock, quickexportdocker,
    preset_groups, quick_brush_size, separatebrusheraser, layer_kit, timer_watch, krita_work_timer, label-box.
- **Where the time goes:** the plugin records per step (`before`, `apply`, `checkpoint`) and per observation part
  (`refresh`, `read`, `revision`, `view`, `details`). That separates Krita's recomposite from our own work.
- **Why scripts trigger a full refresh** (Krita master `libs/libkis/Document`):
  - `refreshProjection()` calls `refreshGraphAsync()` and then `waitForDone()`;
  - `waitForDone()` forces every delayed node, filter masks included, and blocks;
  - hand strokes go through the stroke system, which reports dirty tiles.

## Decisions

### 1. Foundation first; the fork is the product
- **Fork-first** (the artist's decision, 19 October 2026): artists download our Krita, so the plugin, companion and
  helper are designed for the fork, and never limited to keep stock Krita compatible. New features may be fork-only.
  Stock 5.3.3 support is frozen: kept working only while the artist still paints there, with no new work for it.
- **One repository** (task 1.5): the plugin, companion and helper move into the fork's tree. The licences are
  compatible (the fork ships GPL-3; Krita's LGPL and GPL-2-or-later parts fold in). With our code inside it, upstream
  sync merges upstream master into `krita-agent` monthly instead of rebasing onto it.
- **Phase 0** happens in this repository, before any fork code: the plugin moves to PyQt6 through `qt_compat.py`, and
  the suite runs under PyQt5 and PyQt6 plus `tests/ui_smoke.py`. Stock Krita 5.3.3 keeps working throughout.
- **The fork** is a GitHub fork of `KDE/krita` master, built for Qt6 on macOS first.
  - It uses its own application id and settings folder (not `~/Library/Application Support/krita`), so the artist's
    Krita 5.3.3, its settings and the installed plugin are never touched.
  - *(my call)* The name and branding are the artist's to choose. Until then the working name is "Krita Agent".
- **Upstream sync:**
  - our changes live in clearly separate places: new files, new libkis methods, and a small, listed set of edits to
    existing files;
  - the fork rebases on master on a fixed cadence (monthly, *my call*);
  - every change useful to all scripts (region refresh, async strokes, brush tips from an area) is also offered
    upstream to KDE, which shrinks the patch queue if accepted.
- **GPL compliance:** every binary release publishes the exact source it was built from, and keeps the licence notices
  (Krita's, Revamp's, our MIT-origin notice and the bundled packages' `THIRD_PARTY_LICENSES.txt`).

### 2. Krita's bottleneck: an agent channel into the core, measured

**Source study (Krita master, `forks/krita-master`, 19 October 2026).** Most of what the agent lacks already exists
inside Krita for its own tools; `libs/libkis` (the scripting layer, built for macros) does not expose it:

| Need | In Krita's core | In libkis today |
|---|---|---|
| What changed | `KisImage::sigImageUpdated(QRect)` per changed area | `Notifier` reports only open, save, close |
| Wait for own work | the strokes queue tracks each stroke by `KisStrokeId`; `KisImage::cancelStroke(id)`, `isIdle()`, but no per-stroke completion signal | only `Document.waitForDone()`, which waits for all image jobs and blocks |
| Area recomposite | hand strokes recomposite only dirty tiles | only `refreshProjection()`, the whole image |
| Scaled read | `KisPaintDevice::createThumbnailUncached(w, h, rect, oversample)` (`kis_paint_device.h:565`); level of detail is a stroke and canvas preview mode, not a readback | full-size `pixelData`, whole-node `thumbnail(w, h)` |
| Pressure | `FreehandStrokeStrategy` with a `KisPaintInformation` per point, in 5.3.3 too; master adds `paintPolylineStroke` and `StrokePoint` (tilt, rotation, speed, time) | `paintLine` takes two-point pressure; `paintPath`, `paintPolygon` and `paintRectangle` paint at full pressure |
| Smart regions | `KisFillPainter::createFloodSelection` and `createSimilarColorsSelection` (`kis_fill_painter.h:214-262`, with gap closing), lazy-brush min-cut (`libs/image/lazybrush`), magnetic edge tracing (`KisMagneticWorker`) | rectangles, raw pixels, grow/shrink/feather; colorize mask only as a node. The plugin's Python flood fill took 22 s for 8 seed steps at 6000×4500 (run 13) |
| Selection shape | `KisPixelSelection::outline()` → polygons (`kis_pixel_selection.h:105`), drawn as the marching ants | pixels only: the plugin finds straight selection edges by reading the whole mask with numpy |
| Image analysis | none | none, and Krita's Python has no numpy or OpenCV: the plugin ships them (`python-packages.txt`) and finds baked-in seams with them and Luna |
| Labels | `KisBaseNode::setNodeProperty` (a `KoProperties` bag per node) | most built-in properties wrapped one by one, without undo; custom labels, onion skins and layer-style enable not exposed |

The libkis additions below are therefore mostly wiring, plus new code where a tool's logic lives in its UI class
(the magnetic tool, colour range, smart patch) and has to move into a callable function.

**Wider gap study (Krita master and 5.3.3, 19 October 2026).** Effort is *wiring* (a core API exists), *move-out*
(logic inside a tool or dialog class) or *new*:

| Capability | In Krita's core | Effort |
|---|---|---|
| Undo history: count, text, index, `setIndex`, macros | `KUndo2Stack` (`libs/command/kundo2stack.h:173-236`), `KisDocument::undoStack()` | wiring |
| Named strokes and processing | `startStroke(…, KUndo2MagicString)`; every scripted stroke is "Scripted Brush Stroke" today (`PaintingResources.cpp:58`) | wiring |
| Bucket fill and enclose-and-fill as undoable jobs | `FillProcessingVisitor`, `KisEncloseAndFillProcessingVisitor` (`libs/ui/processing/`) | wiring |
| Selection from a path or polygon, antialias, grow-until-darkest | `KisSelectionToolHelper`, `kis_selection_filters.h:147,226` | wiring |
| Colour range and luminosity selection | `plugins/extensions/colorrange/dlg_colorrange.cc:141` | move-out |
| Change events: node added, removed and changed, selection, undo index, modified, active node, tool, preset | `kis_image.h:855-933`, `KisDocument::modified`, `KUndo2Stack::indexChanged`, `KisSelectionManager::selectionChanged`, `KoToolManager::changedTool` | wiring |
| Gradient as a function | `KisGradientPainter` | wiring |
| Smart patch (inpainting) | `patchImage(…)` (`tool_smart_patch/kis_inpaint.cpp:979`) | move-out |
| Perspective, warp, cage and liquify baked into a layer | `kis_*transform_worker.h` in `libs/image`; strokes in `tool_transform2` | wiring (workers), move-out (strokes) |
| Undoable move | `MoveStrokeStrategy`; `Node.move` sets x and y without undo | wiring |
| Flatten a layer with its masks; merge several layers | `KisImage::flattenLayer`, `mergeMultipleLayers` (`kis_image.h:599,605`) | wiring |
| Colour sampling with radius; histogram | `KisToolUtils::sampleColor`, `kis_histogram.h` | wiring |
| Brush tip from an area; adding a resource | `KisGbrBrush(KisPaintDeviceSP, x, y, w, h)`, `KisResourceModel::addResource` | wiring |
| Per-stroke overrides: mirror, selection, opacity, composite op | `KisResourcesSnapshot::setMirroring`, `setSelectionOverride` | wiring |
| Assistants, reference images, canvas decorations | `kis_painting_assistant.h`, `KisReferenceImagesLayer.h`, `kis_canvas_decoration.h` | wiring, new (decorations) |

**libkis traps the plugin works around, to fix in the fork:**
- `Filter.apply` changes the device directly, with no undo, no redraw and no selection (`Filter.cpp:85-99`); `startFilter`
  is undoable but blocks twice on `waitForDone`, and takes its resources from the active document.
- `Node.setPixelData`, `Node.move` and `setOpacity` have no undo, while `setBlendingMode` does.
- `Selection.contract` and `resize` add a rectangle instead (`Selection.cpp`); the global selection's edits have no
  undo; `cut` and `paste` have no undo.
- Painting needs an active view and dereferences it without a check (`PaintingResources.cpp:36-37`); scripted strokes
  take the view's brush, mirror, eraser, alpha lock and selection even for another document, so turning on mirror in
  the UI mirrors the agent's strokes.
- Paint calls return before the paint lands, while most node and filter edits block the UI thread on `waitForDone`.

The libkis additions:
The target: **strokes per second and observe time independent of document size.** It is measured on
new_moscow_merged (6000×4500) against a 1024×768 painting, with the same `timings_ms` before and after.

- **Region refresh:** `Document.refreshProjection(QRect)`, plus `Node.setPixelData` marking only its own rect dirty, so
  a script write costs what the area costs. The plugin calls it wherever it knows the changed area: every pass result
  has bounds.
- **Asynchronous strokes with job status** (measured 19 October: batching 256 strokes into a few stroke jobs painted
  identical pixels at only 1.02–1.07× the speed, since the brush engine is about 70% of the time; jobs are for status,
  nothing lost, pressure and undo, not raw speed): `Node.paintStrokes(strokes, options, selection) -> StrokeJob`, with
  `state()`, `strokesDone()`, `changedRect()`, `status()`, `wait(timeout)`, `cancel()` and a `finished` signal, run
  through Krita's stroke system off the UI thread. A busy Krita then answers "job 12 is painting, 40% done" instead of
  timing out, which fixes the lost results. Each stroke is one `FreehandStrokeStrategy` stroke with a
  `KisPaintInformation` per point (pressure, tilt, rotation, speed, time), as master's `paintPolylineStroke` builds
  them, plus cubic segments; its brush is the job's own (named preset, no mirror or view state). Each stroke reports
  its own end, after its pixels have landed (a Wash brush's merge included), so `wait()` waits for the job's strokes
  only, never for the whole image as `waitForDone()` does. *(my call, the lead's ruling)* The artist comes first: a
  job keeps at most 32 strokes queued and tops them up as they paint, so an artist's stroke waits behind at most 32;
  job strokes never ask the artist's strokes to end and ignore Esc; the artist's Undo during a job stops it (a whole
  prefix stays) and is then carried out. A job is one undo step, or part of the open move, however many top-ups it
  takes (it holds the step until its last stroke ends). On the GUI thread `wait()` always has a limit.
- **Cheap revision and change reports:** `Document.revision()`, a counter that increases on every change to the
  image, plus `Document.changedRect(since)` and a `Notifier.imageChanged(document, rect, source)` signal, all fed from
  `KisImage::sigImageUpdated`. `source` is `agent` while an agent job or move is open and `artist` otherwise. The
  plugin's revision becomes that counter instead of a SHA-256 of the full projection (108 MB per observation at
  6000×4500), and the agent learns what the artist changed between moves.
- **Scaled projection read:** `Document.projection(rect, scale)`, which reads a 1568 px view without first copying
  the full-size canvas, through `KisPaintDevice::createThumbnailUncached(rect)`, so memory stays at the output size.
- **Agent undo steps:** `Document.beginAgentMove(name)` and `endAgentMove()` wrap a move's passes in one named undo
  command ("Agent: paint sky"), using Krita's undo macros (`KUndo2Command` with children), so 1400 strokes are one
  history entry instead of 1400. The undo history docker marks agent steps. *(my call, after the review of the first
  implementation)* The move's commands are collected apart from the shared undo stack and pushed as one step when the
  move's own strokes finish, so the artist's strokes during a move stay separate steps, Ctrl+Z keeps working and no
  artist stroke is ever ended by the agent. Krita rolls back each layer's tiles strictly in order, so if the artist
  paints on a layer the open move has touched, the move's step is split there ("Agent: sky", then "Agent: sky (cont.)").
  A move a script leaves open is closed on save, on the artist's Undo and after an idle timeout. The artist's Ctrl+Z during a move
  undoes the move's work so far; the script's later work continues as "Agent: <name> (cont.)". Known limit until task
  2.9: a script's stroke start asks other strokes to end (`KisImage::startStroke`), as in stock Krita; the freehand
  brush ignores it, but an in-progress transform, move, crop, line or selection-tool action is committed and animation
  playback stops. Undo of a move removes all its passes; the
  plugin's Keep / Undo maps onto this step. *(my call)* Undoing an agent move that lies under later artist strokes
  stays Krita's normal in-order undo; out-of-order undo is a non-goal.
- *(my call)* The order follows the report's measurement:
  - if `before.refresh` dominates, region refresh comes first;
  - if `read` or `revision` dominate, the cheap revision and scaled read come first.

### 3. The Photoshop-like interface: Revamp ported, then defaults
- Revamp's commits are ported from 5.2.14 (Qt5) onto master (Qt6) one feature at a time, in the order of value to a
  Photoshop user:
  1. clipping masks;
  2. folder-style groups;
  3. brush stroke previews;
  4. scrubby zoom;
  5. instant overview;
  6. toolbar sizing and smoothing slider;
  7. preset persistence.

  Each is a separate commit, so a feature that resists the port can wait.
- Revamp's bundled Python plugins come in after the PyQt6 port, each checked for Qt6. A plugin that duplicates a
  native feature, like layer_kit's clipping masks, is dropped.
- Defaults for a new install: Krita's Photoshop shortcut scheme, a workspace with layers, brushes and the agent panel
  placed as in Photoshop, and a dark theme. Existing Krita settings are never migrated in silently.

### 4. The agent built in
- The agent panel loads with the main window, not with a document. With no painting open it offers "new painting"
  chats: it creates the `.kra` (the companion's new-painting mode) and its assets.
- **Project view:** a docker listing the project folder's paintings, references, brushes and materials, and generated
  assets, with thumbnails. Opening one is a click.
- **Canvas overlays** are drawn by the canvas, not as layers:
  - proposed and kept protected areas, outlined;
  - Luna's finding locations (for example "flat block, top right");
  - the move in progress, highlighted until Keep or Undo.

  They replace the red selection-mask preview.
- The companion stays a separate process (Node, Pi). Krita starts it with the app, and the plugin bridge stays the
  protocol, so the same companion runs on the fork (and on stock Krita while that support lasts).

### 5. The scripting gaps, made native
- **Brush tips from an area:** `Krita.createBrushTip(image, name) -> Resource` and
  `Krita.createPreset(baseXml, tip) -> Resource`, registered in the resource database without a restart: wiring of
  `KisGbrBrush(KisPaintDeviceSP, x, y, w, h)` and `KisResourceModel::addResource`. This is the
  Custom Brush dialog's "Stamp", exposed to scripts. material-stamp then stamps through Krita's own brush engine where
  that is better, and keeps QPainter for speed.
- **Protected areas** moved to the feature map (section 6): protection is a feature property.
- **Merge and bake:**
  - `Document.mergeGroups(nodes)` merges groups exactly by projection (`KisImage::mergeMultipleLayers`);
  - `FilterMask.bake()` applies a filter mask to its layer's pixels (`KisImage::flattenLayer`).

  Both are undoable as one step, and they replace `merge_agent_work`'s projection copies.

### 6. The feature map
The idea comes from map software: pixels (Krita's layers) plus named features with a shape and properties, kept
alongside them and indexed for "what is here" questions. Krita has the pixel half and only one temporary selection
for the other.

- **A feature** is a name, a kind, an author (artist or agent), a state (proposed or kept), a protected flag, and an
  8-bit mask at document size, with measured bounds, area and mean colour updated when the mask changes. It describes
  the painting and never holds pixels, so it can span layers and survives merges.
- **Storage follows Krita's existing pattern, with no new file format.** A document-level `KisFeatureList` is owned
  by `KisImage`. `KisKraSaver` and `KisKraLoader` gain `saveFeatures` / `loadFeatures` the way storyboards and
  assistants are saved (`saveStoryboard` + `saveStoryboardToXML`):
  - the list is a `<features version="1">` element in `maindoc.xml`, one child per feature with its name, kind,
    author, state, protected flag and properties;
  - each mask is a `KisPixelSelection` written by Krita's own paint-device writer, the code path selection masks
    already use, so it is tiled, compressed and tested at any size;
  - the `version` attribute lets later forks migrate old files; stock Krita ignores the unknown element and files, so
    the `.kra` still opens there.
- **Spatial index:** `boost::geometry::index::rtree` over feature bounds answers "what is here" without scanning
  masks; exact answers then read the masks. Krita already requires Boost (`CMakeLists.txt`, `find_package(Boost
  1.69)`) and already uses Boost.Geometry (`libs/image/kis_convex_hull.cpp`), so this adds no dependency.
- **Export for other tools** *(my call)*: features can be exported as GeoJSON outlines and COCO RLE masks, for Luna
  and training scripts. Export only: the `.kra` stays the source of truth.
- **Builders**, each returning a mask the agent proposes as a feature:
  - `fromSelection()`, the current selection;
  - `similarColour(point or colour, tolerance)` and `contiguous(point, tolerance)`, from the similar and contiguous
    selection tools, with their logic moved from the tool classes into callable functions;
  - `snapOutline(points)`, the magnetic tool's edge tracing (`KisMagneticWorker`) between the agent's rough points;
  - `segment(hints)`, the colorize mask's lazy-brush min-cut run on hint strokes, returning one mask per hint colour.
  All builders read the composited image by default, or a named layer.
- **Queries:** `featuresAt(x, y)`, `featuresOverlapping(rect or feature)`, `featuresTouching(feature)`, and
  `selection("Sky - Moon")` combining features by name with union, intersection and difference, all through the
  R-tree and the stored masks.
- **Protection:** a protected feature is enforced where pixels are written: agent jobs paint through a selection that
  excludes every protected feature, and direct pixel writes from scripts are clipped the same way while an agent move
  is open. The pass result names the features it was kept out of. The artist's own painting is never clipped.
- **The plugin and companion:** the panel's protected-areas list becomes a features list (show, protect, rename,
  remove); the agent's `select`, `fill_region`, `stamp_material` and pass tools accept feature names. Fork-first: no
  selection-mask fallback is kept for stock Krita.
- **Overlays:** proposed features are drawn by the canvas overlay of section 4, outlined with their names, until the
  artist keeps, adjusts or discards them.

### 7. Interim: the native helper on stock Krita
Before the fork exists, a C++ helper (`krita-native/agent-accel`, a view plugin built against the exact Krita it loads
into, loaded with `KRITA_PLUGIN_PATH`) reaches Krita's core from the installed 5.3.3. The plugin calls it through Qt's
meta-object system and falls back to libkis when Krita was started without it. Measured live on 19 October 2026:
- area refresh 5 ms against 67 ms for the full recomposite;
- per-point pressure through `FreehandStrokeStrategy`: a tapered stroke measured 1, 16, 60, 16, 1 px wide along its
  length against a constant 60 px;
- batched strokes: identical pixels at 1.02–1.07× the speed, so the plugin's stroke path stays libkis unless strokes
  carry pressure.

Each libkis addition is prototyped in the helper first where 5.3.3 allows it, so the plugin and its tests are ready
when the fork lands; the fork then exposes the same calls in libkis. The helper is not a replacement: it needs a
matching build per Krita version and cannot change libkis's own behaviour.

## Non-Goals
- Windows and Linux builds in the first release (macOS first; the code stays portable).
- Changing Krita's file format: `.kra` from the fork opens in stock Krita, except new annotations, which stock Krita
  ignores.
- Rewriting the companion in C++: it stays Node and Pi, behind the bridge.
- Krita deciding what a region is: features are built by tools the agent or artist calls. Krita runs no image
  recognition of its own; the plugin's seam finder (numpy, OpenCV and Luna) proposes `seam` features from outside.
- Out-of-order undo of an agent move under later artist strokes.
- A faster brush engine: the engine is about 70% of a chunk (docs/2026-10-19-scripted-painting-study.md), and speed
  there comes from fewer, larger marks, which is separate work.

## Risks
- **Upstream drift:** master moves fast and Revamp is on 5.2.14. Mitigations: small, listed edits; separate commits per
  feature; a fixed rebase cadence; upstreaming what is general.
- **Qt6 plugin breakage:** Python plugins written for Qt5, including Revamp's, may break. Phase 0 ports ours; theirs
  are checked one by one.
- **Async strokes and undo:** async jobs must still form one undo step per pass, and Undo of a move must reject all of
  them. Tests cover undo on every async path before the plugin uses it.
- **Feature masks and memory:** a document-size mask per feature is 27 MB uncompressed at 6000×4500. Krita's tiled
  selections store empty and full tiles cheaply, which covers typical features; measure with 30 features on New
  Moscow.
- **Moving tool logic out of UI classes:** the similar-colour and magnetic tools keep their logic in tool classes;
  pulling it into functions touches upstream files, so it goes on the listed edits and is offered upstream.
- **Scope:** six tracks. Phases are independent after phase 0, so the bottleneck can ship before the interface.

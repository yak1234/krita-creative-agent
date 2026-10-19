## 0. Foundation in this repository
- [x] 0.1 Port every plugin module to `qt_compat.py` and scoped enums; drop `exec_()`. Python suite under PyQt5 and
  PyQt6, plus `tests/ui_smoke.py`, in CI. *(Done 19 October: 99 enum names rewritten by `qt6_scoped_enums.py`; suite,
  panel smoke and shutdown tests pass under both; live in Krita 5.3.3. The public repo's CI (`krita-creative-agent/public-repo/.github/workflows/ci.yml`) now runs the suite
  and panel smoke under both; it takes effect at the next approved publish.)*
- [ ] 0.2 Commit the timing instrumentation and measure live (report section 7): `before.*` and `checkpoint.*` on
  new_moscow_merged and on a 1024×768 painting. This sets the order of task 2. *(Instrumentation committed and New
  Moscow measured 19 October: one observation about 0.2 s, saves 26% of runs 5–8 before saving by time; the 1024×768
  comparison remains.)*
- [x] 0.3 The native helper on stock 5.3.3 (design section 7): area refresh (5 ms against 67 ms), per-point pressure
  (taper 1–16–60–16–1 px against a constant 60 px), batched strokes measured (1.02–1.07×, identical pixels).
- [x] 0.4 Helper prototypes before the fork: contiguous and similar-colour selection and selection outline through
  `KisFillPainter` (target: 8 seeds at 6000×4500 under 1 s, from 22 s), then background save with job status.
  *(Protocol 3, 19 October: seed fills in C++ paint identical pixels at 2.3–2.8×, 526 against 1467 ms unbounded. The
  fill was not the cost: a select's build spends about 0.5 s per step moving a 27 MB mask to Python and merging it, so
  8 unbounded steps took 7.7 s of 9.0 s. Protocol 4, 1dede58: the whole multi-step selection in one C++ call, live
  on New Moscow: 8 unbounded seeds 0.67 s for the whole select (build 0.22 s: read 19 ms, fills 168 ms, combine 12 ms),
  bounded 0.31 s, identical pixels to the per-step path. Background save, protocol 6, 2ccd598, live on New Moscow:
  5.4 s either way, and Krita's own save already keeps the window responsive (longest freeze 28 ms against 22 ms), but
  the checkpoint returns in 6 ms instead of 5.5 s, so the agent's next action no longer waits; the file reopens with
  the same 12 layers. Its rename also avoids Krita's macOS save deleting the painting before copying the new file.)*

- [x] 0.5 Pen input beyond pressure in the helper: per-point tilt (x, y), rotation and speed, plus a stroke time so
  speed- and time-based dynamics work, through `KisPaintInformation` like pressure. paint_pass takes them as optional
  per-point lists like `pressure`. Live check: a tilt-sensitive preset turns with the tilt, and a speed-sensitive one
  thins as speed rises. On the fork, task 2.4's `paintPolylineStroke` and `StrokePoint` carry the same values.
  *(Protocol 5, fbf6edd, live 19 October: tilt widens c) Pencil-5 Tilted from 2 to 9 px over 0–60°; speed thins
  d) Ink-1 Precision from 48 to 28 px; pressure unchanged. Open: time showed no visible effect on j) WaterC Basic
  Round-Grunge, so time reaching the brush is unconfirmed.)*
## 1. The fork
- [x] 1.1 Fork `KDE/krita` master; macOS Qt6 build with its own application id and settings folder. Check: Krita
  5.3.3 starts unchanged afterwards. *(19 October: master 6.1.0-prealpha on Qt6, arm64, branch `krita-agent` ff7ec1b
  and 09ef936 in `forks/krita-master`; bundle `local.kritaagent`, settings under `KritaAgent/`; 8,970 stock files
  unchanged across a launch; `.kra` still opens in Krita 5.3.3. Review: unsaved-document autosaves still share the
  home folder with stock Krita, where either app's recovery dialog deletes the other's; the bundle still exports
  Krita's file types; an empty identity is not yet exactly upstream. Fixed on `agent/identity-fixes`, merged ad7c422:
  autosaves in `KritaAgent/autosave`, file types imported not exported (all ranks Alternate), an empty identity is
  upstream exactly, shipped kritarc defaults, kritarunner, and an `agent/check-identity.sh` leak gate; KisAppIdentityTest
  and KisAutoSaveLocationTest pass.)*
- [x] 1.2 Load the plugin and companion in the fork; the Agent-mode test chats pass as on stock Krita.
  *(Code a477e3a: bridge on 5679 in the fork, its own exports, records and cache, `install.py --krita fork`, PyQt6
  docker fix. An Agent-mode chat painted a full move in the fork, but on an app another build rewrote mid-run: a live
  re-check on a clean install is pending. Re-checked on a clean install: health on 5679, canvas saved, stroke read back;
  an Agent-mode move of 46 actions and 468 strokes with no errors, Luna undid 1 of 7. The fork, like stock, stalls while
  the display sleeps: unattended runs keep it awake.)*
- [ ] 1.3 Release pipeline: the build plus its source, licence notices, and the About box.
- [x] 1.4 Upstream policy written down: the list of files we edit, the rebase cadence, and what is offered upstream.
  *(`AGENT-FORK.md` in the fork, 09ef936.)*

- [ ] 1.5 One repository: move the plugin (`krita-mcp`), companion (`krita-creative-agent`) and helper
  (`krita-native`) into the fork's tree with their history (git subtree); build, install and test from there (the
  plugin installed into the fork's own pykrita by the build); CI runs both suites; upstream sync becomes a monthly merge
  of upstream master (AGENT-FORK.md). Stock 5.3.3 support stays frozen until the artist paints in the fork.
  *(Merged 56c7040: the whole repository, 464 files and 204 commits, under `creative-agent/` on `krita-agent`; suites pass
  there (Python 442, JS 392); AGENT-FORK.md switched to monthly merges, c1f3f3b; `digital_art/krita` frozen. Remaining:
  the fork's build installs the plugin into its own pykrita, and CI.)*
- [ ] 1.6 Fork parity, first priority (the artist, 19 October): the fork must be at least as capable as stock Krita with
  the helper. Build the native helper inside the fork's tree for Qt6, installed and loaded with the app; pen pressure,
  tilt and speed through master's `paintPolylineStroke`; native seed selection; background save; the vetted Krita
  actions audited for the fork's version. Live check in the fork: accel, pen, select and save probes, and an Agent-mode
  chat.
## 2. Krita's bottleneck (`agent-speed-api`)
- [x] 2.1 `Document.refreshProjection(QRect)`, and `setPixelData` dirtying only its rect; the plugin passes known
  bounds. Measure.
- [x] 2.2 `Document.revision()`, `changedRect(since)` and `Notifier.imageChanged(document, rect, source)` from
  `KisImage::sigImageUpdated`, marked artist or agent; the plugin's revision uses them, and observations report what
  the artist changed. Measure.
  *(Merged into `krita-agent` after review fixes, 19 October: `revision()` 9 ns against 542 ms to read and hash
  6000×4500; events in one ordered queue, short-lived wrappers, source taken when a change is requested, LOD rects
  in image pixels; TestDocumentChanges 16, TestNotifierChanges 19, TestPythonChangeEvents 3. Tool, preset and active-
  node signals need a live check.)*
- [x] 2.3 `Document.projection(rect, scale)` for views, from the level-of-detail projection where current, else tile
  by tile. Measure.
  *(Branch `agent/speed-region`, 19 October, at 6000×4500: a 1568 px view in 12.8 ms and 9.6 MB against 32.8 ms and
  216 MB for a full read and smooth downscale; an area average, so its time grows with the rect, recorded in the spec.
  Region refresh, 2.1: 0.9 ms against 13.1 ms for 800×600. Merged 178896a after review: refresh grows by effect
  halos (blur 111 and drop shadow 228 levels stale before), the scaled read locks with tryBarrierLock and never ends a
  stroke (null after 5 s), LGPL headers. Plugin side 3d66397. All new libkis suites pass on the merged build; a live
  measurement on New Moscow in the fork remains.)*
- [ ] 2.4 Async stroke jobs on `paintPolylineStroke` with state, progress and changed rect, each holding its
  `KisStrokeId` so `job.wait()` waits for that job only; the companion polls jobs instead of waiting. Tests: nothing is
  lost when Krita is busy, and the window responds while a pass paints.
- [x] 2.5 `Document.beginAgentMove(name)` / `endAgentMove()`: one named undo step per move, marked in the undo
  history docker; the plugin's Keep / Undo uses it. Tests: a 1400-stroke move is one step, Undo of a move rejects all
  its async passes, and earlier artist strokes stay in the history.
  *(Merged 2253af0 after two reviews: agent commands collected apart from the artist's and pushed as one "Agent:
  <name>" step when the move's strokes finish; split on a shared layer; no locks; Ctrl+Z works during a move; a move left
  open rests after save, undo or idle and continues as "(cont.)"; `with doc.agentMove(name):`. TestDocumentHistory 33,
  TestPythonAgentMove 6, libkis set green. A live check in the fork remains.)*
- [x] 2.7 Undo history in libkis: count, text, index, `setIndex`, macros and named steps (`KUndo2Stack`); scripted
  strokes and processing carry a name instead of "Scripted Brush Stroke".
- [x] 2.8 Change events beyond the image: node added, removed and changed, selection, undo index, modified, active
  node, tool and preset, through `Notifier`.
- [ ] 2.9 libkis traps fixed: `Filter.apply` undoable and selection-aware without blocking; undo for
  `Node.setPixelData`, `move` and `setOpacity`; `Selection.contract` and `resize` corrected; painting without an active
  view refused cleanly; per-stroke overrides (mirror, selection, composite op) so the view's state never leaks into
  agent strokes.
- [ ] 2.6 Verify: the New Moscow and 1024×768 chunk times are within a factor of 1.5; an observe at 6000×4500 takes
  under 2 s.

## 3. Photoshop-like interface (`photoshop-workspace`)
- [ ] 3.1 Port Krita-Revamp's features from `revamp-5.2.14`, one commit each: clipping masks, folder groups, brush
  stroke previews, scrubby zoom, instant overview, toolbar sizing and smoothing slider, preset persistence.
- [ ] 3.2 Revamp's Python plugins, after 0.1: check each on Qt6, and drop those duplicated by native features.
- [ ] 3.3 New-install defaults: Photoshop shortcuts, the workspace with the agent panel, a dark theme.

## 4. The agent built in (`built-in-agent`)
- [ ] 4.1 The agent panel loads with the window; new-painting chats with no document open.
- [ ] 4.2 Project view docker.
- [ ] 4.3 Canvas overlays: protected areas, Luna's findings, the move in progress.

## 5. Native agent craft (`native-agent-craft`)
- [ ] 5.1 `createBrushTip` and `createPreset` from scripts, without a restart; material-stamp offers Krita-brush stamps.
- [ ] 5.2 `mergeGroups` and `FilterMask.bake` on `KisImage::mergeMultipleLayers` and `flattenLayer`;
  `merge_agent_work` uses them.
- [ ] 5.3 Tools as functions: bucket and enclose-and-fill, gradient, smart patch (moved out of its tool), undoable move,
  and perspective, warp and liquify baked through the transform workers.

## 6. The feature map (`canvas-features`)
- [ ] 6.1 `KisFeatureList` on `KisImage`: features with mask, name, kind, author, state, protected flag and measured
  properties; `KisKraSaver::saveFeatures` / `KisKraLoader::loadFeatures` on the storyboard pattern (`<features
  version="1">` in `maindoc.xml`, masks through Krita's paint-device writer); a `boost::geometry::index::rtree` over
  bounds. Tests: round trip, and stock Krita opens the file.
- [ ] 6.2 libkis `Feature` and `Document.features()`, add, rename, remove; adding or removing a feature changes no
  pixel and is one undo step.
- [ ] 6.3 Builders: `fromSelection`, `similarColour`, `contiguous` (tool logic moved into functions), `snapOutline`
  (`KisMagneticWorker`), `segment` (lazy-brush). Test on runs 10 and 11: the skyline from 20 rough points leaves no
  band of old sky.
- [ ] 6.4 Queries: `featuresAt`, `featuresOverlapping`, `featuresTouching`, and `selection("Sky - Moon")`.
- [ ] 6.5 Protection as a feature property, enforced on agent jobs and script pixel writes during an agent move; the
  pass result names the features it was kept out of. Test: "leave the buildings alone" over a whole-canvas pass.
- [ ] 6.6 Plugin and companion: the panel's features list replaces protected areas; `select`, `fill_region`,
  `stamp_material` and passes accept feature names (fork-first: no stock fallback).
- [ ] 6.7 Proposed features drawn by the canvas overlay (task 4.3) until kept, adjusted or discarded.
- [ ] 6.8 Measure feature memory with 30 features on New Moscow.
- [ ] 6.9 Export features as GeoJSON outlines and COCO RLE masks for Luna and training scripts.
- [ ] 6.10 Seams as features: confirmed baked-in seams (the plugin's seams.py and Luna) proposed as `seam` features,
  outlined on the canvas, and repaired by the painter before it paints near them.

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
- [x] 1.3 Release pipeline: the build plus its source, licence notices, and the About box.
  *(Finding, 19 October: the app bundle in `_install/bin/krita.app` is a 9 MB shell that loads about 1.3 GB of libraries, Qt
  frameworks and `share` from `_install` through rpath, so it cannot be moved or handed out. 1.3 must build a self-contained
  bundle (libraries, frameworks, resources, the plugin and its Python packages inside `Contents`), installable in
  `/Applications` without a dependency on the build tree, signed with one stable identity: that also ends macOS asking
  again for Documents access after every rebuild. Priority, with 1.5.)*
  *(Done 20 October (UTC) after two reviews and four fix rounds: the real package is 826 MB, 679 Mach-O files checked, signature verifies, smoke imports (krita, PyQt6, kritamcp, numpy, cv2, psutil, xxhash, MLT) pass from a temporary copy with forks/ unreadable; installed into ~/Applications; launched twice on a FRESH temporary settings folder, once directly and once through LaunchServices like a double-click: the launcher enabled the plugin by itself ([python] enable_kritamcp=true), the bridge answered on 5679 in about 40 s, the companion was copied to <AppData>/KritaAgent/creative-agent/<build_id> with a 0600 config, the window shows Krita's start page, quit left "CLOSING SESSION", no autosave, no prompt, the real KritaAgent folders untouched. Still to do by a person: the About box text itself ("Your Rights" tab), "Connect assistant" (Node download), MLT playback, the Documents prompt with a stable certificate; and OPEN above: Developer ID and notarisation for other artists.)*
  *(19 October evening: packaging scripts done on agent/package (agent/package-app.sh, install-app.sh, app-launcher.c, licence notices; 679 Mach-O files checked, signature verifies, headless imports of krita, PyQt6, kritamcp, numpy, cv2 pass), under review. Open: the Node companion and its runtime are NOT in the app (task 1.3b: without them the agent panel cannot run on a clean machine); the About box needs a rebuild; the source URL must default to https://github.com/yak1234/krita-creative-agent now that it is public; repackage and install to ~/Applications after the main rebuild; live checks.)*
  *(Packaging built 19-20 October: `agent/package-app.sh`, `agent/install-app.sh`, AGENT-FORK.md "Packaging".)*
  **OPEN (needs the artist and an Apple Developer account): other artists' Macs.** The app is signed ad hoc or with a local
  self-signed certificate. That is enough for this Mac (no quarantine flag), but an app that arrives by download carries
  `com.apple.quarantine`, and Gatekeeper rejects ad-hoc and self-signed apps that carry it ("cannot be opened because the
  developer cannot be verified"). Handing the fork to other artists needs a Developer ID Application certificate, the
  hardened runtime (already on for a named identity), notarisation (`notarytool`) and a stapled ticket, and the disk image.
  The entitlements stay: `allow-jit` (Qt's QML/JavaScript engine and PyQt/sip JIT need writable-executable memory) and
  `disable-library-validation` (the vendored numpy and OpenCV and Python's extension modules are signed by other parties or
  by us ad hoc: with a Team ID the hardened runtime would refuse to load libraries signed by anyone else; with ad-hoc or
  self-signed code there is no Team ID to match).
- [x] 1.4 Upstream policy written down: the list of files we edit, the rebase cadence, and what is offered upstream.
  *(`AGENT-FORK.md` in the fork, 09ef936.)*

- [ ] 1.5 One repository: move the plugin (`krita-mcp`), companion (`krita-creative-agent`) and helper
  (`krita-native`) into the fork's tree with their history (git subtree); build, install and test from there (the
  plugin installed into the fork's own pykrita by the build); CI runs both suites; upstream sync becomes a monthly merge
  of upstream master (AGENT-FORK.md). Stock 5.3.3 support stays frozen until the artist paints in the fork.
  *(Merged 56c7040: the whole repository, 464 files and 204 commits, under `creative-agent/` on `krita-agent`; suites pass
  there (Python 442, JS 392); AGENT-FORK.md switched to monthly merges, c1f3f3b; `digital_art/krita` frozen. Remaining:
  the fork's build installs the plugin into its own pykrita, and CI.)*
  *(19 October, the artist: 1.5 is a priority, since he is away from the laptop at times. Done: the build installs the plugin
  into `share/krita/pykrita` (`KRITA_AGENT_PLUGIN`), and `agent/ci.sh` runs every suite we own. Remaining: the plugin's
  enabling and Python packages on a fresh settings folder (3.3 and 1.3), and a CI service config when there is a remote.)*
- [ ] 1.6 Fork parity, first priority (the artist, 19 October): the fork must be at least as capable as stock Krita with
  the helper. Build the native helper inside the fork's tree for Qt6, installed and loaded with the app; pen pressure,
  tilt and speed through master's `paintPolylineStroke`; native seed selection; background save; the vetted Krita
  actions audited for the fork's version. Live check in the fork: accel, pen, select and save probes, and an Agent-mode
  chat.
  *(Merged 19 October: the helper builds and installs with the fork (one listed line in plugins/extensions/CMakeLists.txt),
  Qt6 fix; live on New Moscow in the fork: tilt 2→8 px, speed 48→28 px, pressure 1–60–1 px, 8 seeds 0.36 s, checkpoint
  6 ms; 10 Krita actions vetted (stock 11: mirrorNodeX not yet). Agent-mode chat in the fork, New Moscow clouds: 15 actions, 1066 strokes, Luna kept 4 of 4 batches, seam
  candidates reached the painter, no errors, no autosave. Remaining: mirrorNodeX vetted in the fork.)*
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
- [x] 2.4 Async stroke jobs: `Node.paintStrokes(strokes, options, selection) -> StrokeJob` (one freehand stroke per
  stroke with a `KisPaintInformation` per point, as `paintPolylineStroke` builds them) with state, progress and changed
  rect; each stroke reports its own end after its pixels land, so `job.wait()` waits for that job only; the companion
  polls jobs instead of waiting. The artist comes first: at most 32 job strokes queued at a time, no end requests, Esc
  ignored, the artist's Undo stops the job and is then carried out. Tests: nothing is lost when Krita is busy, and the
  window responds while a pass paints.
  *(Libkis side merged after a review and a fix round: `Node.paintStrokes` -> `StrokeJob`, windows of 32 topped up at
  half so the artist's strokes run between them, the artist's Ctrl+Z stops the job and then undoes, Krita's own
  cancellation leaves jobs alone, bounded GUI-thread waits, Wash brushes report after their merge. TestStrokeJobs 24 and
  TestPythonStrokeJobs 6 functions; the Wash test failed once in 27 author runs and 0 in 40 lead runs (watch it).
  Plugin side done on `agent/plugin-jobs`: `paint_pass` paints one `Node.paintStrokes` job on the fork (stage mask as
  the job's selection, pen input as given, Stop as `job.cancel()`, refresh of `changedRect()` only); stock keeps the
  helper and Python paths. Ruling: no bridge job registry. The plugin stays synchronous to the bridge and polls the job
  on the GUI thread (10 ms bounded waits with Qt events between them, since the feeder runs from the event loop); the
  companion already follows a pass through `.progress.json`, so it needs no polling of its own. The artist's Undo
  mid-pass is waited out (the deferred undo must land) before anything is observed, saved or recorded, and the pass is
  then `partial_change`; a job still painting at 100 s is cancelled (the bridge gives a pass 120 s); the artist's layer
  is active again as soon as the job starts. Remaining: the fork's cancel reason (script / undo / document closed; the
  plugin uses `StrokeJob.cancelReason()` when it exists), the fork cloning the preset at the call (the plugin restores
  smudge overlay mode only after the job ends until then), and the live checks in the fork: Stop mid-pass, Ctrl+Z
  mid-pass (also before the first stroke), the artist painting during a pass, pen inputs visibly applied, and a New
  Moscow measurement.)*
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
- [x] 2.9 (branch agent/traps; see AGENT-FORK.md) libkis traps fixed: `Filter.apply` undoable and selection-aware without blocking; undo for
  `Node.setPixelData`, `move` (done in 5.3: `Node.move` is one undo step) and `setOpacity`; `Selection.contract` and `resize` corrected; painting without an active
  view refused cleanly; per-stroke overrides (mirror, selection, composite op) so the view's state never leaks into
  agent strokes. Also (from the 5.3 review): libkis calls that run a stroke must not end the artist's open strokes
  (`setRequestsOtherStrokesToEnd(false)`) and must wait for their own stroke only, never `image->waitForDone()`, which
  ends open strokes and can hang while the artist's pen is down: `DocumentHistory::runCommandStroke` and the waits in
  `Node.cpp` and `Document.cpp`.
  And: 2.5's `collectDevices` cannot see inside a saved macro, so an artist's fill or gradient on another layer
  during an agent move splits the move (found by 5.3's tests).
  *(Future simplification of 2.9, from its review: a const walker on `KisSavedMacroCommand`, `LambdaCommand` and
  `KisProcessingCommand` so `DocumentHistory` reads the transactions of any artist stroke, replacing the thread-local
  `KisTouchedDevices` recording and the per-tool opt-ins, and covering every tool. Not done: the opt-ins work for the
  three tools that matter and cost a few ns per stroke.)*
- [ ] 2.6 Verify: the New Moscow and 1024×768 chunk times are within a factor of 1.5; an observe at 6000×4500 takes
  under 2 s.

## 3. Photoshop-like interface (`photoshop-workspace`)
- [ ] 3.1 Port Krita-Revamp's features from `revamp-5.2.14`, one commit each: clipping masks, folder groups, brush
  stroke previews, scrubby zoom, instant overview, toolbar sizing and smoothing slider, preset persistence.
  *(Survey done 19 October, creative-agent/openspec/changes/krita-fork/revamp-survey.md: scrubby zoom is already native on master (nothing to port); "instant overview" is a one-line constant that does nothing on master (re-tune and measure, may drop); Revamp's clipping mask is a view and a button on top of Krita's alpha inheritance (no format change; the spec's Alt-click between two layers is OUR addition, Revamp has none); preset persistence leaks tweaks into agent strokes (needs the agent gate); order: folder groups, clipping masks, toolbar sizing, preset persistence, smoothing slider, stroke previews, overview, hide-tabs/selection-hold later; three file-disjoint worktrees: layers, brush, shell; about 38 agent-hours of C++, 50 with 3.2 and 3.3.)*
- [ ] 3.2 Revamp's Python plugins, after 0.1: check each on Qt6, and drop those duplicated by native features.
- [ ] 3.3 New-install defaults: Photoshop shortcuts, the workspace with the agent panel, a dark theme.

## 4. The agent built in (`built-in-agent`)
- [ ] 4.1 The agent panel loads with the window; new-painting chats with no document open.
- [ ] 4.2 Project view docker.
- [ ] 4.3 Canvas overlays: protected areas, Luna's findings, the move in progress.

## 5. Native agent craft (`native-agent-craft`)
- [x] 5.1 `createBrushTip` and `createPreset` from scripts, without a restart; material-stamp offers Krita-brush stamps.
- [x] 5.2 `mergeGroups` and `FilterMask.bake` on `KisImage::mergeMultipleLayers` and `flattenLayer`;
  `merge_agent_work` uses them.
  *(Fork side merged 020af6a, after one review and a fix pass: `Krita.createBrushTip` / `createPreset` replace only the
  agent's own resources (else "name (2)"), `Document.mergeGroups` and `FilterMask.bake` refuse locked or hidden parents,
  bake keeps small layers small, both join an open agent move as one step (`KisProcessingApplicator::UndoFacadeOverride`,
  a listed upstream edit). Lead re-ran 14 suites through agent/run-tests.sh: all pass. Remaining for 5.1 and 5.2: the
  plugin side, material-stamp's Krita-brush stamps and `merge_agent_work` on mergeGroups / bake.)*
- [ ] 5.3 Tools as functions: bucket and enclose-and-fill, gradient, smart patch (moved out of its tool), undoable move,
  and perspective, warp and liquify baked through the transform workers.
  *(Part 1 on branch `agent/tools`, 19 October: `Node.fill(x, y, color, options, selection)`,
  `encloseAndFill(area, color, options, selection)`, `gradient(start, end, options, selection)`, `smartPatch(area,
  options)` and an undoable `Node.move(x, y) -> bool`, on `KisToolFunctions` (libs/ui), the tools' own strokes built
  from arguments with the tools' defaults; no view needed; locked layers, groups, the root, detached nodes and bad,
  non-finite or out-of-range options refused with a warning; one named step each, or part of an open agent move. The
  calls never ask the artist's open strokes to end and wait for their own stroke only (60 s, then cancelled and
  refused); the selection is read when the stroke runs; smart patch takes at most 512 x 512 pixels (about 5 s).
  Smart patch's `patchImage()` moved from its plugin into libs/image. The plugin's `move_layer` reports a refused
  move. TestNodeAgentTools 30 functions (plus a timing bench run only with TOOLS53_BENCH), TestPythonAgentTools 1
  function, plugin test_precision_move 2; each seen red first. Remaining: part 2, perspective, warp and liquify baked
  through the transform workers; fill with a pattern; moving a selection's pixels (the move tool with a selection);
  the spec's live scenario, smart patch on New Moscow's sky seam.)*

## 6. The feature map (`canvas-features`)
- [x] 6.1 `KisFeatureList` on `KisImage`: features with mask, name, kind, author, state, protected flag and measured
  properties; `KisKraSaver::saveFeatures` / `KisKraLoader::loadFeatures` on the storyboard pattern (`<features
  version="1">` in `maindoc.xml`, masks through Krita's paint-device writer); a `boost::geometry::index::rtree` over
  bounds. Tests: round trip, and stock Krita opens the file.
- [x] 6.2 libkis `Feature` and `Document.features()`, add, rename, remove; adding or removing a feature changes no
  pixel and is one undo step.
- [x] 6.1b Feature masks follow image operations: crop, canvas resize, scale, rotate, shear and mirror move and cut
  every mask in the same undo step, and a colour-space conversion re-measures the mean colour. Operations on some
  layers only, and the transform tool, change the painting under features like a brush stroke and leave masks alone.
  (Found by the 6.1 review; blocks 6.4/6.5 and any artist build that shows features.)
  *(6.1, 6.1b and 6.2 merged after two reviews and two fix rounds: KisFeatureList with an R-tree, `.kra` storage that
  later versions load, libkis `Feature` and add/rename/remove as one step or part of an agent move; masks follow crop,
  canvas size, scale, rotate, shear and mirror of the image with undo (KisFeatureImageCommand, one-line hooks listed in
  AGENT-FORK.md); names trimmed and de-duplicated; masks bounded to the document. Lead ran 17 suites through
  agent/run-tests.sh: all pass. Notes for 6.8: load re-measure cost, undo memory per image operation.)*
- [ ] 6.3 Builders: `fromSelection`, `similarColour`, `contiguous` (tool logic moved into functions), `snapOutline`
  (`KisMagneticWorker`), `segment` (lazy-brush). Test on runs 10 and 11: the skyline from 20 rough points leaves no
  band of old sky.
  *(Built on `agent/builders`, reviewed once; fix round done. `Document.maskFromSelection`, `maskContiguous`,
  `maskSimilarColor`, `maskSnapOutline`, `maskSegments` return a mask for `addFeature`; they read the image without ending
  the artist's stroke, cap their input and have a time limit. **NOT ticked: the skyline target is not met.** From 20 rough
  points the sky's edge sits on the painting's in the median column (band of old sky: median 1 px), but the 95th percentile
  is 129 px and 1721 of 4752 columns have a band over 10 px (the rough polygon: median 59 px, 95th percentile 236 px).
  The target is p95 <= 10 px (stretch goal 3 px); `testSkylineTarget` holds it as an expected failure. Follow-up, not
  done: run the builders on a worker thread over the snapshot, so a long call never blocks the GUI thread (today they
  process events meanwhile).)*
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

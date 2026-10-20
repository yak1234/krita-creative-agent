# Krita Agent: how this fork stays close to upstream

This is a fork of [KDE/krita](https://invent.kde.org/graphics/krita) `master`, built on Qt6. "Krita Agent" is a working
name; the artist chooses the final one (it is set in one place, `cmake/modules/KritaAppIdentity.cmake`). The built
application is GPL-3.0-or-later: it is a combined work of files under several compatible licences, distributed as a
whole under the GPL-3.0-or-later. Each new file takes the licence of the Krita library or folder it lives in, so it can
be offered upstream as it is: `LGPL-2.0-or-later` in `libs/libkis` and its tests, `GPL-2.0-or-later` in `libs/image`
and `libs/ui`, and elsewhere (`sdk/tests`, the pykrita plugin's Python package and tests) the licence of its
neighbours. New files carry
`SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>`. Build helpers in `agent/` stay as they are.

Our work lives on the branch `krita-agent`, kept current by merging upstream `master` into it. Upstream's history is
never rewritten here.

**One repository.** The creative agent itself lives in this tree under `creative-agent/`: the plugin (`krita-mcp`), the
companion (`krita-creative-agent`), the native helper (`krita-native`), the OpenSpec plan (`openspec/`) and docs,
merged with their history from `digital_art/krita` (task 1.5). Fork-first (the artist's decision, 19 October 2026):
artists download this Krita, so the agent is designed for it and new features may need it; stock Krita 5.3.3 support is
frozen. `creative-agent/` is entirely ours and never conflicts with upstream.
Upstream is the remote that points at `https://invent.kde.org/graphics/krita.git`: `origin` in this checkout (if a
clone's `origin` is our own fork, add KDE's as `upstream` and read `origin/master` below as `upstream/master`).

## Where our changes go

The fork exists for long-term speed, so each change has to be cheap to carry through a rebase:

1. **New files first.** New code goes in new files: new libkis classes and methods in their own `.cpp`, new dockers
   and plugins in their own folders, and build helpers in `agent/`. New files almost never conflict.
2. **Small, listed edits to upstream files.** When an existing file has to change, keep the edit small: a call into
   our new code, a CMake option, or an extra branch. Add the file to the table below in the same commit.
3. **One feature per commit**, with a plain message saying what changed and why. A rebase conflict then names the
   feature that needs a look.
4. **Defaults match upstream when switched off.** Each edit is behind a configure option or identity value. With the
   option at upstream's value the code behaves exactly as stock Krita, so an edit can be offered upstream as it is.

## Upstream files we edit

Keep this table current: every upstream file the `krita-agent` branch changes, and why. New files are not listed
(they are ours); `git diff --stat origin/master...krita-agent` lists everything.

| File | Why | Feature |
|---|---|---|
| `.gitignore` | One block at the end: `agent/build-macos.sh`'s local setup (`env.sh`, `venv`, `cache`, `_krita-tools`, `_stand-ins`, `krita-deps-management`, logs). A nested `.gitignore` cannot ignore top-level paths, and `.git/info/exclude` is not tracked | build (1.4) |
| `CMakeLists.txt` | `include(KritaAppIdentity)`: the build's identity options | identity (1.1) |
| `krita/CMakeLists.txt` | Bundle id and name from the identity; macOS Quick Look/Spotlight extensions optional (they need Xcode and claim Krita's file types; `ff7ec1b` bundled this option with the identity); the Info.plist through `krita_app_identity_info_plist()` (never claims Krita's types) and its check as a test; the identity's qrc (shipped `kritarc` defaults under the identity's config name) | identity (1.1) |
| `krita/main.cc` | `KisAppIdentity::initialize()` first; single-instance key, display name, organization domain, config and crash-log paths from the identity | identity (1.1) |
| `libs/global/CMakeLists.txt` | Builds `KisAppIdentity.cpp` and its generated `config-app-identity.h` | identity (1.1) |
| `libs/global/KisUsageLogger.cpp` | `krita.log`, `krita-sysinfo.log` in the identity's log folder, `kritacrash.log` in its crash-log folder (upstream's config folder when stock) | identity (1.1) |
| `libs/image/CMakeLists.txt` | Builds `KisImageChangeReports.cpp` | change reports (2.2, 2.8) |
| `libs/image/kis_image.cc` | `requestProjectionUpdate()` reports each node's redraw request, with the current level of detail, to `KisImageChangeReports` (one call; a Qt signal with no receivers otherwise) | change reports (2.2, 2.8) |
| `libs/libkis/CMakeLists.txt` | Builds `DocumentChanges.cpp` and `NotifierExtras.cpp` | change reports (2.2, 2.8) |
| `libs/libkis/Document.h` | Declares `revision()`, `changedRect()`, `setAgentActive()`, `agentActive()`, `changeSource()` (defined in `DocumentChanges.cpp`), in a block of their own before the first `public Q_SLOTS:` | change reports (2.2) |
| `libs/libkis/Krita.cpp` | `createDocument()` starts the new document's change report (`DocumentChanges::forImage`), since it adds the document without a notification | change events (2.2) |
| `libs/libkis/Notifier.h`, `Notifier.cpp` | Declares the change signals (`imageChanged`, `nodeAdded`, `nodeRemoved`, `nodeChanged`, `nodePixelsChanged`, `selectionChanged`, `undoIndexChanged`, `documentModified`, `activeNodeChanged`, `toolChanged`, `brushPresetChanged`); the constructor creates `NotifierExtras`, which emits them | change events (2.2, 2.8) |
| `libs/libkis/tests/CMakeLists.txt` | Adds `TestDocumentChanges`, `TestNotifierChanges` | change reports (2.2, 2.8) |
| `plugins/extensions/CMakeLists.txt` | Adds `creative-agent/` (its `CMakeLists.txt`) when the tree has it: the creative agent's native helper (`creative-agent/krita-native/agent-accel`) built and installed with the app as a Krita plugin, its self-tests under ctest with `BUILD_TESTING`; `-DKRITA_AGENT_NATIVE_HELPER=OFF` builds upstream's plugins only | fork parity (1.6) |
| `plugins/extensions/pykrita/CMakeLists.txt` | Adds `tests` (Python-side tests) when `BUILD_TESTING` is on | change events (2.2, 2.8) |
| `plugins/extensions/pykrita/sip/krita/Document.sip`, `Notifier.sip` | The same methods and signals for Python | change reports (2.2, 2.8) |
| `libs/global/tests/CMakeLists.txt` | Adds `KisAppIdentityTest` | identity (1.1) |
| `libs/macosutils/KisMacosSecurityBookmarkManager.mm` | `securitybookmarkrc` in the identity's config folder (through the organization name: this library sits below `kritaglobal`) | identity (1.1) |
| `libs/ui/KisApplication.cpp` | `kritarc` reset/backup in the identity's config folder | identity (1.1) |
| `libs/ui/KisAutoSaveRecoveryDialog.cpp`, `.h` | Autosaves of never-saved documents, and the start-up recovery that deletes those not recovered, in the identity's own folder, never stock Krita's home or temp folder; the class exported so `KisAutoSaveLocationTest` can call it | identity (1.1) |
| `libs/ui/KoDocumentInfo.cpp` | Author info read from the identity's `kritarc` | identity (1.1) |
| `libs/ui/kis_config.cc` | `kritadisplayrc` and other config files in the identity's config folder | identity (1.1) |
| `libs/ui/dialogs/kis_dlg_preferences.cc` | Same, for the preferences dialog | identity (1.1) |
| `libs/ui/dialogs/KisDlgCustomTabletResolution.cpp` | Same, for the tablet resolution setting | identity (1.1) |
| `libs/ui/opengl/kis_opengl.cpp` | Same, for the OpenGL settings | identity (1.1) |
| `libs/ui/tests/CMakeLists.txt` | Adds `KisAutoSaveLocationTest` | identity (1.1) |
| `libs/widgetutils/kis_action_registry.cpp` | `kritashortcutsrc` in the identity's config folder | identity (1.1) |
| `libs/widgetutils/xmlgui/KisShortcutsEditor.cpp` | Same | identity (1.1) |
| `libs/widgetutils/xmlgui/kbugreport.cpp` | Logs read from the identity's log folder | identity (1.1) |
| `libs/widgetutils/xmlgui/kswitchlanguagedialog_p.cpp` | Language override file in the identity's config folder | identity (1.1) |
| `plugins/extensions/buginfo/DlgCrashLog.cpp`, `DlgKritaLog.cpp`, `DlgSysInfo.cpp`, `dlg_buginfo.cpp` | Logs read from the identity's folders | identity (1.1) |
| `plugins/extensions/pykrita/kritarunner/main.cpp` | `KisAppIdentity::initialize()` first, and the identity's organization domain | identity (1.1) |
| `plugins/tools/karbonplugins/tools/CalligraphyTool/KarbonCalligraphyOptionWidget.cpp` | `karboncalligraphyrc` in the identity's config folder | identity (1.1) |
| `plugins/python/scripter/scripter.py` | `krita-scripterrc` in the identity's config folder | identity (1.1) |
| `libs/libkis/Document.h` | Declares `refreshProjection(QRect)` (region refresh) and `projection(QRect, scale)` (scaled read); bodies in our `DocumentAgentSpeed.cpp` | region refresh (2.1), scaled read (2.3) |
| `libs/libkis/Node.cpp`, `Node.h` | `setPixelData` marks its own rect dirty (one line), documented | region refresh (2.1) |
| `libs/libkis/CMakeLists.txt` | Builds `DocumentAgentSpeed.cpp` | region refresh (2.1) |
| `libs/libkis/tests/CMakeLists.txt` | Registers our libkis tests and the `AgentSpeedBenchmark` program | region refresh (2.1), scaled read (2.3) |
| `plugins/extensions/pykrita/sip/krita/Document.sip` | Python bindings of `refreshProjection(QRect)` and `projection(QRect, scale)` | region refresh (2.1), scaled read (2.3) |
| `libs/libkis/Document.h`, `plugins/extensions/pykrita/sip/krita/Document.sip` | One block at the end of the public slots: undo history (`undoCount`, `undoText`, `undoIndex`, `setUndoIndex`, `cleanIndex`), macros (`beginUndoMacro`, `endUndoMacro`) and agent moves (`beginAgentMove`, `endAgentMove`, `agentMoveOpen`, `agentMoveName`), implemented in `DocumentHistory.cpp` | undo history (2.7, 2.5) |
| `libs/libkis/Node.h`, `Node.cpp`, `plugins/extensions/pykrita/sip/krita/Node.sip` | The six `paint*` calls take an optional last argument `name` for their undo step; inside a macro or agent move `setPixelData` queues its write as a stroke of the step (one line before `writeBytes`, `DocumentHistory::queuePixelWrite`); the single-command strokes (`addChildNode`, `remove`, `setBlendingMode`, `setLayerStyleFromAsl`) run through `DocumentHistory::runCommandStroke`, which is upstream's `runSingleCommandStroke` outside a macro or move | undo history (2.7, 2.5) |
| `libs/libkis/PaintingResources.h`, `.cpp` | `createHelper` names the stroke (`DocumentHistory::scriptedStrokeName`: the given name, else the open agent move's, else upstream's "Scripted Brush Stroke") and hands it the open step's undo adapter | undo history (2.7, 2.5) |
| `libs/libkis/CMakeLists.txt`, `libs/libkis/tests/CMakeLists.txt` | Builds `DocumentHistory.cpp` and `TestDocumentHistory` | undo history (2.7, 2.5) |
| `libs/libkis/Filter.cpp` | `startFilter` hands its stroke the open step's undo adapter | undo history (2.5) |
| `libs/libkis/Document.cpp` | `setSelection` runs as a stroke of an open macro or move (`runCommandStrokeInStep`), else as upstream | undo history (2.5) |
| `libs/libkis/VectorLayer.cpp`, `TransformMask.cpp`, `Shape.cpp` | Their single-command strokes go through `DocumentHistory::runCommandStroke` | undo history (2.5) |
| `libs/ui/kis_document_undo_store.cpp` | `KisAgentHooks::beforeAddCommand` before each command joins the document's history (any thread); `beforeBeginMacro` and `afterEndMacro` around the stack's macros | undo history (2.5) |
| `libs/ui/KisDocument.cpp` | `KisAgentHooks::beforeHistoryMove` in the undo stack's `undo`, `redo`, `setIndex`; `KisAgentHooks::beforeSave` at the start of `exportDocumentImpl`, except for exports | undo history (2.5) |
| `libs/ui/tool/kis_resources_snapshot.h`, `.cpp` | `setPostExecutionUndoAdapterOverride`: a stroke's full-resolution commands go to another adapter (level-of-detail previews keep the image's) | undo history (2.5) |
| `libs/ui/tool/kis_figure_painting_tool_helper.h`, `.cpp` | An optional last constructor argument, the undo adapter override for its stroke | undo history (2.5) |
| `libs/ui/CMakeLists.txt` | Builds `KisAgentHooks.cpp` | undo history (2.5) |
| `libs/image/kis_transaction_data.h`, `.cpp` | `device()`: the device a transaction changes | undo history (2.5) |
| `libs/command/kis_command_utils.h` | `CompositeCommand::commands()`: the commands it holds | undo history (2.5) |
| `plugins/extensions/pykrita/plugin/krita/__init__.py` | Installs `Document.agentMove(name)` (`agentmove.py`) | undo history (2.5) |
| `plugins/extensions/pykrita/tests/CMakeLists.txt` | Adds `TestPythonAgentMove` | undo history (2.5) |
| `libs/libkis/Krita.h` | Declares `createBrushTip()` and `createPreset()` (two overloads each), in a block of their own after `resources()`; bodies in our `KritaAgentResources.cpp` | brush tips and presets (5.1) |
| `libs/libkis/Resource.h` | `friend class Krita` (one line), so `createPreset()` reads the base and tip resources | brush tips and presets (5.1) |
| `libs/libkis/CMakeLists.txt`, `libs/libkis/tests/CMakeLists.txt` | Build `KritaAgentResources.cpp`; add `TestKritaAgentResources` | brush tips and presets (5.1) |
| `plugins/extensions/pykrita/sip/krita/Krita.sip` | Python bindings of `createBrushTip()` and `createPreset()` | brush tips and presets (5.1) |
| `libs/libkis/Document.h` | Declares `mergeGroups()`, in a block of its own after `flatten()`; body in our `DocumentAgentCraft.cpp` | merge (5.2) |
| `libs/libkis/CMakeLists.txt`, `libs/libkis/tests/CMakeLists.txt` | Build `DocumentAgentCraft.cpp`; add `TestDocumentAgentCraft` | merge (5.2) |
| `plugins/extensions/pykrita/sip/krita/Document.sip` | Python binding of `mergeGroups()` | merge (5.2) |
| `libs/libkis/FilterMask.h` | Declares `bake()`; body in our `FilterMaskBake.cpp` | bake (5.2) |
| `libs/libkis/CMakeLists.txt`, `libs/libkis/tests/CMakeLists.txt` | Build `FilterMaskBake.cpp`; add `TestFilterMaskBake` | bake (5.2) |
| `plugins/extensions/pykrita/sip/krita/FilterMask.sip` | Python binding of `bake()` | bake (5.2) |
| `libs/image/kis_processing_applicator.h`, `.cpp` | `KisProcessingApplicator::UndoFacadeOverride`: while one lives, the applicators its thread creates send their undo step to the given facade instead of the image's history (a thread-local pointer read in the constructor; none set is upstream's behaviour). `mergeGroups()` sets it around Krita's merge so the merge joins an open agent move or macro | merge (5.2), undo history (2.5) |
| `libs/image/kis_image.h`, `kis_image.cc` | A `KisFeatureList` member: `featureList()`, created with the image's bounds and copied in `copyFromImageImpl()` (so clones for saving and snapshots carry the features) | feature map (6.1) |
| `libs/image/CMakeLists.txt`, `libs/image/tests/CMakeLists.txt` | Build `KisFeature.cpp`, `KisFeatureList.cpp`, `KisFeatureCommands.cpp`, `KisFeatureImageCommand.cpp`; add `KisFeatureListTest`, `KisFeatureImageCommandTest` | feature map (6.1, 6.1b) |
| `libs/image/kis_image.cc` | Feature masks follow the image: five `applicator.end()` calls become `KisFeatureImageCommand::endApplicator(...)` (one line each, marked `// Krita Agent`): `resizeImageImpl()` (crop and canvas resize), `scaleImage()`, `rotateImpl()` and `shearImpl()` (image only: a null image for layer rotations and shears ends as upstream), `convertImageColorSpaceImpl()` (measures the mean colours again); plus the include. With no features each ends exactly as upstream | feature map (6.1b) |
| `libs/ui/kis_node_manager.cpp` | `mirrorNodes()` ends with `KisFeatureImageCommand::endMirrorApplicator(...)` (one line, and the include): Mirror Image and Mirror All Layers without a selection mirror the masks; everything else ends as upstream | feature map (6.1b) |
| `libs/ui/tests/CMakeLists.txt` | Adds `KisFeatureMirrorTest` (Mirror Image through a real `KisNodeManager`) | feature map (6.1b) |
| `plugins/impex/libkra/kis_kra_saver.h`, `.cpp` | `saveFeatures()` (the masks) and `saveFeaturesToXML()` (one call at the end of `saveXML()`), both calling `KisKraFeatures` | feature map (6.1) |
| `plugins/impex/libkra/kis_kra_loader.h`, `.cpp` | `loadXML()` keeps the `<features>` element (one branch); `loadFeatures()` hands it to `KisKraFeatures::load()` | feature map (6.1) |
| `plugins/impex/libkra/kra_converter.cpp` | Calls `saveFeatures()` after the storyboards and `loadFeatures()` after them | feature map (6.1) |
| `plugins/impex/libkra/CMakeLists.txt`, `tests/CMakeLists.txt` | Build `KisKraFeatures.cpp`; add `KisKraFeaturesTest` | feature map (6.1) |
| `libs/libkis/Document.h` | Declares `features()`, `feature()`, `addFeature()`, `renameFeature()`, `removeFeature()` (defined in `DocumentFeatures.cpp`, their commands run through `DocumentHistory::runCommandStroke`, so inside an agent move they join its step), in a block of their own after the change-report block | feature map (6.2) |
| `libs/libkis/CMakeLists.txt`, `libs/libkis/tests/CMakeLists.txt` | Build `DocumentFeatures.cpp`, `Feature.cpp`; add `TestDocumentFeatures` | feature map (6.2) |
| `plugins/extensions/pykrita/sip/krita/Document.sip`, `kritamod.sip` | The feature methods for Python; includes our `Feature.sip` | feature map (6.2) |
| `libs/libkis/Node.h`, `Node.cpp`, `plugins/extensions/pykrita/sip/krita/Node.sip` | `move()` returns `bool` and is one undo step (its body moved to our `NodeAgentTools.cpp`, the old body removed from `Node.cpp`); a block after `position()` declares `fill()`, `encloseAndFill()`, `gradient()` and `smartPatch()`, bodies in `NodeAgentTools.cpp` | tools as functions (5.3) |
| `libs/libkis/Selection.h` | `friend class Node` (one line), so the tool functions read a script's selection | tools as functions (5.3) |
| `libs/libkis/CMakeLists.txt`, `libs/libkis/tests/CMakeLists.txt` | Build `NodeAgentTools.cpp`; add `TestNodeAgentTools` | tools as functions (5.3) |
| `libs/ui/CMakeLists.txt` | Builds our `processing/KisToolFunctions.cpp` (the fill, enclose-and-fill, gradient, smart patch and move strokes as functions) | tools as functions (5.3) |
| `libs/ui/tool/kis_resources_snapshot.cpp` | `setupPainter()` skips the paintop when the snapshot has no preset (one `if`): a snapshot made without a canvas, as the tool functions make, would otherwise dereference a null preset; fills need no paintop | tools as functions (5.3) |
| `plugins/tools/tool_smart_patch/kis_inpaint.cpp` → `libs/image/kis_inpaint.cpp` | Moved (git mv) out of the Smart Patch tool's plugin into the image library, so scripts can patch; one line added (`#include "kis_inpaint.h"`, our new header exporting `patchImage()`); its file-scope classes (`ImageView`, `ImageData`, `MaskedImage`, `NearestNeighborField`, `Inpaint`) and helpers keep their global names, unchanged so the move stays a plain rename: no other file in `libs/` defines these names, and the library's hidden visibility keeps them out of other libraries and plugins, but a future file in `libs/image` must not reuse them (one definition rule); `libs/image/CMakeLists.txt` builds it, the plugin's `CMakeLists.txt` no longer does, and `kis_tool_smart_patch.cpp` includes the header instead of declaring `patchImage()` | tools as functions (5.3) |
| `plugins/extensions/pykrita/tests/CMakeLists.txt` | Adds `TestPythonAgentTools` | tools as functions (5.3) |
| `libs/libkis/Node.h` | Declares `paintStrokes()` (after `paintPolylineStroke()`), with `#include <QVariant>` and a forward declaration of `StrokeJob`; body in our `NodeStrokeJobs.cpp` | stroke jobs (2.4) |
| `libs/libkis/Selection.h` | `friend class Node` (one line), so `paintStrokes()` clips its strokes to a given selection | stroke jobs (2.4) |
| `libs/libkis/CMakeLists.txt`, `libs/libkis/tests/CMakeLists.txt` | Build `NodeStrokeJobs.cpp` and `StrokeJob.cpp`; add `TestStrokeJobs` and the `AgentStrokeJobsBenchmark` timing program | stroke jobs (2.4) |
| `plugins/extensions/pykrita/sip/krita/Node.sip`, `kritamod.sip` | Python binding of `paintStrokes()`; `%Include StrokeJob.sip` | stroke jobs (2.4) |
| `plugins/extensions/pykrita/tests/CMakeLists.txt` | Adds `TestPythonStrokeJobs` | stroke jobs (2.4) |
| `libs/image/KisMagneticWorker.h`, `KisMagneticWorker.cc`, `KisMagneticGraph.h` | Moved from `plugins/tools/selectiontools/` into `kritaimage` (export macro `KRITAIMAGE_EXPORT`), so `snapOutline` can trace edges without the tool; the magnetic tool includes it from there. Edited, in a commit of their own ("KisMagneticWorker: search on flat arrays"): the search keeps its per-vertex data in flat vectors over the search rectangle instead of `std::map`s (a 20-point outline of a 6000x4500 painting went from 40 s to 1 s); `computeEdge()` takes an optional `KisMagneticSearchLimits` (a corridor of `bounds` pixels around the line between the points; a give-up callback asked every 4096 vertices), which the tool does not pass; the rectangle is cut to the image and the lazy filter only touches tiles that exist (a radius past the top or left edge gave negative tile numbers, past the right edge the next row's); no graph is kept between calls (it was leaked each time), and `intensity()` reads the filtered device directly; the first neighbour of a vertex is checked against the rectangle too; helper types and functions of the graph header are in an unnamed namespace and inline | feature builders (6.3) |
| `plugins/tools/selectiontools/CMakeLists.txt` | No longer builds `KisMagneticWorker.cc` (`kritaimage` does) | feature builders (6.3) |
| `libs/image/CMakeLists.txt` | Builds `KisMagneticWorker.cc` and `KisFeatureBuilders.cpp` | feature builders (6.3) |
| `libs/libkis/Document.h`, `plugins/extensions/pykrita/sip/krita/Document.sip` | Declare `maskFromSelection()`, `maskContiguous()`, `maskSimilarColor()`, `maskSnapOutline()`, `maskSegments()` in a block of their own after `removeFeature()`; bodies in our `DocumentFeatureBuilders.cpp` | feature builders (6.3) |
| `libs/libkis/CMakeLists.txt`, `libs/libkis/tests/CMakeLists.txt`, `plugins/extensions/pykrita/tests/CMakeLists.txt` | Build `DocumentFeatureBuilders.cpp`; add `TestDocumentFeatureBuilders` and `TestPythonFeatureBuilders` | feature builders (6.3) |
| `libs/libkis/DocumentAgentSpeed.cpp` | `tryReadLockWithoutEndingStrokes` moved unchanged into our `KisAgentReadLock.h` (`tryLock`, `Scoped`), shared with the builders | feature builders (6.3), scaled read (2.3) |
| `libs/image/tests/CMakeLists.txt` | Adds `KisMagneticWorkerTest` | feature builders (6.3) |
| `libs/image/kis_transaction_data.cpp` | One line at the end of the constructor: `KisTouchedDevices::noteChanged(device)` (a thread-local read; nothing recorded unless a stroke asked) | libkis traps (2.9, item 7) |
| `libs/image/kis_stroke_strategy_undo_command_based.h`, `.cpp` | `setReportsTouchedDevices()` (a stroke records the devices its transactions change and reports them with its undo step); `executeCommand` and the step's hand-over each wrap one `KisTouchedDevices` scope. Off by default | libkis traps (2.9, item 7) |
| `libs/image/kis_processing_applicator.h`, `.cpp` | `REPORTS_TOUCHED_DEVICES` flag (the applicator's strategy reports its devices); `NoEndRequestsOverride` (a thread-local read by `KisImage::startStroke`; it also lists the strokes started under it, so a script can cancel them) | libkis traps (2.9, items 6, 7) |
| `libs/image/kis_image.cc` | `startStroke()` skips `requestStrokeEnd()` while a `NoEndRequestsOverride` lives on the thread (one condition), and tells the override which stroke it started (one call) | libkis traps (2.9, item 6) |
| `libs/image/CMakeLists.txt` | Builds `KisTouchedDevices.cpp` | libkis traps (2.9) |
| `plugins/tools/basictools/kis_tool_fill.cc`, `kis_tool_gradient.cc`, `plugins/tools/tool_enclose_and_fill/KisToolEncloseAndFill.cpp` | One line each: the tool's stroke reports the devices it changes (`setReportsTouchedDevices(true)`, or the applicator flag), so an agent move splits only when the artist touches a layer the move touched | libkis traps (2.9, item 7) |
| `libs/ui/tool/kis_resources_snapshot.h`, `.cpp` | `setCompositeOpId()` and `setGlobalAlphaLock()`, so a script's stroke sets its own | libkis traps (2.9, item 5) |
| `libs/ui/tool/kis_figure_painting_tool_helper.h`, `.cpp` | An optional last constructor argument, a function that configures the stroke's resources (mirror, blending mode, alpha lock, opacity) before it starts | libkis traps (2.9, item 5) |
| `libs/libkis/Node.cpp`, `Document.cpp`, `Filter.cpp`, `FillLayer.cpp`, `Shape.cpp`, `VectorLayer.cpp`, `Selection.cpp`, `Selection.h`, `PaintingResources.cpp`, `.h`, `DocumentHistory.cpp`, `.h`, `NodeAgentTools.cpp`, `DocumentFeatures.cpp`, `FilterMaskBake.cpp`, `DocumentAgentCraft.cpp`, `DocumentAgentSpeed.cpp`, `KritaAgentResources.cpp`, `Document.h` | The traps: waits for the call's own stroke (`ScriptWaits`), no `waitForDone()` in libkis's own calls, undo for `setOpacity`, `setName`, `setVisible`, `setPixelData`, `Filter.apply` (selection-aware); `Selection.contract` and `resize` corrected; painting refused without a view; per-stroke overrides; `Document.waitForDone()` documented | libkis traps (2.9) |
| `plugins/extensions/pykrita/sip/krita/Filter.sip` | `Filter.apply` returns `bool` (it was declared `void`, so Python got None for a refusal) | libkis traps (2.9) |
| `plugins/extensions/pykrita/sip/krita/Node.sip` | `paintLine` takes `QPointF` (it was `QPoint`, though libkis takes `QPointF`) | libkis traps (2.9) |
| `libs/libkis/CMakeLists.txt`, `libs/libkis/tests/CMakeLists.txt`, `plugins/extensions/pykrita/tests/CMakeLists.txt` | Build `ScriptWaits.cpp`; add `TestLibkisTraps`, `TestLibkisNoView`, `TestPythonTraps` | libkis traps (2.9) |

Our own files for the identity: `cmake/modules/KritaAppIdentity.cmake`, `libs/global/KisAppIdentity.{h,cpp}`,
`libs/global/config-app-identity.h.cmake`; tests `libs/global/tests/KisAppIdentityTest.{h,cpp}`,
`libs/ui/tests/KisAutoSaveLocationTest.{h,cpp}` and `sdk/tests/KisTemporaryHomeTest.h` (runs a test in a temporary
home, so tests never touch the user's files; `sdk/tests/KisTemporaryHomeUiTest.h` does the same for tests that need
Krita's resources, as `KISTEST_MAIN` does in the real home, with fontconfig limited to one bundled font). Build helpers and the identity gate: `agent/`. This document:
`AGENT-FORK.md`.

The change-report edits to `libs/image/kis_image.cc`, `libs/libkis/Notifier.cpp` and `libs/libkis/Krita.cpp` are not
behind a configure option (an exception to rule 4): with nothing listening they change no behaviour. A node redraw
request then costs one call and Qt's check for receivers; with listeners, a request on an image without a report
skips all locks unless some image has one, and costs about 0.1 µs when one does, 0.15 µs on an image with a report,
and 0.3 µs with a Notifier queueing it (4 threads at once, measured by `TestDocumentChanges benchmarkDirtyRequests`),
against about 3 µs for the request itself.

Our own files for change reports and events (2.2, 2.8): `libs/image/KisImageChangeReports.{h,cpp}`,
`libs/libkis/DocumentChanges.{h,cpp}` (revision, changed areas and the agent/artist source of an image; C++ callers
mark agent work with `DocumentChanges::forImage(image)->beginAgentWork()` / `endAgentWork()`),
`libs/libkis/NotifierExtras.{h,cpp}`; tests `libs/libkis/tests/TestDocumentChanges.{h,cpp}`,
`libs/libkis/tests/TestNotifierChanges.{h,cpp}`, `libs/libkis/tests/ChangeEventRecorder.h`, and
`plugins/extensions/pykrita/tests/` (`TestPythonChangeEvents`: embeds Python and imports the built `krita` module).

Our own files for fork parity (1.6): `creative-agent/CMakeLists.txt` (the `KRITA_AGENT_NATIVE_HELPER` option, on by
default) and the helper itself, `creative-agent/krita-native/agent-accel` (a `KisActionPlugin`; the plugin finds its
`creative-agent-accel` object on the application). Its self-tests: `ctest --test-dir _build -R kritaagentaccel`.

Our own files for the feature map (6.1, 6.1b, 6.2): `libs/image/KisFeature.{h,cpp}` (a feature: name, kind, author,
state, protected flag, 8-bit tiled mask, measured bounds, area and mean colour), `libs/image/KisFeatureList.{h,cpp}`
(the document's list with an R-tree over bounds, owned by `KisImage`), `libs/image/KisFeatureCommands.{h,cpp}` (add,
remove, rename as undo commands), `libs/image/KisFeatureImageCommand.{h,cpp}` (masks follow crop, canvas resize,
scale, rotate, shear and mirror of the image, and are measured again after those and a colour-space conversion, in the
operation's undo step), `plugins/impex/libkra/KisKraFeatures.{h,cpp}` (the `.kra` format: a `<features version="1">`
child of `<IMAGE>` in `maindoc.xml`, appended after the layers and before `<animation>`, never first; one mask per
feature in `<image>/features/`; later versions are read as far as this one understands them),
`libs/libkis/Feature.{h,cpp}`, `libs/libkis/DocumentFeatures.cpp`, `plugins/extensions/pykrita/sip/krita/Feature.sip`;
tests `libs/image/tests/KisFeatureListTest`, `libs/image/tests/KisFeatureImageCommandTest`,
`libs/ui/tests/KisFeatureMirrorTest`,
`plugins/impex/libkra/tests/KisKraFeaturesTest`, `libs/libkis/tests/TestDocumentFeatures`,
`plugins/extensions/pykrita/tests/TestPythonFeatures`. The `KisImage`, `KisNodeManager` and `.kra` edits are not behind
a configure option (an exception to rule 4): a document without features writes no element and no file, so its `.kra`
is what stock Krita writes, an image operation on it runs as upstream, and an empty list costs one object per image.
Stock Krita opens our `.kra` files but drops their features: saving the file again from stock Krita loses them.

Our own files for the feature builders (6.3): `libs/libkis/KisAgentReadLock.h`, `libs/image/KisFeatureBuilders.{h,cpp}` (the selection tools' logic as
functions on a reference device: the contiguous and similar colour searches through `KisFillPainter`, grow, shrink,
feather and anti-alias through Krita's selection filters, edge tracing through `KisMagneticWorker`, and lazy-brush
segmentation through the colorize mask's own `KisColorizeStrokeStrategy`, run as a stroke that is never undoable,
never asks other strokes to end and never runs at a lower level of detail), `libs/libkis/DocumentFeatureBuilders.cpp`;
tests `libs/libkis/tests/TestDocumentFeatureBuilders` (with the New Moscow skyline: it copies
`digital_art/new_moscow_finished.kra`, or `$KRITA_AGENT_NEW_MOSCOW`, into a temporary folder; it runs only with
`KRITA_AGENT_SLOW_TESTS=1` and skips when the file is missing), `libs/image/tests/KisMagneticWorkerTest` and
`plugins/extensions/pykrita/tests/TestPythonFeatureBuilders`. The builders change no pixel, selection or undo history;
only `addFeature()` of their result is a step. Each call reads the image under a read-only barrier lock that never ends
the artist's stroke (`tryBarrierLock`, retried), works on a copy, takes capped input and has a time limit (`timeoutMs`,
5 s, at most 30 s); on a busy image or a spent limit it gives None with a warning. They still run on the GUI thread (the
events are processed meanwhile): moving the work to a worker thread over the snapshot is a follow-up (tasks.md 6.3).

**The skyline target of 6.3 is NOT met.** On New Moscow, 20 rough points give a sky whose edge is within 2 px of the
painting's in the median column (median band of old sky 1 px), but the 95th percentile is 129 px and 1721 of 4752
columns have a band over 10 px: along the misty horizon and the sky-coloured glass towers the flood leaks or stops short.
The test `testSkylineRegressionFloor` guards what is reached; `testSkylineTarget` holds the target (95th percentile
within 10 px, stretch goal 3 px) as an expected failure that flips when it is met.

Feature masks and image operations (6.1b): Image > Crop, Resize Canvas, Scale, Rotate, Shear, Mirror Image and
Layer > Mirror All Layers without a selection move the masks (they are one path in `KisNodeManager::mirrorNodes`).
Rotate, Shear and Scale All Layers, the transform tool, and any mirror of a selected area or of some layers do not:
they change the painting under the features like a brush stroke does, and the features keep their masks. Notes for
task 6.8 (memory): loading measures every mask once (one pass over its non-default tiles); each image operation keeps
each feature's mask before and after it in the undo step (the "after" mask is new tiles for a transform, shared tiles
for a colour conversion), so undo memory grows by about one mask per feature per operation.

Our own files for the agent speed API (2.x): `libs/libkis/DocumentAgentSpeed.cpp`, `libs/libkis/KisAgentScaledRead.h` and its tests in `libs/libkis/tests/`
(`TestDocumentRegionRefresh`, `TestDocumentScaledProjection`, and the `AgentSpeedBenchmark` timing program, not run by
ctest).

Our own files for brush tips and presets (5.1): `libs/libkis/KritaAgentResources.cpp` and its test `libs/libkis/tests/TestKritaAgentResources.{h,cpp}`.
Our own files for merge and bake (5.2): `libs/libkis/DocumentAgentCraft.cpp` (`Document::mergeGroups()`) and its test `libs/libkis/tests/TestDocumentAgentCraft.{h,cpp}`, with `libs/libkis/tests/AgentCraftTestUtils.h`; `libs/libkis/FilterMaskBake.cpp` (`FilterMask::bake()`) and its test `libs/libkis/tests/TestFilterMaskBake.{h,cpp}`.
Python-side test of both (5.1, 5.2): `plugins/extensions/pykrita/tests/TestPythonAgentCraft.{h,cpp}`.

Brush tips and presets the agent makes (5.1) replace only the agent's own: a resource tagged "Agent" in the resource
folder, of the same name and file format. A name that belongs to any other resource (Krita's own, the artist's, a
bundle's or a document's) is never overwritten; the new resource takes "name (2)" (or the next free number).
Replacing a tip is deliberate and reaches every preset that uses it, the artist's included: presets find their tip by
checksum, which leads to the resource and its latest version. How a tip is applied ("image" or "lightness") is
recorded in the resource database only (a `.gbr` file has no field for it); presets keep it in their own files.
Merge and bake (5.2) refuse locked nodes and nodes in locked or hidden groups, and inside an agent move or macro each
is part of that one undo step (bake runs one command through `DocumentHistory::runCommandStroke`; merge runs Krita's
own merge under `KisProcessingApplicator::UndoFacadeOverride` with `DocumentHistory::scriptUndoFacade`).

Our own files for stroke jobs (2.4): `libs/libkis/NodeStrokeJobs.cpp` (`Node::paintStrokes()`),
`libs/libkis/StrokeJob.{h,cpp}` (the job), `libs/libkis/StrokeJobShared.h` (internal: the state a job shares with its
strokes, the feeder, and `StrokeJobStrokeStrategy`, Krita's freehand stroke reporting its start and end), and the step
holds in our `DocumentHistory.{h,cpp}`,
`plugins/extensions/pykrita/sip/krita/StrokeJob.sip`; tests `libs/libkis/tests/TestStrokeJobs.{h,cpp}`,
`plugins/extensions/pykrita/tests/TestPythonStrokeJobs.{h,cpp}`, and the `AgentStrokeJobsBenchmark` timing program.

### Stroke jobs

`Node.paintStrokes(strokes, options, selection) -> StrokeJob` (GUI thread) reads and checks every stroke first (points
inside the image grown by one brush size; at most 10000 strokes of 10000 points; per-point lists one value per point),
then returns at once. Each stroke is one freehand stroke (Krita's `FreehandStrokeStrategy`, as master's
`paintPolylineStroke` builds them, with a `KisPaintInformation` per point: pressure, tilt, rotation, speed, time). The
job's brush is its own: a private canvas resource provider with the named preset (or a copy of the active view's
preset), the preset's blending mode unless one is given ("erase" erases), no mirror, no eraser mode or alpha lock from
the view, and the selection given or none. So no view is needed, and nothing the artist sets in the view leaks into
agent strokes.

**The artist comes first** (the lead's ruling). A feeder on the GUI thread (`StrokeJobFeeder`) keeps at most 32 of a
job's strokes queued and tops them up when half have painted, so an artist's stroke started during a job waits behind
at most 32 job strokes. Job strokes never ask open strokes to end (`setRequestsOtherStrokesToEnd(false)`) and are not
asynchronously cancellable, so Esc, the Undo History docker and closing views leave them alone. Per image, a guard
(`StrokeJobImageGuard`) listens for `KisImage::sigUndoDuringStrokeRequested`: the artist's Undo during a job stops every
job on the image and, once the image is idle, carries out that undo (Krita drops it on a busy image), unless Krita
managed it at once. `KisImage::sigAboutToBeDeleted` stops the jobs too, so closing a document waits only for the
strokes painting at that moment.

**Ends and waiting.** Each stroke reports its start and its end; the end is a barrier job queued from its finish
callback before the base class queues a Wash brush's merge (jobs a callback adds go in front of the stroke's remaining
jobs), so a stroke counts as done only after its pixels have landed. A stroke dropped unstarted reports from its
destructor. `wait()` waits for the job's own strokes; on the GUI thread it always has a limit (a negative timeout
polls, with a warning), since some strokes need the GUI thread. `changedRect()` collects the layer's redraw requests
while a job stroke runs (`KisImageChangeReports`; strokes on an image run one at a time). `cancel()` sets a flag every
stroke reads: strokes not started paint nothing (they skip their painters altogether), the one painting is rolled back
(its transaction reverted), and the feeder drops the strokes not yet queued, so the layer keeps a whole prefix. It never
calls `KisImage::cancelStroke()`, since the job's strokes are already ended. Job strokes make no level-of-detail copy
and ignore wrap-around mode. While a job stroke paints, its changes are reported as the agent's
(`DocumentChanges::beginAgentWork`, ended after the merge).

**Undo.** The job holds its undo step (`DocumentHistory::holdStep`, a `ScriptStepHold`): the open agent move or script
macro, or else a step of the job's own named by `name`. A held step does not land, so strokes queued in later top-ups
still join it: a move ended by its script while a job still paints lands after the job.

Our own files for the undo history: `libs/libkis/DocumentHistory.{h,cpp}`, `libs/ui/KisAgentHooks.{h,cpp}`,
`plugins/extensions/pykrita/plugin/krita/agentmove.py`; tests `libs/libkis/tests/TestDocumentHistory.{h,cpp}` and
`plugins/extensions/pykrita/tests/TestPythonAgentMove.{h,cpp}`, both on `sdk/tests/KisTemporaryHomeUiTest.h` (which
also runs windows on the offscreen platform, with an in-process clipboard).

### Undo history and agent moves

An agent move (`Document.beginAgentMove(name)` … `endAgentMove()`, or `with document.agentMove(name):` in Python)
and a script macro (`beginUndoMacro` … `endUndoMacro`) collect only the script's own commands. The open step has an
undo store and post-execution undo adapter of its own; the script's strokes (through their resources snapshot),
filters, single-command strokes (new layers and other node edits, the global selection, vector shapes, transform
masks) and pixel writes (queued as strokes of the step, after its earlier strokes) send their commands there. The
artist's work goes to the document's stack as usual, so undo stays available during a move and the artist's strokes
stay separate steps. Ending the step queues a stroke with no work after the script's strokes; when it runs,
everything collected is pushed as one step, "Agent: <name>" (nothing for an empty step). Steps are pushed only from
the strokes queue or, on the GUI thread, when the image is idle, never while a GUI undo macro is open (its begin
pushes the work collected so far first; landings wait for its end). Begin and end take no lock and never ask other
strokes to end. The Undo History docker is not changed: the step's text is the marking.

**Device rule (a design call).** Krita undoes a paint device's changes strictly newest first. When the artist adds
a command while a step holds collected work, the devices it changes are read (transactions, through composites and
saved commands; `KisAgentHooks::beforeAddCommand`): if it may change a device the step has changed, or what it
changes cannot be read (a saved macro, a legacy command of unknown kind), the step's work so far is pushed first,
and the rest of the move continues as "Agent: <name> (cont.)". Artist work on other layers leaves the move whole.

**A move left open** closes by itself with a warning: when the document is saved (not exported; on an idle image
its work lands before the save, so the history is clean there), when the history moves on an idle image (undo,
redo, the docker; on a busy image Krita drops the undo and the move stays), and after 120 s without script work
(queued or running work counts as work; `DocumentHistory::setAgentMoveIdleTimeout`). It then rests: the script's
next work reopens it as "Agent: <name> (cont.)", its end ends it, and `Document.agentMoveId()` stays the same, which
the Python context manager checks so it never ends another move. The undo limit counts each step once.
`setUndoIndex` waits at most 3 s for the image, handling input meanwhile so a held pen can lift.

**startStroke's end requests (fixed in 2.9).** A stroke started by stock Krita makes it ask the open strokes to end
(`KisImage::startStroke` → `requestStrokeEnd`), which commits the transform, move, crop, line and selection tools'
in-progress work and stops animation playback. libkis's own calls no longer do: strokes of `Node.paint*`,
`Filter.apply/startFilter`, node setters and the image operations run under `KisProcessingApplicator::
NoEndRequestsOverride`, or their strategy says `setRequestsOtherStrokesToEnd(false)`, and they wait for their own
stroke only (`ScriptWaits`: the call's completion, or a marker stroke queued after an operation libkis does not
hold), at most `KisToolFunctions::waitLimit()` (60 s), handling events on the GUI thread so a held pen can lift. A
stroke held back past the limit is cancelled and the call returns false (commands) or warns (image operations, which
cannot be taken back and run when the artist's stroke ends). A script's public `Document.waitForDone()` is as
upstream: it ends open strokes and waits for the whole image, and a script that reads the composited image still calls
it first (libkis's own waits make the call's work land, not every redraw).

Rules of the waits (2.9 fix round): `NoEndRequestsOverride` lives only around the upstream call that starts the
strokes (`ScriptWaits::run`), never around the wait, where the GUI thread handles events and the artist may start a
stroke that must ask others to end as usual. An image operation held back past the limit is cancelled (the strokes it
started are cancelled, a warning says so, `mergeDown` and `addFeature` return null, setters return false). On a locked
image (`Document.lock()`) the property and pixel setters and `Filter.apply` run at once and are recorded in the
history (the open step, else the image's), so a script reads its change back inside the lock block; other commands
queue and run on unlock, and the tool functions (`Node.fill` and the like) refuse.

Our own files for the traps (2.9): `libs/image/KisTouchedDevices.{h,cpp}`, `libs/libkis/ScriptWaits.{h,cpp}`; tests
`libs/libkis/tests/TestLibkisTraps.{h,cpp}`, `TestLibkisNoView.{h,cpp}` (a program of its own: no window can exist),
`plugins/extensions/pykrita/tests/TestPythonTraps.{h,cpp}`; plugin side `creative-agent/krita-mcp/krita-plugin/kritamcp/script_steps.py`.

Coordination with the change reports: `DocumentHistory::agentMoveHook()` opens agent work
(`DocumentChanges::beginAgentWork()`) when a move begins or continues and ends it once the move's step has landed,
and emits `DocumentHistory::agentMoveChanged(bool open, QString name)`; `DocumentHistory::isAgentMoveOpen(image)`
answers from any thread.

### What the identity does

With `KRITA_APP_SETTINGS_FOLDER=KritaAgent` (the fork's default). Empty gives stock Krita's behaviour exactly: the
other identity values (display name, organization domain, bundle id and name, `KRITA_BUILD_MACOS_INTEGRATION`) are
derived from the folder unless set, so an empty folder gives `Krita`, `krita.org`, `org.krita` and the integration
extensions on.

| | Stock Krita (macOS) | Krita Agent (macOS) |
|---|---|---|
| Bundle identifier | `org.krita` | `local.kritaagent` (placeholder until the name is chosen) |
| Organization domain | `krita.org` | `kritaagent.local` |
| Config (`kritarc`, `kritadisplayrc`, `kritashortcutsrc`, ...) | `~/Library/Preferences/` | `~/Library/Preferences/KritaAgent/` |
| Resources, resource database, Python plugins | `~/Library/Application Support/krita/` | `~/Library/Application Support/KritaAgent/krita/` |
| Logs (`krita.log`, `krita-sysinfo.log`) | `~/Library/Application Support/` | `~/Library/Application Support/KritaAgent/` |
| Crash log (`kritacrash.log`) | `~/Library/Preferences/` | `~/Library/Application Support/KritaAgent/` |
| Autosaves of never-saved documents (`krita-<pid>-<id>-autosave.kra`), and the start-up recovery that deletes those not recovered | `~/` | `~/Library/Application Support/KritaAgent/autosave/` |
| File types (`Info.plist`) | Exports and owns `.kra`, `.krz`, `.kpp`, `.ora` | Imports them, opens Krita files only as an alternate app; configuring fails if a claim survives |
| Caches | `~/Library/Caches/krita/` | `~/Library/Caches/KritaAgent/krita/` |
| macOS defaults (bundle-id domain) | `~/Library/Preferences/org.krita.plist` | `~/Library/Preferences/local.kritaagent.plist` (when macOS writes one) |
| Single-instance channel | `Krita5<home>` | `Krita5KritaAgent<home>` (the fork never hands its files to a running stock Krita) |

The application name stays `krita`, so installed data, translations and menus are found as upstream finds them
(tested on macOS only; Linux and Windows builds with an identity are untested). The organization name (empty upstream) is set to the settings folder, which is how Qt separates the data and
cache folders.

## Building and running (macOS, Qt6)

Only the Command Line Tools are needed (no Xcode); one architecture, the Mac's own.

```sh
# one-time setup (all ignored through .git/info/exclude): see the header of agent/fetch-deps.sh
agent/build-macos.sh          # fetch KDE's prebuilt Qt6 dependencies if needed, configure, build, install to _install
agent/run.sh                  # start _install/bin/krita.app (bundle id local.kritaagent)
```

`env.sh` (written by the dependency fetch) is an environment snapshot: never commit it. The fetch runs with a clean
environment so it holds no keys, and `agent/fetch-deps.sh` refuses to run in any other. The local setup is ignored
through the fork's block at the end of `.gitignore`.

Tests: configure with `-DBUILD_TESTING=ON` (`agent/build-macos.sh --tests` on a fresh `_build`), then
`ctest --test-dir _build -R 'KisAppIdentityTest|KisAutoSaveLocationTest|krita-app-identity-info-plist'`. Run
`ninja -C _build install` first, or remove Krita's own `lib/libkrita*.dylib` from `_install`: test binaries look in
`_install/lib` before the build folder.

A second worktree (for an agent building beside the main checkout) shares the fetched dependencies instead of
downloading them again; its build installs into its own `_install`:

```sh
git worktree add ../krita-agent-x -b agent/x krita-agent
../krita-agent-x/agent/setup-worktree.sh "$PWD"     # clones _install minus Krita's own files, links the tools, writes env.sh
../krita-agent-x/agent/build-macos.sh --tests
```

In a worktree, run test binaries from `_build` with `KIS_TEST_PREFIX_PATH=<worktree>/_install` (macOS resource lookup)
and `DYLD_LIBRARY_PATH=<worktree>/_build/bin` (set in the shell, not through `/usr/bin/env`, which drops `DYLD_`
variables), so the last built libraries load rather than the last installed ones. Use the `ninja` in `_krita-tools`:
an older system `ninja` resets the build log and the next build starts over.

## Upstream sync cadence

- **Monthly**, in the first week of the month, merge the current upstream `master`:
  `git fetch origin && git checkout krita-agent && git merge origin/master`. A merge rather than a rebase: with the
  creative agent's own history in this branch (`creative-agent/`), rebasing would rewrite hundreds of our commits.
- Before merging, tag the current state (`agent-YYYY-MM-pre-sync`) so it can be compared and restored.
- After merging: run `agent/check-identity.sh` (fails on new upstream code that reaches per-user config or data
  folders, QSettings or `*rc` config names without going through `KisAppIdentity`; `agent/check-identity.allow` lists
  the known-safe lines), rebuild (`agent/build-macos.sh --deps`, since KDE's dependency packages move with master), run
  the identity tests above, the creative agent's suites (`creative-agent/krita-creative-agent`: Python and JS) and the Agent-mode test chats against the fork, the Krita actions audit against the fork (`KRITA_CREATIVE_CONFIG=<fork pykrita>/kritamcp/creative-agent-config.json node creative-agent/krita-creative-agent/scripts/audit-krita-actions.mjs`, no painting open; it lists the fork as `KritaAgent <release>`), and update the
  table above if a conflict changed what an edit touches.
- Out of cycle only for an upstream fix we need now, or before a release.
- Dependencies follow upstream's Qt6 branch of `krita-deps-management` (`transition.now/qt6` today; the branch name is
  in upstream's `.gitlab-ci.yml`, `DEPS_QT6_BRANCH_NAME_MACOS`). Read it at rebase time; do not assume it.

## What we offer upstream

Every change that would help any Krita script or user is offered to KDE as a merge request on invent.kde.org, written
against upstream `master` without our branding. If it is accepted, our copy goes away at the next sync. In
particular:

- **Scripting speed (libkis):** region refresh (`Document.refreshProjection(QRect)`), `setPixelData` dirtying only its
  rect, document revision and changed-area reports, scaled projection views, async stroke jobs with per-job waits, and
  one named undo step per scripted operation.
- **Native craft:** brush tips and presets created from an area or image without a restart; merge kept work; bake
  filter masks.
- **Tool logic as functions:** similar-colour, contiguous and magnetic-outline selection moved out of the tool classes
  so scripts can call them.
- **Build:** the optional macOS integration extensions (building without Xcode) and the identity options, offered as
  "run a development build beside an installed Krita".

Kept in the fork (not offered): the built-in agent panel and project view, Krita-Revamp's interface port and the
Photoshop-style defaults, the canvas feature map until it has proven itself, and our branding.

## Licence

Every binary release publishes the exact source it was built from (this branch at the release tag) under
GPL-3.0-or-later, with Krita's, Krita-Revamp's, the bundled packages' and our MIT-origin licence notices. See the
release task (1.3).

## Shipping the plugin and running the suites (krita-fork 1.5)
- `creative-agent/CMakeLists.txt` installs the Python plugin (`creative-agent/krita-mcp/krita-plugin/kritamcp` and its `.desktop` file) into
  `share/krita/pykrita` with the build (option `KRITA_AGENT_PLUGIN`, on by default): a build is usable without a separate install
  step. A copy in the artist's own pykrita folder (what `scripts/install.py --krita fork` writes) is found first and shadows it: remove
  it to run the shipped one. Enabling the plugin on a fresh settings folder belongs to the new-install defaults (task 3.3).
- `agent/ci.sh` runs every suite we own (plugin Python, companion JS and typecheck, then the C++ programs in `agent/ci-tests.txt` through
  `agent/run-tests.sh`); it is what a CI service runs and what a merge needs green. `--no-cpp` needs no build.
- Commits in this repository carry the artist's identity (repository config). Commits made before 19 October evening carry the machine's
  host name address: rewrite them (mailmap or filter) only as a deliberate step before anything is published.

## Publishing (krita-fork, 19 October)
- The public repository is `github.com/yak1234/krita-creative-agent`, branch `main`: the fork and the plugin in one repository.
  Its earlier, plugin-only `main` is kept as the branch `plugin-only` by the first push.
- Krita's own history is about 10 GB on GitHub, so it is not pushed. `agent/publish.sh` publishes a replay of the local main
  line: a root commit with Krita's tree at the base commit, then one commit per first-parent commit (message, author and dates
  kept; addresses other than the artist's replaced), recorded in `<git-dir>/publish-map` so later runs only append. The local
  repository stays the truth and is never rewritten.
- Policy (the artist): a merge into `krita-agent` that passes `agent/ci.sh` (built, tested) and `agent/prepublish-check.sh` is
  published to `main` with `agent/publish.sh --push`. The very first push (`--first`, which replaces the old `main`) waits for
  the artist's go. Never push anything else, never to KDE's `origin`.
- Upstream edits: `README.md` is now ours (Krita's is `README.krita.md`, renamed). `.github/workflows/ci.yml` is ours.

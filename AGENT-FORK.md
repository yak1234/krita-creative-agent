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
| `libs/image/CMakeLists.txt`, `libs/image/tests/CMakeLists.txt` | Build `KisFeatureProtection.cpp` and `KisFeatureQueries.cpp`; add `KisFeatureProtectionTest` | protection (6.5), queries (6.4) |
| `libs/libkis/CMakeLists.txt`, `libs/libkis/tests/CMakeLists.txt` | Build `DocumentFeatureQueries.cpp`, `DocumentFeatureProtection.cpp`; add `TestDocumentFeatureQueries`, `TestFeatureProtection` | queries (6.4), protection (6.5) |
| `libs/libkis/Document.h`, `plugins/extensions/pykrita/sip/krita/Document.sip` | Declare `featuresAt()`, `featuresOverlapping()` (rect, feature, selection), `featuresTouching()` (feature, name), `selection(expression)` (an overload of the active-selection getter), `lastKeptOut()`, `agentMoveKeptOut()`, `setProtectionSuspended()`, `protectionSuspended()` in a block of their own after `maskSegments()`; bodies in our `DocumentFeatureQueries.cpp`, `DocumentFeatureProtection.cpp` | queries (6.4), protection (6.5) |
| `libs/libkis/Feature.h`, `Feature.cpp`, `plugins/extensions/pykrita/sip/krita/Feature.sip` | `setProtected()` (an undo step through the new `KisSetFeatureProtectedCommand`); our files | protection (6.5) |
| `libs/libkis/StrokeJob.h`, `StrokeJob.cpp`, `StrokeJobShared.h`, `NodeStrokeJobs.cpp`, `plugins/extensions/pykrita/sip/krita/StrokeJob.sip` | `keptOut()` and `status()["keptOut"]`; each window of a job's strokes is clipped to its selection minus the protected features (our files) | protection (6.5) |
| `libs/libkis/NodeAgentTools.cpp`, `libs/ui/processing/KisToolFunctions.{h,cpp}` | `allowProtected` option; `Target::enforceProtection`; the tool functions read the selection through the protected features when their stroke runs, and `Completion::keptOut()` (our files) | protection (6.5) |
| `libs/libkis/Filter.cpp`, `Selection.cpp`, `DocumentHistory.{h,cpp}` | `Filter.apply()`, `startFilter()`, `Selection.cut()` and `paste()` and `Node.setPixelData()` keep out of protected features while the agent works (`DocumentHistory::protectionFor()`); an agent move's start and end reset what was kept out and any suspension of protection (upstream files, small branches each) | protection (6.5) |
| `libs/image/KisFeature.h`, `KisFeature.cpp`, `KisFeatureList.h`, `KisFeatureList.cpp`, `KisFeatureCommands.{h,cpp}` | `hasPixelIn()`; the list's `revision()`, protection cache (`protectedMask()`), suspension and kept-out records; `KisSetFeatureProtectedCommand` (our files) | protection (6.5), queries (6.4) |
| `libs/libkis/tests/CMakeLists.txt` | `kritatransformmaskstubs` added to the libkis tests' `LINK_LIBRARIES` (a transform mask asks the registry for its parameters' holder, which the stubs provide) | protection (6.5) |
| `agent/run-tests.sh` | The failure summary also prints the `Loc:`, `Actual` and `Expected` lines and `QINFO` lines of the test log (a failing test said nothing about where) | build (6.5) |
| `libs/libkis/Node.h`, `Node.cpp`, `plugins/extensions/pykrita/sip/krita/Node.sip` | `scaleNode`, `rotateNode`, `cropNode`, `shearNode` return `bool` (they were `void`); they, `setColorSpace`, `setColorProfile` and `mergeDown` refuse when the layer's pixels reach a protected feature | protection (6.5) |
| `libs/libkis/Channel.cpp` | `Channel.setPixelData()` keeps protected pixels while the agent works | protection (6.5) |
| `plugins/extensions/pykrita/tests/CMakeLists.txt`, `agent/ci-tests.txt` | Add `TestPythonProtection`; the new test programs | protection (6.5) |
| `libs/ui/dialogs/kis_about_application.cpp` | Window title and the top of the "Your Rights" tab come from our `KisAboutAgent` (name, version and commit, GPL-3.0-or-later notice, source offer); both empty for stock Krita. **Needs a rebuild to show** | packaging (1.3) |
| `libs/ui/CMakeLists.txt` | Builds `dialogs/KisAboutAgent.cpp` | packaging (1.3) |
| `plugins/extensions/pykrita/plugin/utilities.cpp` | `Python::setPath`: `runningInBundle` is also true for an app bundle not called `krita.app` (`.app/contents` in the root). **Needs a rebuild to take effect** | packaging (1.3) |
| `libs/ui/tests/CMakeLists.txt` | Adds `KisAboutAgentTest` | packaging (1.3) |

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

Our own files for the queries and protection (6.4, 6.5): `libs/image/KisFeatureQueries.{h,cpp}` (point, rectangle,
feature and selection queries over the stored masks, touching with a gap of one pixel, and the expression grammar of
`Document.selection()`), `libs/image/KisFeatureProtection.{h,cpp}` (the protected area as a selection, the write
clips, `clipPixelWrite()` for raw pixel writes, the canvas-alignment check), `libs/libkis/DocumentFeatureQueries.cpp`,
`libs/libkis/DocumentFeatureProtection.cpp`; tests `libs/image/tests/KisFeatureProtectionTest`,
`libs/libkis/tests/TestDocumentFeatureQueries`, `libs/libkis/tests/TestFeatureProtection`. The `.kra` already carried
`protected` on each `<feature>` (task 6.1, version 1), so no format version changes: a reader that does not know the
attribute ignores it.

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
job on the image and waits (at most 3 s, processing no input events) for them to stop and land their step, so Krita's
own undo, which follows the signal and succeeds whenever the image is idle, undoes the job's step and never the one
before it; if the jobs have not stopped in time, the undo is carried out after they have (Krita drops it on a busy
image). `KisImage::sigAboutToBeDeleted` stops the jobs too, so closing a document waits only for the
strokes painting at that moment.

**Why a job was cancelled.** `StrokeJob.cancelReason()` (also `status()["cancelReason"]`) is empty while the job is not
cancelled, then `"script"` (`cancel()`, so the plugin's Stop), `"undo"` (the artist's Undo, through the image guard) or
`"document_closed"` (the document closing, or its image gone). The first reason stays; a cancel that came too late to
stop anything leaves the job "done" with an empty reason. **The brush is fixed at the call:** `paintStrokes()` clones the
preset once, so a change to the view's preset (or a plugin toggling a setting on it and restoring it) after the call
never reaches the windows queued later.

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
(`DocumentChanges::beginAgentWork`, ended after the merge). Every stroke gets a resources snapshot of its own, as Krita's
tools make them (each deep-copies the preset and its brush settings), never one shared between strokes.

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

## Packaging: a self-contained Krita Agent.app (krita-fork 1.3)

`_install/bin/krita.app` is a shell: its executable loads about 1.3 GB of libraries, Qt frameworks and resources from
`_install/lib` and `_install/share` by rpath, so it cannot be moved. `agent/package-app.sh` makes `Krita Agent.app`, which
stands alone (about 800 MB), from a finished build, and `agent/install-app.sh` puts it in place. **The app is arm64-only**
(the architecture is read from the build's main executable, not from the machine; anything else is refused).

    agent/package-app.sh [INSTALL_DIR] [--out DIR] [--source DIR] [--release DIR] [--source-url URL]
                         [--allow-dirty] [--allow-stale-build] [--allow-unpublished] [--no-sign]
    agent/package-app.sh --check|--verify|--smoke|--sizes "Krita Agent.app"
    agent/install-app.sh [--to ~/Applications] [--dry-run] "Krita Agent.app"

It only reads `_install`, never builds, and refuses to run while a build is installing (a half-written tree). The work is in
`agent/package_app.py` (packaging, checks, signing) and `agent/package_notices.py` (the build record and the licence texts);
both are plain functions, tested by `creative-agent/krita-creative-agent/tests/test_package_app.py` on fake bundles.

**Which commit.** THE commit of the app is the one the Krita executable reports (`krita --version`), because that is what the
binaries were built from. The script refuses unless that commit is the source checkout's HEAD (`--allow-stale-build`), neither
the source nor this checkout has uncommitted changes (`--allow-dirty`), and the commit is in `public/main` (`--allow-unpublished`;
the public hash comes from `<git-dir>/publish-map`, because local and public hashes differ). Each allowance is written into
the app (`notes:` in BUILD.txt, `KritaAgentNotes` in Info.plist, the README and the About box). The source offer names the
public repository, `https://github.com/yak1234/krita-creative-agent` (branch main), and the exact public commit, with the local
commit beside it. That repository carries the fork's whole source tree at that commit (Krita's tree at its base plus ours,
replayed onto the published main line), which is why the address is the corresponding source; no personal email is in the app.
`Resources/BUILD.txt` is the one place the About box reads.

**Output folders.** The bundle in `--out` is deleted and made again, so the script refuses (before writing anything) an output
folder that is, in any spelling (case, links, relative paths), `/Applications` or `~/Applications`, a system folder, the home
folder itself, the inside of an app, or one that contains (or lies inside) the install tree; and it only replaces a
`Krita Agent.app` whose Info.plist is ours. `install-app.sh` makes the same checks for its destination (plus Documents, Desktop,
Downloads and iCloud/CloudStorage, which macOS protects with prompts), refuses while the installed copy is running, and puts the
old copy back if the second move fails.

**Layout** (what Krita's own lookups need: `KoResourcePaths::getInstallationPrefix` finds `Contents/` because
`Contents/Resources/kritaplugins` exists; `KoJsonTrader` finds `Contents/PlugIns`; Qt finds `PlugIns` and `Resources/qml` by
itself; `Python::setPath` finds `Frameworks/Python.framework` and `Resources/krita-python-libs` through `Contents/share`):

| Folder | Holds |
|---|---|
| `MacOS/krita` | our launcher (`agent/app-launcher.c`): first-run default, bundle environment, then `exec`s `krita-app` |
| `MacOS/krita-app`, `kritarunner`, `ffmpeg`, `ffprobe` | the real executables (rpath `@executable_path/../Frameworks`) |
| `Frameworks` | Krita's, KDE's and third-party dylibs, the Qt frameworks, `Python.framework` (one architecture, without pip, tests, Tk) |
| `PlugIns` | Qt plugins (`platforms/`, `imageformats/` ...), Krita's plugins (`kritaplugins/*.so`, flat, as upstream), `mlt/` |
| `Resources` | `share` (krita, color, icons, locale ...), `qml`, `translations`, `etc/fonts`, `krita-python-libs`, `LICENSES/`, `BUILD.txt` |
| `Resources/krita/pykrita/kritamcp/_vendor/macos-arm64` | numpy, OpenCV (headless), psutil, xxhash for the bundle's Python version |
| `share -> Resources`, `etc -> Resources/etc` | the symlinks Krita's root-relative paths go through |

`Frameworks` holds only libraries and frameworks, because codesign treats everything in it as code (a Python package folder
there fails signing): that is why `krita-python-libs` lives in `Resources`. Every Mach-O file has the rpaths that left the
bundle replaced by one that leads to `Frameworks`; install names become `@rpath/...`; the closure of dependencies is copied
from `_install/lib`. Wheels' own `.dylibs` links are left as they are. Every `.pyc` is written at packaging time, with
the stored file names of `/Applications/Krita Agent.app`, hash-based and **unchecked**: Python never writes into the signed
bundle, and editing a `.py` inside an installed app has no effect (the `.pyc` wins) and would break the signature anyway.
The fontconfig file loses upstream's CI cache-folder entry.

**Checks** (`--check`, `--verify`, `--smoke`, and all of them at the end of every packaging run):
- no Mach-O file refers to a path outside the system, or to `_install` / `forks/`; every `@rpath`, `@loader_path` and
  `@executable_path` dependency resolves to a file inside the bundle; no rpath leaves the bundle; no symlink leaves it;
- the strings of every Mach-O file and the text of every other file are scanned for `/_install`, `/_build`, the forks folder
  and the packaging account's home folder. Harmless: source-file names the compiler recorded, upstream's CI paths
  (`/Users/gitlab/...`, other projects' build paths are not ours), and two compile-time constants of Krita's build that do nothing
  on macOS (`PYKRITA_PYTHON_LIBRARY`, the version header's build folder); they change with a rebuild;
- the layout above is complete, `codesign --verify --deep --strict` passes;
- a headless smoke test imports `krita`, `PyQt6`, `kritamcp`, numpy, cv2, psutil and xxhash through `kritarunner`, starts MLT's
  factory and makes a producer, and fails on any `sys.path` entry outside the bundle and the temporary home. It runs **from a
  temporary copy**, in `env -i`, with the launcher's environment, with `CFFIXED_USER_HOME` set to a temporary home (Qt on
  macOS ignores `$HOME`) and, inside `sandbox-exec`, with the install tree, the source tree and the forks folder made
  unreadable: a bundle that still needs them fails.
**Nothing is executed from a bundle whose signatures do not all verify**: on Apple silicon an edited, unsigned Mach-O is killed by
the kernel and macOS shows a "quit unexpectedly" dialog. Every file the script edits is signed at once, frameworks are sealed as
units, and `require_runnable()` refuses (with a message) before the version query, the bytecode step and the smoke test.

**The Creative Agent companion in the app.** `--release DIR` (the output of `krita-creative-agent/scripts/build-release.py`; with
none given the script builds one from this checkout, which needs `npm ci` there and, the first time, a network for the pinned
Node used only to validate it) puts `companion/` (pure JavaScript, JSON and wasm) and `release-manifest.json` in
`Resources/creative-agent-bundle` (a name of its own: `creative-agent` is where the copies go in the user's folder), with a `bundle-info.json` that records when the app was built; the plugin's own verifier checks them against each other at packaging time. On the first "Connect
assistant" the plugin (`kritamcp/bundled_release.py`) checks the files against the manifest again, copies the companion through a
temporary folder and one rename (a `.complete` marker is written first: a copy without it is broken and is replaced) to
`~/Library/Application Support/KritaAgent/creative-agent/<build_id>/`, and writes
`~/Library/Application Support/KritaAgent/creative-agent-config.json`. **A config next to the plugin wins** (the dev fork and
`install.py --krita fork` write one there); the AppData one serves the packaged app, which ships none. It holds the companion path, the managed Node runtime (`node_runtime`, `node_runtimes`), the bridge address, data and cache
folders and an absolute `paintings_dir` (default `<AppData>/paintings`, no macOS prompt; change it in the file). A complete install is
never touched or re-hashed; the manifest is hashed only when copying. A config the artist or the installer made is never replaced (a
file that cannot be read or is damaged is left alone and named in the message). A config this module wrote follows a newer build
(by the app's build time, so an older app opened later does not move it back), keeps every key it does not own (the paintings
folder, the bridge address, unknown keys), and other build copies and day-old leftovers are removed. The paintings folder can be
changed in that file (`paintings_dir`, `project_root`); the README in the app says so. The copy runs on the GUI thread, once per
build, at the first "Connect assistant". Node itself is **not** bundled: the existing one-time, SHA-256-verified download on the
first "Connect assistant" stays. `scripts/install-release.mjs` and `scripts/install.py` default to the fork's own pykrita folder
and refuse to install a second copy of the plugin there while Krita Agent.app is installed (it would be found first and hide the
app's), unless `--allow-shadow`; stock Krita's folder needs an explicit `--destination`. The plugin of a package is the one the
build installed (`ninja install` copies it from this tree): after merging plugin changes, install before packaging, or use
`--overlay-plugin DIR` (stamped into the notices) to take it from the checkout.

**Python packages.** `vendor.py` reads `kritamcp/_vendor/<os>-<machine>/`, so the packages are installed there (`uv pip install
--target`, wheels only, the bundle's Python version, from `python-packages.txt`). A plugin that carries that folder uses only
it: the shared `~/Library/Application Support/Creative Agent/python/...` folder is user-writable and, with
`disable-library-validation` on, must not also be searched for native code. `--packages DIR` uses a ready folder (offline).

**First run and environment.** The plugin is enabled by `[python] enable_kritamcp=true` in
`~/Library/Preferences/KritaAgent/kritarc`. A build's shipped defaults (`krita/data/kritarc`) are compiled in, so changing them
needs a rebuild; without one, the executable `MacOS/krita` is a small C launcher that, once per settings folder (marker
`.agent-first-run-1` beside kritarc), merges that one key into kritarc and `exec`s `krita-app`. It never overrides a value the
artist set (`key=`, `key =`, `key[$i]=` all count), never repeats, keeps CRLF line ends, a byte order mark, the file mode and a
symlinked kritarc; any problem (unreadable file, a folder named kritarc, read-only file or folder) means nothing is changed and no
marker is written; the marker comes only after the new file is fsynced and renamed into place. The launcher also sets
`PYTHONNOUSERSITE=1` and `MLT_REPOSITORY`, `MLT_DATA`, `MLT_PROFILES_PATH`, `MLT_PRESETS_PATH` to the bundle's folders (Krita sets
the MLT ones only for AppImage and Android). It is built with the build's settings folder (`-DSETTINGS_FOLDER`, from the CMake
cache), and without test hooks. The bridge port needs nothing: `bridge_config.py` takes 5679 for an app with a settings folder.
A later build that ships the key in `krita/data/kritarc` makes the key part unnecessary.

**Signing.** `KRITA_AGENT_SIGN_IDENTITY="<keychain identity name>"` signs with that identity (hardened runtime plus
`packaging/macos/entitlements.plist`); otherwise ad hoc. An identity that is not in the keychain stops with one line saying so and
that the bundle is left as the build step signed it (ad hoc, runnable). Everything is signed inside-out: libraries and plugins,
then each framework as a unit, then the app. The two entitlements: `allow-jit` because Qt's QML/JavaScript engine and the Python
extension modules need writable-executable memory under the hardened runtime; `disable-library-validation` because the vendored
numpy and OpenCV, PyQt and Python's extensions are not signed by the same Team ID as the app (there is none: ad hoc or
self-signed), and the hardened runtime would otherwise refuse to load them. macOS remembers "allow access to Documents/Desktop"
per code identity. An ad-hoc signature is identified by the hash of the code, so **every rebuild is a new app to macOS and it asks
again**; a certificate-based signature is identified by the certificate, which does not change, so the answer sticks. Make the
certificate once (the script never creates one):

1. Keychain Access -> menu Keychain Access -> Certificate Assistant -> Create a Certificate...
   Name `Krita Agent Local`, Identity Type `Self Signed Root`, Certificate Type `Code Signing`, Create.
2. Check: `security find-identity -p codesigning` lists `Krita Agent Local` (if it shows `CSSMERR_TP_NOT_TRUSTED`, open the
   certificate in Keychain Access -> Trust -> Code Signing: Always Trust).
3. Package with it: `KRITA_AGENT_SIGN_IDENTITY="Krita Agent Local" agent/package-app.sh`, then `agent/install-app.sh`.
   The first launch asks once for permission to use the key (Always Allow) and for Documents.

(The same can be done in a shell with `openssl req -x509 ... -addext extendedKeyUsage=codeSigning`, `openssl pkcs12 -export` and
`security import ... -T /usr/bin/codesign`; the steps above are the dependable way and were not run here.) **Other artists' Macs
are open work** (tasks.md 1.3): Gatekeeper rejects ad-hoc and self-signed apps that arrive with the quarantine flag; they need a
Developer ID certificate and notarisation.

**Licences and source.** `Resources/LICENSES/` holds `README.txt` (what the app is, the GPL-3.0-or-later notice, the commit and
where the source is), `THIRD-PARTY-NOTICES.txt` and the SPDX texts from `LICENSES/`, upstream's `credits`, `developers` and
`libraries` lists, and the vendored packages' own licence files (`python-packages/`). The notices are derived from what is
shipped, not written by hand: FFmpeg's licence, version and codec libraries from the shipped `libavutil`'s own strings (it reports
LGPL, so the notice says LGPL, names LAME, libvpx, libaom, OpenH264, Opus, Vorbis, Theora and libwebp with their licences and
sources, and points at FFmpeg's release tarball and the krita-deps-management recipe); Qt's version and the LGPL-3.0 rights
(replacing the frameworks and re-signing, reverse engineering for debugging, the recipe and `ext_qt` patches of the pinned
krita-deps-management commit); each wheel's full `License-Expression`, the libraries it carries (`.dylibs`: OpenBLAS,
libgfortran/libquadmath/libgcc with the runtime exception, FFmpeg inside OpenCV ...) and its licence files, including
`LICENSES_bundled.txt` and `LICENSE-3RD-PARTY.txt`. The About box (`KisAboutAgent`, a few lines in `kis_about_application.cpp`,
`KisAboutAgentTest`) shows the name, the compiled version and commit, the licence notice, and the exact source commit and address
from BUILD.txt; it is C++ and **appears only after the next build**.

**C++ edits for packaging (take effect at the next rebuild; none is needed to run the packaged app).** `libs/ui/dialogs/
KisAboutAgent.{h,cpp}` and its test (new files), two edits in `kis_about_application.cpp`, one line each in `libs/ui/CMakeLists.txt`
and `libs/ui/tests/CMakeLists.txt`; and `plugins/extensions/pykrita/plugin/utilities.cpp`: `Python::setPath`'s `runningInBundle`
tests for `krita.app` in the path, which is false for `Krita Agent.app`; it now also accepts `.app/Contents`. Python starts
without it (it finds its prefix through the framework), so after the rebuild check that it still does and that
`sys.path` has the bundle's `lib-dynload` and `site-packages` entries.

**Known limits.** The process is `krita-app` in Activity Monitor (the launcher `exec`s). Editing files inside the installed app
is not supported.

## Ported from Krita-Revamp (task 3.1, layers docker)

Source: Krita-Revamp (github.com/10zindraws/Krita-Revamp, branch revamp-5.2.14, GPL-3.0; author "10zindraws" / "Tenzin Rangdol",
one person). We took ideas and the code of the commits named below, adapted to master and Qt 6; their SPDX lines stay in the files
they touch. Their two folder PNGs and the clipping-mask PNG are NOT used (art origin and licence unknown): the icons are our own SVGs.

| Feature | Revamp commits | Our files |
|---|---|---|
| Folder-style groups | e76a4e1 (group-row part only) | `plugins/dockers/layerdocker/NodeDelegate.cpp/.h`, new `krita/pics/layers/{dark,light}_folder{Closed,Opened}.svg`, preference `groupRowHeightPercent` (default 70) |
| Alpha-inheritance indentation | 3b598ec | `NodeDelegate.cpp` (drawn only in the clipping mask view) |
| Clipping mask view (default OFF) | f754aab, bd64c4e, 02fbd9b | `NodeDelegate.cpp`, `NodeView.cpp/.h`, `libs/ui/KisClippingUtils.*` (new, shared rules), preference `enableClippingMaskView` |
| Clipping button / action | 697c81b (button), 48ba22a (not taken) | `LayerBox.cpp/.h`, `WdgLayerBox.ui`, action `clip_to_layer_below`, icon `clip-to-layer` (own SVG) |
| Alt-click between two layers | none (our addition) | `NodeView.cpp/.h`, `LayerBox.cpp` |
| Icons | none (own SVGs) | `krita/pics/layers/*_folder*.svg`, `krita/pics/layerbox/{dark,light}_clip-to-layer.svg` and their `.qrc` lists |
| Tests | none | `libs/ui/tests/KisClippingUtilsTest.*`, `plugins/dockers/layerdocker/tests/TestNodeDelegate.*`; `agent/ci-tests.txt` lists them and `TestNodeView` |

Upstream (Krita) files edited, each small and listed here:
- `libs/ui/kis_node_juggler_compressed.cpp/.h`: `enableInheritAlpha` (default false) on `copyNode/moveNode/addNode`.
- `libs/ui/kis_node_manager.cpp/.h`: drops pass through `KisClippingUtils::adjustDropTarget` when the view mode is on; new slot `clipActiveLayerToLayerBelow` and its action.
- `libs/ui/kis_layer_manager.cc`: `adjustLayerPosition` and `addLayerCommon` follow the clipping mask view rules (only when the mode is on).
- `libs/ui/kis_config.cc/.h`, `libs/ui/dialogs/kis_dlg_preferences.cc`, `libs/ui/forms/wdgdisplaysettings.ui`: the two preferences (Settings > Display > Miscellaneous).
- `libs/ui/CMakeLists.txt` (one source file), `krita/krita.action` (the action is in the layers docker menu and button; krita5.xmlgui is hash-guarded and left alone), `krita/pics/layers/layers-icons.qrc`, `krita/pics/layerbox/layerbox-icons.qrc`.
- `plugins/dockers/layerdocker/*` as listed above.

Licence of the new files: `libs/ui/KisClippingUtils.*` and its test are GPL-3.0-or-later because the rules in them are Revamp's helpers
(`isClippingMaskGroup`, `shouldEnableInheritAlphaForNewLayer`, `shouldEnableInheritAlphaForDrop`, GPL-3.0) moved into one place, not a clean-room
rewrite; the planning and apply code in them is ours. Revamp's copyright lines are added to `kis_node_manager.cpp`, `kis_layer_manager.cc` and the
juggler where its code was taken over. Further juggler edit: `applyExtraCommand` (one more command in the same undo step, for the clip action).

Behaviour to know with the clipping mask view ON (default OFF):
- The hidden wrapper group's own opacity, blend mode, visibility and lock are unreachable in the docker: the stack cannot be dragged, hidden or
  deleted as one object (select its layers, or switch the view off). "Clip to layer below" moves a base's blend mode and opacity onto the new group
  (Photoshop-faithful) so a Multiply base keeps its look; `create_quick_clipping_group` is unchanged.
- Clip wrappers are always shown expanded (the node's collapsed flag is not written); Up/Down/Page keys skip the hidden wrapper rows.
- The selection highlight's left edge for a child of a hidden wrapper may start one indent too far right (live look).
- Agent gate: with the view ON, `KisLayerManager::addLayerCommon/adjustLayerPosition` change layer placement for any caller that goes through an
  ACTION by name (`add_new_paint_layer` etc.) when the active layer is in a clip stack. The agent's libkis paths are not affected, but the live gate
  must run one agent chat with the view ON.
- Group rows show a static folder icon instead of the group's composite thumbnail, at any height.

Not ported on purpose: Revamp's `layer_kit` plugin; its selection sync (selecting the top clipped layer also selects the hidden wrapper group, which would make Delete remove the whole stack); the Alt+click isolate gesture (bb9cc08); the properties button row (48ba22a); the narrow docker (c94e713). libs/image is untouched, there is no `.kra` change, and libkis `Node.setInheritAlpha` (the plugin's `clip_to`) does not pass through any of the changed paths.
## Ported from Krita-Revamp (task 3.1, brush batch: preset persistence)

Source: Krita-Revamp (branch revamp-5.2.14, GPL-3.0; author "10zindraws" / "Tenzin Rangdol"). Commits b908ad5 and the sliderChanged part
of 681ef9f; their SPDX lines stay in `KisPaintOpPresetSessionStorage.*`. The smoothing slider (6b) and stroke previews (3) are parked.

- A brush tweak (any setting) is stored as settings XML in `presetTweaksrc` (the build's own settings folder, through
  `KisAppIdentity::configFileName`) under `Preset_<resourceId>_<md5>`; loaded when the preset is selected (preset dirty); cleared by
  Reload and by Save (all MD5s of the resource; Save-as-new keeps the original's). The "Temporarily save tweaks" checkbox is gone.
- Agent gate. Finding: `View.setBrushSize/setPaintingOpacity/setPaintingFlow/setBrushRotation/setPatternSize/setBrushFade/
  setEraserMode/setCurrentBlendingMode` write into the view's preset (derived resources, `kis_derived_resources.cpp`), and
  `Preset.fromXML` (configure_brush) changes it in memory. They do not reach `sliderChanged` (slider signals are blocked), but whether
  the option widget then calls `slotGuiChangedCurrentPreset` could not be excluded by reading. The plugin's own flows (paint passes,
  set_brush, configure_brush, the eraser toggles) mostly run OUTSIDE an agent move and never call `setAgentActive`, so the probe
  (`KisAgentHooks::agentWorkOpen`: an open agent move, an asynchronous stroke job, or `Document.setAgentActive`) is only one guard.
  The storage therefore also:
  - marks a preset a script changes (`markScriptChanged`, called BEFORE the change by every View brush setter above and by
    `Preset.fromXML`, with a snapshot of its settings XML and a log line) and saves nothing for it while its settings differ from the
    snapshot; the mark ends when the settings are back as they were (restore_brush), when stored tweaks replace them, or on Reload/Save;
  - loads nothing while a script selects a preset (`View.setCurrentBrushPreset` holds a `ScriptSelection`) or an agent works, and never
    over a preset that is dirty (newer memory state wins).
- Tweaks load in `setCurrentPaintop(preset)`, so the brush the last session ended with has its tweaks at startup; the stored XML leaves
  out `EraserMode` and `CompositeOp`. Size, opacity, flow and rotation changes by shortcut are saved too (when the preset is dirty and not
  in eraser mode); scripts' changes are refused by the marks.
- The "Temporarily Save Tweaks To Presets" checkbox is removed and `useDirtyPresets` is always true: tweaks are always kept and always
  persist (before, switching presets with the box unticked reloaded the preset from disk, dropping tweaks).
- `Node.paintStrokes` uses the preset AS SAVED (`KisResourceLocator::loadStoredCopy`), unless `useViewTweaks: true`. The plugin's
  smudge overlay passes `presetProperties` ({MergedPaint, SmudgeRateValue}), applied to the job's own copy; it no longer touches the
  view's brush on the fork. `StrokeJobBrush::setViewPresetForTesting` is exported only so the tests (separate binaries) can supply a
  view preset; it is not in any shipped header.

Upstream files edited: `libs/resources/KisResourceLocator.h/.cpp` (public `loadStoredCopy`), `libs/ui/kis_paintop_box.cc/.h`,
`kis_config.cc` (useDirtyPresets always true), `dialogs/KisDlgSavePreset.cpp`, `forms/wdgpaintopsettings.ui`,
`widgets/kis_paintop_presets_editor.cpp/.h`, `widgets/kis_preset_chooser.cpp`, `libs/ui/CMakeLists.txt`,
`libs/ui/tests/CMakeLists.txt` (adds `TestPresetSessionStorage`), `libs/libkis/View.cpp`, `Preset.cpp`, `DocumentChanges.cpp`,
`NodeStrokeJobs.cpp`, `Node.h`, `libs/libkis/tests/TestStrokeJobs.*`.

Live look: tweak a brush size/spacing, quit, reopen: the tweak and the dirty mark are back; Reload clears it; Save clears it. Run an
Agent-mode chat after tweaking: strokes use the saved brush and `presetTweaksrc` is unchanged.

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

## Plugin craft: live checks (krita-fork 5.1 stamps, 5.3 tools)

Written for the plugin side on `agent/plugin-craft`. Everything below was tested only against fakes; run these in the fork.

1. **Brush size.** The stamp assumes a brush tip's `size` equals the tip image's side in pixels at 100%. Stamp a cloud with a known
   `size` and measure it, also for a rotated or stretched variant (its square is about 1.41 x the tip).
2. **Base preset.** `b) Basic-1` should paint the tip with no pressure or speed shaping; check `createPreset` keeps spacing and
   the blending mode, and that an eraser or multiply preset is refused as `brush`.
3. **Resources.** A second stamp of the same material (same chat, new chat, after a Krita restart) must reuse the presets and make
   no new resource version. Remaking the material replaces the agent's own tip and preset under the same name; an artist's
   same-name resource is left alone and the agent paints with the "name (2)" preset.
4. **Brush list.** The Agent-tagged presets show in Krita's own brush list but not in the painter's `list_brushes` or
   `krita_capabilities`.
5. **Undo during a stamp.** Ctrl+Z during a multi-variant stamp (several jobs inside one agent move): the pass must end as
   `partial_change`, the layer removed, nothing recorded.
6. **Undo during the tools.** Ctrl+Z during `bucket_fill`, `enclose_and_fill`, `krita_gradient` and a long `smart_patch`: the
   plugin reads the history after the call (plus one event-loop turn), so an Undo that only lands later cannot be seen.
7. **Closing the document** during a call: the result should say the document was closed, not a pass-record error.
8. **Refusals.** The fork only warns and returns false; the plugin's error says "see Krita's log". Check the log names the
   reason for a locked layer, an empty selection and a bad seed.
9. **A call that changes nothing** (a fill clipped away by the stage region or by protection): rejected, layer removed; with
   protection 6.5 `Document.lastKeptOut()` names the features and the result carries `kept_out`.
10. **Smart patch.** Time at the 512 x 512 limit (about 5 s); the repair layer must hold only the patched pixels; protected
    features inside the copied context are holes the patch searches around (`kept_out_note`), so a repair next to one may look
    thin. A patch layer sits in its stage group, which may lie below artist layers that cover the seam.
11. **Redo stack.** A refused or failed tool call leaves a net-zero "Agent: ..." move (the layer was made, then removed) that
    purges the artist's redo stack. Not avoided: the layer must exist before the call.
12. **Stage groups.** A rejected FIRST call of a stage leaves its empty stage group (as `paint_pass` does); a failed
    `clip_base` call now removes its own clip group.

### Cost of a stamp
Each dab is a one-point stroke, so a 2000-dab stamp is 2000 strokes in jobs of windows of 32 (one job per tip variant). A snapshot
per stroke copies the preset and tip. A multi-point stroke cannot stand in for them: it draws a continuous line between its
points, not separate dabs. Measure a 2000-dab stamp on New Moscow; if it is slow, lower `MAX_DABS` or ask the fork for a
"dab list" stroke kind.

### Growth of the agent's resources and a cleanup recipe
A stamp makes one tip and one preset per (material, tip, rotation bucket, stretch bucket), up to 48 variants per stamp
(`MAX_VARIANTS`), named `Agent stamp <material> <hash> t<i> r<rot> s<stretch>` and tagged "Agent". They are reused while Krita's
settings (`creative-agent/stamp-resources`) record them; a remade material replaces its own. Nothing is deleted automatically.
To clean up: quit the fork, delete `Agent stamp *` from the `brushes/` and `paintoppresets/` folders of the fork's resource folder
(Settings > Manage Resources > Open Resources Folder), and remove the `[creative-agent]` `stamp-resources` key from the fork's
`kritarc`. The tag and the database entries are rebuilt on the next start.

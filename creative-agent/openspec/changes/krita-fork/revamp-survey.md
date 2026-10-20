# Krita-Revamp survey: porting its interface features to the fork (tasks 3.1, 3.2, 3.3)

Read-only survey, 19 October 2026. Nothing in `forks/krita-master` or its worktrees was touched; nothing was built or run.
Sources: `forks/krita-revamp` (branch `revamp-5.2.14`, blobless clone, GPL-3.0 per its README), `forks/krita-master`
(`krita-agent` at `f5622d8`, upstream base `548939f` of 18 Oct 2026), `AGENT-FORK.md`, the OpenSpec `krita-fork` change.

## 0. Read this first: facts that change the plan

1. **Scrubby zoom is already on master.** `KisConfig::zoomHorizontal()`, the `chkZoomHorizontally` preference and the
   `cfg.zoomHorizontal() ? -diff.x() : diff.y()` lines in `kis_zoom_action.cpp` are present, identical in effect to Revamp's.
   Nothing to port; only check the default (off) and map it in the Photoshop scheme.
2. **"Instant overview" is a one-line change** in `libs/image/kis_idle_watcher.h` (`KisIdleWatcher(int delay = 200` becomes
   `10`). On 5.2.14 `KisIdleTasksManager` used that default. On master every caller passes its own delay
   (`KisIdleTaskStrokeStrategy::preferredIdleWatcherInterval()` returns 50 ms and the watcher checks four times, so about
   200 ms), so the Revamp line would do nothing on master. The port is a re-tune of that constant plus a live measurement.
3. **The Revamp "clipping mask" is a view and a button on top of Krita's alpha inheritance**, not a new layer type: no change to
   compositing, to libs/image or to the `.kra` format. The button (`bnClippingMask`) triggers `toggle_layer_inherit_alpha` then
   `create_quick_group`. Master already has `create_quick_clipping_group` (in `KisNodeManager`). Revamp has **no Alt-click
   between two layers**; the spec's scenario ("Alt-click between two layers") needs our own addition. Revamp's Alt+click is
   an unrelated "isolate layer" gesture (`bb9cc08`).
4. **`separatebrusheraser` is a Python plugin**, derived from Wojciech Trybus's Shortcut Composer code (GPL-3.0-or-later), not
   C++. It swaps the view's brush preset when `erase_action` toggles. The agent's plugin calls `view.setEraserMode(...)`
   (`creative_tools.py` lines 1346, 1371, 1405, 1425), so with the plugin enabled an agent eraser pass swaps the view's preset
   (section 3, row 8). Its C++ side is only two small stroke-preview/snapshot fixes (`c202fef`).
5. **Preset persistence writes a new config file.** `KisPaintOpPresetSessionStorage` uses
   `KSharedConfig::openConfig("presetTweaksrc")`. In the fork this must go through `KisAppIdentity::configFileName(...)`, or it
   lands in the stock Krita folder (the identity gate `agent/check-identity.sh` should catch it). Stroke previews write PNGs
   to `QStandardPaths::CacheLocation/brush_stroke_previews`; same identity check.
6. **Revamp's 10 Python plugins are all PyQt5-only except `krita_ui_tweaks`**, which has a PyQt5/PyQt6 switch (`pyqt.py`).
7. **Packaging already has a first-run mechanism** (`agent/app-launcher.c`, marker `.agent-first-run-1`) and a compiled-in
   `krita/data/kritarc`; the default theme is already "Krita dark". Task 3.3 is mostly one more shipped-default entry plus a
   workspace, not new machinery.

What I could not determine: section 8.

## 1. Revamp's own history

Base `31056c6` (krita/5.2, 9 Dec 2025; the README says "5.2.14"; the `v5.2.14` tag was not fetched, so I diffed against this
commit, which is in the clone). 113 non-merge commits (+3 merges) from 11 January to 5 July 2026, author "10zindraws" (59)
and "Tenzin Rangdol" (54), both `tenzindraws@gmail.com`: one person. About 55 are README, FUNDING and changelog edits.
Diff against base: C++ and UI (`libs`, `plugins/dockers|paintops|tools`, `krita`, `pics`, `cmake`): 196 files, +10,939/-2,772.
Python plugins: 163 files, +23,813/-3,480. `libs/image`: 4 files, +9/-5 (preset.h override, idle watcher default, two lines for
a "smoothing" uniform-property id). Revamp adds no unit tests (only a moved brush-HUD test).

Mixed commits to know: `e76a4e1` ("first changes", 11 Jan) holds folder groups, scrubby zoom, toolbar sizing, extra spacers,
the toolbar smoothing slider, the selection-tool hold action, line-tool activation, welcome-page cuts and all the bundled
Python plugins; its hunks must be carved out per file. `870ff51` ("On-Canvas Brush Editor HUD docker") is mostly a backport of
upstream's own refactors that **master already has** (brush HUD in `plugins/dockers/brushhud`, `overviewdocker_page.cpp`);
treat it as not portable. A full per-directory commit list is already in `revamp-map.md`.

## 2. Feature table

Line counts are git numstat (added/removed) against the 5.2 base.

| # | Feature | Revamp commits | Files touched | Self-contained? | New .ui / resources / icons | libs/image? | Authorship / licence |
|---|---|---|---|---|---|---|---|
| 1 | Folder-style groups | part of `e76a4e1` | `plugins/dockers/layerdocker/NodeDelegate.cpp` (~+90), `pics/icons.qrc` (+2), `pics/psclosedfolder.png`, `pics/psopenfolder.png`. Group rows drawn at 70% height, folder icon instead of thumbnail, hit-rects adjusted | Yes, but shares NodeDelegate.cpp with 2 and 9 | 2 PNG icons (Revamp's own art; origin and licence not stated) | No | 10zindraws; Krita file headers (GPL-2.0-or-later) |
| 2 | Clipping masks (layers-docker "clipping mask view" and button) | `f754aab` (+510/-32, 10 files), `3b598ec` (alpha-inheritance indentation, +168/-10), `bd64c4e`, `02fbd9b`; button: `48ba22a`, `697c81b` (`LayerBox.cpp` +402, `WdgLayerBox.ui` +189/-27, `clippingmask.png`); narrow docker `c94e713` | `libs/ui/kis_layer_manager.cc` (+90), `kis_node_manager.cpp` (+79/-3), `kis_node_juggler_compressed.cpp/.h` (+41/-9, +6/-3; new `enableInheritAlpha` parameter), `kis_config.cc/.h` (`enableClippingMaskView`), `dialogs/kis_dlg_preferences.cc` (+3), `forms/wdgdisplaysettings.ui` (+8), layerdocker `NodeDelegate.cpp` (~+300), `NodeView.cpp` (+164), `LayerBox.cpp/.h/.ui` | Entangled with 1 and 9 in NodeDelegate.cpp; the rest is its own | `clippingmask.png`; a Display-settings checkbox; a button in `WdgLayerBox.ui` | No (UI only; uses the existing `inheritAlpha` property and `KisNodePropertyListCommand`) | Tenzin Rangdol / 10zindraws; the `layer_kit` plugin has other authors |
| 3 | Brush stroke previews | `26851a8` (+~1,170), `a9698ce` (rewrite), `2971f6c`, `e3cd494`, `ec4b087`; fixes in `681ef9f`, `1f0e361`, `c202fef`, `f142e6d` | New: `libs/ui/widgets/KisBrushStrokePreviewCache.cpp/.h` (588+), `KisBrushStrokePreviewGenerator.cpp/.h` (332+). Edited: `kis_preset_chooser.cpp/.h` (+309/-71), `kis_preset_live_preview_view.cpp/.h` (+141/-72), `kis_paintop_presets_chooser_popup.cpp`, `kis_paintop_presets_editor.cpp`, `kis_paintop_box.cc`, `libs/ui/CMakeLists.txt`, `plugins/paintops/colorsmudge/KisColorSmudgeStrategyLightness.cpp` (+6), `libs/resources/KisResourceModel.cpp` and `KisTagResourceModel.cpp` (name refresh), `libs/brush/KisColorfulBrush.cpp` (ARGB32 fix) | Mostly; coupled to 7 (the cache is invalidated by session-storage signals after `681ef9f`). Uses `KisPresetLivePreviewView` (a throw-away paint device, not an image stroke) | A "Strokes" view mode in the chooser; PNG disk cache | No | Tenzin Rangdol (SPDX 2026 header, GPL-2.0-or-later) |
| 4 | Scrubby zoom | part of `e76a4e1` | `kis_zoom_action.cpp` (+11/-7), `kis_config` (`zoomHorizontal`), preferences `.ui` | **Already on master** | none | No | n/a |
| 5 | Instant overview | part of `e76a4e1` | `libs/image/kis_idle_watcher.h` (default delay 200 to 10) | One line; see section 0 point 2 | none | A header default only (no effect on master) | n/a |
| 6a | Toolbar sizing (vertical toolbar icon size, "extra space" spacer actions) | part of `e76a4e1` | `libs/widgetutils/xmlgui/ktoolbar.cpp/.h` (+90), `kedittoolbar.cpp` (+63/-3), `kxmlguibuilder.cpp` (+51/-1), `kis_config.cc/.h`, `libs/global/kis_config_notifier.cpp/.h` (`sigToolBoxIconSizeChanged`), `kis_dlg_preferences.cc`, `wdggeneralsettings.ui` | Yes | A spinbox in Settings > Window; spacer actions in `krita.action` (+84 in `681ef9f`) | No | 10zindraws |
| 6b | Smoothing slider (paintop-box slider; brush-HUD property) | part of `e76a4e1` (`kis_paintop_box.cc` +87); `4a1167c` (+101); HUD dropdown `9bbda0f`, `a951809`, `516120d` (~+900 in `kis_brush_hud.cpp`); `2c28f7a`, `607d363` | `kis_paintop_box.cc`, `plugins/paintops/libpaintop/kis_brush_based_paintop_settings.cpp` (+94), `libs/image/brushengine/kis_standard_uniform_properties_factory.cpp/.h` (+4, +3: only an id and a `qFatal` branch), brushhud, `libs/flake/KoToolManager` (+13, only for the HUD) | Slider: yes. HUD dropdown: no (needs Revamp's HUD) | none | Trivial (an id) | Tenzin Rangdol |
| 7 | Preset persistence | `b908ad5` (+~300/-~60), `681ef9f` (parts) | New `libs/ui/KisPaintOpPresetSessionStorage.cpp/.h` (169+94). Edited: `kis_paintop_box.cc` (`resourceSelected`, `slotReloadPreset`, `slotGuiChangedCurrentPreset`, `sliderChanged`), `kis_config.cc` (`useDirtyPresets` forced true), `dialogs/KisDlgSavePreset.cpp` (+4), `wdgpaintopsettings.ui` (-16: removes the "temporarily save tweaks" checkbox), `kis_paintop_presets_editor.cpp/.h`, `kis_preset_chooser.cpp` | Yes (small); coupled to 3 by signals | removes a checkbox | No | New files carry an SPDX "2025 Krita Developers" GPL-2.0-or-later header; authorship is Revamp's |
| 8 | separatebrusheraser behaviour | plugin in `e76a4e1`, `d4e21ad`, `db7ebf2`; C++: `c202fef` | Python: 35 files, 2,546 lines. C++: `kis_resources_snapshot.cpp` (+5/-1), `kis_preset_live_preview_view.cpp` (+3/-2) | Plugin yes; the C++ part is tied to 3 | none | No | Plugin: GPL-3.0-or-later, derived from W. Trybus (Shortcut Composer, 2022-23) |

Other notable Revamp changes (not on your list):

| Change | Commits | Size | Verdict |
|---|---|---|---|
| Selection-tool hold: hold the shortcut 200 ms and release to switch to Move (Photoshop habit) | part of `e76a4e1` | new `libs/ui/tool/KisSelectionToolHoldAction.cpp/.h` (250+79), `KisMainWindow.cpp` (+22) | Port later, optional |
| Line tool via Shift only when the freehand brush is active | part of `e76a4e1` | `kis_tool_invocation_action.cpp` (+41/-7) | Port later, small |
| Hide tabs bar in canvas-only mode | `5c7979c` | ~+90, 7 files | Port later, small |
| Marker blend mode | `c54b79a` | `libs/pigment` +140 (a new composite op) | Drop for now: a new composite-op id hurts `.kra` portability to stock; core change |
| Preset drag-reorder (`KisPresetOrderManager`), tag-selector merge, bundle auto-repair, startup-speed | `8918b4f`, `0328adc`, `f4a43d8`, `c085489`, `a0bcc32`, `31f6a81` | `libs/resources` ~+1,500 incl. `KisResourceCacheDb` (+196) and `KoResourceBundle` (+393) | Drop (resource-database territory, big merge risk; `c085489` replaces the tag combo that `separatebrusheraser` drives) |
| Welcome page stripped, splash, startup warning off, narrow layers docker, smaller palette docker, docker-size persistence | `e76a4e1`, `b488c88`, `9f4fd35`, `c94e713`, `0e34dcb`, `b2b3727` | small to medium | Pick individually later |

## 3. Port assessment per feature (without porting)

"Drift" = number of differing lines between the 5.2 base file and master's file (a rough size of upstream's own changes since).
Every touched file exists on master except Revamp's own new ones and `KisSelectionToolHoldAction`.

| Feature | (a) Files and APIs on master | (b) Conflicts with our edits | (c) Risk to agent strokes | (d) Effort / risk | (e) Verdict |
|---|---|---|---|---|---|
| 1 Folder groups | `NodeDelegate.cpp` drift 120; added code uses `qobject_cast` on the node models and `KisIconUtils::loadIcon`: nothing Qt5-only | None (we do not edit it) | None (paint only) | 1.5-2 agent-hours, **low** | **Adapt**: redraw the two icons as SVG in Krita's icon style (art licence unknown); make the 70% row height a preference |
| 2 Clipping masks | `kis_layer_manager.cc` drift 214, `kis_node_manager.cpp` 172, `NodeView.cpp` 181, `NodeDelegate.cpp` 120, `LayerBox.cpp` 43, `kis_node_juggler_compressed.cpp` 1 (header 0), `kis_dlg_preferences.cc` 1,088, `kis_config.cc` 698. No Qt5-only API in the added lines. New juggler parameter `enableInheritAlpha` must default to false | `kis_node_manager.cpp`: we edit `mirrorNodes()` (one line), Revamp edits `moveNodesDirect` and drop paths: no overlap. `kis_config.cc`, `kis_dlg_preferences.cc`: we edit config-file names, Revamp adds keys elsewhere: textual merge only. libs/image stroke, undo, `kis_processing_applicator`, `kis_image::startStroke`: **not touched** | The agent's `clip_to` sets alpha inheritance through libkis, which does not pass through `KisLayerManager::adjustLayerPosition` or the new juggler paths, so agent-made clip stacks are unchanged. The view mode changes how the docker draws and where the UI inserts layers; it matters only if the agent triggers UI actions (`add_new_paint_layer`) with the mode on | 8 agent-hours for the Revamp part + 3 for an Alt-click-between-layers gesture (ours; absent from Revamp). **medium** (intricate docker code, four commits built on each other, no tests) | **Port, adapted**: the four view-mode commits plus the button; leave `layer_kit` out (it duplicates this); add the Alt-click gesture; default the mode on only after the artist has seen it |
| 3 Stroke previews | Drift is small for the files it builds on: live preview view 2, chooser 18, popup 2, colorsmudge 0, `KisColorfulBrush` 0. `KisResourceModel`/`KisTagResourceModel` drift 188/59: redo by hand. Qt6: `event->pos()`/`globalPos()` are deprecated but compile (`QT_DISABLE_DEPRECATED_BEFORE=0x050E00`); nothing removed | `libs/ui/CMakeLists.txt` (we add `KisAgentHooks.cpp`, `KisToolFunctions.cpp`, `KisAboutAgent.cpp`): add-only, trivial. The generator uses a throw-away device: no image stroke, no libs/image edits | Indirect: previews are painted by up to 3 worker threads after start-up and when presets change; CPU contention with an agent pass is the only plausible effect. It never uses the view's own preset object | 12 agent-hours (the largest; Revamp rewrote it once, port the final form only), **medium** (threads, disk cache, chooser state) | **Port as is, final form**, after 7; make generation idle-only and pause it while `Document.agentActive()` |
| 4 Scrubby zoom | Present | n/a | none | 0.5 h to verify, **low** | **Drop the port** (native) |
| 5 Instant overview | `preferredIdleWatcherInterval()` returns 50 on master | None | Idle tasks are image strokes (`KisIdleTaskStrokeStrategy`): they start after the image has been idle for 4 x interval and are cancelled by the next stroke. A shorter interval starts them more often between agent stroke jobs; they must not delay `paintStrokes` | 1 h incl. a live measurement and `AgentStrokeJobsBenchmark`, **low-medium** | **Adapt**: change that constant (not the unused `KisIdleWatcher` default); measure; drop if it costs agent speed |
| 6a Toolbar sizing | `ktoolbar.cpp` drift 48, `kedittoolbar.cpp` 189, `kxmlguibuilder.cpp` 2, `kis_config_notifier.cpp` 27. Qt6: `orientationChanged`, `widgetForAction`, `Qt::Alignment()` fine. `ktoolbar.cpp` reads `verticalToolbarIconSize` through a raw `KSharedConfig::openConfig()`: wrong file under our identity | `kis_action_registry.cpp` and `KisShortcutsEditor.cpp` are ours (identity) but not touched by this port | none | 4 h, **low** | **Port, adapted** (read the size through `KisConfig` and the notifier) |
| 6b Smoothing slider | `kis_paintop_box.cc` drift 140: the slider chooser was reworked upstream, re-apply by hand. Smoothing writes `KisConfig::lineSmoothingType/Distance` (global tool settings) and calls `slotSetSmoothingType`/`slotSetSmoothnessDistance` by `QMetaObject::invokeMethod` on the active tool | `kis_resources_snapshot.cpp` not involved | Agent strokes (libkis freehand strokes) take no smoothing from `KisConfig`: `libs/libkis` has no use of it (only a doc comment), so the slider cannot change them | 3 h for slider + uniform property, **low-medium** | **Port the slider, adapted**; make sure the `qFatal("Not implemented")` branch of the uniform-property factory cannot be reached; leave the HUD dropdown out |
| 7 Preset persistence | `kis_paintop_box.cc` drift 140, `kis_preset_chooser.cpp` 18, `wdgpaintopsettings.ui` 28, `KisDlgSavePreset.cpp` 0, `kis_config.cc` 698. Master still has `useDirtyPresets`, `m_dirtyPresetsEnabled` and `dirtyPresetCheckBox`, so Revamp's removals apply in spirit. Storage: settings XML in `presetTweaksrc` under `Preset_<resourceId>_<md5>`, loaded in `resourceSelected` with `setDirty(true)`, cleared on Reload and on Save | `kis_paintop_box.cc`, `kis_config.cc`: ours only in the identity block. The conflict is **conceptual**: `Node.paintStrokes` copies the view's preset (`viewPreset()` then `clone()`) or finds one by name (`bestMatch`), then sets size, flow, composite op and opacity itself (`NodeStrokeJobs.cpp` 480-499). A persisted tweak is therefore inherited by agent strokes in a new session (spacing, dynamics, textures the agent does not override) | **Needs attention.** (i) Cross-session leak: yesterday's artist tweaks silently shape today's agent stroke. (ii) Write leak: if the agent's `configure_brush` reaches `sliderChanged` or `slotGuiChangedCurrentPreset`, the agent's size/flow would be saved as the artist's tweak and `presetTweaksrc` synced to disk on every call. Whether those paths fire for Python-side changes is **not determined** (needs a live check) | 5 h, **medium-high** | **Port, adapted**: config through the identity; save only when `!agentActive()`; give `paintStrokes` a way to use the preset as saved on disk; unit-test Reload and Save clearing |
| 8 separatebrusheraser | The plugin reads `resourcecache.sqlite` directly through `PyQt5.QtSql` and finds the Brush Presets docker's tag combo box by widget search. C++ `c202fef` uses `effectivePaintOpCompositeOp()`, which exists on master | `c202fef` edits the `KisResourcesSnapshot` constructor (`compositeOpId` from the preset override); we edit the same file in other hunks (`setPostExecutionUndoAdapterOverride`, `setCompositeOpId`, `setGlobalAlphaLock`, `setupPainter`). Our `paintStrokes` calls `setCompositeOpId` after construction, so the snapshot change does not alter agent strokes | **Yes**: with the plugin enabled, `view.setEraserMode(True)` from `creative_tools.py` swaps the view's preset to the eraser brush, and a stopped pass may not restore it; native strokes read the view's preset | 2 h for the C++ fixes + the Python port (section 6) + 2 h for an agent-active guard, **medium** | **Adapt**: Python plugin in 3.2, off by default; the agent selects the eraser brush by name (`paintStrokes` option `preset`) and never relies on the swap; the plugin ignores toggles while `agentActive()` |

## 4. Agent risk and the tests that catch it

| Feature | What could change an agent stroke | Test that catches it |
|---|---|---|
| 7 Preset persistence | Persisted tweaks applied to the view's preset; agent size/flow written back as tweaks | New `TestPresetSessionStorage` (libs/ui): save/load/clear/reload, key by resource id and md5, config file in the identity folder. Extend `TestStrokeJobs`: "view preset carries a tweak; `paintStrokes` with `preset=` name gives the saved brush". Agent-mode chat before and after (same pixels) and one stopped mid-way; assert `presetTweaksrc` unchanged after an agent pass |
| 8 separatebrusheraser | Preset swap on `setEraserMode` | `TestPythonStrokeJobs` plus an Agent-mode chat with an eraser pass, plugin enabled, asserting the preset name before, during and after |
| 6b Smoothing | None for libkis strokes; only the GUI freehand tool changes | `TestLibkisTraps` unchanged and green; one UI check |
| 2 Clipping masks | UI paths only | Existing upstream `kis_node_juggler_compressed_test`, `kis_node_manager_test`, `TestNodeView`, plus new tests for the `enableInheritAlpha` paths; `TestNodeAgentTools` (`clip_to`) unchanged; an Agent-mode chat that builds a clipped shadow with the view mode on, then look at the docker |
| 3 Stroke previews | CPU contention only | `AgentStrokeJobsBenchmark` with generation running against idle |
| 5 Instant overview | Idle tasks between stroke jobs | `AgentStrokeJobsBenchmark`, `TestStrokeJobs`, `TestLibkisTraps` |
| 1, 6a | none | build plus the existing suites |

Gate for every feature (design "Revamp gate"): the Agent-mode test chats pass unchanged, `agent/ci.sh` suites green, and the new
tests added to `agent/ci-tests.txt`.

## 5. Order, worktrees, acceptance

### Order (value to a Photoshop workflow against risk, with dependencies)

1. **Folder groups** (quickest visible win, 2 h).
2. **Clipping masks** (highest Photoshop value, 8 + 3 h): after 1, since both rewrite `NodeDelegate.cpp`.
3. **Toolbar sizing** (4 h): independent, no agent exposure.
4. **Preset persistence** (5 h): before the previews (signals) and before the plugin work; it carries the agent gate.
5. **Smoothing slider** (3 h): after 4 (same `kis_paintop_box.cc`).
6. **Stroke previews** (12 h): after 4; last of the big C++ ports so a stall blocks nothing else.
7. **Instant overview** (1 h; measure; may be dropped).
8. **Scrubby zoom**: nothing to port; verify (0.5 h).
9. Later, small: selection-tool hold, line-tool Shift rule, hide tabs in canvas-only mode (about 8 h together).

One commit each, as the spec says; the mixed `e76a4e1` is split by hand into one commit per feature, naming the source hash and
author in the message (no AI attribution lines). C++ port total about 38 agent-hours without the optional items, about 50 with
3.2 and 3.3. These are estimates, not measured (no build was run, and a full Qt6 build time here was not measured).

### Worktrees and parallel work

Features that share files are serial. Three groups are file-disjoint, except add-only hunks in `libs/ui/kis_config.cc/.h`,
`libs/ui/dialogs/kis_dlg_preferences.cc` and `libs/ui/CMakeLists.txt` (separate blocks; the lead resolves them at merge).

| Worktree / branch | Features (serial inside) | Shared-file notes |
|---|---|---|
| `forks/krita-agent-revamp-layers`, `agent/revamp-layers` | 1 folder groups, then 2 clipping masks (+ Alt-click gesture) | layerdocker, `kis_layer_manager`, `kis_node_manager`, juggler |
| `forks/krita-agent-revamp-brush`, `agent/revamp-brush` | 7 persistence, then 6b smoothing slider, then 3 stroke previews | `kis_paintop_box.cc`, `kis_preset_chooser.cpp`, `libs/ui/widgets/*`, `libs/resources` models |
| `forks/krita-agent-revamp-shell`, `agent/revamp-shell` | 6a toolbar sizing, 5 overview constant, 4 scrubby check; later hide-tabs, selection hold | `libs/widgetutils/xmlgui`, `KisMainWindow.cpp`, `kis_config_notifier` |
| plugin side (this repository, no fork worktree) | 3.2 plugins on PyQt6, 3.3 defaults and launcher | Python and `agent/` only |

With the "two agents per batch" rule: batch A = layers + brush (the two longest chains); batch B = shell + the plugin-side 3.2/3.3.

### Acceptance per feature

| Feature | The artist sees by eye | A test proves |
|---|---|---|
| 1 | Groups look like Photoshop folders (closed/open icon), shorter rows; layers unchanged | Existing `TestNodeView`; a delegate size-hint test |
| 2 | The clipping button puts a layer in a clip group; the docker shows it indented under its base; new layers added above the clipped one land outside the group; dragging into the group clips; Alt-click between two layers clips | New juggler/manager tests for `enableInheritAlpha`; `clip_to` test unchanged |
| 3 | A "Strokes" view of presets with a stroke thumbnail each; a changed brush refreshes its thumbnail; no stutter while painting | Cache unit test (LRU, disk file in the identity cache folder, invalidate); benchmark |
| 4 | Scrubby zoom drags by horizontal motion when the option is on | Existing |
| 5 | The overview follows brushstrokes within a frame or two | Measured latency before and after |
| 6a | Vertical toolbar icons resize live in Settings > Window; extra spacers appear in the toolbar editor | Config round-trip test; screenshot |
| 6b | A Smoothing slider in the brush toolbar changes the freehand stabiliser | Mapping test (0 = none, 1-100 = stabiliser 3-100) |
| 7 | Tweak a brush, quit, reopen: the tweak is still there; Reload clears it; saving the preset clears it | `TestPresetSessionStorage`; an "agent pass leaves no tweak" test |
| 8 | With the plugin on, E swaps to the eraser brush and back | Python test; Agent-mode eraser chat |

## 6. Task 3.2: Revamp's Python plugins

All ten are installed by Revamp's `plugins/python/CMakeLists.txt` and are **community plugins by other authors** bundled in; most
files carry no licence header, so authorship and licence must be checked per plugin before bundling (`separatebrusheraser`,
`krita_redesign`, `label_box` and `quick_brush_size` do state GPL-3.0-or-later; `krita_ui_tweaks/plugin.py` says CC0-1.0; the
rest state nothing). Revamp also removed upstream's `lastdocumentsdocker`, `mixer_slider_docker`, `photobash_images`,
`quick_settings_docker`, `selectionsbagdocker`, `tenbrushes`, `tenscripts`; master still has them, keep them. `preset_groups` and
`dockerundercursor` were added and then removed again by `31f6a81`.

| Plugin | What it does | Py lines | Duplicates something master has natively? | PyQt5-only? | Verdict |
|---|---|---|---|---|---|
| `layer_kit` | Rearranges Layers docker buttons; "Create Clipping Mask" (inherit alpha + quick group); move to top/bottom | 2,055 | **Yes**, once feature 2 is ported (the code skips its own button if the native one exists); master also has `create_quick_clipping_group` | Yes (4 imports) | Drop |
| `quick_brush_size` | Accelerated size up/down shortcuts and a docker | 1,792 | Partly (native increase/decrease brush size actions) | Yes (6 imports, 27 unscoped enums) | Optional, low priority |
| `separatebrusheraser` | Separate brush and eraser presets; swaps on eraser toggle | 2,546 | No | Yes (35 PyQt5 imports, `PyQt5.QtSql`, `exec_`) | Port and guard (section 3, row 8) |
| `quickexportdocker` | Docker for quick multi-size export | 1,006 | Partly (File > Export, Export Layers plugin) | Yes (3 imports, 10 enums) | Optional |
| `super_docker_lock` | Lock all dockers with one action | 774 | No single native action found (master has "Show docker titlebars" and the toolbar lock) | Yes (4 imports) | Port: cheap and Photoshop-like |
| `timer_watch` | Stopwatch docker | 457 | No | Yes, and uses `PyQt5.QtMultimedia.QMediaContent`, which Qt6 removed | Drop or rewrite the audio |
| `krita_work_timer` | Productive-time tracker with a "cognitive profile" | 3,575 | Partly (document editing time in `KisDocument::updateEditingTime`) | Yes (16 imports, 56 unscoped enums) | Drop (not interface work) |
| `krita_redesign` | Flat theme styling and toolbox/tool-options pads (Kapyia, Pedro Reis) | 1,933 | Overlaps 3.3 (dark theme) and the toolbar port | Yes (11 imports, `exec_`) | Drop; the theme and 6a do its job |
| `label_box` | Colour labels from the Layers docker (LunarKreatures) | 2,881 | No | Yes (`from PyQt5.QtCore import *`) | Drop (Revamp itself reverted its own removal) |
| `krita_ui_tweaks` | Split panes and UI tweaks | 5,359 | No | **No**: `pyqt.py` switches PyQt5/PyQt6 | Check on master; the only one nearly ready, low priority |

Port route for those kept: run `krita-mcp/scripts/qt6_scoped_enums.py` for scoped enums, replace `exec_()` with `exec()`, import
`QAction`/`QShortcut` from `QtGui`, and use the try-import (PyQt6, else PyQt5) pattern master's own plugins use. About 6
agent-hours for `super_docker_lock`, `separatebrusheraser` and `quick_brush_size` together.

## 7. Task 3.3: new-install defaults

- **Shortcut scheme.** `krita/data/shortcuts/photoshop_compatible.shortcuts` (installed to `share/krita/shortcuts/`, beside
  `krita_default`, `clip_studio_paint_compatible`, `paint_tool_sai_compatible`, `tablet_pro`). 416 entries; includes B
  (`KritaShape/KisToolBrush`), E (`erase_action`: eraser mode, not a separate eraser tool), Ctrl+J (`duplicatelayer`),
  Ctrl+Shift+N (new paint layer), Alt+[ and Alt+]. Qt maps Ctrl to Cmd on macOS. It is selected by `[Shortcut Schemes]
  Current Scheme=<name>` in `kritarc` (`kis_action_registry.cpp` line 190; it falls back to "Default" if the scheme file is
  missing). The exact scheme name string (probably "Photoshop compatible") was not read from a running app; check
  `KisKShortcutSchemesHelper::schemeFileLocations()`.
- **kritarc keys.** `[Shortcut Schemes] Current Scheme=<name>`; the theme is already "Krita dark" by default
  (`readEntry("Theme", "Krita dark")`), so no key is needed; `CurrentWorkspace=<name>` (read in `KisMainWindow.cpp` line 627,
  default "Default"); plus the keys the ports add (`enableClippingMaskView`, `verticalToolbarIconSize`).
- **Workspace.** A `.kws` resource (`krita/data/workspaces/Default.kws` is a base64 `QMainWindow` state keyed by dock object
  names). A Photoshop-like one: toolbox left, Layers docker right-lower, Brush Presets and colour right-upper, the Creative Agent
  panel docked. A Qt5-made saved state is not guaranteed to restore on Qt6, so author it in the fork's Qt6 build (dock the
  dockers, then `saveState`), check it into `krita/data/workspaces/` and its `CMakeLists.txt`. The agent panel's dock object
  name was not determined (`creative_docker.py` registers the factory; read its id first).
- **Shipping without overriding an artist.**
  1. Preferred: put `[Shortcut Schemes] Current Scheme` and `CurrentWorkspace` in `krita/data/kritarc` (compiled in as
     `:/kconfig/<folder>/kritarc`, read **under** the user's file, so any value the artist sets wins). Needs a rebuild.
  2. Without a rebuild: extend `agent/app-launcher.c` `first_run_defaults()`. It already merges `enable_kritamcp` into
     `~/Library/Preferences/KritaAgent/kritarc` once per settings folder (marker `.agent-first-run-1`), never overrides a key
     that exists (`key=`, `key =`, `key[$i]=`), and keeps mode, BOM, CRLF and symlinks. Its matcher is built for the `[python]`
     group only, so it needs a group parameter; use a new marker (`.agent-first-run-2`) so settings folders that already ran the
     first version still get the new defaults exactly once, still without overriding keys the artist has.
  3. `agent/package_app.py` (its Python mirror of the launcher near line 311; tests compare the two) must ship the workspace
     file and the scheme in the bundle's `share/krita/`.
  4. Existing Krita settings are never migrated: the launcher acts only on the fork's own `KritaAgent` settings folder, which is
     separate from stock Krita 5.3.3's.
- Effort 4 agent-hours (scheme and kritarc keys 1, workspace authoring 2, launcher and test mirror 1). Risk low; the workspace
  is the only fragile part (saved dock state across Qt versions).

## 8. What I could not determine

- The upstream `v5.2.14` tag was not fetched; I used Revamp's actual base commit `31056c6` (in the clone). Revamp's README compare
  link is against the tag; the two should be nearly equal.
- The clone folder already existed from an earlier attempt: a complete blobless history (264 commits) with **no working tree**
  (its checkout had failed). I read everything through `git show/diff/archive`; nothing was written into the fork. Running
  `git restore --source=HEAD :/` in `forks/krita-revamp` would give a tree later.
- Nothing was built or run: effort numbers are estimates; Qt6 compile problems in the added C++ are unknown beyond a grep of
  Revamp's added lines for removed Qt5 APIs (QRegExp, QStringRef, QDesktopWidget, QMatrix and similar: none found).
- Whether the agent's brush setters reach `KisPaintopBox::sliderChanged` or `slotGuiChangedCurrentPreset` (and so would save a
  "tweak"); this sets the severity of the write leak in feature 7.
- How Revamp's "instant overview" feels on 5.2.14, and master's overview latency; both need a live measurement.
- The licence and origin of Revamp's two folder PNGs, and the licences of most bundled plugins (headers absent).
- The exact scheme name string and the Creative Agent dock's object name (needed for the workspace and `kritarc` keys).
- How the stroke-preview worker threads behave under the fork's stroke code: judged from reading, not run.

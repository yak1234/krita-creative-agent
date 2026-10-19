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

Our own files for the agent speed API (2.x): `libs/libkis/DocumentAgentSpeed.cpp`, `libs/libkis/KisAgentScaledRead.h` and its tests in `libs/libkis/tests/`
(`TestDocumentRegionRefresh`, `TestDocumentScaledProjection`, and the `AgentSpeedBenchmark` timing program, not run by
ctest).

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

**startStroke's end requests (deferred to task 2.9).** Every stroke libkis starts, the agent's included, makes
Krita ask the open strokes to end (`KisImage::startStroke` → `requestStrokeEnd`). The freehand brush keeps going
and the agent's strokes wait behind it, but the transform, move, crop, line and selection tools commit their
in-progress work, and animation playback stops. Per-stroke overrides in 2.9 are to turn this off for agent strokes.

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

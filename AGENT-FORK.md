# Krita Agent: how this fork stays close to upstream

This is a fork of [KDE/krita](https://invent.kde.org/graphics/krita) `master`, built on Qt6. "Krita Agent" is a working
name; the artist chooses the final one (it is set in one place, `cmake/modules/KritaAppIdentity.cmake`). Krita is
GPL-3.0-or-later, and so is everything we add.

Our work lives on the branch `krita-agent`, rebased on upstream `master`. Upstream's history is never rewritten here.
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

Our own files for the identity: `cmake/modules/KritaAppIdentity.cmake`, `libs/global/KisAppIdentity.{h,cpp}`,
`libs/global/config-app-identity.h.cmake`; tests `libs/global/tests/KisAppIdentityTest.{h,cpp}`,
`libs/ui/tests/KisAutoSaveLocationTest.{h,cpp}` and `sdk/tests/KisTemporaryHomeTest.h` (runs a test in a temporary
home, so tests never touch the user's files). Build helpers and the identity gate: `agent/`. This document:
`AGENT-FORK.md`.

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

## Rebase cadence

- **Monthly**, in the first week of the month, onto the current upstream `master`:
  `git fetch origin && git rebase origin/master krita-agent`.
- Before rebasing, tag the current state (`agent-YYYY-MM-pre-rebase`) so it can be compared and restored.
- After rebasing: run `agent/check-identity.sh` (fails on new upstream code that reaches per-user config or data
  folders, QSettings or `*rc` config names without going through `KisAppIdentity`; `agent/check-identity.allow` lists
  the known-safe lines), rebuild (`agent/build-macos.sh --deps`, since KDE's dependency packages move with master), run
  the identity tests above, the plugin's test suite and the Agent-mode test chats against the fork, and update the
  table above if a conflict changed what an edit touches.
- Out of cycle only for an upstream fix we need now, or before a release.
- Dependencies follow upstream's Qt6 branch of `krita-deps-management` (`transition.now/qt6` today; the branch name is
  in upstream's `.gitlab-ci.yml`, `DEPS_QT6_BRANCH_NAME_MACOS`). Read it at rebase time; do not assume it.

## What we offer upstream

Every change that would help any Krita script or user is offered to KDE as a merge request on invent.kde.org, written
against upstream `master` without our branding. If it is accepted, our copy goes away at the next rebase. In
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

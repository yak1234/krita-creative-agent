# Krita fork and painting speed: findings and changes

**Date:** 18 October 2026
**Branch:** `agent-mode-tests` (changes not committed)
**Status:** findings complete; instrumentation written and unit-tested; live measurement not yet run
**Decided (18 October 2026):** the fork targets **Krita master on Qt6**. Porting the plugin to PyQt6 is its first step (section 9).

## 1. The question

The plan is to move from the Krita plugin to a full fork of Krita, the way Cursor forked VS Code, with ideas borrowed from [Krita-Revamp](https://github.com/10zindraws/Krita-Revamp). The fork has two goals:

1. A friendly, Photoshop-like interface.
2. An agent that is part of Krita from launch, not a plugin. It can create `.kra` files and assets before a painting is open. It shows the project like an IDE (paintings, references, brushes, generated assets) inside a Photoshop-style layout. Painting gets faster and better.

This report covers which problems a fork actually solves, based on the Langfuse logs and the plugin code.

## 2. The Photoshop-like UI does not need a fork

Most of it can ship as a Krita bundle today:

- Krita already includes a Photoshop shortcut scheme.
- Themes, workspace layouts, docker placement and Qt stylesheets can all be packaged. Krita-Revamp is mostly this.

Only these parts need a fork:

- replacing the welcome screen;
- a native project tree;
- agent overlays drawn on the canvas.

The UI work can therefore start separately from the fork decision.

## 3. What the Langfuse logs show

Source: Langfuse observations from 9 to 19 October 2026, 98 chats, about 9,200 observations.

| Where the time went | Hours |
|---|---|
| Krita doing the work (tool calls) | **31.3** |
| Model calls (all generations) | 12.4 |

Krita time is about 2.5 times model time, so a faster model would not fix the slowness.

| Finding | Evidence | Would a fork help? |
|---|---|---|
| Reference painting is slow, and its speed varies widely | `paint_from_reference`: 2.0M strokes in 16.8 h, about 33 strokes/s overall. Per call: 15 / 63 / 296 strokes/s (p10 / p50 / p90). Two New Moscow transfers of about 135k strokes took about 4 h each. | **Yes, the most.** See section 4. |
| Paint batches are slow | `paint_batch`: about 4 strokes/s. A 900-stroke batch with a Gaussian blur filter took 591 s. | **Yes.** Redraw only the changed area. |
| Results lost and Krita unreachable | 5 × "Lost the painting operation result". One observe ran 910 s and then failed with "Could not reach Krita". | **Yes.** Run agent work off the UI thread and report real job status. |
| Startup timeouts | 7 × `bootstrapTimedOut` (`krita_screen`, `krita_press_key`) | **Yes.** The agent is built in from launch. |
| Bad model arguments | Most of the 279 tool errors: aspect-ratio mismatch (28), recipe over 200k samples (17), schema errors (about 20) | **No.** Prompt and tool design. |
| Canvas missing from context | 10 × "Canvas not included" | **No.** Panel UX. |

## 4. Why each chunk rebuilds the whole image

The plugin already avoids a rebuild after every stroke. A comment in `creative_tools.py` records that doing so made passes "dozens of times slower". The rebuild happens **once per 256-stroke chunk**, and the canvas is read **twice** per chunk.

Per-step timings the plugin already records (`timings_ms`), taken from today's benchmark runs. This is a small sample, 22 passes longer than 2 s:

| Step | Median | Share of time |
|---|---|---|
| `before`: rebuild, read the full canvas, hash it, save the JPEG view | 6.1 s | 26% |
| `apply`: 256 brush strokes and one rebuild | 13.6 s | 59% |
| `checkpoint`: read again; save the `.kra` every 8 chunks | 0.2 s typical, up to 22.8 s | 12% |

The cost has three sources.

### 4.1 Krita's design: its Python API, not the brush engine

When a person paints by hand, Krita redraws only the tiles that changed. The Python API offers only blunt tools:

- `Document.refreshProjection()` re-composites every layer and reruns every filter mask.
- `waitForDone()` blocks the UI thread.
- `Node.paintPath()` runs synchronously and cannot take pressure. `precision_tools.py:109` refuses pressure for this reason.
- There is no "refresh this area" call and no "tell me when these strokes finish" call.

**Only a fork fixes this.**

### 4.2 Our plugin's choices: fixable now

- The full canvas is read before *and* after every chunk. For a 6000×4500 painting that is about 108 MB copied and SHA-256 hashed, twice per chunk.
- Each 256-stroke chunk gets its own layer. A 135k-stroke transfer creates hundreds of layers, and each new layer makes the next rebuild slower. This compounding explains the 20× speed spread and the 147-group New Moscow file.
- A shortcut already exists: a continuation chunk (`continue_layer_id`) reuses the previous chunk's image instead of reading again (`creative_tools.py`, operation `before` step). It is not used for every chunk.

### 4.3 Pi: not at fault

Pi calls the tool and waits. The 256-stroke chunking lives in our own `krita-creative-agent/src/recipe-tool.mjs`.

### 4.4 Why the rebuild exists: don't remove it, narrow it

From Krita's source (`libs/libkis/Document.h` and `Document.cpp`, current master):

- `refreshProjection()` is documented as "a synchronous recomposition of the projection: everything will wait until the image is fully recomputed". It calls `image()->refreshGraphAsync()`, then `waitForDone()`.
- `waitForDone()` first runs `KisLayerUtils::forceAllDelayedNodesUpdate(rootLayer)`, which brings delayed nodes such as filter masks up to date, and then waits for all image jobs.
- Normal hand painting never uses a full refresh. Strokes go through Krita's stroke system, which reports changed tiles, and only those are redrawn. The full refresh is the safety net for changes outside that system: script pixel writes (`setPixelData`) and structural changes.

Why the plugin calls it. These are correctness guards:

- after `setPixelData` writes (32 call sites), so reads aren't stale;
- before the full-canvas `_creative_revision` hash, so the "painting changed" guard neither refuses falsely nor misses real changes;
- so the model's view shows the true result, filter masks included.

Implications:

- **Plugin:** call the full rebuild only after direct pixel writes or structural changes. *Hypothesis, untested:* after brush-only chunks (`paintPath` goes through the stroke system), `waitForDone()` alone may be enough. Confirm with `before.refresh` timings and a pixel comparison (`scripts/check-live-pixels.py`) before relying on it.
- **Fork:** keep the full refresh; add a region refresh that scripts can call. Scripts then use the same dirty-tile path as hand painting.

### 4.5 Upstream already added pressure strokes

Krita master has `Node.paintPolylineStroke(QList<StrokePoint>)`:

- each `StrokePoint` carries position, pressure, x/y tilt, rotation, tangential pressure, time and speed;
- the whole stroke is one undoable freehand stroke.

The installed Krita **5.3.3** does not have it: searched `/Applications/krita.app`, not found. That's why `precision_tools.py:109` refuses pressure. Pressure strokes therefore need a newer Krita, or a fork based on current master, not new fork code. Take upstream first.

## 5. Model image size stays as it is

The model never receives the full-resolution canvas. `_creative_observe` shrinks every view to **1568 px** at most (`VIEW_SIDE`) and saves it as JPEG (about 0.2 MB). That cap was chosen for speed and token cost, and it stays. A 1M-token context helps keep more history, but each image still costs model time and tokens.

The proposed changes affect only Krita's **internal** full-canvas read, which the model never sees.

## 6. Changes made in this session

Not committed. They are not yet built, installed or loaded in Krita.

### `krita-mcp/krita-plugin/kritamcp/creative_tools.py`

- `_creative_observe` times five parts of every observation and leaves them in `session['observe_ms']`:
  - `refresh`: Krita's recomposite (`refreshProjection` and `waitForDone`). **Cost inside Krita: fork territory.**
  - `read`: `doc.projection(...)` copies the full canvas out.
  - `revision`: SHA-256 of the full canvas plus the layer manifest.
  - `view`: crop, shrink to 1568 px, save JPEG or PNG.
  - `details`: layer list, painted share, content hash, painting weight, artist focus, comic model, protected areas.
- The canvas operation's `lap()` files those parts under the step that observed, as `before.refresh`, `checkpoint.read` and so on.
- `timings_ms.total` sums only the top-level steps (keys without a dot), so totals stay comparable with earlier runs.

`timings_ms` is already logged by `live-diagnostics.mjs` and kept from the model by `tools.mjs:58` (tested in `core.test.mjs:99`). No companion change was needed.

### `krita-creative-agent/tests/test_layer_craft.py`

- New test `test_each_canvas_observation_reports_its_parts_inside_its_step`. A stubbed observation reports parts, and the test checks that:
  - they appear under `before.*`;
  - a step that did not observe has none;
  - `total` excludes them.
- The full Python suite passes: 278 tests (`uv run -q --with pyqt5 --with pillow --with numpy --with httpx python -m unittest discover -s tests -p 'test_*.py'`).
- Limitation: the test harness stubs both `_creative_observe` and `_creative_checkpoint`. The real observation's timings are only checked by a live run.

## 7. Next steps

1. **Live measurement.** This was paused because another session (`poll2.py`) was watching `benchmark-runs/202610190139-tool-choice/test-1`, and its copy `new_moscow_merged.kra` was open in Krita with unsaved changes. When Krita is free:
   1. Build and install (`scripts/build-release.py`, then `scripts/install.py`).
   2. Reload through the bridge. This is a plugin-module change, so no restart is needed.
   3. List open documents, then run `node scripts/evaluate-tool-choice.ts --only moscow-sky --runs 1` with deepseek / deepseek-flash. List open documents again afterwards.
   4. Read `before.*` and `checkpoint.*` from the run's `data/diagnostic-events.jsonl`.
2. **Read the result:**
   - if `refresh` dominates, the cost is inside Krita and is the fork's first job;
   - if `read`, `revision` or `view` dominate, it is our cost.
3. **Plugin fixes, no fork:**
   - skip the extra `before` read by reusing the previous chunk's after-image;
   - hash a smaller copy, or tiles, instead of the full canvas;
   - keep continuation chunks on one layer so the layer count doesn't grow;
   - skip the full rebuild after brush-only chunks, but only if the pixel check in 4.4 confirms it's safe.
4. **Re-measure** with the same Langfuse queries (strokes/s per `paint_from_reference` call) and `timings_ms`. What remains is the fork's job.
5. **Fork, step one:** port the plugin to PyQt6 through a `qt_compat.py` module (section 9).
6. **Fork, first speed milestone:** make strokes per second independent of document size. That needs a region refresh alongside the existing full one, and asynchronous strokes off the UI thread. The fork is based on master, so `paintPolylineStroke` (section 4.5) comes with it instead of us writing a pressure API.
7. **UI track, in parallel, no fork:** a Photoshop-style bundle (shortcuts, theme, workspace), plus fixing the panel's canvas-context handling.

## 8. How the numbers were produced

- Langfuse v2 observations API via `npx langfuse-cli api observations list --from-start-time 2026-09-18T00:00:00Z` (data returned covers 9 to 19 October), grouped by observation name. Latency comes from the `metrics` field.
- Strokes per second come from `completed_strokes` in `paint_from_reference` and `paint_batch` outputs, divided by call latency.
- Step timings: distinct `timings_ms` records with `total` over 2 s, from `benchmark-runs/*/data/diagnostic-events.jsonl` (five runs from 18 to 19 October).
- Working files are in the session scratchpad and are not part of the repo.

## 9. Decision: the fork targets Krita master on Qt6

**Decided:** 18 October 2026, by the artist.

### Krita release lines, checked live on 18 October 2026

Source: download.kde.org/stable/krita/ and the invent.kde.org branches.

| Line | Qt | Plugin as written today | Has `paintPolylineStroke` (pressure, tilt, speed per point)? |
|---|---|---|---|
| 5.3.x (newest 5.3.4.1; installed 5.3.3) | Qt5 | Works | No |
| 6.0.x (newest 6.0.4.1) | Qt6 | Breaks until ported to PyQt6 | No (`krita/6.0` branch checked) |
| master (5.4.0-prealpha on Qt5, 6.1.0-prealpha on Qt6) | Qt5 or Qt6 | Qt5 build works; Qt6 build breaks | **Yes, only here** |

### Why master on Qt6

- The pressure stroke API exists only on master. Basing on master means taking upstream's work instead of writing our own.
- Qt6 is Krita's forward line. A Qt5 fork would need porting later anyway.
- The plugin's Krita 5 / PyQt5 target was never a recorded decision. It most likely came from an assistant working from outdated training data instead of checking current releases. Moving to Qt6 undoes a default, not a deliberate choice.

### What the PyQt6 port involves

- 15 plugin files import `PyQt5` directly (`QtGui` 20 times, `QtCore` 15, `QtWidgets` 4).
- **Enum names:** PyQt6 needs scoped names, e.g. `Qt.SmoothTransformation` becomes `Qt.TransformationMode.SmoothTransformation`, and likewise for `Qt.KeepAspectRatio`, `Qt.UserRole`, `Qt.AlignCenter`, `Qt.ScrollBarAlwaysOff`, `Qt.ItemIsEnabled` and others.
- **Removed:** `exec_()`, in 6 places.
- **Moved classes:** e.g. `QAction` and `QShortcut` move from QtWidgets to QtGui.
- **Tests:** the Python tests run with `uv run --with pyqt5`. They need a PyQt6 run as well.

### How to port

1. Add `krita-mcp/krita-plugin/kritamcp/qt_compat.py`. It imports PyQt6 if available, otherwise PyQt5, and exports the Qt names the plugin uses, with scoped enums mapped on PyQt5.
2. Route every plugin import through it. From then on, no new code imports PyQt5 directly.
3. Run the full suite under both PyQt5 and PyQt6, plus the panel smoke test (`tests/ui_smoke.py`).
4. Live-check on a Krita 6 / master build using a **separate settings folder**, not `~/Library/Application Support/krita`, which holds the working 5.3.3 setup and the installed plugin.

This keeps the plugin running on the current 5.3.3 throughout, so the artist's work continues while the fork is built.

### Until then

- Staying on 5.3.x is fine. Upgrading to 5.3.4.1 is low risk (same Qt) but adds nothing for the agent. Run the test suite and the action audit after any upgrade.
- Before choosing any app, runtime or toolkit version, check what is current upstream. Never assume it from memory.

## 10. Decision: GPL-3.0-or-later for the whole project

**Decided:** 19 October 2026, by the artist.

- Krita's extension API is GPL, and Krita says a distributed plugin must be GPL too. Krita's own sources are `GPL-3.0-or-later` (some files `GPL-2.0-or-later`). So the fork, and the plugin already, are GPL whatever we choose.
- The plugin (`krita-mcp`), the companion (`krita-creative-agent`) and the fork are all **GPL-3.0-or-later**. The companion talks to Krita over a local connection and could arguably stay MIT, but it ships with the plugin and moves into the fork, so one licence keeps it simple.
- `krita-mcp` was MIT. That text is kept verbatim in `krita-mcp/LICENSE.MIT-original`, for any code that came from elsewhere. MIT code may be included in GPL work as long as its notice stays. Pi (MIT) is used the same way.
- Not affected: the artist's paintings, and outside services the app calls (Luna, model endpoints). The app can still be sold, as Krita is on Steam and the Microsoft Store.

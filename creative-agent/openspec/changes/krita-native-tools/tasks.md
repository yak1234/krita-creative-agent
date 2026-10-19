# Krita Native Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The agent reaches clone layers, split by colour, colour to alpha and vetted Krita actions, and picks
Krita's features over strokes when they fit, measured by a tool-choice test set.

**Architecture:** New plugin operations live in a `NativeCraft` mixin (`native_craft.py`) on `CreativeTools`, with
Qt pixel work for splitting in `color_split.py`; each runs through `cmd_creative` (journal, protection, Keep/Undo).
The companion gets tool schemas in `tools.mjs`, a reorganised painter prompt whose worked examples are on-demand
skills, a shipped Pi extension for tool-result hints (the look nudge among them), and a scoring module plus a live
benchmark script that runs each request three times.

**Tech Stack:** Krita 5.3.3 Python API (PyQt5), Node companion (Pi SDK, TypeBox schemas), node:test, unittest.

**Spec:** `openspec/changes/krita-native-tools/specs/krita-native-tools/spec.md`, design in `design.md` beside it.

## Global Constraints

- Never touch Krita while the agent is painting: check idle (`creative_recent_events`, busy false) in its own step
  before any live probe, install or reload. Never call `brush_probe`.
- Live checks run on copies (File → Save As), never on `new_moscow.kra` or another original.
- Python tests: `uv run -q --with pyqt5 --with pillow --with numpy --with httpx python -m unittest discover -s tests -p 'test_*.py'`
  from `krita-creative-agent`; panel smoke `uv run -q --with pyqt5 python tests/ui_smoke.py`; JS `npm run test:unit`
  and `npm run typecheck`. Tests delete every file they write.
- Every new operation: one reversible pass (Keep / Undo), protected areas enforced, the artist's layers' pixels never
  changed, no change to the canvas size.
- Pixel work: no per-pixel Python (Qt, `bytes.translate`, regex runs, big-int bit operations).
- The painter prompt does not grow: after Task 5 it is at most its length at the start of Task 5. Worked examples
  live in on-demand skills, each named by one trigger line in the prompt (Harness² finding: always-on text is paid
  on every turn; a skill costs nothing until it is opened; an unnamed skill is never opened).
- Hints added to tool results live in one shipped Pi extension, `extensions/loop-guards.mjs`, loaded by path
  (`additionalExtensionPaths`) with Pi's extension discovery still off (`noExtensions: true`), the way skills load.
  The benchmark can run with it left out, so its effect is measured apart from the prompt and the tools.
- Split by colour defaults to saved selections; layers only with `as_layers: true` (the artist's choice).
- Plugin fixes need build + install + reload; panel (`creative_docker.py`, `__init__.py`) changes need one Krita
  restart for the whole batch, asked once at the end.

## Review Focus

1. A krita_action while the artist has their own selection → the artist's selection is exactly restored (Task 1).
2. The same krita_action operation_id sent twice (companion retry) → replayed, not mirrored twice (Task 1).
3. Split by colour on a 6000×4500 painting → done in seconds, not minutes (Task 3).
4. Split by colour on a painting that is not 8-bit RGBA → refused before anything changes, as other pixel tools do (Task 3).
5. A clone of a layer that shows inside a protected area → hidden there by a transparency mask (Task 2).

---

### Task 1: Vetted Krita actions

**Files:**
- Create: `krita-mcp/krita-plugin/kritamcp/native_craft.py` (mixin `NativeCraft`), `krita-mcp/krita-plugin/kritamcp/krita_actions.json`
- Create: `krita-creative-agent/scripts/audit-krita-actions.mjs`
- Modify: `creative_tools.py` (mixin, operation tuple, validate/apply branches, `NEW_CONTRIBUTIONS`), `tools.mjs`, `craft.mjs`
- Test: `krita-creative-agent/tests/test_native_craft.py`, `tests/core.test.mjs`

**Interfaces:**
- Produces: plugin operation `krita_action {action: str, target?: layer_id, selection?: saved name, save_as?: saved
  name, name?}`; `NativeCraft._native_actions(version: str) -> list[dict]` (entries `{id, label, kind: 'pixels' |
  'selection', needs: ['target'] | ['target','selection'] | ['selection']}`); plugin operation `krita_actions_audit
  {candidates: [str]}` → `{version, results: [{id, status: 'ok'|'dialog'|'missing'|'error', changed, undone}]}`,
  allowed only with no creative session; companion tool `krita_action` whose `action` enum is the list for the
  connected Krita's version (from `krita_capabilities`).
- `krita_actions.json` shape: `{"<krita version>": [entry, …]}`; empty object until the audit runs.

- [ ] **Step 1: Write failing tests** in `test_native_craft.py` with a fake Krita whose `action(id).trigger()` records
  calls and edits the active node:
  - `test_an_action_not_on_the_list_is_refused_with_the_list`: unknown id → `ValueError` naming available ids; no trigger.
  - `test_no_actions_on_an_unaudited_krita_version`: version missing from the json → refused, message says the
    installed Krita has not been audited.
  - `test_a_pixel_action_edits_a_copy_of_an_agent_layer_and_reject_restores_it`: mirror on an agent paint layer →
    trigger ran with the copy active; `review_pass` reject → original visible, copy gone.
  - `test_a_pixel_action_refuses_the_artists_layer`: target not owned → refused, no trigger.
  - `test_a_selection_action_restores_the_artists_selection` (Review Focus 1): artist selection S set; run
    `selectopaque` with `save_as: 'Car'` → saved selection "Car" exists, `doc.selection()` equals S afterwards.
  - `test_a_replayed_action_runs_once` (Review Focus 2): same operation_id twice → one trigger, second replayed.
  - `test_the_audit_refuses_during_a_session`.
- [ ] **Step 2: Run them; expect** failures on unknown operation `krita_action`.
- [ ] **Step 3: Implement** in `native_craft.py`: `_native_validate_action(doc, session, params)`,
  `_native_action(doc, session, params) -> dict`, `_native_actions(version)`, `_native_audit(params) -> dict`.
  Pixel kind: `_craft_edit_copy` on the target, make the copy active, `Krita.instance().action(id).trigger()`,
  `doc.waitForDone()`, `_craft_finish_copy`. Selection kind: keep `doc.selection()`, set the input selection
  (saved name or none), make the target active, trigger, read `doc.selection()` into a saved selection via
  `_region_save`, restore the artist's selection in `finally`. Audit: create a throwaway 256×256 document with one
  painted layer and a selection, show it in a view, trigger each candidate, check `QApplication.activeModalWidget()`
  and new top-level windows on a timer at 300 ms and 1500 ms (close any found → `dialog`), compare pixel data
  before/after (`changed`) and after `edit_undo` (`undone`), close the document without saving.
- [ ] **Step 4: Companion:** `krita_action` tool in `tools.mjs` (description: Krita's own menu commands from the
  vetted list; pixel actions change a copy of your layer, selection actions save a named selection), add to
  `CRAFT_TOOLS` and `CRAFT_OPERATIONS` in `craft.mjs`, and to `routing.mjs` `transform` and `move`. Test in
  `core.test.mjs`: `krita_action` schema accepts `{action:'mirrorNodeX', target:'L1'}`.
- [ ] **Step 5: `audit-krita-actions.mjs`** sends `krita_actions_audit` over the bridge with the candidates from the
  design (mirrorNodeX, mirrorNodeY, rotateLayer180, rotateLayerCW90, rotateLayerCCW90, selectopaque,
  selectopaque_add, selectopaque_subtract, selectopaque_intersect, invert_selection, clear, split_alpha_into_mask,
  convert_to_paint_layer) and writes the `ok` and `undone` ones to `krita_actions.json` under the reported version
  with labels and kinds; it refuses when the companion reports busy.
- [ ] **Step 6: Run all suites; expect** green. Commit `Native craft: vetted Krita actions and their audit`.

### Task 2: Clone layers

**Files:** Modify `native_craft.py`, `creative_tools.py`, `protection.py` (`MASKED_TYPES`), `tools.mjs`, `craft.mjs`;
Test `test_native_craft.py`, `test_protection.py`.

**Interfaces:**
- Produces: plugin operation `clone_layer {source: layer_id, name, blend_mode?, opacity?, clip_to?, offset?: [dx,
  dy], stage_id?, region?}` → `{layer_id, layer_type: 'clonelayer', source_layer_id}`; companion tool `clone_layer`.

- [ ] **Step 1: Failing tests:** `test_a_clone_of_the_artists_layer_leaves_it_unchanged` (pixels, name, parent,
  visibility equal before/after; reject removes only the clone); `test_a_clone_offset_moves_it` (offset [400, 0]
  → a transform mask with move [400, 0] on the clone, through `_transform_apply`'s XML); in `test_protection.py`
  `test_a_clone_is_masked_inside_a_protected_area` (Review Focus 5: `clonelayer` in `MASKED_TYPES`, a transparency
  mask added).
- [ ] **Step 2: Run; expect** failures on unknown operation `clone_layer`.
- [ ] **Step 3: Implement** `_native_validate_clone`, `_native_clone` with `doc.createCloneLayer(name, source)`,
  placed like `_craft_create` places a new layer (stage container, `_craft_apply` for blend/opacity/clip); offset via
  a transform mask as in `transform_craft.py`. Add `clonelayer` to `MASKED_TYPES` and `MOVABLE`.
- [ ] **Step 4: Companion** `clone_layer` tool (description: a live copy of any layer that follows the original: a
  repeated motif, a reflection with transform_layer and a blur filter mask); `CRAFT_TOOLS`, `CRAFT_OPERATIONS`.
- [ ] **Step 5: Suites green.** Commit `Native craft: clone layers`.

### Task 3: Split by colour

**Files:** Create `krita-mcp/krita-plugin/kritamcp/color_split.py`; modify `native_craft.py`, `creative_tools.py`,
`tools.mjs`, `craft.mjs`, `routing.mjs`; Test `tests/test_color_split.py` (real Qt in a child process, as
`test_protection_raster.py`), `test_native_craft.py`.

**Interfaces:**
- Produces: `color_split.palette(bgra: bytes, width: int, height: int, count: int) -> list[tuple[int,int,int]]` (on a
  downscaled copy, at most 400 px on the long side, opaque pixels only, median cut); `color_split.assign(bgra, width,
  height, palette) -> bytes` (one palette index per pixel, by Qt `convertToFormat(Format_Indexed8, table,
  Qt.ThresholdDither)`; transparent pixels get 255); `color_split.masks(indices: bytes, count: int) -> list[bytes]`
  (255 where the index matches, by `bytes.translate`).
- Plugin operation `split_by_color {source: layer_id | 'visible', colors: 2-24 = 8, region?, min_area?: int = 0.2%
  of the canvas, as_layers?: false, name_prefix?: 'Split'}` → `{selections: [{name, color: '#rrggbb', share: 0-1,
  bounds}], group_id?}`. Without `as_layers` it is not a canvas change (no pass), like `select`; with it, one pass
  whose `layer_id` is a group holding one agent layer per colour.

- [ ] **Step 1: Failing tests** in `test_color_split.py`: `test_palette_finds_the_main_colours` (an image of three
  flat colours → three palette colours within 8 per channel); `test_assign_and_masks_partition_the_pixels` (every
  opaque pixel in exactly one mask, transparent in none); `test_a_full_size_split_takes_seconds` (Review Focus 3:
  6000×4500 with three colours and noise, `palette`+`assign`+`masks` under 5 s). In `test_native_craft.py`:
  `test_split_saves_named_selections_without_a_pass` (names `Split 1 · #rrggbb`, shares sum ≤ 1, small regions
  dropped); `test_split_as_layers_is_one_pass_reject_removes_the_group`; `test_split_refuses_a_non_rgba_painting`
  (Review Focus 4, via `_craft_check_rgba`).
- [ ] **Step 2: Run; expect** import and unknown-operation failures.
- [ ] **Step 3: Implement** `color_split.py`, then `_native_validate_split` and `_native_split` (read the source in
  strips like `_region_source`, save each mask with `_region_save`; layers: one paint layer per colour with
  `setPixelData` of the source pixels where the mask is set, in one new group in the stage).
- [ ] **Step 4: Companion** `split_by_color` tool (description: the painting's main colour regions as saved
  selections for select/fill_region; finds areas of one colour, not objects: combine several with select steps);
  `CRAFT_TOOLS`; `routing.mjs` `fill` and `inspect`. Schema test in `core.test.mjs`.
- [ ] **Step 5: Suites green.** Commit `Native craft: split by colour`.

### Task 4: Colour to alpha

**Files:** Modify `tools.mjs` (`apply_filter` description), `prompt.mjs`; only if Krita lacks the filter:
`native_craft.py`, `region_raster.py`. Test `core.test.mjs` or `test_native_craft.py`.

- [ ] **Step 1: Check, read only, Krita idle:** `krita_capabilities` lists `colortoalpha` and its properties (the
  colour and threshold names). Ledger the result.
- [ ] **Step 2 (filter present): Failing test** `apply_filter describes colour to alpha` asserting the
  description names `colortoalpha` with its colour and threshold property names; then add that sentence (mode copy
  on your layer, or a copy of the artist's sketch through a clone or an edit copy). (Filter absent): failing test
  `test_color_to_alpha_lifts_white_off_a_copy` and an operation `color_to_alpha {layer_id, color, threshold}` with
  pixel code in `region_raster.py` (alpha from the distance to the colour, colour un-premultiplied).
- [ ] **Step 3: Suites green.** Commit `Native craft: colour to alpha`.

### Task 5: Choosing the right tool — the prompt and skills

**Files:** Modify `src/prompt.mjs`, `src/studio.mjs` (`BATCH_GUIDANCE`), `skills/paint-sky/SKILL.md`,
`skills/fix-region/SKILL.md`; Create `skills/repaint-area/SKILL.md`, `skills/repeat-motif/SKILL.md`; Test
`tests/brush-catalog.test.mjs`, existing prompt assertions in other tests.

- [ ] **Step 1: Record the baseline:** `PAINTING_INSTRUCTIONS.length` at the start of this task, as a constant in
  the test.
- [ ] **Step 2: Failing tests:** sections `<role>`, `<choosing_a_tool>`, `<tool_calling>`, `<protection>` present in
  that order; `<choosing_a_tool>` is a short job → feature table naming seed, split_by_color, fill_region,
  create_layer fill, apply_filter mask, clone_layer, krita_action and "strokes for marks, edges, texture and detail";
  `<tool_calling>` says to name the Krita method in one line before each painting call and not to observe again
  without a change; every skill directory under `skills/` is named verbatim in the prompt by a "load the `<name>`
  skill" trigger line; length ≤ baseline; `BATCH_GUIDANCE` no longer recommends paint_recipe for a sky or mass.
- [ ] **Step 3: Failing tests for the skills:** `repaint-area` holds the worked sequences for an existing area
  (repaint a sky; make windows glow; darken a street): select with a seed or split_by_color, then fill_region, a
  fill layer or an apply_filter mask, strokes only as clipped texture; `repeat-motif` holds the lamp-post sequence
  (clone_layer with offset, krita_action mirror, transform_layer); each has `name:` matching its folder and a
  `description:` naming its trigger.
- [ ] **Step 4: Reorganise** `PAINTING_INSTRUCTIONS` into those sections, moving existing guidance (the five-step
  layer order goes into `<choosing_a_tool>`), not duplicating it; procedure that has a recognisable trigger moves
  out to a skill, which is what pays for the new table. `BATCH_GUIDANCE`: a mass is a fill or fill layer inside a
  selection; recipes are texture on a clipped layer. paint-sky step 2 and fix-region: select an existing area with a
  seed or split_by_color.
- [ ] **Step 5: All suites green** (existing prompt tests updated only where they quoted moved text). Commit
  `Painter prompt: sections and a tool-choice guide; worked examples as skills`.

### Task 6: Loop guards as a Pi extension

**Files:** Create `extensions/loop-guards.mjs`; modify `src/runtime.mjs` (`openSession`: `additionalExtensionPaths`,
a shared `eventBus`), `src/skills.mjs` or a new `src/extensions.mjs` (`EXTENSIONS_DIR`), `src/studio.mjs` (remove
`craftNudge` and its call in `afterPainting`; emit settings on the bus), `scripts/build-release.py` and
`scripts/curate-public-repo.py` (copy `extensions/` beside `skills/`); Test `tests/loop-guards.test.mjs`, the
existing `craftNudge` tests moved there.

**Interfaces:**
- Produces `export default function loopGuards(pi: ExtensionAPI)`: one `pi.on('tool_result', …)` handler that
  returns `{ content: [...event.content, { type: 'text', text: JSON.stringify({ craft_hint }) }] }` or nothing. It
  never blocks a call and adds at most one hint per result.
- The handler keeps its own state from the events it sees (no import from `src/`): looks in a row, plain-stroke
  streak, the last observed canvas width, height and revision (read from observe results).
- Settings arrive on the shared bus as `pi.events.on('krita:guards', { native_craft })`; with `native_craft` false it
  adds nothing. `config.loopGuards === false` leaves the extension out of `additionalExtensionPaths` entirely.

- [ ] **Step 1: Failing test, real loader:** `the shipped extension loads with discovery off` — a
  `DefaultResourceLoader` with `noExtensions: true` and `additionalExtensionPaths: [EXTENSIONS_DIR]` lists
  `loop-guards`, and a session with one stub custom tool fires its `tool_result` handler for that tool. If
  `tool_result` does not fire for custom tools, stop and ledger a ruling: the guards then wrap tool `execute`.
- [ ] **Step 2: Failing tests, fake `pi`:** the existing craftNudge cases (a plain stroke pass over ≥ 12% of the
  canvas → the mass hint; four plain-stroke calls in a row → the streak hint; clipped or blended passes do not
  count); `four looks without a change carry the nudge` (fourth `observe_canvas` result contains "looked 4 times
  without changing anything"); `a painting call resets the look count`; `a new canvas revision resets it`;
  `reference views do not count`; `a refused batch gets its fix hint` (an `isError` result whose text names an
  off-canvas coordinate or an unknown layer id gets one line saying what to change); `native_craft false adds
  nothing`; `an error result is never given two hints`.
- [ ] **Step 3: Implement** the extension and the loading. Look-nudge text: `You have looked N times without
  changing anything. Select the area with a seed or split_by_color, take colours with sample_canvas_colors, then
  act.` The mass and streak texts are moved verbatim from `craftNudge`.
- [ ] **Step 4: `npm run build:release`**, then check the bundle has `extensions/loop-guards.mjs` and a release
  session lists it.
- [ ] **Step 5: Suites green.** Commit `Loop guards: a shipped Pi extension for tool-result hints, with a look
  nudge`.

### Task 7: Tool choice measured

**Files:** Create `src/tool-choice.mjs`, `scripts/tool-choice-scenarios.json`, `scripts/evaluate-tool-choice.mjs`;
Test `tests/tool-choice.test.mjs`.

**Interfaces:** Produces `methodsOf(call, canvas: {width, height}) -> string[]` (`seed`, `split`, `fill`,
`fill_layer`, `filter_mask`, `clone`, `action`, `strokes`, `strokes_mass` when a plain stroke pass covers ≥ 12% of
the canvas, `look`); `scoreToolChoice(calls, scenario) -> {used: string[], score: 0-1, missing: string[], avoided:
string[]}` where `scenario = {id, painting, prompt, good: string[][] (any one method of each inner list),
bad: string[]}`.

- [ ] **Step 1: Failing tests** for `methodsOf` on each tool and for `scoreToolChoice` (a sky run with seed + fill →
  1; with strokes_mass → penalised, `avoided` lists it).
- [ ] **Step 2: Implement.** Scenarios: about 10 across copies of New Moscow, Starry Night and the Great Wave
  (repaint the sky; make the windows glow; darken the street; repeat a lamp post; lift the moon's glow; soften the
  background; recolour a coat; add a reflection in the water; a cloud bank; mirror a figure), each with good and bad
  methods.
- [ ] **Step 3: `evaluate-tool-choice.mjs`** runs each scenario `--runs 3` times (default) as
  `live-painting-run.mjs` does (own data folder, test painter model deepseek-flash, a fresh copy of the painting per
  run), reads the chat's tool calls, scores them and writes `benchmark-runs/<stamp>-tool-choice/report.json` and a
  table. Per scenario the report gives counts across runs, not one run ("seed or split in 3/3; strokes_mass in
  0/3"), the mean score, and runs that changed nothing (a run that painted nothing is the worst outcome and is
  listed by name). `--no-guards` starts the companion with `loopGuards: false`; `--compare <earlier report>` prints
  both side by side, marking a difference that appears in only one run of three as noise.
- [ ] **Step 4: Suites green.** Commit `Tool choice: scoring and a live test set`.

### Task 8: Install and live check

- [ ] **Step 1:** Check whether any panel file changed in Tasks 1-7 (`git diff --stat` for `creative_docker.py`,
  `__init__.py`). If none, a bridge reload suffices; otherwise one install and one restart, asked once.
- [ ] **Step 2:** Krita idle → build, install, reload; confirm the build id in `creative_inspect_state`.
- [ ] **Step 3:** Krita idle → run `audit-krita-actions.mjs`; commit `krita_actions.json`; build, install, reload again.
- [ ] **Step 4:** On a copy of New Moscow: "repaint the sky to be more natural looking". Expect a seed or split
  selection, a fill or fill layer, no stroke pass over 12% of the canvas, the woman and car untouched.
- [ ] **Step 5:** Run `evaluate-tool-choice.mjs` three ways, so each change is measured on its own: the old build
  (`--companion`, the release before Task 1); the new build `--no-guards` (tools, prompt and skills); the new build
  in full. Report the three side by side, with each difference given a verdict: helped, hurt, no observed effect, or
  noise. "Keep the old build" is an allowed conclusion. Mark the OpenSpec tasks done.

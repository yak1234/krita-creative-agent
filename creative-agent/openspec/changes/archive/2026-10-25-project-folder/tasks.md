# Guided Trace and Project Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> In this repository: one agent per task group (A, B) in its own worktree, a fresh reviewer per branch, lead
> verification, then merge (krita-fork/batches.md quality gates).

**Goal:** The agent draws its own construction guides from references on separate guide layers before painting an
element, and the artist can open a folder of references that the agent reads, plans from (one element per move, plan
approved first) and keeps notes in.

**Architecture:** Guides are a new plugin operation that paints thin strokes onto agent-owned layers inside one
"Guides · Creative Agent" group, outside every stage group, so Keep/merge never takes them; Undo of a move hides them
with the move's other passes. The companion gets two tools (`draw_guide`, `finish_guide`) whose lines may be given in
reference pixels and are mapped like the reference tools. The project folder is a read-only scan (a new strict
TypeScript module) that attaches the folder's images as references, feeds Plan proposal in Agent mode, and writes only
Markdown (`PLAN.md`, `NOTES.md`, backups) back into the folder.

**Tech Stack:** Python plugin (kritamcp, PyQt5/PyQt6 via qt_compat, tests with uv + unittest), Node companion
(ES modules; new modules strict TypeScript; `node --test` via `npm run test:unit`; `npm run typecheck`).

**Spec:** `creative-agent/openspec/changes/project-folder/proposal.md` (approved 2026-10-20).

## Global Constraints

- The reference tools (`paint_from_reference`, `paint_reference_edges`, `paint_reference_surface`,
  `continue_reference_painting`, `list_reference_paintings`) are not changed in any way.
- Nothing reaches the painting except through painting tools; no reference is placed as an image layer.
- A guide layer never holds reference pixels, is never merged, never feeds Luna's review or pass checks, and is hidden
  when its element is ticked.
- In Agent mode the agent stops after each element (one move, then Keep / Undo / Refine), as today.
- The folder: read PNG, JPEG, GIF images and `.md`, `.txt`, `.json` (as text); never run, follow links out of, or write
  anything but Markdown into it. WebP is listed as skipped ("not supported yet") until `files.mjs` decodes it.
- Protection changes stay the artist's: the agent only proposes (existing `propose_protection`).
- The painter prompt (`PAINTING_INSTRUCTIONS`) may not exceed 13330 characters (brush-catalog.test.mjs): guide guidance
  goes in a skill file plus at most one short line in the prompt.
- New companion modules are strict TypeScript; plugin code uses qt_compat and scoped enums.
- Tests clean up after themselves; Python via uv; no test opens a dialog or touches a real profile.

## Review Focus

1. A guide drawn inside a move, then Keep: the guide must stay a separate, still visible guide layer (not merged).
2. A move with a guide, then Undo: the guide disappears with the move.
3. `tidy_painting` and `merge_agent_work` after an element is ticked: the hidden guide survives tidy (the artist may
   show it again) and is never merged.
4. A folder with 40+ images, a 50 MB file, a symlink pointing outside, a script and a WebP: scan stays within caps,
   skips and lists the rest, follows nothing outside.
5. Resume after the artist hand-edited `PLAN.md` (reordered or removed lines): the agent shows the difference and asks
   before following it.

---

## Group A: guided trace (ships first)

### Task A1: Guide layers in the plugin

**Files:**
- Create: `creative-agent/krita-mcp/krita-plugin/kritamcp/guide_craft.py`
- Modify: `creative-agent/krita-mcp/krita-plugin/kritamcp/creative_tools.py` (dispatch of mutating ops ~:555-611,
  :650-738; journal ~:782-819; `CreativeTools` class list), `native_craft.py` (`_native_tidy` ~:180,
  `_native_merge_agent` ~:218), `creative_validation.py` (a `validate_guide`), `canvas_view.py` or
  `creative_tools.py::_creative_observe` (~:2047) for the `guides` flag
- Test: `creative-agent/krita-creative-agent/tests/test_guide_craft.py`

**Interfaces:**
- Produces: plugin ops
  - `draw_guide {element: str ≤60, strokes: [stroke ≤256], stage_id, expected_revision}` → `{status, layer_id,
    pass_id, element}`. Strokes use the `paint_pass` stroke shape; the plugin forces its guide brush (thin round,
    2-4 px, colour `#4fb3ff` at 70 % layer opacity). Creates or extends the layer "Guide · <element>" inside the group
    "Guides · Creative Agent" (top of the stack, outside stage groups), records a pass `{kind:'guide', stage_id,
    layer_id, element}` so `review_pass reject stage:move-N` hides it.
  - `finish_guide {element}` → `{status, layer_id, visible:false}`: hides that guide layer (not a pass; idempotent).
  - `observe` gains optional `guides: bool` (default true): false hides the guides group for the projection read and
    restores it in a `finally`.
- Merge: `merge_passes` and `_native_merge_agent` never take a layer inside the guides group; `_native_tidy` never
  removes it.

- [x] **Step 1: Write the failing tests** in `test_guide_craft.py` with the `test_native` stub tree pattern
  (`tests/test_layer_craft.py:1-30`): `test_draw_guide_creates_its_layer_in_the_guides_group` (group name, layer name
  "Guide · Towers", outside every 'Creative Agent · <stage>' group, opacity 0.7),
  `test_a_second_guide_for_the_same_element_extends_its_layer`, `test_reject_of_the_move_hides_the_guide`,
  `test_finish_guide_hides_and_is_idempotent`, `test_merge_passes_and_merge_agent_ignore_guides`,
  `test_tidy_keeps_hidden_guides`, `test_observe_without_guides_hides_and_restores_the_group` (also on an exception),
  `test_guide_rejects_bad_input` (empty element, >256 strokes, unknown fields).
- [x] **Step 2: Run them to see them fail**
  Run (from creative-agent/krita-creative-agent): `uv run -q --with pyqt5 --with pillow --with numpy --with httpx
  --with opencv-python-headless python -m unittest tests.test_guide_craft -v` — Expected: errors (no module).
- [x] **Step 3: Implement** `GuideCraft` (mixin like the other *Craft classes) in `guide_craft.py` with
  `_guide_draw(doc, session, params) -> dict` and `_guide_finish(doc, session, params) -> dict`; reuse the
  `paint_pass` stroke path (`_creative_stroke_job` on the fork) with the forced brush; wire validation, dispatch and
  journal; exclude the group in merge/tidy; add the `observe` flag.
- [x] **Step 4: Run** the new tests and the whole Python discover suite — Expected: all pass.
- [x] **Step 5: Commit** "Guide layers: draw_guide and finish_guide in their own group, never merged, hidden on undo".

### Task A2: Guide tools, setting and skill in the companion

**Files:**
- Create: `creative-agent/krita-creative-agent/src/guide-tool.ts`, `creative-agent/krita-creative-agent/skills/guided-trace/SKILL.md`
- Modify: `src/tools.mjs` (register via `paintingTools`, ~:151-320), `src/studio.mjs` (`mutates()` ~:96 adds
  `draw_guide`; `selectTools` ~:828 offers the tools in Agent and Autopilot), `src/settings-schema.mjs` (one entry),
  `src/prompt.mjs` (one line in `<painting>` pointing to the skill; skills list ~:19-25), `src/reference-generator.mjs`
  (export the source→target point mapping used at ~:36/:61 as `mapReferencePoint`)
- Test: `tests/guide-tool.test.mjs`, prompt assertions added to `tests/brush-catalog.test.mjs`

**Interfaces:**
- Consumes: A1 ops `draw_guide`, `finish_guide`.
- Produces:
  - tool `draw_guide {element, reference_id?, source?: [x,y,w,h], target?: [x,y,w,h], lines: [{points: [[x,y],
    ...2..64]}] ≤128}`: without `reference_id`, points are canvas pixels; with it, points are reference pixels mapped by
    `mapReferencePoint(source, target)` (same aspect rule as `sameAspect`). Each polyline becomes one stroke for the
    plugin.
  - tool `finish_guide {element}`.
  - setting `{key:'guides', type:'boolean', default:true, panel:'generic', label:'Draw guides from references',
    tooltip:'Before painting an element from a reference, sketch construction lines on a hidden guide layer.'}`.
  - skill `guided-trace`: when to guide (placement and shape of an element from a goal image or an element
    reference), what to draw (horizon, vanishing lines, silhouette and block-in, key proportions; a few dozen lines,
    never outlines of every detail), that the goal image decides placement and an element reference decides shape,
    then paint over the guide in its own strokes (the reference tools may give colour), then `finish_guide`.

- [x] **Step 1: Write the failing tests** in `tests/guide-tool.test.mjs` with `fakeRuntime()` from
  `tests/tool-functions.test.mjs:13-18`: `draw_guide in canvas pixels reaches the plugin as strokes`,
  `draw_guide maps reference points through source and target` (a point at the source centre lands at the target
  centre; a mismatched aspect is refused with the reference tools' message),
  `finish_guide reaches its operation`, `the guides setting off removes both tools from the offered list`; and in
  `tests/brush-catalog.test.mjs`: `the prompt names the guided-trace skill and stays under 13330 characters`.
- [x] **Step 2: Run** `npm run test:unit` — Expected: the new tests fail.
- [x] **Step 3: Implement** `guideTools(runtime): Tool[]` in `src/guide-tool.ts`; export `mapReferencePoint` from
  `reference-generator.mjs` without changing the reference tools' behaviour (their tests stay green); add the setting,
  the prompt line and the skill.
- [x] **Step 4: Run** `npm run test:unit` and `npm run typecheck` — Expected: all pass, reference tests unchanged.
- [x] **Step 5: Commit** "Guided trace: draw_guide and finish_guide tools, the setting, the guided-trace skill".

### Task A3: Guides never judge the painting

**Files:**
- Modify: `src/studio.mjs` (`reviewCanvas` ~:2011, `visualPassCheck` ~:667 and the before/after observes that feed
  Luna) to pass `guides:false`; `extensions/luna-review.ts` only if it observes itself
- Test: `tests/studio.test.mjs`

- [x] **Step 1: Write the failing tests** with `harness(respond, bridgeHook)` (`tests/studio.test.mjs:40`):
  `review and pass checks observe without guides` (every observe sent for Luna, pass checks and the final review has
  `guides:false`), `the painter's own observe still shows guides` (no `guides` key or true), and
  `a move with a guide: Keep merges the paint and leaves the guide` (bridge hook records `merge_passes` params; the
  guide's layer id is absent).
- [x] **Step 2: Run** `npm run test:unit` — Expected: fail.
- [x] **Step 3: Implement** the flag on those call sites.
- [x] **Step 4: Run** `npm run test:unit` — Expected: pass.
- [x] **Step 5: Commit** "Guides: Luna's review and pass checks look at the painting without guides".

**Group A done when:** the lead rebuilds and packages, and a live Agent move on a copy painting draws a guide, paints
over it, keeps the guide layer separate, and hides it on `finish_guide`.

---

## Group B: project folders (after Group A is merged)

### Task B1: Reading a folder

**Files:**
- Create: `creative-agent/krita-creative-agent/src/project-folder.ts`
- Test: `tests/project-folder.test.mjs`

**Interfaces:**
- Produces: `scanFolder(dir: string, limits = FOLDER_LIMITS): Promise<FolderIndex>` with
  `FOLDER_LIMITS = {images: 40, imageBytes: 12_000_000, textBytes: 200_000, files: 400}` and
  `FolderIndex = {root: string, goal: FolderImage | null, elements: FolderImage[], texts: FolderText[],
  prompts: Record<string,string>, skipped: {name: string, reason: string}[]}`;
  `FolderImage = {name, path, width, height, mimeType, role: 'goal'|'element', guess: string}`;
  `FolderText = {name, path, kind: 'brief'|'readme'|'plan'|'notes'|'other', chars: number}`.
  Rules: only regular files directly in the folder and one level of subfolders; `realpath` must stay inside `dir`
  (`containedFile` pattern from `src/files.mjs:5`); image types by `imageInfo` (`src/files.mjs:13`); the goal is a file
  named like `final_goal`, `goal`, `target` (case-insensitive) or, failing that, none; element guesses from the file
  name (`04-kremlin-towers.png` → "Kremlin towers") and a matching entry in a `*prompts*.json`; `PLAN.md` and
  `NOTES.md` are recognised as plan and notes.

- [x] **Step 1: Write the failing tests** with temporary folders (removed after): `the artist's layout is read`
  (a copy of the new_moscow shape built from tiny PNGs: goal found, 12 elements ordered by their number, guesses
  "Moonlit sky" … "Vintage convertible", the brief recognised, prompts read), `caps and skips` (41 images → 40 read +
  1 skipped "too many images"; a 13 MB file skipped "too large"; `run.py`, `app.zip`, a `.webp` skipped with reasons),
  `a symlink pointing outside is skipped`, `nothing is written while scanning` (folder bytes unchanged).
- [x] **Step 2: Run** `npm run test:unit` — Expected: fail.
- [x] **Step 3: Implement** `scanFolder` (no external dependencies).
- [x] **Step 4: Run** `npm run test:unit`, `npm run typecheck` — Expected: pass.
- [x] **Step 5: Commit** "Project folder: a read-only scan with caps, roles and guesses".

### Task B2: Opening a folder from the panel

**Files:**
- Modify: `creative-agent/krita-mcp/krita-plugin/kritamcp/creative_docker.py` (the attach menu ~:1471-1483: "Open
  project folder…"; a compact folder card above the plan bar ~:1369 listing the goal, the elements with their guesses
  and an Edit control for a guess, and the skipped count), `src/main.mjs` (command switch ~:34-71), `src/studio.mjs`
  (`openFolder`, `renameFolderElement`, attaching folder images through `addReferences` ~:1004 with role
  `'reference'`/purpose `'composition'` for the goal and role `'asset'` for elements, `context()` ~:979 gains
  `folder: {root, goal, elements:[{name, reference_id, guess}], texts}`)
- Test: `tests/studio.test.mjs` (folder events), `tests/ui_panel_folder.py` (new, registered in `agent/ci.sh`'s panel
  UI group)

**Interfaces:**
- Consumes: `scanFolder` (B1).
- Produces: panel → companion `{type:'open_folder', path}`, `{type:'folder_guess', name, guess}`; companion → panel
  `{type:'folder', index: FolderIndex (paths relative to root), references: {name: reference_id}}`. The folder path
  is stored on the study (`study.folder`) and so follows the chat.

- [x] **Step 1: Write the failing tests**: companion `opening a folder attaches its images and tells the panel`,
  `a corrected guess reaches the painter's context`; panel (stubbed `process.write`, pattern of
  `tests/ui_panel_features.py:90-104`) `the attach menu has Open project folder`, `a folder event shows the goal, the
  elements and the skipped count`, `editing a guess sends folder_guess`.
- [x] **Step 2: Run** the tests — Expected: fail.
- [x] **Step 3: Implement**; strings through `product_name()` where they name the app.
- [x] **Step 4: Run** `npm run test:unit`, the uv discover suite and `uv run -q --with pyqt5 python
  tests/ui_panel_folder.py` — Expected: pass.
- [x] **Step 5: Commit** "Project folder: open it from the panel; the agent sees the goal and elements".

### Task B3: The element plan in Agent mode, Markdown in the folder, resume

**Files:**
- Create: `creative-agent/krita-creative-agent/src/folder-notes.ts`
- Modify: `src/studio.mjs` (Agent mode with `study.folder`: the first turn must call `propose_plan` with one step per
  element and no painting tool is offered until the artist approves; after each kept move the step's checkbox is
  ticked and `NOTES.md` gets a line; when a step is ticked the companion calls `finish_guide` for its element and the
  painter may call `propose_protection` for it), `skills/guided-trace/SKILL.md` (one paragraph on folder plans),
  `creative_docker.py` (the plan bar shows the current element)
- Test: `tests/folder-notes.test.mjs`, `tests/studio.test.mjs`

**Interfaces:**
- Consumes: B2 `study.folder`, A2 tools, existing `propose_plan` / `editPlan` / `approved_revision`.
- Produces: `writePlan(root: string, brief: Brief, ticked: number[]): Promise<void>` (writes `PLAN.md`: a few intent
  lines, then `- [x] 1. <step title> (<reference file>) · layer "<name>"` lines); `appendNote(root, line: string)`;
  `readPlan(root): Promise<{lines: string[]} | null>`; `planDifference(brief, lines): string[]` (human-readable
  changes); `editMarkdown(root, name, text)` that, for a file the agent did not create, first writes
  `<name>.backup-<yyyy-mm-dd>.md` and returns `{changed: true, backup}`. All writes stay inside `root`
  (realpath check) and only to `.md`.

- [x] **Step 1: Write the failing tests**: `PLAN.md is written with ticks and references`, `NOTES.md only grows`,
  `editing the artist's brief makes a dated backup first`, `writing anything but .md or outside the folder is refused`,
  `planDifference lists a reorder and a removal`; studio: `with a folder, Agent mode proposes the element plan and
  paints nothing before approval`, `after Keep the step is ticked, PLAN.md updated, NOTES.md gains a line and the
  element's guide is finished`, `resume with a hand-edited PLAN.md shows the difference and waits`.
- [x] **Step 2: Run** `npm run test:unit` — Expected: fail.
- [x] **Step 3: Implement** `folder-notes.ts` and the studio wiring.
- [x] **Step 4: Run** `npm run test:unit`, `npm run typecheck`, the uv suite and the panel UI scripts — Expected:
  pass.
- [x] **Step 5: Commit** "Project folder: an element plan approved first, PLAN.md and NOTES.md, resume".

**Group B done when:** a live session on a copy of the `new_moscow` folder (never the original; images only read)
opens the folder, shows the plan, paints the sky as one element with a guide, ticks it in `PLAN.md`, and resumes after
a restart.

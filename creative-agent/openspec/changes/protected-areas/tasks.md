# Protected Areas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The artist marks areas of the painting the agent must never change; the plugin enforces it after every
painting operation and the agent reports each hit right away.

**Architecture:** Protected areas are selection masks inside one plugin-owned, locked, empty group layer, so they are
saved in the `.kra`. A new plugin mixin (`ProtectionCraft`) lists, adds and removes them; `cmd_creative` captures the
protected pixels before each mutating operation and enforces after it (erase, mask or refuse, then a before/after
backstop). Pixel work runs in Qt (C++), never per pixel in Python. The companion adds one painter tool
(`propose_protection`), shows hits, and lifts the transfer size caps when an area is active. The panel gets a
Protected areas section.

**Tech Stack:** Krita 5.2/5.3 Python API, PyQt5 (`QImage`/`QPainter`), Node 22 companion (`// @ts-check` JS, Pi), TypeBox.

**Spec:** `openspec/changes/protected-areas/design.md`, `proposal.md`, `specs/protected-areas/spec.md`

## Global Constraints

- The rule: **nothing the agent does may change a visible pixel inside an active protected area.**
- An area the agent proposes is **pending** and protects nothing until the artist presses **Keep**.
- The agent can never keep, adjust, remove or change an area: those are panel-only, in-process calls, never bridge
  operations the companion can send.
- Locked layers are protected automatically; locked layers alone do **not** lift the transfer size caps.
- Each hit is reported right away: chat line `Move N reached into '<name>'. I kept that area untouched (about P% of the pass).`
  In Autopilot the run continues.
- Never touch the artist's painting files in tests or live checks: live checks use a **copy** of `new_moscow.kra`.
- Check Krita is idle in its own command before any reload or live step; never call `brush_probe`.
- Tests clean up every file they write. Painter fixes need build + install + reload; panel changes need a Krita restart.
- Copy rules: no version numbers in code, comments or messages.

## Review Focus

1. **Soft mask edges** (feathered, anti-aliased): the agent's paint is erased in proportion to the mask, and the
   backstop counts only pixels with mask ≥ 128 as inside, so a half-protected edge pixel is not a false violation.
   Test in Task 1.
2. **A 6000×4500 canvas**: enforcement works only within the intersection of the operation's bounds and the
   protected areas' bounds, and costs well under a second. Test in Task 3 (bounds passed to the raster calls).
3. **The artist deletes the protection group, or a mask in it, by hand**: listing returns what is left, nothing
   crashes, and the next add recreates the group. Test in Task 2.
4. **Operations without a layer** (`merge_passes`, `review_pass` reject, `transform_layer` of an existing layer): no
   erase target, but the backstop still runs. Test in Task 3.
5. **Only pending areas, or only locked layers**: transfers keep their size caps. Test in Task 4.

---

### Task 1: Pixel work for protection

**Files:**
- Create: `krita-mcp/krita-plugin/kritamcp/protection_raster.py`
- Test: `krita-creative-agent/tests/test_protection_raster.py`: runs its checks in a **child Python process** with real
  PyQt5 (`subprocess.run([sys.executable, '-c', …])`), because `test_native.py` replaces PyQt5 with stubs in-process.

**Interfaces:**
- Produces (all buffers 8-bit; colour BGRA, masks one byte per pixel, no row padding, as in `region_raster.py`):
  - `union(masks: list[bytes], width: int, height: int) -> bytes`: per-pixel maximum.
  - `erase_inside(bgra: bytes, mask: bytes, width: int, height: int) -> tuple[bytes, int]`: alpha scaled by
    `(255 - mask) / 255`; returns the new pixels and how many pixels had alpha > 0 where mask ≥ 128.
  - `changed_inside(before: bgra bytes, after: bgra bytes, mask: bytes, width: int, height: int) -> int`: count of
    pixels with mask ≥ 128 whose BGRA differ.

- [ ] **Step 1: Write the failing tests** `test_erase_inside_scales_alpha_by_the_mask`,
  `test_changed_inside_ignores_soft_edges_below_half`, `test_union_is_the_maximum`. Use a 4×2 image; masks
  `[255,128,127,0, 255,0,0,0]`. Assert: alpha at mask 255 → 0, at mask 0 unchanged, at 128 → `round(a*127/255)`;
  removed count = 3 (the opaque pixels at mask ≥ 128); a change only at the mask-127 pixel gives `changed_inside == 0`.
- [ ] **Step 2: Run them to see them fail**
  Run: `cd krita-creative-agent && uv run -q --with pyqt5 --with pillow --with numpy --with httpx python -m unittest tests.test_protection_raster -v`
  Expected: FAIL, the child process reports `No module named 'protection_raster'`.
- [ ] **Step 3: Implement the three functions** with `QImage`/`QPainter` (mask as an `Format_Alpha8` image,
  `CompositionMode_DestinationOut` to erase, `CompositionMode_Difference` then the mask to compare) and `bytes.count`
  for counting, so no Python loop runs per pixel. Import only `PyQt5` in it, like `region_raster.py`.
- [ ] **Step 4: Run the tests to see them pass** (same command). Expected: OK.
- [ ] **Step 5: Commit** `git commit -m "Protection: pixel work for erasing and checking protected areas"`.

### Task 2: Protected areas in the document

**Files:**
- Create: `krita-mcp/krita-plugin/kritamcp/protection.py` (mixin `ProtectionCraft`)
- Modify: `krita-mcp/krita-plugin/kritamcp/creative_tools.py:57` (add the mixin), `:192-217` (allow
  `propose_protection` and `protection_list` operations only)
- Test: `krita-creative-agent/tests/test_protection.py` (fake layer tree from `test_layer_craft.py`; a fake
  `creative_test_package.protection_raster` module installed as `test_region_craft.py` does for `region_raster`)

**Interfaces:**
- Consumes: `union` from Task 1; `_region_build(doc, session, steps)` and `_region_bounds(doc, selection)` from
  `region_craft.py`.
- Produces:
  - `PROTECTION_GROUP = 'Protected areas · Creative Agent'`: the plugin-owned group (locked, empty of pixels, at the top).
  - Each area is a selection mask in that group; its state is stored in the session journal by mask id:
    `{'id', 'name', 'state': 'pending'|'active', 'by': 'artist'|'agent'}`.
  - `_protect_list(doc, session) -> list[dict]`: areas with `bounds` [x,y,w,h], plus one entry
    `{'id': 'locked-layers', 'name': 'Locked layers', 'state': 'active', 'by': 'automatic', 'count': n}` when any
    layer is locked. Masks deleted by hand are dropped from the journal.
  - `_protect_add(doc, session, name: str, selection, by: str, state: str) -> dict` (the area).
  - `_protect_set_state(doc, session, area_id, state)`, `_protect_remove(doc, session, area_id)`: panel only.
  - `_protect_mask(doc, session, rect) -> bytes | None`: union of **active** masks and locked layers' alpha within
    `rect`, `None` when nothing is protected there.
  - Operation `propose_protection` `{name (1-60 chars), area (selection steps)}` → `{'status':'ok','area':{…,'state':'pending'}}`;
    operation `protection_list` → `{'areas': [...]}`. The `observe` result gains `protected_areas` (active only).

- [ ] **Step 1: Write the failing tests** `test_propose_creates_a_pending_area_in_the_owned_group`,
  `test_pending_areas_protect_nothing`, `test_keep_makes_it_active_and_remove_deletes_the_mask`,
  `test_locked_layers_are_listed_and_protected`, `test_a_mask_deleted_by_hand_is_dropped_and_the_group_recreated`
  (Review Focus 3), `test_companion_cannot_keep_or_remove` (`cmd_creative` with `protection_keep` or
  `protection_remove` → error "Only the artist can change protection in the panel.").
- [ ] **Step 2: Run them to see them fail** (Task 1 environment, `tests.test_protection`).
- [ ] **Step 3: Implement `ProtectionCraft`** and the two operations. The group is created on first add, locked,
  named `PROTECTION_GROUP`; masks are created with `doc.createSelectionMask(name)` and `setSelection`.
- [ ] **Step 4: Run them to see them pass.**
- [ ] **Step 5: Live probe on a scratch document** (Krita idle, checked in its own command): add an area through the
  bridge on a new 400×300 document, save, close, reopen; the area is listed and the rendered image is unchanged.
  Record what Krita did in `design.md` under "Where a protected area lives". If a selection mask cannot live in a
  group, stop and report: it changes the storage decision.
- [ ] **Step 6: Commit** `git commit -m "Protection: areas saved in the painting, proposed by the agent, kept by the artist"`.

### Task 3: Enforcement on every operation

**Files:**
- Modify: `krita-mcp/krita-plugin/kritamcp/creative_tools.py:286` (capture before), `:401-410` (enforce before the
  checkpoint), validation section `:217-280` (refuse artist-layer settings)
- Modify: `krita-mcp/krita-plugin/kritamcp/protection.py`
- Test: `krita-creative-agent/tests/test_protection.py`, `krita-creative-agent/tests/test_native.py`

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces:
  - `_protect_capture(doc, session, operation, params) -> dict | None`: `{rect, mask, projection}` for the
    intersection of the operation's region (or the canvas) and the protected bounds; `None` when nothing is protected.
  - `_protect_enforce(doc, session, operation, params, result, captured) -> dict`: returns
    `{'protected': [{'name', 'share', 'pixels'}]}` or an error result
    `{'status': 'error', 'error_code': 'protected_change', 'error': "… would change '<name>'; it was undone."}`.
  - Erase: agent pixel layers (`result['layer_id']` when owned by the agent and a paint layer). Mask: agent layers whose
    look is not their pixels (fill, generator, filter layers, filter masks, layer styles) get a transparency mask
    excluding the area. Refuse (validation, before painting): `adjust_layer`/`set_layer` on an artist layer with
    pixels inside an active area: "That layer shows inside the protected area '<name>'."
  - Backstop: `changed_inside(captured projection, new projection, mask) > 0` → remove the contribution the way
    `review_pass` reject does and return the `protected_change` error.

- [ ] **Step 1: Write the failing tests** in `test_native.py`'s fake-Krita style:
  `test_a_stroke_pass_into_an_area_is_erased_there_and_reported` (result `protected[0].name == 'Woman and car'`,
  share > 0, projection inside unchanged), `test_a_fill_layer_over_everything_gets_a_mask`,
  `test_an_artist_layer_overlapping_an_area_cannot_change_opacity`,
  `test_the_backstop_undoes_a_change_that_got_through`, `test_operations_without_a_layer_still_run_the_backstop`
  (Review Focus 4), `test_enforcement_reads_only_the_overlap` (Review Focus 2: assert the rect passed to
  `pixelData`/`projectionPixelData` is the intersection, not the canvas).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement capture, enforce and the refusal**; call `_protect_capture` next to `before = …` and
  `result.update(self._protect_enforce(...))` right after the `try/finally` that runs the operation, before
  `_creative_commit_view`.
- [ ] **Step 4: Run the whole Python suite** (`python -m unittest discover -s tests -p 'test_*.py'`, Task 1 env).
  Expected: OK.
- [ ] **Step 5: Commit** `git commit -m "Protection: enforced after every painting operation, with a backstop"`.

### Task 4: The companion: proposing, reporting, and the transfer caps

**Files:**
- Modify: `krita-creative-agent/src/craft.mjs:4-6` (add `propose_protection` to `CRAFT_TOOLS` and `CRAFT_OPERATIONS`)
- Modify: `krita-creative-agent/src/tools.mjs` (the `propose_protection` tool, beside `select`)
- Modify: `krita-creative-agent/src/studio.mjs:1394` (`callNative`: hits and proposals), `selectTools` (offer
  `propose_protection` in every phase with vision), `context()` (`protected_areas`)
- Modify: `krita-creative-agent/src/reference-tool.mjs` (`transferRefusal` option `protectedAreas`)
- Test: `krita-creative-agent/tests/craft.test.mjs`, `tests/studio.test.mjs`, `tests/reference.test.mjs`

**Interfaces:**
- Consumes: plugin results from Tasks 2-3 (`area`, `protected`, `observe.protected_areas`).
- Produces:
  - Tool `propose_protection({name, area})`, description: "Mark an area the artist asked to protect. It is shown in red
    and protects nothing until the artist keeps it. You cannot remove or change protection."
  - Events: `{type:'protection_proposed', area}` and `{type:'protection_hit', move?:number, areas:[{name,share}]}`.
  - The status/transcript line from Global Constraints; the painter's tool result text adds, after the third hit on one
    area in a plan step or move: "You keep painting into '<name>'. Leave it alone."
  - `transferRefusal(goal, recipe, canvas, paintedJobs, {established, protectedAreas=0})`: size caps skipped when
    `protectedAreas > 0` (active, excluding locked layers); `start()` passes `observation.protected_areas?.length`.

- [ ] **Step 1: Write the failing tests**: `propose_protection is offered in every phase and creates a pending area`;
  `a hit reaches the chat right away and the painter's result; Autopilot keeps painting`;
  `the third hit on one area tells the painter to leave it alone`;
  `an active protected area lifts the transfer size caps; pending areas and locked layers do not` (Review Focus 5,
  New Moscow numbers: a sky target of a third of a 6000×4500 canvas on an established painting).
- [ ] **Step 2: Run them to see them fail**: `npm run test:unit` (managed Node 22 runtime).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: `npm run test:unit` and `npm run typecheck`.** Expected: all pass, no type errors.
- [ ] **Step 5: Commit** `git commit -m "Protection: the painter proposes areas, reports hits, and protection lifts the transfer caps"`.

### Task 5: The panel's Protected areas section

**Files:**
- Modify: `krita-mcp/krita-plugin/kritamcp/creative_docker.py` (section under the references; `handle_event` for
  `protection_proposed` and `protection_hit`; paint-over bar)
- Test: `krita-creative-agent/tests/ui_smoke.py`

**Interfaces:**
- Consumes: `ProtectionCraft` methods in-process (Task 2); events from Task 4.
- Produces (exact copy):
  - Section title **Protected areas**; rows: red swatch, name, "made by the agent · you approved" or "made by you",
    👁 (accessible name "Show <name> in red"), ✕ ("Remove protection <name>"); the automatic row
    "Locked layers · N layers · automatic" without ✕.
  - Buttons **Ask the agent…** (puts `Protect ` in the composer and focuses it), **Paint over it**, **Use my selection**
    (empty selection → "Select an area first.").
  - Proposal in the transcript: "I marked '<name>' in red. Keep this protection?" with **Keep**, **Adjust**, **Discard**.
  - Paint-over bar: "Painting protection · Done · Cancel" (Cancel restores the mask as it was).
  - Busy: buttons disabled, tooltip "Pause to change protection".

- [ ] **Step 1: Extend `ui_smoke.py`**: the section and buttons exist; a `protection_proposed` event shows Keep/Adjust/
  Discard and Keep calls `_protect_set_state(..., 'active')`; a `protection_hit` event adds the chat line; busy
  disables the buttons; no horizontal scroll at 360 px.
- [ ] **Step 2: Run it to see it fail**: `QT_QPA_PLATFORM=offscreen uv run -q --with pyqt5 python tests/ui_smoke.py`.
- [ ] **Step 3: Implement the section.** Paint over it: set the mask as the active node, select a round brush preset,
  turn on the selection overlay; Done/Cancel restore the previous active node and tool.
- [ ] **Step 4: Run `ui_smoke.py` and the Python suite.** Expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Protection: the Protected areas section in the panel"`.

### Task 6: Ship and check live

**Files:** none new.

- [ ] **Step 1: Build and install**: `env -u NODE_OPTIONS python3 scripts/build-release.py --output output/protected-areas`,
  then `python3 scripts/install.py --bundle output/protected-areas --project <your paintings folder>`.
  Confirm `image-resize-worker.js` and `photon_rs_bg.wasm` are in `companion/src`.
- [ ] **Step 2: Ask the artist to restart Krita** (panel change). Wait for them.
- [ ] **Step 3: Live check on a copy of `new_moscow.kra`** (Krita idle, checked in its own command): ask Agent mode
  "Protect the woman and the car", press Keep; ask "Repaint the street"; compare the area's pixels before and after
  (identical), and confirm a hit line appeared if the move reached into it.
- [ ] **Step 4: Mark tasks done in this file and commit.**

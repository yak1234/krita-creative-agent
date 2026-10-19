# Reference Parts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The artist cuts a part or a crop out of an attached reference with Krita's selection tools, and the agent
paints only that part.

**Architecture:** The reference preview gains two buttons that open the reference as a temporary Krita document; the
panel shows Use this part / Cancel, composes the part (full size, alpha from the selection) or crop with Qt, and
attaches it like a pasted reference with `part_of` and `bounds`. The companion passes those to the painter, and the
transfer rules measure a part by its opaque area. **Starts after `openspec/changes/protected-areas` is done.**

**Tech Stack:** Krita Python API, PyQt5, Node 22 companion (`// @ts-check` JS).

**Spec:** `openspec/changes/reference-parts/design.md`, `proposal.md`, `specs/reference-parts/spec.md`

## Global Constraints

- The artist's painting and reference files are never opened for writing or saved.
- One temporary document at a time; it always closes without saving, and the painting's view is restored.
- Parts count toward the four references per chat ("Remove a reference to add a part").
- Names: "<name> (part)" or "<name> (crop)"; the name prompt is prefilled "Part of <original name>".
- Protected areas still apply inside a part; the second-half-of-plan rule still applies in Autopilot.
- Tests clean up every file they write; no version numbers in code or copy.

## Review Focus

1. **The artist closes the temporary document themselves**: the bar disappears as if Cancel was pressed. Test in Task 2.
2. **A reference with its own transparency** (a PNG cut-out): the part's alpha is the reference's alpha times the
   selection. Test in Task 1.
3. **The selection reaches past the image** (Krita allows it): it is clipped to the image. Test in Task 1.
4. **The reference is still pending** (attached but not yet sent): the part works from its path. Test in Task 2.
5. **A crop of a part**: allowed; `part_of` names the part. Test in Task 3.

---

### Task 1: Composing a part or a crop

**Files:**
- Create: `krita-mcp/krita-plugin/kritamcp/reference_parts.py`
- Test: `krita-creative-agent/tests/test_reference_parts.py`: checks run in a child Python process with real PyQt5
  (`test_native.py` stubs PyQt5 in-process), as in protected-areas Task 1.

**Interfaces:**
- Produces:
  - `part_image(bgra: bytes, mask: bytes, width: int, height: int) -> bytes`: same size; alpha × mask / 255.
  - `crop_image(bgra: bytes, width: int, height: int, rect: list[int]) -> tuple[bytes, list[int]]`: the rectangle
    clipped to the image, opaque pixels as they are.
  - `opaque_bounds(bgra: bytes, width: int, height: int) -> list[int] | None`.

- [ ] **Step 1: Failing tests** `test_part_keeps_size_and_multiplies_alpha` (Review Focus 2),
  `test_crop_is_clipped_to_the_image` (Review Focus 3), `test_opaque_bounds_of_an_empty_part_is_none`.
- [ ] **Step 2: Run to fail**: `uv run -q --with pyqt5 --with pillow --with numpy --with httpx python -m unittest tests.test_reference_parts -v`.
- [ ] **Step 3: Implement with `QImage`/`QPainter`** (`CompositionMode_DestinationIn` with the mask), no per-pixel Python.
- [ ] **Step 4: Run to pass.**
- [ ] **Step 5: Commit** `git commit -m "Reference parts: composing a part or a crop"`.

### Task 2: Select a part in Krita, from the reference preview

**Files:**
- Modify: `krita-mcp/krita-plugin/kritamcp/creative_docker.py:347-374` (`ReferencePreview` buttons), the panel
  (selecting bar, temporary document lifecycle, name prompt, attach)
- Test: `krita-creative-agent/tests/ui_smoke.py`

**Interfaces:**
- Consumes: Task 1; `attach_paths` (pasted-reference folder as in `attach_pasted_image`).
- Produces: buttons **Select a part in Krita…** and **Crop in Krita…** (disabled while busy: "Pause the agent to select
  a part"); bar "Selecting a part of <name> · Use this part · Cancel"; empty selection → "Select the part first.";
  the new reference entry `{path, role:'reference', name, purpose, notes:'', part_of: <original path>, part_kind:
  'part'|'crop', bounds}`.

- [ ] **Step 1: Extend `ui_smoke.py`**: buttons present and disabled when busy; Use with an empty selection keeps the
  document open; Use attaches "Sky (part)" with `part_of`; closing the temporary document hides the bar (Review
  Focus 1); a pending reference can be split (Review Focus 4); the fifth reference is refused.
- [ ] **Step 2: Run to fail**: `QT_QPA_PLATFORM=offscreen uv run -q --with pyqt5 python tests/ui_smoke.py`.
- [ ] **Step 3: Implement**: copy the reference to a temp file, `Krita.instance().openDocument()` + a new view,
  preselect similar colour select (part) or rectangle select (crop); on Use read `doc.pixelData` and
  `doc.selection().pixelData` over the image, compose, save PNG, attach; on Use or Cancel `setModified(False)`,
  `close()`, restore the previous view, remove the temp file.
- [ ] **Step 4: Run `ui_smoke.py` and the Python suite.**
- [ ] **Step 5: Commit** `git commit -m "Reference parts: select a part or crop in Krita from the reference preview"`.

### Task 3: The painter follows the part

**Files:**
- Modify: `krita-creative-agent/src/studio.mjs:905-925` (`addReferences` keeps `part_of`, `part_kind`, `bounds`;
  `context()` lists them), `src/prompt.mjs` (one guidance line)
- Modify: `krita-creative-agent/src/reference-tool.mjs` (`transferRefusal`, `wholeReferenceRefusal`: a part is
  measured by its opaque area and not refused for size)
- Test: `tests/studio.test.mjs`, `tests/reference.test.mjs`

**Interfaces:**
- Consumes: Task 2's reference entry; `transferRefusal(..., {established, protectedAreas})` from protected-areas Task 4.
- Produces: guidance line: "A part reference is see-through outside the one area to follow; a transfer from it paints
  only that area, in the place it has in the original. A crop is a close-up of `bounds` of the original."

- [ ] **Step 1: Failing tests**: `a part reaches the painter with part_of and bounds`; `a transfer from a part on an
  existing painting is not refused for its size`; `a crop of a part names the part` (Review Focus 5);
  `the second half of an Autopilot plan still refuses a large part`.
- [ ] **Step 2: Run to fail**: `npm run test:unit`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: `npm run test:unit` and `npm run typecheck`.**
- [ ] **Step 5: Commit** `git commit -m "Reference parts: the painter follows a part, and its size is the artist's choice"`.

### Task 4: Ship and check live

- [ ] **Step 1: Build and install** (as in protected-areas Task 6), then ask the artist to restart Krita.
- [ ] **Step 2: Live on a copy of `new_moscow.kra`** (Krita idle, checked in its own command): protect "Woman and car"
  and "Buildings"; make "Sky" from the reference with similar colour select; ask Agent mode to paint the sky from it;
  confirm only the sky changed.
- [ ] **Step 3: Mark tasks done and commit.**

# Element-scoped painting: tasks

Proposal: `proposal.md` (approved 2026-10-23). Phase A is goals 2 and 3; the later phases (5-7, then 1 and 4, then 8)
get their tasks when they start.

## Phase A

### Goal 2: Adjust a proposed protection with a selection tool, not the brush

- [x] 2.1 Adjust (on a `protection_proposed` chat message) sets the artist's selection aside (a copy, or none), loads the
      area's shape as the document selection (`Document.setSelection`) and chooses the Freehand Selection Tool
      (`KisToolSelectOutline`); `creative_docker.adjust_protection`.
- [x] 2.2 The protection bar has a switch to the Magnetic Selection Tool (`KisToolSelectMagnetic`) and back.
- [x] 2.3 Done writes the selection back into the area (`SelectionMask.setSelection`), updates its bounds, makes it
      active and restores the artist's selection (or clears it). Done with nothing selected keeps the bar open:
      "Select an area first."
- [x] 2.4 Cancel leaves the area unchanged and restores the artist's selection.
- [x] 2.5 Adjust waits while the agent paints (`feature_wait_reason`); the Keep / Adjust / Discard buttons stay usable.
- [x] 2.6 Paint over it (the Protected areas dialog) keeps the brush; it is not reachable from Adjust any more.
- [x] 2.7 Panel tests under PyQt5 and PyQt6 (`tests/ui_panel_features.py`, `AdjustWithSelectionTools`).

### Goal 3: The painter's protection

- [x] 3.1 The plugin refuses `propose_protection` areas with a seed or colour step, with or without invert
      (`protection.py`, `COLOUR_REFUSAL`).
- [x] 3.2 `select` records in each saved selection whether it picked pixels by colour, through any saved selection it
      used too (`region_craft._region_colour_based`); a saved selection built from colours is refused as protection,
      and one saved before this was recorded counts as built from colours.
- [x] 3.3 The companion refuses seed and colour steps before the plugin, with the same message
      (`tools.mjs`, `COLOUR_PROTECTION`).
- [x] 3.4 The result message and the tool description say the area is proposed ("Proposed and shown in red; the
      artist keeps or discards it. Until then you keep out of it."); the prompt's protection section says to build it
      from shape or polygons; the paint-sky skill protects buildings with shape boxes, not the sky's inverse.
- [x] 3.5 The panel's Protected section lists pending proposals, so "No features yet" does not show while some wait.
- [x] 3.6 Tests: plugin (`tests/test_protection.py`, `ColourProtectionTests`), companion (`element-shapes.test.mjs`,
      `brush-catalog.test.mjs`), panel (`ui_panel_features.py`).
- [ ] 3.7 Live check in Toska on a copy of New Moscow: "protect the buildings" proposes shapes, not a seeded sky
      (needs a build, an install and a restart; for the lead).

## Goal 1: Select object ("Find it for me"), and element steps routed through it (approved by the artist 2026-10-24)

- [x] 1.1 Find it for me beside Paint only here and on the area card: the artist names the part ("the sky"); the
      companion peeks the painting without guide lines and finds the outline on it (`find-it.ts`); the panel loads it as
      the document selection and chooses Freehand to adjust it (Shift adds, Alt subtracts). Timings in the status line;
      cached per view content in this chat folder's `.shapes/found-*.png` (the panel reads only that folder). By name
      only (review ruling 2026-10-24): no canvas click is intercepted, since Krita's input manager re-installs its filter
      on focus and the click reached the tool, and an input grab is what froze the artist's app. Escape closes the field.
- [x] 1.2 A name is located by the selected decision model on a numbered grid of the view (`find-it-locate.ts`, one
      request, one yes/no question a cell); each confident cell is one point for SAM 2.1, masks leaking into confident
      "not" cells are dropped, the rest merged, specks without a seed removed and small holes filled. Without a decision
      model that reads images, a name is refused with "click it on the canvas instead".
- [x] 1.3 Consent: Find it for me uses the shapes model's existing question (artist-initiated); a host proposal
      (`proposeArea`) is only made when the model is allowed and downloaded, so the host never asks.
- [x] 1.4 Element steps: an Agent move on a folder element step with no area shows the card first ("Is this the sky?"
      with the outline selected: Use this / Adjust with Freehand / Paint everywhere; or Find it for me / Select with
      Freehand / Use my selection / Paint everywhere); the answer paints what was asked before it; Paint everywhere is
      remembered for that step. A proposal never replaces the artist's own selection: with one there, it waits for Use
      this or Adjust with Freehand, which say that Undo brings their selection back. Autopilot adopts a found outline as
      the area by itself (bridge `paint_only_here`) and says so; every such area is tagged `auto` (its step, or the run)
      and cleared when its step ends, the run ends, Stop, or a switch out of Autopilot; an Agent message never inherits
      one. A bridge failure leaves no area and no file, and Autopilot paints without an area. `ask_for_selection` goes
      through the same `askForArea`.
- [x] 1.5 With the area set, an element step's move is the scoped transfer of the goal then `paint_accents` in the area;
      `split_by_color`, colour selections (seeds, colour ranges, bucket fill "similar"), `make_material` /
      `stamp_material` and typed strokes are refused there unless the artist asks (`element-step-rules.ts`).
- [x] 1.6 Tests: companion (`find-it.test.mjs`, `element-step-rules.test.mjs`, `paint-only-here*.test.mjs`,
      `studio.test.mjs`), plugin (`test_paint_only_here.py`), panel (`ui_panel_paint_only_here.py`, PyQt5 and PyQt6);
      one real SAM 2.1 + Luna run on a copy of New Moscow's goal ("the sky": 3.6 s cold, at once cached).
- [ ] 1.7 Live test in Toska on a copy (not run yet): the panel's Find it for me and Escape, the card with a proposal
      (with and without the artist's own selection; whether Undo brings that selection back after Use this), Use this /
      Adjust / Paint everywhere, an element step's scoped transfer and accents, Autopilot's area set and cleared,
      Undo/Redo, and the painting result.

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

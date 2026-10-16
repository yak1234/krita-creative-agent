## Why

Computer use was added so the painter could operate Krita's window the way Codex did on the New Moscow cleanup. It hasn't paid off. Of the last 1,000 painter tool calls in Langfuse (Oct 12–15), 10 were computer use:
- 8 failed with `bootstrapTimedOut`, about 9 s each, and one of those stopped a painting run;
- 2 were screenshots that no action followed;
- 3 were ctrl+z presses, which `computer-use.mjs` refuses anyway.

In the Codex transcript, computer use did layer housekeeping: revealing paint beneath overlays, removing misplaced passes, scaling a layer and setting canvas size. It didn't paint.

The painter already does that housekeeping through `adjust_layer`, `set_layer`, `select` and `apply_filter`, and does a lot of it. The same 1,000 calls contain 530 `adjust_layer` actions:
- **Hides dominate.** 315 of the 530 were hides, mostly to discard failed passes.
- **Each hide costs a batch slot.** 8 batches were nothing but 10 hides.
- **Stale ids break batches.** "That layer is no longer in this painting" failed 9 actions and stopped their batches, although a hidden or missing layer was already the goal.
- **Two tools do the same job.** `adjust_layer` and `set_layer` overlap: both set opacity and visibility on any unlocked layer.
- **The model passes names as ids.** `set_layer` was called with layer names in `layer_id`.
- **Fussy validation.** `apply_filter` rejected `horizRadius: 2.5` (must be int), and `fill_region` rejected selections reaching past the image edge.
- **There is no way to see one layer by itself.** Finding the overpaint to remove needs that, and it's what Codex used screenshots for.

The painter is an Agent Pi session, and Pi supports skills, but the companion turns them off (`noSkills: true`). Long tool descriptions explain workflows such as cleaning up overpaint or grading with filters, and they ride along on every call (inputs average about 41k tokens; see `faster-agent-runs`).

## What Changes

- **Remove computer use.** This deletes the `computer_use` execution setting, the eight `krita_*` UI tools, the "Creative Agent Computer Use" helper app, `codex-computer-use-mcp`, the panel checkbox and their tests. This work was never committed: `computer-use.mjs`, `computer-use-service.mjs` and their tests are untracked. A saved `computer_use` setting is ignored, not rejected.
- **One layer-settings tool.** `set_layer` takes `layers: [...]`, up to 50 entries per call, and absorbs `adjust_layer`, which is removed. Hiding ten failed passes becomes one action.
- **Forgiving layer references:**
  - a layer can be named by id or by exact name;
  - hiding a layer that no longer exists counts as done and is reported, not failed;
  - any other unknown layer fails with the nearest current layer names.
- **`view_layers`:** shows up to 12 layers, each by itself, as one labelled contact sheet. The painter can find overpaint before hiding it.
- **Forgiving inputs for `apply_filter` and `select`:**
  - filter settings are coerced to the type Krita expects (round to int, `"true"` to a boolean);
  - selection shapes are clipped to the image instead of rejected;
  - an `apply_filter` on an artist layer falls back to `mode: copy` (the original is hidden, and reject restores it) instead of failing.
- **Painter skills (pilot).** Bundled Agent Skills hold workflow know-how; tools keep the facts. This pilot ships two skills, `layer-cleanup` and `filter-grading`. They load through a read-only `read_skill` tool, so the painter doesn't get a general file `read`. The descriptions of the four tools shrink to what the schema needs.

## Capabilities

### New Capabilities
- `layer-tools`: batched layer settings, forgiving layer references, single-layer previews, and input coercion for filters and selections.
- `painter-skills`: bundled Agent Skills for the painter, listed in its prompt and loaded on demand through `read_skill`.
- `painter-tool-surface`: the painter has no computer-use tools; canvas changes go only through the plugin's journalled operations.

### Modified Capabilities
<!-- None archived yet. native-painting-craft introduced set_layer/select/apply_filter; its requirements for ownership and reject still hold. -->

## Impact

- **Companion:**
  - delete `src/computer-use.mjs`, `src/computer-use-service.mjs` and their tests;
  - `src/studio.mjs`: tool lists, `checkComputerUse`, `computerUseFailed`, `LAYER_SETTINGS`;
  - `src/main.mjs`: `SERVICE_FLAG`;
  - `src/execution-settings.mjs`, `src/tools.mjs` (`set_layer`, `view_layers`, `read_skill`, `BATCH_TOOLS`), `src/pacing.mjs` (`NOT_AUTHORED`), `src/runtime.mjs` (skill loading);
  - new `skills/` directory;
  - `package.json`, `scripts/build-release.py`, the README.
- **Plugin:**
  - `creative_tools.py`: `set_layer` with several layers, name resolution, a `layer_previews` operation, filter-config coercion, clipping selection shapes;
  - `creative_docker.py`: remove the checkbox.
- **Risk:**
  - **A bulk hide can hide the wrong layers.** It is one pass, so reject restores every layer it touched.
  - **Name matching could pick the wrong layer.** It is exact only, and a name shared by two layers is refused.
  - **Models may skip a skill.** Pi notes that models don't always read skills, so the slimmed tool descriptions keep one line pointing to the skill.

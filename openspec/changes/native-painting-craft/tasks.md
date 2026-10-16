Test rule for every task: tests write only to temporary folders they remove (`t.after` / `after` in Node, `tempfile.TemporaryDirectory` or `addCleanup` in Python), and run through `npm run test:unit`, which also gives each run a private `TMPDIR` that is deleted afterwards. Live acceptance uses a disposable document and deletes its study folder, exports and probe files when it finishes, pass or fail.

## 1. Capability manifest

- [x] 1.1 `kritamcp/capabilities.py`: read filter ids with default configurations (`Krita.filters()`, `Krita.filter(id).configuration().properties()`), blend mode ids, fill generators and their defaults, and preset, pattern and gradient names. Cache per Krita version in Krita settings. Verify with a fake-Krita unit test, and in live Krita that common filters (colour balance, curves, HSV, Gaussian blur, sharpen) are listed with their defaults.
- [x] 1.2 Shared validators: filter id, generator, blend mode and configuration keys and types against the manifest, raising `validation_rejected` before any mutation. Verify with unit tests for unknown ids, unknown keys and wrong types.
- [x] 1.3 Companion `krita_capabilities` tool: a compact manifest (names plus the most useful properties of common filters), full on request. Verify with a studio test that the compact form stays under 4k characters.
- [x] 1.5 Generator settings: known settings per generator (`color` takes `#RRGGBB`, `pattern` a name), `QColor` filter settings offered as colours, other types recorded as `unsupported_settings`, and a compact manifest that trims itself to 3,800 characters. Found in the live run: new fill layers report empty configurations and came out black; Context7 docs show `InfoObject.setProperty` takes hex strings for colours. Verify with `test_layer_craft.py`.
- [x] 1.4 Live check on the installed Krita (5.3.3): the manifest lists the common filters with their defaults and the fill generators; each id in `BLEND_MODES` changes compositing on a probe layer (Krita has no blend-mode list, and `setBlendingMode` accepts any string). Remove any id that does not. Passed on build `76f4fc94`: 52 filters with defaults, generators color, gradient, pattern, screentone and multigrid, all 30 blend modes change compositing, multiply/screen/darken/lighten match their formulas within 2 levels, compact manifest 3,511 characters, a colour fill layer is exactly `#3a6ea5`.

## 2. Layer craft

- [x] 2.1 `kritamcp/layer_craft.py` `create_layer`: paint, fill and group layers (filter layers come with 4.1) with name, blend mode, opacity, visibility, alpha lock (paint only) and `clip_to`. The layer is added to the agent's layers and recorded as a `layer` pass through the journal. Verify with fake-Krita tests for each type and for refusals.
- [x] 2.2 Clipping: clip base (`clip_base`, a layer alone in its agent group) → live clip with `setInheritAlpha`; any other base → transparency mask from the base's alpha, recording `base_id` and an alpha digest, with the artist's layer unchanged (same parent, index, pixels and properties). Verify both paths in unit tests, and live: a clip to an agent layer follows later edits to the base.
- [x] 2.3 `set_layer`: opacity and visibility on any unlocked layer (as `adjust_layer`); blend mode, alpha lock, clip and name on layers the agent created. The full prior state is recorded on a `set_layer` pass, and reject restores it. `adjust_layer` is unchanged. Verify that the existing `adjust_layer` tests pass unchanged, plus new reject-restores tests.
- [x] 2.4 Companion: `create_layer` and `set_layer` tools, batchable, paced, mutating, offered in the painting phase; in `paint_batch` a later action can name an earlier action's layer as `"$N"`. (Brought forward from 6.1 so the operations are reachable.) Verify with `tests/craft.test.mjs`.
- [x] 2.5 Live check on a disposable document: a clip-base flats layer with a clipped Multiply layer stays clipped after the flats are extended; a mask clip to an artist layer leaves that layer's parent, index, pixels and properties unchanged; reject of a `set_layer` pass restores blend mode and alpha lock. Passed on build `76f4fc94`: reject restores the blend mode; a Multiply fill clipped to a clip base is live and shows only inside the base; a mask clip to an artist layer shows only inside that layer's alpha, and the artist's layer keeps its id, parent, depth, opacity and visibility. Extending the flats with `fill_region` keeps the clipped Multiply layer over the new area (3.3, build `2fc1ac3c`).

## 3. Selections and region fills

- [x] 3.1 `select` (`kritamcp/region_craft.py`): steps with a shape, layer alpha (read only), colour range or saved selection; replace/add/subtract/intersect; grow, shrink, border, feather, smooth, invert; saved under a name in the study folder. No pass or checkpoint, and the document selection is never set. Verify with `test_region_craft.py`, including that the artist's selection is untouched and refused steps save nothing.
- [x] 3.2 `fill_region`: solid colour, linear or radial gradient with stops, and pattern, drawn by Qt (`region_raster.py`) onto a new layer (with blend, opacity, `clip_base` and `clip_to`) or a copy of an agent layer (original hidden, alpha lock honoured). Companion `select` and `fill_region` tools, batchable. Verify with `test_region_craft.py` and `craft.test.mjs`.
- [x] 3.3 Live check on a disposable document: a polygon flat has exact edges with no brush strokes; a radial gradient and a pattern fill render; filling more of a clip-base flats layer keeps its clipped Multiply layer over the new area (completes 2.5); reject restores the original flats; a colour-range and a layer-alpha selection match the expected pixels. Passed on build `2fc1ac3c`: the polygon flat is exactly `#3a6ea5` up to its edge; colour-range and layer-alpha selections agree within 2.4% (antialiased edges); the clipped Multiply shadow follows the extended flats and reject restores them, which are then a live clip base again; radial gradient, pattern and alpha-locked recolour render as expected; the artist's selection is untouched.

## 4. Filters

- [x] 4.1 `kritamcp/filters.py` `apply_filter`: `mask` (default; on an agent paint, fill or group layer), `layer` (a filter layer inside an agent group: at its top when the target is the group, else directly above the target) and `copy` (`Filter.apply` on a copy, original hidden; an area is blended in with Qt) modes, limited by a saved selection or inline steps, and artist targets refused with the suggestion to use `layer` on the agent's own group. Runs with batch mode on, `waitForDone` at the end, progress reported. The companion waits 300 s for a filter (120 s otherwise); past that the outcome is uncertain. Companion `apply_filter` tool, batchable, `"$N"` allowed in `target`. Verify with `test_filters.py` and `craft.test.mjs`.
- [x] 4.2 Pass history: `apply_filter` passes record `filter`, `filter_mode` and `target_id`; reject hides the mask or filter layer (copy: hides the copy, shows the original), fade sets opacity, compare uses the usual before/after images. Older sessions load unchanged. Verify with `test_filters.py`, including a saved pre-filter session.
- [x] 4.3 Live check on a disposable document: a colour-balance mask leaves the layer's pixels unchanged and changes the visible result; fading the mask weakens the effect; reject removes it; a filter layer at the top of an agent group grades only that group; a blur limited to an area of a copy changes only that area; an artist target is refused. Passed on builds `8e069033`/`4955575d`, except fade: Krita ignores filter-mask opacity. Masks now save their coverage and fade rewrites it as coverage × strength; a probe on `4955575d` faded a mask to 0.3 (`[255,1,1]` → `[166,90,90]`). The fade trigger was then keyed on saved coverage rather than the newest pass (a `set_layer` on the mask hid it), covered by `test_filters.py`; it loads with the next build.

## 5. Colorize flats

- [x] 5.1 `colorize_flats` (`kritamcp/colorize.py`): the line art's pixels are copied into a helper layer the agent owns, directly below it. A colorize mask goes on the helper, with key strokes from seeds (a disc per seed, cropped to the canvas; `transparent` keeps a region empty). Then `updateMask(True)` runs, followed by a wait. The colours are read by clearing the helper for a moment and are copied into a new flat layer below the line art (a clip base by default). The helper stays hidden with its mask, for the artist to refine. Verified with `test_colorize.py` (call order, placement, transparent seeds, refusals, crash recovery) and live on build `f8221532`:
  - an artist's three-region drawing got exactly `#3a6ea5`, `#d9a441` and `#7a9e4f`;
  - the outside stayed empty and the line art was unchanged and stayed on top;
  - the helper was hidden and reject hid the flats;
  - opaque inked line art on white also worked.

## 6. Companion integration

- [x] 6.1 `tools.mjs` schemas for `create_layer`, `set_layer`, `select`, `fill_region`, `apply_filter`, `colorize_flats` and `krita_capabilities`, with short descriptions. Add them to `BATCH_TOOLS`, `PACED_TOOLS`, `bridge.mjs` mutating operations and `runtime.mjs` activity labels. Verify with studio tests that a `paint_batch` mixing craft and strokes runs as one batch and counts toward allowances. Done:
  - the craft tool lists live once in `src/craft.mjs` (`CRAFT_TOOLS`, `CRAFT_OPERATIONS`, `LONG_OPERATIONS`), used by the bridge, the pacing, the activity labels and studio;
  - `colorize_flats` and `transform_layer` are added, and `"$N"` also works in `line_layer`;
  - the studio test checks that one painter call ran the batch and three craft actions counted three passes.
- [x] 6.2 Agent mode: craft results belong to the move, and Undo hides them all. Verify with a studio test: a move with a fill, a clipped Multiply layer and a filter mask is one card, and Undo hides all three. Done in studio and plugin tests, which found and fixed two bugs:
  - A stage made of craft passes offered only Reject. One `NEW_CONTRIBUTIONS` rule now covers stage cards and reviews.
  - Adding a mask to an agent layer, or hiding one in a review, changed the parent's recorded state, so its reject was refused as an "artist change". `_creative_settle_containers` now updates the parents.
- [x] 6.3 Painter instructions (layer-first order) and `routing.mjs` (fill, shade, light, grade and soften intents mapped to craft tools). Craft tools are offered in painting phases only, and the `native_craft` execution setting (default on) hides them. Verify with studio tests for tool lists per phase and setting. Done:
  - `prompt.mjs` has the layer-first paragraph (flats, clipped form layers, filters, strokes last);
  - `native_craft` hides the craft tools from the tool list, from `paint_batch` and from routing advice, and takes effect on a setting change mid-chat;
  - the panel has a Painting method selector, which loads at the next Krita restart;
  - tested in `craft.test.mjs`, `routing.test.mjs` and `execution-settings.test.mjs`.
- [x] 6.5 Routing and pacing for craft (part of 6.3, brought forward): `routing.mjs` adds `shade`, `light`, `grade` and `soften`; `fill` and `gradient` route to `fill_region` first; each craft route carries a one-line how-to hint; a gradient no longer needs the native gradient tool. The stalled-step pacing note suggests the craft tools. Verify with `routing.test.mjs`. Still open in 6.3: painter instructions and the `native_craft` setting.
- [x] 6.4 Journal and recovery: a crash during a craft operation leaves an uncertain outcome that blocks painting until acknowledged. Verify with the existing interrupted-operation tests extended to `apply_filter` and `colorize_flats`. Done in `test_filters.py` and `test_colorize.py`: a crash mid-operation refuses new work and replays as `outcome_unknown` until `reconcile`.

## 7. Acceptance

- [x] 7.1 Live, disposable document: a lit sphere with a cast shadow in at most 6 craft operations, no `paint_pass`, and the review passes. The test deletes its study folder and exports afterwards. `scripts/live-craft-acceptance.mjs --scenario sphere` uses a real painter, the real bridge and no mocks. Passed on build `f8221532` with `deepseek/deepseek-flash`, Autopilot and Luna Guide:
  - 5 `fill_region` calls, 0 strokes;
  - 0.8 minutes of painting;
  - the independent review met 5 of 5.
- [ ] 7.2 Benchmark: Starry Night with `native_craft` on and off on the same model, comparing painter model calls, strokes, painting time and review results with `scripts/benchmark-run.mjs`. Record the numbers in the README speed table.
  Partial, stopped by the user.
  - **Craft on** (`deepseek-flash`, Luna Guide, 20-minute cap) stopped at its allowance before any review:
    - 92 passes: 37 craft operations, 38 `paint_pass`, 15 `adjust_layer`;
    - 5,992 strokes;
    - the village was missing.
  - **Craft off** never produced a usable run:
    - one provider stall over 120 s on the first painter call;
    - one active-document switch mid-run;
    - a third run was stopped.

  There's no comparison yet. Rerun with `scripts/live-craft-acceptance.mjs --scenario starry --craft on|off --idle-seconds 300`, and don't switch documents in Krita during the run.
- [x] 7.3 Docs: README highlights, `docs/architecture.md` (new plugin modules and the manifest), and `docs/safety.md` (clipping to artist layers through masks, and that artist layers are never filtered).

## 8. Found in the Krita API study (Context7, 2026-10-11)

- [x] 8.1 Layer styles: `set_layer(style)` through `Node.setLayerStyleFromAsl`, for drop shadow, glow and bevel without strokes. Agent-owned layers only; reject restores the prior style (`layerStyleToAsl`).
  Done in `layer_style.py` and `set_layer(style)`. Live on build `d68f840d`:
  - a drop shadow appeared outside the moon's pixels (`[1,1,1]`);
  - an outer glow replaced it;
  - rejects restored the shadow, then no style.
- [x] 8.2 Transform masks: non-destructive move, scale and rotate of a part (`createTransformMask`, `fromXML`/`toXML`, Krita 5.2+), as a reversible pass.
  Done in `transform_craft.py`, with the companion's `transform_layer`. Live on build `d68f840d`:
  - a 100 px move showed at the new place, and reject put the layer back;
  - scale 2 with a 45° rotation grew the block about its centre.
- [x] 8.3 Follow the artist: "the layer I selected" (`View.selectedNodes`) and their current colour (`View.foregroundColor`) as painter context.
  Done in `canvas_view.py`: observations carry `artist_focus` (selected layers, foreground and background colours), and the painter is told about it. Live on build `d68f840d`: the selected layer and colours came through.
- [x] 8.4 Composition guides: thirds, horizon and centre lines through `guidesConfig`/`setGuidesConfig`, restored when the chat ends.
  Done with the `guides` operation and the companion's `composition_guides`. They make no pass, and the artist's guides are restored at `end`. Live on build `d68f840d`: thirds plus a horizon at y 200.
- [x] 8.5 Progress on the canvas: `View.showFloatingMessage` for the current pass, and optionally `Canvas.pan`/`setZoomLevel` to where the agent paints.
  Done: a floating message when each operation starts. Pan and zoom were left out because they would move the artist's view.
- [x] 8.6 Gradient generator settings: add them to `GENERATOR_SETTINGS`. The live run (build `76f4fc94`) showed that a new gradient, screentone or multigrid fill layer reports an empty configuration, so no `unsupported_settings` are recorded; take the keys from Krita's generator source instead.
  Done: keys from Krita's gradient generator plugin, `start_color`/`end_color` written as stop-gradient XML, and options validated. Manifest version 3 replaces stale caches. Live on build `d68f840d`: a radial gradient went from `[255,1,1]` at the centre to `[5,1,251]` at the edge.
- [x] 8.7 DRY cleanup from group 3: share the ellipse/polygon mask and polygon validation between `region_raster.shape_mask`/`_region_polygon` and the toolbox's `cmd_selection` (`precision_tools.py`); share the "hidden source's last pass ends in this state" update between `fill_region` and `painting_toolbox`; one 8-bit RGBA check for `layer_craft` and `region_craft`. Touches the toolbox selection command, so re-run a live selection check.
  Done:
  - `geometry_data.polygon` and `region_raster.shape_mask` are shared with the toolbox's `cmd_selection`;
  - `_creative_settle` is used by `fill_region`, filters and the toolbox;
  - one `_craft_check_rgba`.

  Live on build `d68f840d`: the toolbox's ellipse and polygon selections came out at the expected bounds.
- [x] 8.8 Hot reload for development: the bridge's `reload` command re-imports the creative modules from the installed plugin, swaps their methods onto the live plugin object, and restarts the companion when no painting session is active, so an installed build needs no Krita restart unless `__init__.py` or `creative_docker.py` changed. Verify with `test_dev_reload.py` and live.

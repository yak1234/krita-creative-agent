## Context

The plugin runs inside Krita and owns every canvas change. Each creative operation goes through one journal in `creative_tools.py`:
1. validate the whole request;
2. record intent (`status: partial`) before the first mutation;
3. mutate on Krita's main thread;
4. record the result and a pass entry;
5. commit a checkpoint and return the canvas image.

A crash in between leaves an uncertain outcome that must be inspected, never repeated. The agent may change only layers it created or copied (`session['layers']`). Passes are layer-based: compare, fade and reject act on a pass's layer.

The scripting API offers what this change needs (all present in Krita 5.3.3's `libkritalibkis`):
- **Layers:** `Node.setBlendingMode`, `setAlphaLocked`, `setInheritAlpha`, `setOpacity`, `setVisible`, `setColorLabel`; `GroupLayer.setPassThroughMode`.
- **Creating nodes:** `Document.createFillLayer(name, generator, InfoObject, Selection)`, `createFilterLayer`, `createFilterMask(name, Filter, Selection|Node)`, `createTransparencyMask`, `createColorizeMask`, `createGroupLayer`.
- **Filters:** `Krita.filters()`, `Krita.filter(name)`, `Filter.configuration`/`setConfiguration`, `Filter.apply(node, x, y, w, h)`; `InfoObject.properties`/`setProperty`.
- **Selections:** `Selection.select`, `selectAll(node, value)`, `add`/`subtract`/`intersect`, `grow`/`shrink`/`feather`/`border`/`invert`, `pixelData`/`setPixelData`.
- **Colorize:** `ColorizeMask.setKeyStrokePixelData`, `setEditKeyStrokes`, `setUseEdgeDetection`, `updateMask`, `setShowOutput`.
- **Synchronisation:** `Document.waitForDone`, `tryBarrierLock`, `setBatchmode`.

The scripting API has no undo grouping, which is why passes are layers. Every design choice below keeps that model.

## Goals / Non-Goals

**Goals:**
- Layer craft (blend, alpha lock, clipping, fill and filter layers), selection-driven fills, filters and colorize flats as first-class, validated, reversible operations.
- No change to the journal, the ownership rule or the pass model's guarantees.
- A painter that reaches flats, shading, light and colour with a few native operations and keeps strokes for edges and detail.

**Non-Goals:** animation, vector shapes, document crop/resize/guides, Notifier and View signals, and image generation.

## Decisions

### 1. First-class tools, not more toolbox commands
New companion tools: `create_layer`, `set_layer` (`adjust_layer` stays unchanged; `set_layer` is a superset), `select`, `fill_region`, `apply_filter`, `colorize_flats` and `krita_capabilities`. Each maps to one plugin creative operation with its own schema.
- **Why:** blend mode and alpha lock already exist inside `painting_toolbox`, and the painter rarely uses them. A named tool with a typed schema is discoverable, routable (`routing.mjs`) and traceable per operation in Langfuse.
- **Alternative rejected:** a single generic `run_action(name)` over Krita actions. It's too loose to validate, and many actions open dialogs or act on whatever is active.

### 2. Clipping has two forms: live above a clip base, a mask otherwise
- **Clip base:** `create_layer(clip_base: true)` puts the new layer alone in an agent group `Creative Agent · <name>`. A layer clipped to it is added at the top of that group with `inheritAlpha = true`. Clipping is live: repainting the base updates the clip. Clip group ids are recorded on the pass (`clip_group_id`) and rebuilt on resume.
- **Any other base** (the artist's layers, or an agent layer outside a clip group): the clipped layer gets a transparency mask whose pixels are the base's alpha at that moment, read in 256-row strips from `projectionPixelData` (8-bit RGBA paintings). The base is never moved, regrouped or edited. This clip is a snapshot; the pass records `clip: {mode: 'mask', base_id, base_alpha}` (a digest) so a later review can tell that the base changed.
- **Why:** inherit alpha clips to everything below the layer in its group, not to one base, so it is exact only when the base is the bottom layer of its own group. Moving an existing layer into such a group would change its parent, which our pass records treat as an edit, and for the artist's layers would break our main safety rule.

### 3. Filters default to masks
`apply_filter` takes `target` (an agent-owned layer or group), `filter`, `config`, an optional `selection`, and `mode`:
- `mask` (the default): a filter mask on the target. It's non-destructive, and rejecting it hides the mask.
- `layer`: a filter layer above the target, inside the target's agent group. It affects everything below it in that group and is used for grading a whole agent group.
- `copy`: `Filter.apply` on an agent-owned copy of the target, used when later strokes need the filtered pixels (for example a blur before painting texture back in).

The artist's layers are never filtered directly. To grade the whole picture, the agent adds a filter layer at the top of its own topmost group; it doesn't touch the artist's layers.

### 4. A manifest validates everything
At bridge start (and on `krita_capabilities`), `capabilities.py` collects:
- filter ids, with each default configuration's property names, types and values (from `InfoObject.properties()`);
- blend mode ids (from a probe layer, then cached);
- fill generators (`color`, `gradient` and `pattern`, as present) with their default configurations;
- installed preset, pattern and gradient names.

It's cached per Krita version. Validation rejects an unknown filter id, an unknown config key, or a value whose type differs from the default, before any mutation (`validation_rejected`, not `partial`). The painter gets a compact manifest: names plus the 5–8 most useful properties for common filters. Full defaults are available on request.

### 5. Every operation is a pass
| Operation | Pass kind | Reject restores |
|---|---|---|
| `create_layer`, `fill_region` (new layer), `colorize_flats` | `layer` | hides the layer (as today) |
| `fill_region` (agent layer) | `layer` on a copy | hides the copy, shows the original |
| `apply_filter` mask/layer | `filter` | hides the mask or filter layer |
| `apply_filter` copy | `layer` | hides the copy, shows the source |
| `set_layer` | `adjust` | the recorded prior state (blend, opacity, visibility, alpha lock, inherit alpha, name), extending today's `adjust_layer` restore |
| `select` | none | selection state only. Not a canvas change: no pass, no checkpoint |

Fade applies to layer and filter passes through opacity.

### 6. Selections are named steps, never the document selection
A selection is a list of steps (a source, a combine mode, refinements). `select` builds it and saves it under a name in the study folder (`.selections/`, the mask bytes compressed); `fill_region` takes that name or the steps inline. The document selection is never set, so the artist's selection needs no restoring.
- **Why:** inside `paint_batch` the painter only knows a tool's arguments from that tool's own schema, so a batch-only "current selection" would be invisible to it. Names also make a region reusable in later turns and after a resume, without a canvas change: a selection mask would hang on a layer and change the layer stack, while a selection creates no pass or checkpoint.
- **Pixels:** shape masks and fills are drawn by Qt (`region_raster.py`), which handles gradients, patterns and compositing in C++; a colour range uses byte-table translation over projection strips. Both read and write 8-bit RGBA, so other colour models are refused.
- **Filling an agent layer** fills a copy above it and hides the original, the same model as `painting_toolbox` with `source_layer_id`, so reject restores the original. A clip group's base is its lowest *visible* layer, so a filled copy of the flats stays the live base.

### 7. Colorize flats
`colorize_flats(line_layer_id, seeds[{color, points|region}], edge_detection?, cleanup?)`:
1. copy the line-art layer if the artist owns it;
2. add a colorize mask;
3. paint the seed key strokes through `setKeyStrokePixelData`;
4. `updateMask`, then `waitForDone`;
5. render the result into a new flat layer the agent owns, and hide the helper mask.

The flat layer becomes the natural base for clipped shading.

### 8. Main-thread work and blocking
Filters and colorize can run for seconds. Each runs as a queued command on the main thread with `setBatchmode(True)`, ends with `waitForDone()`, and reports progress through the existing `_creative_progress`. The companion waits 300 s for these operations instead of 120 s: the plugin cannot interrupt a filter once Krita runs it, so a budget scaled by area would only change when the companion stops waiting. A timeout leaves an uncertain outcome (it's journaled as partial), never a silent retry.

### 9. The painter's workflow
The painter instructions add a layer-first order:
- flats (`fill_region`, `colorize_flats`);
- shadow (`create_layer` Multiply clipped to the flats, then `fill_region` or a gradient fill);
- light (Screen or Add, clipped);
- colour and atmosphere (`apply_filter` masks or filter layers);
- strokes (`paint_pass`, `paint_recipe`) for edges, texture and detail.

`routing.mjs` maps operation intents (`fill`, `shade`, `light`, `grade`, `soften`) to these tools. Luna pacing counts native operations like passes.

## Risks / Trade-offs

- **Filter configuration formats differ per filter and version.** This is why the manifest validates against defaults read live from the installed Krita, never a hard-coded table. Unknown filters are refused, not guessed.
- **Clipping to an artist layer is a snapshot.** If the artist repaints the base, the clip is stale. Each pass records `base_revision`, and the review sees when it changed. Offering a "re-clip" is follow-up work.
- **Colorize masks are slow on large canvases and sensitive to gaps in the line art.** Seeds are validated inside the canvas; `edge_detection` and `cleanup` are exposed; large areas get a longer timeout; failure leaves the helper hidden and reports a partial outcome.
- **Fill generators vary by build.** Only generators found in the manifest are offered.
- **More tools enlarge the painter's prompt.** Tool descriptions stay short, the manifest is compact, and craft tools are shown only in the painting phase.

## Migration Plan

- `adjust_layer` stays as an alias of `set_layer`. Saved chats and existing tests keep working.
- `painting_toolbox` keeps its `blend_mode` and `layer_settings` commands.
- Pass history gains the `filter` kind. Older sessions without it load unchanged.
- Rollback: the companion can hide the new tools behind an execution setting (`native_craft: on/off`, default on) without a plugin downgrade.

## Open Questions

- Should the artist be able to accept a filter pass as destructive (apply the mask into the pixels) from the panel? Not needed for the first version.
- `fill_region` rasterises gradients for now (they work with alpha lock). An editable gradient fill layer can be offered once the generator's settings are known (task 8.6).

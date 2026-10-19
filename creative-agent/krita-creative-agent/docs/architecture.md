# Architecture

Krita Creative Agent has two halves:

- a **Krita plugin** (`krita-mcp/krita-plugin/kritamcp/`), which runs inside Krita and changes the painting;
- a **Node companion** (`krita-creative-agent/src/`), which runs the chat, the painter model and the review.

They talk over a local HTTP bridge on `127.0.0.1:5678`. Every request is a JSON object: `{"action": "creative", "params": {operation, session_id, operation_id, params}}`.

## The creative operation journal

Every change to the canvas goes through `cmd_creative` in `creative_tools.py`, which works like this:

1. **Validate.** The whole request is checked before anything changes. A refused request leaves the painting untouched.
2. **Record intent.** The operation is saved as `outcome_unknown` before the first change. A crash part-way leaves that record behind. Painting is then blocked until the artist inspects the canvas and acknowledges it with `reconcile`, and the operation is never repeated blindly.
3. **Change the canvas.**
4. **Checkpoint and record the pass.** The working `.kra` is saved, and a reversible pass is added to `.passes.json` with its before and after state. The pass history can compare, fade, hide or reject each pass. Passes of the same plan step or Agent move form a group that can be rejected together, which is Undo in Agent mode.

Replaying an `operation_id` returns the stored result and never paints twice.

## Native craft modules

Craft tools make whole areas through Krita's own layers instead of brush strokes. Each one is a mixin on the plugin object:

| Module | Operations | What it does |
| --- | --- | --- |
| `capabilities.py` | `capabilities` | The manifest of what this Krita offers: filters and their settings, blend modes, fill generators, and the names of presets, patterns and gradients. It is cached per Krita version. Validators check ids, setting names and types before any change. |
| `layer_craft.py` | `create_layer`, `set_layer` | Paint, fill and group layers with blend mode, opacity, alpha lock, clipping and layer styles. Also has the shared helpers for copies, clip groups and alpha masks. |
| `layer_style.py` | (used by `set_layer`) | Drop shadow, inner shadow, outer glow and outline, written as the ASL XML that `Node.setLayerStyleFromAsl` reads. |
| `region_craft.py` | `select`, `fill_region` | Named selections built from steps, saved in the study folder. Solid, gradient and pattern fills onto a new layer or a copy. |
| `region_raster.py` | (Qt pixel work) | Shape masks, fills and partial blends. Also used by the toolbox's `selection` command. |
| `filters.py` | `apply_filter` | Filter masks, filter layers or filtered copies, limited by a selection. Fading a mask rewrites its saved coverage, because Krita ignores filter-mask opacity. |
| `colorize.py` | `colorize_flats` | Flat colours from closed line art with Krita's colorize mask. |
| `transform_craft.py` | `transform_layer` | Moves, scales or rotates an agent layer with a transform mask. |
| `canvas_view.py` | `guides`, and `artist_focus` in observations | The artist's selected layers and colours, composition guides that are restored when the chat ends, and a floating message on the canvas when an operation starts. |
| `dev_reload.py` | bridge `reload` | Loads an installed build into the running Krita without a restart. |

### Recorded passes

A pass records what was made and which existing layer it relates to:

- the new layer, mask or copy (`layer_id`);
- the related layer: `source_layer_id` for a copy, `target_id` for a filter or transform, `clip.base_id` for a clip.

Reject hides what the pass made. When the pass made a copy, reject also shows the original again.

When an operation adds a mask or child layer, or a review hides one, the parent layers' recorded state is updated. The journal therefore doesn't mistake its own change for the artist's.

## Companion

- **`tools.mjs`** defines the painter's tools and their schemas. `paint_batch` runs up to 10 actions in one model call, and `"$N"` names a layer made earlier in the same batch.
- **`craft.mjs`** lists the craft tools once, for the bridge, the pacing, the activity labels and the `native_craft` setting.
- **`studio.mjs`** runs the four modes:
  - Ask and Plan only read the canvas.
  - Ask is teacher mode. It explains how a painter would build the picture in Krita, step by step, with the Krita feature for each step and an Agent message that does it. A full lesson starts with `# Lesson:`. The companion saves it as `goal.lesson`, and the panel's Lesson chip opens it in any mode, beside the plan. The lesson is for the artist: it is never added to the painter's context, unlike the plan.
  - Agent makes one move per message.
  - Autopilot works through the plan to completion.

  It also decides which tools each phase offers. With `native_craft` (an execution setting, on by default) switched off, the craft tools disappear from the tool list, from `paint_batch` and from routing advice.
- **`prompt.mjs`** holds the painter instructions. When craft tools are offered, the painter works layer-first:
  1. flats;
  2. clipped Multiply and Screen layers for form;
  3. filters for colour and softness;
  4. strokes last.
- **`routing.mjs`** handles Luna routing. Fill, gradient, shade, light, grade, soften, move and transform intents go to the craft tools, each with a one-line hint on how to use them.

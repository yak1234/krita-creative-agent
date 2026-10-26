## Why

The painter reaches almost every result with brush strokes. To shade a figure it paints hundreds of darker strokes; to warm a whole scene it repaints it; to keep shading inside a shape it has to aim every stroke at the edge. A digital painter does these with Krita's layer craft instead: flat colour regions, a Multiply layer clipped to the flats for shadow, a Screen or Add layer for light, alpha lock to repaint inside existing paint, and filter masks to adjust colour without touching pixels.

An audit of Krita 5.3.3's scripting API (`libkritalibkis`, 704 public methods) found the plugin calls about a third of it. The agent creates only paint and group layers, applies no filters, and never clips one layer to another. Blend mode and alpha lock exist, but only as commands buried inside `painting_toolbox`, on the toolbox's own new layer, so the painter rarely uses them.

Giving the painter Krita's native craft as first-class tools should cut strokes and model round trips sharply and improve quality: edges stay clean, shading follows form, and colour changes stay reversible.

## What Changes

- **Layer craft as first-class tools.**
  - `create_layer`: paint, fill (colour, gradient or pattern), filter and group layers, created with blend mode, opacity, alpha lock and clipping in one call.
  - `set_layer`: a superset of `adjust_layer`, which stays as it is. Opacity and visibility work on any unlocked layer; blend mode, alpha lock, clipping and name on layers the agent created.
  - **Clipping** (`clip_to`): a layer is clipped live to a clip base, a layer the agent created alone in its own group with `clip_base`, through Krita's inherit alpha. Clipping to any other layer, including the artist's, uses a transparency mask taken from that layer's alpha, without moving or regrouping it.
- **Selections drive region work.** `select` builds a selection from shapes, from a layer's alpha, or from a colour range, and can refine it (grow, shrink, feather, border, invert). `fill_region` fills a selection with a colour, gradient or pattern in one call. Together they replace the stroke-by-stroke fills.
- **Filters.** `apply_filter` runs any filter Krita reports, with a validated configuration. Its modes are a filter mask (non-destructive, the default), an adjustment layer above a group, or a destructive apply on an agent-owned copy. Colour adjustment (curves, levels, HSV, colour balance), blur, sharpen and noise become one call instead of a repaint.
- **Flats from line art.** `colorize_flats` uses Krita's colorize mask: colour seeds on a line-art layer fill closed regions, and the result becomes a flat layer the agent owns.
- **A capability manifest.** At startup the bridge reports what Krita offers: filter names with their default configurations, blend modes, fill generators and installed presets, patterns and gradients. Tools validate against it, and the painter reads it instead of a fixed list.
- **The painter paints like a digital painter.** Its instructions, routing and pacing prefer the order flats, then clipped shadow and light layers, then filter adjustments, then strokes for edges and detail only. Every new operation is a reversible pass that can be compared, faded and rejected, and it can go in a `paint_batch`.

## Capabilities

### New Capabilities
- `native-painting-craft`: first-class layer craft (blend modes, alpha lock, clipping, fill and filter layers), selection-driven region fills, filters as masks, layers or copies, colorize flats, the capability manifest, and the painter's layer-first workflow.

### Modified Capabilities
<!-- `adjust_layer` becomes an alias of `set_layer` (same arguments, same result). `painting_toolbox` keeps `blend_mode` and `layer_settings` for existing chats. -->

## Impact

- **Plugin** (`krita-mcp/krita-plugin/kritamcp/`):
  - new `layer_craft.py` (layers, clipping, selections, fills), `filters.py` (filters, masks, colorize) and `capabilities.py` (the manifest), each under 500 lines;
  - `creative_tools.py` dispatches the new operations through the existing operation journal (intent recorded before mutation, uncertain-outcome handling, pass history, checkpoints);
  - the ownership rules extend to masks and fill or filter layers.
- **Companion** (`krita-creative-agent/src/`): `tools.mjs` (schemas), `studio.mjs` (painter instructions, `BATCH_TOOLS`, `PACED_TOOLS`), `routing.mjs` (operations mapped to the new tools), `runtime.mjs` (activity labels), `bridge.mjs` (mutating operations).
- **Safety:** unchanged in principle. The agent never paints on, moves or regroups the artist's layers; clipping to one of them uses a mask on the agent's own layer.
- **Tests:** plugin unit tests with a fake Krita API, companion studio tests, and live acceptance on a disposable document.
- **Non-goals:** animation, vector shapes, document-level crop/resize/guides, and listening to the artist's actions (Notifier and View signals). Those are separate changes.

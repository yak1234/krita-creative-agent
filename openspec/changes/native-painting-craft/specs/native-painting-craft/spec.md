## Purpose

Gives the Creative Agent Krita's native painting craft as first-class tools: layers with blend modes, alpha lock and clipping; fill and filter layers; selection-driven region fills; filters as masks, layers or copies; and colorize flats from line art. These let the painter reach flats, shading, light and colour with a few validated, reversible operations, and keep brush strokes for edges and detail. They never change the ownership rule: the agent never paints on, moves, regroups or filters the artist's layers.

## ADDED Requirements

### Requirement: Capability manifest
The plugin SHALL report what the running Krita offers:
- filter ids, with each default configuration's property names, types and values;
- blend mode ids;
- available fill generators, with their settings. A new fill layer reports an empty configuration, so known settings (`color` for the colour generator, `pattern` for the pattern generator) SHALL be listed by the plugin; colour settings SHALL take `#RRGGBB`;
- installed preset, pattern and gradient names.

Settings of types the painter cannot set yet SHALL be recorded as `unsupported_settings`. The manifest SHALL be read from the installed Krita, cached per Krita version and manifest version, and exposed to the painter as `krita_capabilities` (compact by default, trimmed to fit 3,800 characters; full on request). Every craft operation SHALL be validated against it before any mutation. An unknown filter, generator, blend mode or configuration key, or a value whose type differs from the default, SHALL be refused with `validation_rejected` and leave the canvas unchanged.

#### Scenario: Unknown filter
- **WHEN** the painter calls `apply_filter` with a filter id the manifest does not list
- **THEN** the operation is refused with `validation_rejected`, no layer or mask is created, and no pass is recorded

#### Scenario: Wrong configuration type
- **WHEN** a filter's default configuration has a numeric `radius` and the painter supplies `"radius": "big"`
- **THEN** the operation is refused before any mutation

### Requirement: Layer creation with craft properties
`create_layer` SHALL create a paint, fill, filter or group layer the agent owns. In the same call it SHALL set any of: name, blend mode, opacity, visibility, alpha lock (paint layers only), and clipping (`clip_to`). Fill layers SHALL take a generator from the manifest (colour, gradient or pattern) and an optional selection to limit the fill. The new layer SHALL be added to the agent's layers and recorded as a reversible `layer` pass.

#### Scenario: Shadow layer in one call
- **WHEN** the painter creates a paint layer named "Shadow" with blend mode `multiply`, opacity 0.6 and `clip_to` the agent's flats layer
- **THEN** one layer exists with those properties, clipped to the flats, recorded as one pass

#### Scenario: Alpha lock on a fill layer
- **WHEN** the painter asks for alpha lock on a fill layer
- **THEN** the call is refused with `validation_rejected`

### Requirement: Clipping without touching the artist's layers
Krita's inherit alpha clips to everything below a layer in its group, so a live clip SHALL be offered only above a clip base. `create_layer` with `clip_base` SHALL create the layer alone in a new agent clip group. `clip_to` SHALL clip the layer to the base's alpha:
- **Base is a clip base:** the clipped layer SHALL be added at the top of the base's clip group with inherit alpha on, so the clip follows later changes to the base.
- **Any other base** (the artist's layers, or agent layers outside a clip group): the clipped layer SHALL get a transparency mask built from the base's alpha at that moment. The base SHALL NOT be moved, regrouped, renamed or edited. The pass SHALL record the base id and a digest of the alpha used.

Clip groups SHALL remain live clip targets after a chat is resumed.

#### Scenario: Clip to a clip base is live
- **WHEN** a Multiply layer is clipped to the agent's flats layer, created with `clip_base`, and the agent later extends the flats
- **THEN** the shadow layer is visible over the extended area too, without another clip operation

#### Scenario: Clip to an artist layer leaves it in place
- **WHEN** the painter clips a light layer to the artist's "Figure" layer
- **THEN** "Figure" keeps its position, parent, pixels and properties, and the light layer shows only where "Figure" was opaque

### Requirement: Layer settings and their reversal
`set_layer` SHALL change opacity and visibility on any unlocked layer, as `adjust_layer` does, and blend mode, alpha lock (paint layers), clip (inherit alpha, only above a clip base) and name on layers the agent created. It SHALL record the complete prior state of those properties as an `adjust` pass, and rejecting that pass SHALL restore it. `adjust_layer` SHALL remain available with its current arguments and results, as an alias.

#### Scenario: Reject restores the blend mode
- **WHEN** the painter sets a layer from `normal` to `overlay` and the artist rejects that pass
- **THEN** the layer is `normal` again, with its opacity and visibility unchanged

#### Scenario: The artist's layer keeps its craft settings
- **WHEN** the painter calls `set_layer` with a blend mode on a layer the agent did not create
- **THEN** the call is refused and the layer is unchanged; the same call with only opacity succeeds

### Requirement: Selections for region work
A selection SHALL be described as steps. Each step has at most one source: a rectangle, ellipse or polygon; a layer's alpha (read only); a colour range on the visible image (with a tolerance, optionally within bounds); or a saved selection. A step's source SHALL combine with the selection so far by replace, add, subtract or intersect, and the step SHALL then refine it by grow, shrink, border, feather, smooth and invert, in that order. `select` SHALL save the result under a name in the study folder, so later operations and later turns reuse it, including after a resume; `fill_region` SHALL take that name or the same steps inline. Selections SHALL NOT change the artist's selection. An empty result SHALL be refused. A selection alone SHALL NOT create a pass or a checkpoint.

#### Scenario: Selection from a layer's alpha
- **WHEN** the painter selects from the artist's "Figure" layer alpha and then fills the selection on a new layer
- **THEN** the fill covers exactly the figure's opaque area, and "Figure" is unchanged

#### Scenario: The artist's selection survives
- **WHEN** the artist has a selection and an Autopilot batch uses `select` and `fill_region`
- **THEN** the artist's selection is unchanged throughout

### Requirement: Region fills
`fill_region` SHALL fill a saved selection or inline selection steps with a solid colour, a gradient (linear or radial, with 2-16 stops) or a pattern from the manifest, as pixels. It SHALL fill a new paint layer (the default, optionally with blend mode, opacity, `clip_base` and `clip_to`) or an agent-owned paint layer, honouring that layer's alpha lock. Filling an agent layer SHALL fill a copy placed directly above it and hide the original, so rejecting the pass restores the original; a filled copy of a clip base SHALL remain the live base of its clip group. An area that is empty inside the canvas SHALL be refused with nothing changed. Editable gradient fill layers wait for the gradient generator settings (task 8.6).

#### Scenario: Flat in one call
- **WHEN** the painter fills a polygon selection of the sky with a solid colour on a new layer
- **THEN** one layer holds the flat colour exactly inside the polygon, recorded as one pass, without any brush strokes

#### Scenario: Alpha-locked recolour
- **WHEN** the painter fills a gradient onto an alpha-locked agent layer
- **THEN** only that layer's existing opaque pixels change colour

#### Scenario: Extending the flats keeps the clip
- **WHEN** the painter fills more area onto a clip-base flats layer that has a clipped Multiply layer
- **THEN** the Multiply layer shows over the extended area too, and rejecting the fill restores the original flats

### Requirement: Filters as masks, layers or copies
`apply_filter` SHALL apply any manifest filter with a validated configuration to an agent-owned target, optionally limited to a selection, in one of three modes:
- `mask` (the default): a filter mask on the target;
- `layer`: a filter layer inside one of the agent's groups, at its top when the target is the group, otherwise directly above the target;
- `copy`: applied to the pixels of an agent-owned copy of the target, with the source hidden.

The artist's layers SHALL never be filtered directly. Mask and layer results SHALL be recorded as `filter` passes, whose rejection hides the mask or filter layer and whose fade weakens the effect: a filter layer's opacity, or, because Krita ignores a filter mask's opacity, the mask's coverage scaled from its saved original. Copy results SHALL be recorded as `layer` passes. Long filters SHALL run with dialogs suppressed, report progress, and end in a definite result or an uncertain outcome, never a silent retry. An area that is empty inside the canvas SHALL be refused with nothing changed.

#### Scenario: Non-destructive warm grade
- **WHEN** the painter applies a colour-balance filter in `mask` mode to the agent's painting group
- **THEN** the group's pixels are unchanged, the visible result is warmer, and rejecting the pass removes the effect

#### Scenario: The artist's layer is protected
- **WHEN** the painter targets the artist's layer with `apply_filter`
- **THEN** the call is refused and suggests a `layer` mode adjustment inside the agent's own group

### Requirement: Colorize flats from line art
`colorize_flats` SHALL take a line-art layer and colour seeds (each a colour with points or a region inside the canvas), plus optional edge detection and cleanup. It SHALL:
1. copy the line-art layer if the artist owns it;
2. run Krita's colorize mask with those seeds;
3. wait for it to finish;
4. produce a new flat-colour layer the agent owns, recorded as one `layer` pass, with the helper mask hidden.

Seeds outside the canvas or with invalid colours SHALL be refused before any mutation.

#### Scenario: Flats for a character
- **WHEN** the painter seeds skin, hair and coat colours on a closed line drawing
- **THEN** a new layer holds a flat colour in each enclosed region, and the line-art layer is unchanged

### Requirement: Batching, journaling and pass history
Every craft operation SHALL go through the existing operation journal: intent recorded before mutation, an operation id that cannot be reused with different instructions, uncertain outcomes that block further changes until inspected, and a checkpoint and canvas image after canvas changes. Craft operations SHALL be allowed in `paint_batch`, where a layer made by an earlier action SHALL be addressable as `"$N"` (its action number) in `layer_id`, `clip_to` and `source_layer_id`. They SHALL count as painting actions for pacing, allowances and Agent-mode moves, and SHALL show in pass history with compare, fade (where applicable) and reject.

#### Scenario: Agent-mode move with craft
- **WHEN** an Agent-mode move is one batch with a flat fill, a clipped Multiply layer and a filter mask
- **THEN** the move card shows one move, and Undo hides all three results

#### Scenario: Crash during a filter
- **WHEN** Krita stops while a filter is running
- **THEN** the next session reports an uncertain outcome for that operation and refuses further painting until the artist inspects and acknowledges it

### Requirement: Layer-first painter workflow
In the painting phase, the painter's instructions SHALL prefer this order:
1. flats with `fill_region` or `colorize_flats`;
2. shadow and light on clipped layers with suitable blend modes;
3. colour and atmosphere with `apply_filter`;
4. brush strokes for edges, texture and detail.

Routing SHALL map fill, shade, light, grade and soften intents to these tools. The craft tools SHALL be offered only in painting phases. An execution setting `native_craft` (default on) SHALL hide them for a chat when off.

#### Scenario: Shaded form without strokes
- **WHEN** the live acceptance asks for a lit sphere with a cast shadow on a disposable document
- **THEN** the painter produces it with at most 6 craft operations and no `paint_pass`, and the review passes

#### Scenario: Fewer round trips
- **WHEN** the Starry Night benchmark runs with `native_craft` on and then off, on the same model
- **THEN** the run with it on uses fewer painter model calls and fewer strokes, and both runs' reviews are recorded for comparison

### Requirement: Layer styles
`set_layer` SHALL accept a `style` for layers the agent created: drop shadow, inner shadow, outer glow and outline, applied through Krita's layer style (`setLayerStyleFromAsl`), so the effect follows the layer's pixels without strokes. The style SHALL replace the layer's style. Rejecting the pass SHALL restore the previous style, or no style when the layer had none. A style on the artist's layers or on a mask SHALL be refused.

#### Scenario: Shadow without strokes
- **WHEN** the painter gives a moon layer a drop shadow and then rejects that pass
- **THEN** the shadow appears outside the moon's pixels, and after the reject the area is back to the background

### Requirement: Transform masks
`transform_layer` SHALL move, scale and rotate a layer the agent created through a transform mask, about a pivot that defaults to the layer's centre. The layer's pixels SHALL stay unchanged, and rejecting the pass SHALL hide the mask. The artist's layers SHALL never be transformed.

#### Scenario: Moving a finished part
- **WHEN** the painter moves its block layer 100 px to the right and then rejects the pass
- **THEN** the block shows at the new place, and after the reject it is back at the old place

### Requirement: Following the artist
Every observation SHALL include `artist_focus`: the layers the artist has selected in the view of the painting, and their foreground and background colours. It SHALL be omitted when no view shows the painting. The painter's instructions SHALL say that "this layer" and "my colour" refer to it.

#### Scenario: The selected layer
- **WHEN** the artist selects a layer and asks the agent to shade it
- **THEN** the painter's observation names that layer in `artist_focus.selected_layers`

### Requirement: Composition guides and canvas progress
A `guides` operation SHALL show thirds, centre or horizon guides, or given positions, as Krita guides. It SHALL record no pass or checkpoint. The artist's own guides SHALL be restored when the chat ends. Each canvas operation SHALL show a short floating message in the painting's view when it starts. Both SHALL be best effort and never stop painting.

#### Scenario: Thirds for a composition
- **WHEN** the painter asks for thirds guides with a horizon at y 200 on a 256 × 256 painting
- **THEN** vertical guides sit at one third and two thirds of the width, and a horizontal guide at 200

### Requirement: Gradient fill layers
A `gradient` fill layer SHALL take the keys of Krita's gradient generator (shape, repeat, reverse, start and end positions with their units), plus `start_color` and `end_color`, which become the generator's gradient stops. Unknown shapes, repeats and units SHALL be refused before any change.

#### Scenario: A live radial gradient
- **WHEN** the painter creates a radial gradient fill layer from red to blue
- **THEN** the layer is red at its centre and bluer towards its edge, and stays editable as a Krita fill layer

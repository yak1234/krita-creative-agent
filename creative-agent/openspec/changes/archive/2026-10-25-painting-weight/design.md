## Context

The observation is built in `creative_tools._creative_observe`. The tidy (`native_craft._native_tidy`) already finds
the agent's hidden leftovers, the hidden layers inside "Creative Agent ·" groups. Krita keeps a cached projection for
every group layer and recomputes filter masks on `refreshProjection()`. At 6000×4500 one full-canvas RGBA8 layer is
108 MB in memory.

## Decisions

### The measure (plugin, `painting_weight.py`)
`weight(nodes, width, height) -> dict`. It takes the plugin's node walk and reads only per-node metadata: `type()`,
`visible()`, `name()`, `bounds()`, and for filter masks `filter().name()`.
- `nodes`, `groups`, `paint_layers`, `filter_masks`, and `expensive_filters`: the names of filters on the list
  `EXPENSIVE = ('waveletnoisereducer', 'gaussiannoisereducer', 'oilpaint', 'kuwahara', 'unsharp', 'lens blur')`.
- `hidden_agent_layers`: the tidy's leftover count.
- `estimated_mb`: the sum over paint layers and filter masks of bounds area × 4, plus each visible group's bounds
  area × 4 (its projection), in MB. This is an upper estimate: Krita stores only tiles that hold paint.
- `level`:
  - `too_heavy`: estimated over 6000 MB, or an expensive filter on a canvas over 8 MP;
  - `heavy`: estimated over 2500 MB, or more than 60 groups, or more than 30 hidden agent layers;
  - otherwise `ok`.
- `reasons`: short facts, biggest first, e.g. "10 live filter masks (wavelet noise reducer) recompute on every refresh".
- `fixes`: some of `tidy`, `merge_kept`, `bake_filters`.

*(my call: the thresholds come from this painting, which is 4.3 GB estimated by groups alone. To be tuned on 3
paintings, per build-for-the-general-case.)*

### Reaching the painter (`extensions/painting-weight.ts`)
- On `tool_result`, read `details.weight` and the operation's `timings_ms.total`.
- Append `{painting_weight: "<line>"}` when the level rises in this chat, or when an operation took over 60 s and the
  level is not `ok`. The line says why the call was slow.
- At most one line per level per chat, and one per slow operation. Each line is under 300 characters.
- Example: "This painting is heavy (147 groups, 10 live filter masks incl. a wavelet noise reducer): every refresh
  recomposites them, so calls take minutes. Work in a few large passes; don't add filter masks; the artist can
  merge kept moves."

### Reaching the artist (studio)
- One status notice per chat when `level` is not `ok`, with the reasons and the fixes as words. The buttons come in a
  later panel change.

## Non-Goals
- Changing the painting automatically (merging, baking, deleting).
- Measuring real RSS: Krita exposes no API for it, and an estimate from metadata is enough to name causes.

## Risks
- The estimate overstates tile-sparse layers. The level uses counts and filters as well as MB, so it does not cry wolf
  on a few big sparse layers.

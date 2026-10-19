## Context

The agent's Krita tools today: strokes (`paint_pass`, `paint_recipe`, `paint_contours`), `fill_region`,
`create_layer` (paint, fill with a live generator, group), `select` (shapes, layer alpha, colour range, seed),
`apply_filter` (mask, filter layer or copy), `set_layer`, `transform_layer`, `colorize_flats`, `adjust_layer`,
`painting_toolbox` (legacy commands), lettering, references, protection. The plugin already drives fill layers,
filter layers and masks, vector layers, colorize and transparency masks through Krita's scripting API, and triggers
Krita actions for undo and redo.

What Krita's scripting API offers (apidoc.krita.maou-maou.fr): `Document.createCloneLayer(name, source)`,
`createFillLayer`, `createFilterMask(name, filter, selection_source)`, `Krita.filter(name)` with `InfoObject`
configuration, `Krita.instance().action(id).trigger()`. Krita's own Split Layer is a dialog that scripts cannot fill
in, so splitting is built here.

A live run on New Moscow after the seed selection landed: it used a seed twice, but still made six zoomed looks before
its first move, traced a polygon by hand, and fell back to airbrush strokes for the base gradient.

## Goals / Non-Goals

**Goals**
- The agent can reach clone layers, split by colour, colour to alpha and a vetted set of Krita actions.
- The agent picks the Krita feature that fits the job, and a test set shows it.
- Every new operation is reversible, respects protected areas and never touches the artist's layers' pixels.

**Non-Goals**
- A script tool that runs agent-written Python (later, once we see what jobs are still missing).
- File chores: export, file layers, document settings.
- Reorganising the artist's layers. The agent may group, name and merge its own.
- Anything that changes the canvas size (trim, crop image, resize). Sessions refuse a canvas change today.

**Anti-goals** (failure even if it works)
- Any tool that bypasses protection, undo or the journal.
- A Krita action that opens a dialog or waits for a click: it would hang the agent or crash Krita.
- A prompt that grows into a wall. Reorganising must not make it much longer.

## Decisions

### Clone layers
`clone_layer {source: layer_id, name, blend_mode?, opacity?, clip_to?, offset?: [dx, dy]}` creates a Krita clone
layer in the agent's stage, a live copy that follows its source. The source may be any layer, including the
artist's, read only: a clone changes nothing in its source. Uses: repeated motifs (lamp posts, windows) moved with
`offset` or `transform_layer`, reflections (clone, flip with transform_layer, blur with a filter mask). Protection
treats a clone like a fill layer: a transparency mask hides it inside protected areas.

### Split by colour
`split_by_color {source: layer_id | "visible", colors: 2-24 (default 8), region?: [x,y,w,h], min_area?: pixels,
as_layers?: false, name_prefix}`. The palette is found on a downscaled image (median cut or k-means, in Python, a few
hundred thousand pixels at most). Each full-resolution pixel is assigned to its nearest palette colour by Qt
(`QImage.convertToFormat(Format_Indexed8, colorTable, ThresholdDither)`), so no per-pixel Python. Each colour becomes
a saved selection named `<prefix> 1 · #RRGGBB` with its share of the canvas; regions under `min_area` are dropped.
`as_layers: true` also makes one agent layer per colour, a copy of those pixels (Krita's Split Layer).

Default is selections, not layers (the artist's choice): 8 full-size layers of a 6000×4500 painting is heavy, and the agent
mostly needs the areas. Honest limit: split by colour finds areas of one colour (sky, road, a coat). It does not find
objects ("the woman"). An object is several colours combined with `select` steps (`saved` + `add`).

### Colour to alpha
If the installed Krita lists the `colortoalpha` filter, colour to alpha goes through `apply_filter` (mode copy, or
mask where Krita allows it) with a named entry in the tool description and the prompt. If not, a `color_to_alpha
{layer_id, color, threshold}` operation does it in pixel code beside `region_raster.py`. The audit decides *(my call:
prefer Krita's filter)*.

### Krita actions, vetted
`krita_action {action: one of the vetted ids, target?: layer_id}` runs one of Krita's menu commands. The vetted list
lives in the plugin as data: action id, a one-line description, what it needs (an agent target layer, a saved
selection), whether it changes pixels, and how Reject undoes it. The agent sees only that list.

How it runs: inside `cmd_creative` like every operation. Pixel-changing actions act on an agent layer only (the target
is made active first), are recorded as a pass whose Reject restores the layer's earlier pixels, and go through the
protection backstop. Selection actions change the agent's working selection only, never the artist's.

How an action gets on the list: an audit script runs each candidate on a throwaway document in the installed Krita
with a watchdog. It goes on the list only if no dialog or modal window appears, Krita stays responsive, and undo
restores the document. Candidates to audit (from Krita's menus): mirror layer horizontally and vertically, rotate
layer 90°/180°, select opaque (replace/add/subtract/intersect), invert selection, clear inside the selection, fill
the selection with the foreground or background colour, split alpha into a mask, convert a layer to a paint layer,
alpha lock. Trim and crop are out (they change the canvas size). The list grows by running the audit again, never by
hand. The audit writes the list per Krita version into the plugin's data and the bundle ships the list for the
version audited here (5.3.3) *(my call)*; the audit detects a dialog with `QApplication.activeModalWidget()` and
top-level windows checked on a timer after the trigger, and closes it.

### Choosing the right tool
- **Prompt in named sections**, modelled on agentic coding prompts: `<role>`, `<choosing_a_tool>` (the job → the
  Krita feature: an existing area → seed or split by colour; a mass → fill_region or a fill layer; a whole-area change
  → a filter mask; a repeat → a clone layer; lifting a colour → colour to alpha; flips and rotations → krita_action;
  strokes → marks, edges, texture and detail only), `<tool_calling>` (rules), `<protection>`, plus the existing
  teaching and reference sections. Existing guidance is moved, not duplicated, and the prompt does not grow.
- **Worked examples are skills, not always-on text** (from Google Research's Harness²: always-on text is paid on
  every turn, a skill costs nothing until opened, and a skill nobody names is never opened). `repaint-area` (repaint
  a sky, make windows glow, darken a street) and `repeat-motif` (repeat lamp posts, mirror a figure), each named by a
  trigger line in the prompt.
- **The agent names the method** in its progress line before each painting call ("Seed-select the sky, then a live
  gradient fill layer"). The artist sees it in the chat. No schema field *(my call)*: a required field would be one
  more thing to fill in mechanically.
- **Loop guards are a shipped Pi extension**: `extensions/loop-guards.ts` (TypeScript, checked strictly against Pi's
  types), a `tool_result` handler registered inline (`extensionFactories`) with Pi's extension discovery still off.
  Inline, not by path: inside the release bundle Pi's path loader cannot resolve its own modules (found by a bundled probe). Hints acting in the tool loop cannot be skipped the way
  prose can, and cost nothing in the prompt. It carries the existing craft hints (moved from `craftNudge`), a fix
  hint on a refused call, and the look nudge: after four observe calls in a row with no canvas change, the next
  observation carries a line: you have looked N times without changing anything; select the area with a seed or
  split_by_color, sample_canvas_colors for colours, then act. A nudge, not a refusal *(my call: four, since the live
  run made six)*. Discovery stays off so no extension we do not ship runs in the painting loop.
- **A scored tool-choice test set**: about 10 requests on 3 paintings (copies of New Moscow, Starry Night and the Great Wave *(my call: the paintings
already used for live checks)*), run live
  with the test painter model, three runs per request: a result seen in one run of three is noise. Builds are compared
  three ways (old; new without the loop guards; new in full) so each change is measured on its own. Each request lists the methods a good run uses and the ones it should not (for "repaint
  the sky": a seed or split selection and a fill or fill layer; no stroke pass covering more than 12% of the canvas).
  The script reports per request what the agent used and a score, saved in benchmark-runs, so builds can be compared.

### Panel
Move cards name the new tools (Clone layer, Split by colour, Colour to alpha, Krita action). These are panel changes,
so the batch ends with one install and one Krita restart.

## Risks / Trade-offs

- **An action opens a dialog on another Krita version** → the audit runs per installed version; an unknown version
  offers no actions until audited.
- **Split by colour on a noisy painting gives many small regions** → `min_area` and the colour count bound it; shares
  are reported so the agent can pick.
- **The prompt reorganisation changes behaviour in ways tests miss** → the tool-choice set runs before and after, and
  existing prompt tests keep their assertions.
- **Clone layers of the artist's layers** → read only by construction; protection masks them.

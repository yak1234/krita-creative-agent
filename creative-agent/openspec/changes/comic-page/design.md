## Context

Every canvas change goes through the creative operation journal in `creative_tools.py`: validate, record intent, mutate, record a pass, checkpoint. Passes are layers; reject hides what a pass made. New paint from a plan step or an Agent move goes into a stage group at the top of the painting (`_creative_stage_group`), and craft layers find their parent through `_craft_container`.

The companion keeps per-chat state on the goal (`goal.brief`, `goal.lesson`, …) and sends the panel one `goal` event with all of it. Painting starts in `runMove` (Agent) and in the Autopilot run, each after `bindCanvas()` and a fresh observation.

Krita APIs used (all in 5.3.3's `libkritalibkis`): `createGroupLayer`, `createTransparencyMask` plus `Selection.setPixelData`/`Node.setPixelData` for the panel shape, `createVectorLayer`, `VectorLayer.addShapesFromSvg`, `Node.setLocked`, `QFontDatabase` and `QFontMetricsF` (PyQt5) for fonts and line breaking.

## Goals / Non-Goals

**Goals:**
- A page of panels built in one reversible operation, with art that cannot cross a border.
- A panel model the painter, the plan and the review share.
- Lettering that stays editable in Krita and is found by Krita's comics tools.
- Comic as a setting that every mode honours, including Autopilot from a story.

**Non-Goals:** multi-page projects, adopting other plugins' panels, panel-local coordinates, text fitted to arbitrary shapes, image generation.

## Decisions

### 1. Layout format: rows of column ratios
A layout is `{rows: [h1, h2, …], cols: [[w…], [w…], …], margin, gutter, border, page_color, border_color}`, or `{preset: name}`. Heights and widths are relative weights, normalised per row, so `{rows:[1,1,1,1], cols:[[1,1],[1,1],[1,1],[1,1]]}` is the 4×2 page and `{rows:[2,1], cols:[[1],[1,1,1]]}` a splash over a strip. Gutters and margins are pixels. This is Manga Panel Creator's model in a form a model can write and a person can read. Presets: `grid-2x2`, `grid-2x3`, `grid-2x4`, `manga-3-tier`, `splash-strip`, `two-plus-one`, `four-strip`, `single`.

Panels are numbered `P1`…`Pn` in reading order: rows top to bottom, panels left to right (`reading: "rtl"` reverses columns for manga). `comic_layout.py` is pure Python with no Krita import, so the panel's layout picker uses the same function for its preview and tests run without Krita.
- **Alternative rejected:** free polygons from the model. Too easy to produce overlapping or gapped panels; slanted panels can come later as an optional `skew` per gutter.

### 2. Page structure: masks clip, borders sit on top
```
Comic page                    (group, agent)
├─ Lettering                  (group, agent)    ← letter() adds "text · …" vector layers here
├─ Panel borders              (vector layer, agent, locked) stroke-only rectangles
├─ Panel 1 … Panel n          (groups, agent)   each with a "Panel shape" transparency mask
└─ Page                       (fill layer, agent) page_color behind the gutters
```
- **Masks clip.** A transparency mask on each panel group, painted with the panel's rectangle, clips everything inside the group, however it was added. Inherit alpha (Manga Panel Creator's approach) would need every new container to set it and would clip to the border stroke, which lets art cover the border.
- **Borders on top.** One locked vector layer above all panels keeps borders crisp and out of reach of panel art.
- **One pass.** `comic_page` records one pass whose layer is the page group; its result carries the panel model. Reject hides the page, and is refused while unrejected passes have layers inside it ("Reject the panel work first, or start a new chat").
- The live check confirms masks clip a group's later children regardless of child order (Krita lists masks among children). Fallback if it does not: a `Panel shape` paint layer at the bottom of each group with inherit alpha on every container the agent adds there.

### 3. The panel model
`comic_page` returns `comic: {page_id, borders_id, lettering_id, reading, panels: [{id, bounds: [x,y,w,h], order, group_id}]}`. The plugin stores it on the session and rebuilds it on resume from the last unrejected `comic_page` pass, like clip groups. Every observation carries `comic` while the page exists. The companion stores the same model on `goal.comic.panels`.

### 4. Panel scoping through stage groups
`_creative_stage_group(doc, session, stage_id, parent=None)` gains a parent: the panel's group instead of the document root. `_craft_container` and `_creative_new_layer` resolve `panel` to that group, so plan-step and Agent-move grouping (and Undo) keep working inside panels. `paint_pass`, `create_layer`, `fill_region` and `apply_filter` (`layer` mode) accept `panel`; an unknown panel, or `panel` with `clip_to`/`target` outside it, is refused before any change. `apply_filter` `mask` mode and `transform_layer` need no `panel`: they act on a layer that is already in a panel.

### 5. Lettering
`letter` takes `{panel, kind: caption|speech|thought|shout, text, at: [x,y], width, tail_to?, font?, size?, fill?, ink?}` (page pixels). `lettering.py` builds the SVG: the shape (caption rectangle; speech ellipse with a tail drawn as one path; thought ellipse with a trail of circles; shout as a burst polygon) and `<text>` with one `<tspan>` per line. Lines are broken by `QFontMetricsF` in Krita and by an injected measure in tests, so the text never depends on Krita's automatic wrapping. Fonts are checked against `QFontDatabase().families()`; an unknown font falls back to the default with a note. Each call makes one vector layer named `text · <kind> <panel>` in the Lettering group: one pass, rejectable on its own, and found by the comics plugin's translation scraper (it matches `text` in vector layer names).

### 6. Comic setting in the companion
- **State:** `goal.comic = {layout, panels, built, page_id}` or `null`. The panel sends `{type: 'comic', layout}` (or `null` to turn it off before the page exists). The panel computes the preview panels with `comic_layout.py` and sends them, so Plan can name `P1`…`Pn` before anything is painted; the plugin's result replaces them when the page is built.
- **Building:** when painting starts (`runMove`, the Autopilot run) and `goal.comic` is set but not built, the host calls `comic_page` itself after the first observation, with `stage_id: 'comic-page'` so an Agent move's Undo never removes the page. Ask and Plan never build it; they are read-only.
- **Context:** `comic: {panels, built}` joins the painter's context. A comic section joins the painter's instructions (use `panel`, letter last, captions at a panel's top-left, keep characters to their records), the teacher instructions (comic craft) and the review rubric.
- **Plans:** with Comic on, `propose_plan` requires `story: {logline, panels: [{panel, beat, shot, characters, caption?, dialogue?}]}` covering every panel once, and steps that name their `panel` (a final lettering step names none). Missing plot is asked about, with a "You decide" option, like any requirement.

### 7. Panel UI
A `Comic` checkbox next to the mode selector; ticking it opens the layout picker (preset thumbnails drawn from `comic_layout.py`, a custom rows-and-columns editor, gutter and margin). A `▦ Comic · N panels` chip in the scope tray opens the same picker read-only once the page is built. This is `creative_docker.py`, so it ships with one Krita restart.

## Risks / Trade-offs

- **Mask ordering in groups** → verified live before the panel scoping depends on it; fallback in decision 2.
- **SVG text support differs across Krita versions** → only `<text>`/`<tspan>` with `x`, `y`, `dy`, `font-family`, `font-size`, `fill`; checked live on 5.3.3.
- **Page coordinates for panel work** → the model must stay inside a panel's bounds; clipping hides strays, and the observation lists bounds. Panel-local coordinates are a later change.
- **Rejecting the page** would orphan panel art → refused while panel work exists.

## Migration Plan

Additive. Chats without `goal.comic` behave as before; plugin operations without `panel` are unchanged. The panel UI arrives with the next Krita restart; the companion and plugin hot-reload.

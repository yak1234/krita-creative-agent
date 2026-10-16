## ADDED Requirements

### Requirement: Page layouts
The plugin SHALL compute a page's panels from a layout: a named preset, or rows of relative heights each with a list of relative column widths, plus margin, gutter and border in pixels. Panels SHALL be numbered `P1`…`Pn` in reading order: rows top to bottom, and within a row left to right, or right to left when `reading` is `rtl`. A layout whose panels would be smaller than 32 pixels on a side, or that has no panels or more than 24, SHALL be refused before any change. The same layout function SHALL serve the operation, the panel's picker preview and tests, without importing Krita.

#### Scenario: Four rows of two
- **WHEN** the layout is `{rows:[1,1,1,1], cols:[[1,1],[1,1],[1,1],[1,1]], margin:40, gutter:20}` on a 1200 × 1800 page
- **THEN** there are 8 panels, `P1` top left and `P2` top right, all the same size, with 20 pixels between neighbours and 40 pixels to the page edge

#### Scenario: Manga reading order
- **WHEN** the same layout has `reading: "rtl"`
- **THEN** `P1` is the top right panel

#### Scenario: Too small
- **WHEN** a layout would make a panel 20 pixels wide
- **THEN** the layout is refused and nothing is created

### Requirement: Comic page operation
`comic_page` SHALL build the page as one reversible pass:
- a page group the agent owns;
- inside it, bottom to top: a page fill layer in `page_color`; one group per panel, clipped by a transparency mask in the panel's rectangle; a locked `Panel borders` vector layer with each panel's rectangle as a stroke; and a `Lettering` group.

The result SHALL carry the panel model: page, borders and lettering ids, the reading direction, and for each panel its id, bounds, order and group id. A chat SHALL hold at most one comic page; a second `comic_page` SHALL be refused while an unrejected page exists. Rejecting the page SHALL be refused while unrejected passes have layers inside it.

#### Scenario: Building the page
- **WHEN** the agent builds a `grid-2x2` page
- **THEN** one pass exists, four panel groups each have a panel-shaped transparency mask, the borders layer is above every panel and locked, and the artist's layers are unchanged

#### Scenario: Rejecting a page with work in it
- **WHEN** a panel holds an unrejected fill pass and the page pass is rejected
- **THEN** the reject is refused and the page stays visible

### Requirement: Panel model in observations
While a comic page exists, every observation SHALL include `comic` with the panel model. The model SHALL be rebuilt when a chat resumes, from the last unrejected `comic_page` pass.

#### Scenario: Resume
- **WHEN** a chat with a comic page is resumed
- **THEN** the first observation lists the same panels with the same ids and group ids

### Requirement: Panel-scoped painting
`paint_pass`, `create_layer`, `fill_region` and `apply_filter` in `layer` mode SHALL accept `panel`. Their new layers SHALL be created inside that panel's group (in the stage group of the plan step or Agent move, made inside the panel group), so nothing they paint shows outside the panel. An unknown panel, `panel` without a comic page, or a `clip_to` or `target` outside the named panel SHALL be refused with `validation_rejected` before any change. Without `panel`, these operations SHALL behave as before.

#### Scenario: Fill that overruns the panel
- **WHEN** the agent fills a rectangle larger than `P2` with `panel: "P2"`
- **THEN** the new layer is inside `P2`'s group and no pixel outside `P2`'s rectangle changes

#### Scenario: Unknown panel
- **WHEN** a call names `panel: "P9"` on a four-panel page
- **THEN** it is refused and no pass is recorded

### Requirement: Lettering
`letter` SHALL add a caption box or a speech, thought or shout balloon with its text as vector shapes that stay editable in Krita. Each call SHALL create one vector layer named `text · <kind> <panel>` in the page's Lettering group, recorded as its own pass. Text SHALL be broken into lines by the plugin to fit the given width and written as one `<tspan>` per line. A font not installed SHALL fall back to the default font, and the result SHALL say so. Text longer than 400 characters, an empty text, or a position outside the named panel SHALL be refused.

#### Scenario: Caption
- **WHEN** the agent letters a caption in `P1` at its top-left with a 300-pixel width
- **THEN** a vector layer `text · caption P1` holds a filled rectangle and the text in lines no wider than the box, and rejecting that pass hides only that caption

#### Scenario: Speech balloon with a tail
- **WHEN** the agent letters a speech balloon with `tail_to` pointing at a character
- **THEN** the balloon and its tail are one outlined shape with no stroke across the tail's base

### Requirement: Comic setting across modes
The companion SHALL keep `goal.comic` (`layout`, `panels`, `built`, `page_id`) per chat, set from the panel. Comic SHALL NOT be a mode: Ask, Plan, Agent and Autopilot SHALL each work with it on. Ask and Plan SHALL NOT build the page. When painting starts in Agent or Autopilot and the page is not built, the host SHALL build it with `comic_page` before the painter's first turn, outside any Agent move's Undo group. The painter's context SHALL include the panel model; its instructions, the teacher instructions and the review SHALL include comic guidance while Comic is on. Turning Comic off SHALL be refused once the page is built.

#### Scenario: Autopilot from a story
- **WHEN** Comic is on with a four-panel layout and Autopilot starts an approved plan
- **THEN** the host builds the page first, the painter's context lists `P1`–`P4`, and the plan's steps run panel by panel

#### Scenario: Agent Undo keeps the page
- **WHEN** the first Agent move builds the page and paints in `P1`, and the artist presses Undo
- **THEN** the move's paint is rejected and the page stays

### Requirement: Story-shaped plans
With Comic on, `propose_plan` SHALL require `story` with a `logline` and one entry per panel (`panel`, `beat`, `shot`, `characters`, optional `caption` and `dialogue`). A story that misses a panel, names an unknown panel, or repeats one SHALL be refused with a message naming the problem. Each plan step SHALL name its `panel`, except lettering or whole-page steps. Plan SHALL ask for missing plot details with a "You decide" option rather than invent a different story from the one the artist described.

#### Scenario: Missing panel in the story
- **WHEN** a four-panel page's plan has story entries for `P1`, `P2` and `P4`
- **THEN** `propose_plan` is refused with a message that `P3` has no beat

### Requirement: Panel controls
The panel SHALL show a `Comic` checkbox beside the mode selector in every mode. Ticking it SHALL open a layout picker with preset previews and a custom rows-and-columns editor, drawn with the same layout function as the plugin. While Comic is on, a `▦ Comic · N panels` chip SHALL appear beside the Plan and Lesson chips and open the layout; once the page is built, the layout SHALL be shown read-only.

#### Scenario: Picking a layout
- **WHEN** the artist ticks Comic and chooses the 4×2 preset
- **THEN** the companion receives that layout with eight preview panels and the chip reads `▦ Comic · 8 panels`

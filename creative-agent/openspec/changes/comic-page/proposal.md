## Why

Artists want to make comic pages with the agent: a page of panels, a short story told across them, and captions or speech balloons. Today the agent sees one undivided canvas. It cannot keep paint inside a panel border, tell panel 3 from panel 4, or letter text. A user with no comics background also does not know how to lay out a page or pace a story.

Krita already has the parts: groups and transparency masks keep art inside a shape, vector layers hold borders and balloons (`Document.createVectorLayer`, `VectorLayer.addShapesFromSvg`), and the bundled Comics Project Management Tools recognise vector layers whose names contain `text` for translation. The community plugin Manga Panel Creator (MIT) shows a compact row-and-column layout format and a per-panel group structure; it has no API and lets art cover the borders, so we take its ideas, not the plugin.

## What Changes

- **Comic is a setting, not a mode.** A `Comic` checkbox in the panel works with Ask, Plan, Agent and Autopilot. Ticking it opens a layout picker (presets or a custom row-and-column layout). A `▦ Comic · N panels` chip shows the page beside the Plan and Lesson chips.
- **One page per chat.** A chat makes one comic page in its one document. Multi-page projects are a later change.
- **`comic_page` operation.** Builds the page as one reversible pass: a page group with one group per panel, each clipped by a transparency mask in the panel's shape; a `Panel borders` vector layer above every panel, so art never covers a border; and a `Lettering` group above that. The panel model (`P1`…`Pn`, bounds, reading order, group ids) is recorded in the study and returned in every observation.
- **Panel scoping.** `paint_pass`, `create_layer`, `fill_region` and `apply_filter` (filter layers) take `panel: "P3"`. Their new layers go inside that panel's group and are clipped to it. Coordinates stay in page pixels; each panel's bounds are in the observation.
- **`letter` operation.** Captions, speech, thought and shout balloons as editable vector shapes, each on its own layer named `text · …` in the Lettering group, so each can be rejected on its own and Krita's comics tools find the text.
- **Story-shaped plans.** With Comic on, a plan carries a story: a logline and, for every panel, the beat, shot, characters and caption. Plan asks for missing plot details. Steps go panel by panel, then lettering. Autopilot runs it straight through.
- **Comic-aware teaching and review.** Ask teaches comic craft (shot variety, reading order, caption placement, the 180° rule). The review checks each panel against its beat and the page for consistent characters and readable flow.

## Capabilities

### New Capabilities
- `comic-page`: page layouts, the panel model, panel-scoped painting, lettering, story-shaped plans, and the Comic setting across modes.

### Modified Capabilities
<!-- None: native-painting-craft operations gain an optional `panel` argument; their behaviour without it is unchanged. -->

## Impact

- **Plugin** (`krita-mcp/krita-plugin/kritamcp/`): new `comic_layout.py` (pure layout geometry, shared with the panel's picker), `comic.py` (`comic_page`, `letter`, panel resolution), `lettering.py` (balloon and caption SVG); `creative_tools.py` dispatch, stage groups inside panel groups, the panel model in observations; `creative_docker.py` checkbox, picker and chip (needs one Krita restart).
- **Companion** (`krita-creative-agent/src/`): comic state on the goal, the page built when painting starts, `panel` on painting tools, the `letter` tool, comic prompt, story fields and validation in plans, panel-aware review.
- **Safety:** unchanged. Everything the page holds is the agent's own; the artist's layers are never moved into or out of a panel.
- **Non-goals:** multi-page projects and Comics Manager export, adopting panels made by other plugins (a later task), panel-local coordinates, automatic text fitting inside arbitrary shapes, and image generation.

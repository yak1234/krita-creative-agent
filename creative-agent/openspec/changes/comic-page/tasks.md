Test rule for every task: tests write only to temporary folders they remove, and run through `npm run test:unit` (JS) or `unittest discover` (Python). Live checks use a disposable document and delete their study folder afterwards, pass or fail. Live checks wait until no painting session is active in Krita.

## 1. Layout

- [ ] 1.1 `kritamcp/comic_layout.py`: presets, rows-of-column-ratios layouts, margin, gutter, `rtl` reading order, validation (1–24 panels, at least 32 px a side). Pure Python. Verify with `test_comic.py`.

## 2. Page

- [ ] 2.1 `kritamcp/comic.py` `comic_page`: page fill, panel groups with rectangle transparency masks, locked borders vector layer above, Lettering group; one pass; the panel model on the session and the result; refuses a second page. Verify with fake-Krita tests.
- [ ] 2.2 Panel model in observations, rebuilt on resume from the last unrejected `comic_page` pass. Reject of the page refused while unrejected passes have layers inside it. Verify with unit tests.
- [ ] 2.3 Live check: masks clip later children of a panel group in any child order; borders stay above art; reject behaviour; resume keeps the model.

## 3. Panel scoping

- [ ] 3.1 `_creative_stage_group` takes a parent; `paint_pass`, `create_layer`, `fill_region` and `apply_filter` (`layer` mode) accept `panel`, resolved to the panel group, with refusals for unknown panels, no page, and `clip_to`/`target` outside the panel. Verify with unit tests; existing tests pass unchanged.
- [ ] 3.2 Live check: a fill larger than its panel changes no pixel outside it; Agent move Undo inside a panel.

## 4. Lettering

- [ ] 4.1 `kritamcp/lettering.py`: caption, speech (one path with tail), thought, shout SVG; line breaking with an injected measure; font fallback. Verify with unit tests.
- [ ] 4.2 `letter` operation: one `text · <kind> <panel>` vector layer per call in the Lettering group, one pass, refusals. Verify with fake-Krita tests.
- [ ] 4.3 Live check on 5.3.3: the SVG text renders with its lines, is editable with the text tool, and the comics plugin's scraper pattern finds the layer.

## 5. Companion

- [ ] 5.1 `goal.comic` state; `comic` command from the panel; refused to turn off once built; persisted and restored. Verify with studio tests.
- [ ] 5.2 Host builds the page when painting starts (Agent and Autopilot), with stage `comic-page`; Ask and Plan never build it. Verify with studio tests including Agent Undo keeping the page.
- [ ] 5.3 Tools: `panel` on `paint_pass`, `create_layer`, `fill_region`, `apply_filter`, `paint_recipe`, `paint_contours`; new `letter` tool; batchable; activity labels; bridge mutating list. Verify with `craft.test.mjs`.
- [ ] 5.4 Context, painter instructions, teacher instructions and review rubric gain comic guidance while Comic is on. Verify with studio tests.
- [ ] 5.5 Plans: `story` required with Comic on, validated against the panels; steps name panels. Verify with studio tests.

## 6. Panel

- [ ] 6.1 `creative_docker.py`: Comic checkbox, layout picker (presets drawn from `comic_layout.py`, custom rows and columns), chip; sends `{type:'comic', layout, panels}`. Verify with `ui_smoke.py`.

## 7. Acceptance

- [ ] 7.1 Live Autopilot run of a four-panel page from a two-sentence plot: every panel matches its beat, captions are lettered, no paint crosses a border, and the review passes.
- [ ] 7.2 Docs: `docs/architecture.md`, `docs/safety.md`, README.

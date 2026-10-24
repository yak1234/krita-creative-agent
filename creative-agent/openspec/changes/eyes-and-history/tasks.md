## 1. Views capped at 2000 px

- [x] 1.1 `view-size.ts` MAX_VIEW_SIDE 2000; the view size choices Auto/1024/1568/2000 (`settings-schema.mjs`); a saved
  2048 becomes 2000 (`execution-settings.mjs`); the probe's PROBE_VIEW_CAP 2000; the plugin's comment.

## 2. Close-ups of the area being worked

- [x] 2.1 `src/closeup-crops.ts` (strict): the area a call names (`callArea`), the crops of an area (`cropRects`: none
  when the whole view shows actual pixels, one window of at least 512 px, else two along the long side, each at most the
  crop side), the labelled crops added to an observation (`addCloseupCrops`, a read-only `peek` of the same revision).
- [x] 2.2 Wired: `tools.mjs nativeExecute` asks `runtime.addCloseups` on a whole-canvas observe; the studio's area is
  Paint only here, else the newest area a call names in this move (recorded on `tool_execution_start`); side
  `min(painter's measured crop side or 1536, view side)`. Older crops leave the history with the other images.

## 3. Resolution probe

- [x] 3.1 Tokens are input + cache read + cache write (`sizeTokens`); without tokens, cost growth decides.
- [x] 3.2 Sizes 1024, 1280, 1536, 1792, 2048, 2560. A dip below the bar at one size between sizes the model reads is
  noise, not a limit (deepseek-flash at 1280, two live runs); probing stops where the cost stops growing.
- [x] 3.3 Re-measured for real (2026-10-24) and recorded in `src/model-resolutions.json` with the scores, sides capped
  at 2000: claude-haiku-5.5 2000 (reads 2560), glm-5.3-flash 1792, qwen3.8-flash 1792, deepseek-flash 1536 (a second
  deepseek run, seed 20261025, also 1536).

## 4. Compaction is not silence

- [x] 4.1 `runtime.mjs`: `compaction_start` pauses the model watch (activity "compacting"), `compaction_end` restarts it
  from its end; reset at each run.

## 5. Shorter history

- [x] 5.1 `src/history-trim.ts` (strict): results older than the last 3 assistant turns become one line when they are
  observe_canvas or longer than 1500 characters; in the agent's transformContext before keepRecentImages.

## 6. No layer blindness

- [x] 6.1 `tools.mjs modelResultText`: over the limit, the layers as a compact list (id, name, set flags) in the layer
  index's budget, then the top-level layers with counts; always the revision and size; never the bare stub with layers.

## 7. Fewer layers

- [x] 7.1 Keeping a move also runs `tidy_kept` on every earlier undone move not yet tidied (`mergeKept`), once each.

## 8. A changed painting does not stop the move

- [x] 8.1 Every native result's `revision` refreshes the expected revision (`nativeExecute`).
- [x] 8.2 In an Agent move `canvas_changed` re-observes and hands the painter the fresh canvas with a note
  (`freshAfterChange`, through `error.recovered`); not for a canvas of another size; at most three times a move.

## 10. Review fixes (2026-10-24)

- [x] 10.1 Only mutating operations' results move the expected revision (`mutates`, now in `craft.mjs`); a read-only
  result such as sample_colors no longer hides the artist's edits.
- [x] 10.2 `tidy_kept` `undone: true`: only layers the undone move's rejected passes made (new contributions, not
  continued, not set_layer/adjust_layer, never guides), none another stage's pass still uses.
- [x] 10.3 Lookups (list_brushes, painting_tool_help, krita_capabilities, a skill read) stay whole in the history; a
  shortened paint result keeps layer_id and job_id.
- [x] 10.4 The layer budget always makes progress (a single huge entry has its name cut).
- [x] 10.5 Close-ups only where the move names an area (strokes no longer count), saved as JPEG (`peek` `jpeg`), and
  counted apart in keepRecentImages: the newest look keeps view and crops, the look before its view.
- [x] 10.6 After a compaction the activity returns to what it was.
- [x] 10.7 Panel: with no model chosen, OpenRouter qwen/qwen3-vl-235b-a22b-instruct is pre-selected when connected.

## Builder's notes

- 2: the area is the newest one a call names (region, box, or an observe region; not stroke bounds), not Find it's own outline unless the artist adopts
  it as Paint only here. Crops are peeks with `refresh:false`, so a crop is only sent when its revision matches.
- 3: the old rule ("every size up to it scores") called deepseek-flash a 1024 reader on both runs because of 1280.
  `probe` in the record is the first run's scores.
- 5: no test drives the wiring through a whole session (the trimming itself is tested); checked by reading the request.
- 6: document_id and image paths stay host-only (in `details`, the image as its own part), as for every result.
- 7: Undo itself deletes nothing: the artist can still look back until a later move is kept. tidy_kept undone removes only
  the hidden layers the undone passes made (never the artist's, never a guide, never one another stage uses); Krita's own undo history can still bring a removed layer back.
- 8: autopilot keeps its pause (its tests unchanged); the dimensions check keeps "Canvas dimensions changed" pausing.
- 10.5: an installed plugin without the `peek` `jpeg` field refuses it, so crops stop (the look itself never fails);
  plugin and companion ship together.

## 9. Live in Toska on a copy (lead)

- [ ] 9.1 Live in Toska on a copy (lead): view size 2000 in Settings, close-ups in an Agent move with Paint only here, a
  long move past compaction, an observe with 60+ layers, Keep after Undo (layer count), the artist painting mid-move.

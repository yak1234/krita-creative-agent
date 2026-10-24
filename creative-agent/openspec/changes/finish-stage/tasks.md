# Finish stage: tasks

## 1. Finish — branch agent/finish
- [x] 1.1 Plugin: finish pass (soft-area blend + form strokes), baked per tile into a "Finish" group in the move's stage group
- [x] 1.2 Companion: paint_finish tool, goal placement, progress, likeness, Undo; default folder plan underpainting -> finish -> accents
- [x] 1.3 Sharpen offer for any attached goal; "no more detail, sharpen it" guidance
- [x] 1.4 Tests (Python under PyQt5 and PyQt6, companion unit), timings on the New Moscow copy
- [x] 1.5 Live in Toska on a copy (lead, 2026-10-24, build 9cf3db8b): plan underpainting -> Finish -> accents; Sharpen card; underpainting 10 min (ΔE 61.9 -> 0.3); Finish 70 s, 108 squares, progress on the Now card, look matches the spike; accents 15 s; Finish with Paint only here on the sky: outside unchanged (3 of 1.4 M preview pixels over 8 levels). Not verified live: Undo of a Finish move by pixels (the move was marked undone; preview vs export comparison inconclusive), Stop mid-Finish, the attach-after-underpainting Sharpen case, the no-more-detail note

Builder's notes (section 1): `finish_pass.py` (plugin operation `finish`) runs the spike's algorithm per 512 px tile: each
tile reads the clean composite below the Finish group (one read of the padded work, before anything is written) and the
goal resampled onto the canvas (one bicubic warp of the goal's crop under the whole work: OpenCV's fixed-point warp
rounded a pixel's position by where its rect started, so tiles resampled apart differed by a level and their strokes
with them), padded by the reach of the soft mask (3 sigma kernels: 139 px at 6000 px), the guided filter (21 px) and the
strokes (25 px). Seeds lie on one grid over the whole canvas and draw their random numbers from a hash of their cell
(fixed seed 7), so a stroke that crosses a tile edge is drawn identically in both; tiles of 96 and 1024 px give the same
pixels (test_finish_pass). Two baked layers: "blend" (the smoothed canvas, alpha the soft mask) under "strokes" (alpha
the strokes' own times the hard mask), which over the canvas is the spike's composite; a layer with nothing to show is
removed. Sizes scale with the canvas's long side against 6000 px (gradient too), never below a pixel or two. Krita's
events run every 0.2 s between strokes (longest gap measured 0.12 s inside a tile), the Now card shows the square and
stroke count, Stop keeps the squares done. The goal is the chat folder's file (the attached goal or its sharpened copy;
hash, PNG/JPEG header and pixel count checked before an OpenCV decode), placed as goal likeness places it
(`studio.mjs goalPlacement`: the kept whole transfer, else a goal of the canvas's proportions). Refused before an
underpainting: a kept whole-picture transfer, or a painting the chat started on (an underpainting from an earlier chat
counts). Timing on the 6000 x 4500 New Moscow copy with the 4x goal, offline, this Mac: 60 s for the whole picture
(108 tiles, 1.47 M strokes drawn including the ones shared by two tiles; decode 0.6 s), difference to the goal 7.1 ->
4.7 (spike 4.6); the bridge allows the operation 300 s (LONG_OPERATIONS). Fix 4: `pictureGoal` is the folder's goal, else
the first attached general or composition reference of the canvas's proportions, checked again whenever the artist
attaches one. Fix 5: a refine request (refine, detail, sharper, crisper, clean up, finish...) in an Agent move whose canvas
is within goal likeness 3 of a goal enlarged more than 2x and not sharpened adds a GOAL RESOLUTION note and shows the card
again if it was never answered. Not done here: a goal placed by a transfer of other proportions is not offered Sharpen;
the live test in Toska (1.5).

## 2. Fine Finish and full-size checks — branch agent/fine-finish
Approved by the artist 2026-10-24 ("yess we need both"; goal 8 the same night: "i want the end result where our accents and
finishes make it move eventually to the final. Right now we just have a very crisp underpainting").
- [x] 2.1 Plugin: `finish` detail `fine` (the church try-out's sizes, scaled with the canvas) for an area of at most 15% of the canvas, and `finer` (goal 8's second level)
- [x] 2.2 Companion: paint_finish `detail`; after the whole-picture Finish an element or refine step in an area is paint_finish detail fine then paint_accents (element-step-rules.ts, the Paint only here context, the folder element move); typed strokes stay capped
- [x] 2.3 Plugin: full-size checks for an area (area_compare.py: area_likeness, area_accents, refine_map), read only, guides left out
- [x] 2.4 Companion: paint_accents in an area from the placed goal compares at full size; goal likeness measures the move's area at full size before and after each batch (reported, never used to undo)
- [x] 2.5 Refine to the goal (goal 8): refine_to_goal, the host's loop; default folder plan step "Refine to the goal" between Finish and Accents; a refine request without an area after the whole-picture Finish runs it
- [x] 2.6 Tests (Python under PyQt5 and PyQt6, companion unit), offline timings on the church files and the whole New Moscow canvas export
- [ ] 2.7 Live in Toska on a copy (lead)

Builder's notes (section 2): **Fine Finish.** `finish_pass.DETAILS` lists only what differs from the default: fine is strokes
2-4 px wide, 6-18 long, a seed every 2 px, colour stop 20, guided filter r 4 (the lead's try-out); finer is 1.5-2 px wide, 4-10
long, stop 14, r 2 (sizes at 6000 px, scaled with the long side, floors as before: the seed spacing never under 2 px). Fine and
finer are refused on more than `FINE_SHARE` 15% of the canvas (the whole 6000 x 4500 canvas fine would be about 6 M strokes;
15% is about 4 MP, about 30 s at the measured rate). Offline, the plugin's code on the church (550 x 750 at [1150, 750] of the
artist's canvas export, the 4x-sharpened goal): 109,183 strokes in 2.9 s, difference to the goal (blurred 4 px, the lead's
measure) 5.17 -> 2.19 (try-out 2.14); fine again changes nothing (its strokes are the same strokes), finer then 2.45 -> 1.27
colour. paint_finish's report and Now card say the detail. The studio records `goal.whole_finish` when a whole-picture,
default-detail Finish paints (finish-tool.ts `finishDone`); element steps then refine fine (`refineSequence`), not a second
scoped transfer. The goal spec paint_finish sends moved to goal-spec.ts (shared with the checks).
**Full-size checks.** `area_compare.py` reads the goal as paint_finish does (chat folder, hash, GoalOnCanvas; decoded once and
kept on the session per goal and placement) and the composite with the guide group hidden, in 1024 px squares padded by the
blurs' reach (tiles give the same numbers). `colour` is the mean CIE76 ΔE of both blurred 2 px, `edges` the mean difference of
their gradient magnitudes through 1 px (both scaled with the canvas). On the church: colour 4.95 -> 2.45, edges 3.59 -> 2.44
after the fine Finish, where the 64-cell likeness grid said 0.38 -> 0.17 (the artist's "0.4"); 13 ms for the church, 0.7 s for
the whole 27 MP canvas (refine_map). The accent finder in an area runs `accent_find.find` on the goal's and the canvas's own
pixels of the area, at most `AREA_PIXELS` 4 MP (area-averaged above it), answering in canvas pixels: the church found 112
accents before (68 lights, 3 glints, 32 darks, 9 lines) and 105 after the fine Finish (57, 4, 41, 3), 0.55 s; the old reduced
path (goal at 4 MP, the 1568 px view) found 96 and 73 there. The likeness grid's undo thresholds are unchanged: the full-size
area measure is recorded, shown on the move line ("the area at full size ΔE 5.0 -> 2.5") and told to the painter, never used
to undo (it is not calibrated for undo; finish, refine and accents are exempt anyway). The area is the Paint only here area
(Find it and element steps set it) or a box the call names.
**Refine to the goal.** refine-goal.ts: refine_map in `REGION` 512 px squares (scaled) over the whole canvas or the area; each
round takes the squares scoring above `DONE_SCORE` 4 (colour + edges), worst first, and runs the plugin's `finish` (box, the
square's next level: fine, then finer) and the accents the canvas still lacks there (area_accents, at most 40 a square, protected
areas skipped, then the plugin's `accents`), then measures the square; each pass is its own reversible pass under the call's id
(`<id>/r<round>-<n>-finish|accents`) in the move's group. It ends when no square is above 4, when the squares left have had both
levels, or at the budget (15 minutes, 12 M strokes, both arguments), checked between squares; Stop ends it there. The Now card:
"Refine: round N, region M of K, difference X -> Y"; an action line per round. Goal likeness exempts it as paint_finish. Offline
on the whole 6000 x 4500 export (finish only: the accents need Krita's filters): the squares scored 3.8-15 after the
whole-picture Finish (median 7.7); round 1 fine on 93 squares, 131 s, 8.0 -> 4.8 on average; round 2 finer on 68, 78 s,
5.3 -> 3.0; 210 s, 9.46 M strokes, whole canvas colour 4.19 -> 1.59 and edges 3.23 -> 1.59, 3 of 108 squares left above 4
(worst 5.0). Images: scratchpad `fine-finish/whole_before_after_goal.jpg`, `crop_church.jpg`, `crop_skyscrapers.jpg`,
`crop_bridge.jpg` (before | after | goal). In Krita each square adds two passes (Finish and Accents groups) until the move is
kept and merged, and each finish re-reads its square: expect it slower than offline.
Not done here: a full-size measure for a selection or shape the call names (the Paint only here area or a box only); the
offline runs have no accents; nothing ran in Toska.

Review fixes (section 2, 2026-10-24): refine_to_goal paints a round as a few finish passes (batches of at most 14% of the
canvas, a mask of their squares cut to the Paint only here area) and one accents pass, not two passes a square (New Moscow:
about 14 passes and 45 layers for the offline run's 161 squares instead of ~320 passes and ~1,000 layers; computed, not
measured in Krita: each pass still observes the canvas before and after it, the checkpoint is the plugin's timed one);
squares mostly protected or outside the area are left; Stop, the allowance or a failed pass end it with the report. The
refine note runs it only for the whole picture, never negated, a named part is asked for its area (Luna's message reading
decides when it answered, keywords otherwise). "The whole picture is finished" follows its move (undone: unset) and the
plugin's finish_whole on the pass. Fine's 15% counts the area's own pixels; a larger area goes to refine_to_goal. The speck
rule scales with the compared image (2-4 px darks survive at full size). Luna review records refine_to_goal's findings and
never undoes it.

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

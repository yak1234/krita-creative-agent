# After the underpainting: close-ups, a stretch limit, one unify pass, ask when it may be done

Status: PROPOSED (2026-10-23, written up at the artist's request); waiting for the artist's go. Would build after
sharper-guides merges.

## Why

The last two traced New Moscow chats (Langfuse sessions 9f8202e8…, 94cea8db…, 2026-10-23 02:51-03:36 EDT, the build
before aa514e8e) share one shape: an excellent whole-picture underpainting, then 20-30 minutes of decline.

- **The underpainting spends all the reference has.** The goal is 1448x1086 on a 6000x4500 canvas (4.1x). Later
  transfers re-sample the same pixels: hair from a 210x180 source onto 870x746, the figure 340x320 onto 1409x1326.
  `MAX_PATCH_SCALE` (2x) guards only `paint_from_reference` patches; `paint_reference_surface` and
  `paint_reference_edges` have no stretch limit.
- **Then it smears or invents.** 94cea8db ran four whole-canvas smudge transfers ("Fuse dabs", "Soften every mass",
  "Big smudge masses"…) and a filter over the underpainting. 9f8202e8 spent about 18 minutes hand-placing
  `paint_batch` strokes on one head; Luna flagged flat_block 1.0 and hard_graphic 1.0 right after the underpainting,
  later stripes 0.94 and ellipses 0.78.
- **Nobody knows what is next.** `decision-choose-next-layer` confidence falls from 0.97 before the underpainting to
  0.12-0.22 after it, spread over texture, accents and done (done 0.23-0.27).
- **Noise.** Four `paint_batch` calls failed with "pressure needs one value per point" (the schema wants one more
  value than segments, the painter sends one per segment), one on a stale observation.

## Goals

1. **Close-up references for detail.** A reference (or a project-folder element image such as
   `11-woman-back-view.png`) that shows part of the goal is aligned to its place in the goal automatically (feature
   matching, shapes where needed), shown to the artist for a yes before first use, and from then on detail transfers
   for that area sample the close-up, not the goal. The painter is told which areas have a close-up.
2. **A stretch limit for every transfer.** `paint_reference_surface` and `paint_reference_edges` get the same rule as
   patches: above about 2x enlargement on a painted canvas they are refused with a message that names the area and
   asks for a close-up (goal 1), or offers to stop there. The first whole-picture underpainting is unaffected.
3. **One unify pass.** After a whole-picture underpainting, at most one whole-canvas smudge/blend transfer or filter
   per chat; further softening must be scoped to an element or region.
4. **Ask when it may be done.** When the next-layer decision puts "done" in its top two, or its confidence falls
   below about 0.3, the painter stops after the move and asks the artist what to work on next (offering the elements
   still without a close-up), instead of inventing detail.
5. **Pressure that matches the painter.** `paint_batch` accepts one pressure value per segment or per segment end
   (and the same for tilt and the other per-point lists), resampling the shorter form; the error, if any, says exactly
   how many values were expected.

## Non-goals

- The whole-picture underpainting and the reference tools stay as they are (the artist's rule: reference tools stay).
- No AI-generated detail; detail comes from references or from the artist's direction.
- Hand strokes (`paint_batch`) are not removed; goal 4 stops the long blind runs.

## Done when

On a copy of the New Moscow folder: the figure's head is refined from `11-woman-back-view.png` (aligned, confirmed
once), a 4x hair transfer from the goal is refused with a pointer to the close-up, the chat runs at most one
whole-canvas blend, and after the main elements the painter asks instead of polishing one area for many minutes.
Checked on two other references for the general case; timings of the alignment measured.

## Left to the builder

The alignment method (ORB/SIFT homography in the plugin's OpenCV, with SAM as a fallback for low-texture close-ups),
the exact thresholds, the panel display of an aligned close-up, and the wording of the questions.

# Crisp accents: stage two after the underpainting; visible tracing removed

Status: APPROVED by the artist (2026-10-23: "renove traces, call it accents", "accents go on their own layer", "yes please 1 and 2, exempt accents from 2x limit").

## Why

The whole-picture underpainting is Toska's strength. Stage two — making the painting crisp — is where it goes wrong:

- **Edges look scratchy.** `paint_reference_edges` (`generateEdgePlan`, `reference-generator.mjs`) seeds a stroke at every
  pixel with 10% contrast, follows raw single-pixel gradients for at most about 16 steps, stops at 50-degree turns,
  paints two strokes per edge in single-pixel colours and shuffles them. On a painterly goal (brush texture, snow,
  reflections) that is thousands of short, paired, noisy dashes, magnified by the enlargement (4.1x on New Moscow).
- **Hand strokes fail.** In the Langfuse logs since 2026-10-10 (3,053 tool calls, 113 chats), typed-coordinate
  `paint_batch` is a third of all calls and Luna flags 39% of the checked ones (texture over forms, hard graphic marks,
  flat blocks, stripes); planned tools are flagged about half as often (edges 18%, `paint_pass` 20%).
- **Traced guides never helped a painting** and distracted the artist ("the traces are terrible and distracting
  compared to the solid underpainting").

The artist (2026-10-23): silhouettes come from paint, not lines; what makes a painting crisp is **accents**; remove
tracing; accents go on their own layer.

## Decided by the artist

1. **Remove visible tracing.** `draw_guide from_reference` (traced outlines, structure, lights, masses as guide lines),
   the traced block-in, the `/trace` command and its "/" menu entry, and the guided-trace skill's tracing guidance go.
2. **Stage two is "accents"** (the term the artist chose): small, high-contrast, deliberate marks.
3. **Accents go on their own layer** (one per accents move), so they can be kept or undone together.
4. Silhouettes and masses come from the underpainting's paint, never from outlines.

## Goals

1. **`paint_accents`**, one tool. The painter names an area (the whole picture, an element, a selection, a box) and
   which kinds and how many ("the 40 strongest city lights", "railing bars and lamp posts"). The host finds and places
   them; the painter types no coordinates. Kinds:
   - **lights**: small bright spots (windows, lamps, stars, a moon's rim) — a dot, optionally with a soft halo;
   - **lines**: thin straight or gently curved features (railing bars, posts, masts, the spire, window frames) — one
     smooth stroke each, tapered;
   - **glints**: small sharp highlights (wet road, snow, chrome, water) — a short tapered stroke along the
     highlight's direction;
   - **darks** (the darkest small accents: gaps, deep shadows under objects) — a short stroke or dot.
2. **Found in the reference, painted at canvas resolution.** An accent needs position, colour, size and a sharp brush,
   so it survives enlargement: positions and colours come from the reference (or an aligned close-up), each mark is
   painted crisply at the canvas's own resolution with a sharp preset. The tracer merged on 2026-10-23
   (`trace_edges`: full resolution, smoothed, coherent lines; outlines from shapes) becomes the finder for **lines**;
   lights, glints and darks come from local contrast in the reference.
3. **Colour by role**: lights and glints from the reference's brightest core (not an averaged neighbourhood, which
   dulls them); darks from its darkest core; lines from the line's own colour along its length.
4. **Size and order**: marks sized from the feature's size on the canvas (with a sensible minimum and maximum),
   strongest first, capped per call; the move's layer is named for its accents.
5. **Painter guidance**: after the underpainting, crispness comes from `paint_accents`; long `paint_batch` runs and
   scratchy edge passes are not the way to finish.

6. **Accents are exempt from the 2x stretch limit** (the artist, 2026-10-23): an accent is a position, a colour and a
   size, painted crisp at canvas resolution, so enlargement does not blur it; the limit stays for texture transfers.
7. **The underpainting move ends when the transfer finishes** (the artist's fix 1): in a move whose step is the
   whole-picture underpainting, the host closes the move as soon as the whole transfer completes; no hand strokes or
   other painting follow inside that move. Live chat 34deca0e (2026-10-23): after a clean 39,918-stroke transfer the
   painter added about 177 typed strokes in the same move until the size limit stopped it.
8. **A goal-likeness check** (the artist's fix 2): with a goal reference, the host measures how close the canvas is to
   the goal before and after every painting batch (the whole canvas and the batch's area, at a scale where brushwork
   texture does not count). A batch that makes the canvas clearly less like the goal is undone by the host and the
   painter is told what got worse and where; accents (small by design) and deliberate artist-requested departures
   ("make the sky warmer than the reference") are measured but not undone. In 34deca0e Luna reported "no regressions"
   for every damaging batch: it judges how strokes look, not whether the painting moved away from the goal.

## Non-goals

- No outlines of masses, no paired edge strokes, no texture edges as accents.
- No invented detail: accents mark what the reference shows (faces and hair still need a close-up or a sharper goal).
- The reference transfers stay (the artist's rule: reference tools stay).

## Anti-goals (a failure even if it "works")

- Accents that read as a uniform sprinkle of dots or scratches over the whole picture.
- Lines that look traced (even width, hard start and end, following every wobble).
- Accents that dull the underpainting's colour (averaged, greyish lights).

## Constraints

- Real Krita brushes through `Node.paintStrokes`; no pixels placed from outside Krita, no image layers.
- Fork-first; plugin code via `qt_compat` (PyQt5 and PyQt6); new companion modules strict TypeScript.
- Shapes model only with the artist's consent and never prompting from an automatic step.
- Live tests on copies, never the artist's `new_moscow` folder.

## My calls (the artist can overrule)

- **Kept**: hand-placed guide lines and perspective in `draw_guide` (no reference tracing), only when the artist asks,
  since they are not tracing; the mass-map summary and panel thumbnail (invisible analysis); `trace_edges`'s interior
  structure chains as the finder for **lines**.
- **Lines never come from outlines**: only thin interior structure (bars, posts, masts, the spire, frames), never a
  shape's or mass's boundary, so the shapes model is not needed and never asked for by this tool.
- **Choosing which accents** is by area (whole picture, element shape when already allowed, selection, box) plus kind,
  count and strength; no object recognition per accent.
- **Layer**: one accents layer per move; later `paint_accents` calls in the same move add to it.
- **Canvas changed since the underpainting**: an accent is skipped where the canvas under it no longer resembles the
  reference there (moved or repainted), and never placed in a protected area; the result says how many were skipped.
- **Other changes amended by this one**: sharper-guides goals 2-4 lose their visible guide lines (the tracer and the
  mass map stay as analysis), element-shapes' `from_reference` with `shape` goes with tracing, and `layer-need.mjs`'s
  accents hint points to `paint_accents`; their proposals and tasks are updated in the same branch.
- **`paint_reference_edges`** stays available as a reference tool (the artist's rule), but the painter's guidance stops
  recommending it for finishing; accents replace it there.
- **Large batches**: when one call would place more than about 150 accents, the painter shows the count and asks
  before painting.
- Sharper-guides goal 1 (Krita perspective assistants) is parked.

## Done when

On a copy of the New Moscow folder, after the underpainting: one or two `paint_accents` calls add the city lights,
the lamp posts and railing bars, the spire tip and the wet-road glints on their own layer; Luna's move check shows no
stripes, ellipses or flat blocks; the artist calls it crisper. Checked on a portrait and a landscape too; time and
counts measured.

## Left to the builder

Detection methods and thresholds for each kind, the preset per kind (from the existing brush cards), halo rendering
with Krita presets, caps, and the exact schema names.

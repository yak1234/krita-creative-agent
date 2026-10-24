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
   *(Replaced by decision 7 below: the kinds are found as described, but adjusted in the canvas's own paint, not drawn as marks.)*
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

## Decided by the artist during the build (2026-10-23)

5. **Accents only where the canvas lacks them.** The reference (mapped onto the canvas) and the current canvas view are
   compared at fine scale (each one's detail: the plane minus its blur at the accent scale, in lightness plus chroma);
   the residual decides: a sharp light the canvas blurred away is a light or glint, a sharp dark it lacks a dark, a thin
   residual ridge a line. Nothing is added where the canvas has the accent already, or was repainted there. The finder
   decides only each mark's shape; its strength is the residual. Without a canvas view the finder refuses. This
   replaces the "canvas still resembles the reference" skip.
6. **Lights stamped from a real lamp in the reference, dot as fallback**: lights (and glints where it works) are stamped
   with a material cut from a real accent in the reference (the material stamp), today's dot and soft halo as the
   fallback.
7. **Accents adjust the painting's own paint with Krita's features, not marks** (supersedes 6 and the marks in goals
   1-3): no dots, strokes, needles or stamps. Where the residual (5) finds the canvas softer, duller or paler than the
   reference, soft (feathered) masks made from the found accents limit Krita's own filters on a copy of the canvas's own
   visible pixels: lights by Dodge (highlights; exposure from the strength) with a bloom (the same pixels blurred, Screen,
   low opacity); darks by Burn (shadows); lost detail (thin lines, edges) by Gaussian High Pass in Overlay. Nothing of the
   reference's pixels is placed on the canvas. Each call is one reversible pass: one Accents group of baked layers in
   the move's group (no live filter masks, so nothing recomputes on refresh). Material stamping stays its own tool.

## Decided by the artist after a live New Moscow chat (2026-10-23)

After an excellent underpainting, the folder plan's element steps made the painter repaint each element by hand (typed
`paint_batch` strokes, `stamp_material`): blobs, "hard graphic", "mechanical stripes". The goal likeness got worse
(ΔE 0.6 → 0.7) and was never undone, because element steps were measure-only. The artist approved three changes:

9. **The default folder plan is underpainting, then accents, then the artist decides.** Step 1 is the whole-picture
   underpainting from the goal image, step 2 is `paint_accents` on the whole picture (lights, darks, detail), and then
   the host asks the artist what to refine next, naming the elements not yet done. An element's step is added only when
   the artist asks for it, by name (the host adds the step and paints it, since the artist asked) or by adding the step.
   The element images stay attached as references.
10. **Element steps are judged against the goal.** The "folder element steps are measure-only" exemption is gone. Once a
    kept whole underpainting of the goal exists, an element step's batch that makes the canvas clearly less like the goal
    is undone like any other. Departures the artist asked for and accents stay exempt. With no goal underpainting yet,
    an element step is measured only.
11. **Typed strokes are capped after the underpainting.** Once the canvas has a kept whole-picture transfer, an Agent
    move's typed-coordinate call (`paint_batch` summed over its actions, `paint_pass`, `painting_toolbox` strokes and
    shapes, `paint_contours`, `stamp_material` dabs) is refused before it paints if it has more than **12 marks** or a
    mark wider than **2% of the canvas's long side**. `paint_recipe` and toolbox flood fills, clears and gradients
    (broad coverage) are refused too. The cap lifts while the artist's latest typed message asks for hand-painted work
    ("hand-paint", "by hand", "freehand", "your own strokes"); Keep, retry and plan steps inherit that answer. The
    refusal points to `paint_accents` or to asking the artist.

    Why these caps: 12 marks is a handful of corrections (a glint, a post, a window edge), well below the 4-8 action
    batches of 20-256 strokes that repainted elements. 2% is a detail brush (120 px on 6000 px, 20 px on 1024 px). The
    blobs and stripes came from brushes several times wider. Fills, filters, layers, transfers and accents are not
    typed strokes, and the goal-likeness check still judges them.

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

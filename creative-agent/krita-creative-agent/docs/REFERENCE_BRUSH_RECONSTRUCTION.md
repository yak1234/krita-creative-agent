# Reference-assisted native painting: working notes

Recorded 14 September 2026 after the user accepted the finished faces-and-shawl study. The original note recorded a reusable method and implementation proposal; subsequent implementation status is below.

Update: the user subsequently authorized gaps 1, 2 and 4. The reference-driven generator, refinement workflow and resumable chunk integration are now implemented and installed pending restart. See [implementation and validation status](REFERENCE_PAINTING_IMPLEMENTATION.md). The historical recipe and proposal below describe the evidence that motivated that implementation; critic improvement remains separate.

## What actually succeeded

The successful finish was a **reference-sampled brush reconstruction**. A local Python program read the attached reference, computed short colored strokes, and sent them to Krita's native brush engine. Codex selected the approach, scales and focal regions, inspected the actual canvas between passes, and managed the files. The Creative Agent did not execute this successful run.

This distinction matters: the preceding manually authored contours were too simplified and the user rejected them. The successful method transferred the reference's spatial color information. It did not solve facial anatomy by independent drawing, nor did the language model individually invent 95,660 accurate strokes. The earlier manual layers remain underneath, but the reconstruction covers them; their drawing was not necessary to the final likeness.

Evidence:

- [Accepted layered artwork](../../projects/moonlit-canal/faces-and-shawl-finished.kra) and [matching PNG](../../projects/moonlit-canal/faces-and-shawl-finished.png).
- [Original reference](../../projects/moonlit-canal/reference-board/original.png), [native Krita crop](../../projects/moonlit-canal/reference-board/faces-and-shawl.png), and [coordinate mapping](../../projects/moonlit-canal/reference-board/regions.json).
- [Whole-image renderer](../../projects/moonlit-canal/.painting-process/reference_brush_finish.py) and [focal renderer](../../projects/moonlit-canal/.painting-process/reference_focus_finish.py). These are historical execution scripts, not safe general-purpose agent tools.
- [Rejected manual result](../../projects/moonlit-canal/.painting-process/stage-04-light-edges.png), [coarse reconstruction](../../projects/moonlit-canal/.painting-process/07-tonal-reconstruction.png), [fine reconstruction](../../projects/moonlit-canal/.painting-process/08-fine-materials.png), and [focal finish](../../projects/moonlit-canal/.painting-process/09-faces-and-hands.png).
- Each reconstruction pass has its complete `*-commands.json` receipt beside the script. The saved KRA's embedded merged image was verified pixel-for-pixel against the final PNG, at 900 × 900.

## Exact recipe used

1. Inspect the live Krita document, original reference and crop. Preserve existing work. The source crop was 600 × 600, taken in Krita from original bounds `[100,240,700,840]` (xyxy). The painting was 900 × 900. Thus `canvas = crop_coordinate × 1.5`.
2. Read the crop's RGB values locally. The scripts did not import the reference raster as a canvas layer or write a reconstructed pixel buffer into Krita. They used its values to author native brush commands.
3. Make one new named layer per scale. Select the exact preset `b) Basic-2 Opacity`, with opacity and flow 1.
4. Generate a jittered grid of sample centers. Jitter each axis by up to `0.22 × step`; use the deterministic seed `714 + int(step × 10)`. Shuffle stroke order to avoid a visible scanline progression.
5. For the first two passes, average the reference neighborhood with radius `max(1, int(step × 0.38))`. Approximate the local RGB-mean gradient with differences across that neighborhood. Above the gradient threshold, orient the stroke perpendicular to the gradient; otherwise use a seeded random angle. This is a simple tonal heuristic, not semantic contour recognition.
6. Each mark is a short two-point native path: source-space length `step × 0.42`; canvas brush diameter `step × 1.5 × 1.50`; opacity 1. The extra width overlaps neighboring samples. Coordinates are scaled to canvas space.
7. Send sequential raw bridge batches of 100 strokes. Save the native file and a review PNG after each completed scale, then inspect the actual image before choosing the next scale.

| Pass | Source-space sample step | Canvas brush diameter | Coverage | Strokes | Recorded execution time |
|---|---:|---:|---|---:|---:|
| 07 · Tonal reconstruction | 6 px | 13.50 px | Entire crop | 10,000 | 146.8 s |
| 08 · Fine materials | 2.5 px | 5.62 px | Entire crop | 57,600 | 550.1 s |
| 09 · Faces and hands | 1.2 px | 2.70 px | Three focal rectangles | 28,060 | 285.6 s |

Total: **95,660 native strokes**, approximately **16 minutes 22 seconds of recorded pass execution**, excluding preparation and review. These timings describe this run and machine, not a performance guarantee.

The focal rectangles were `[128,151,240,270]`, `[430,94,547,228]` and `[140,409,243,520]`, in crop-space xyxy coordinates. They cover the woman's face, man's face and hands. The focal script sampled a single pixel (`r=0`), so its gradient calculation is zero and its stroke angles are random. Do not describe that pass as edge-following. These coordinates belong only to this crop.

## Why this looked better

The color-to-position mapping carried the reference's proportions, facial modeling, folds and irregular pattern into the painting. Smaller marks recovered details that coarse marks could not resolve. The focal pass sharpened expressions and fingers while leaving the surroundings broader. Visual inspections prevented the coarse pass from being mislabeled as finished.

The output remains softer and more stippled than the reference, particularly in hair, fabric and architecture. It reproduces this crop; it does not recreate the entire canal scene. User acceptance establishes success for this delivered result, not general artistic competence or generalization to unseen references.

## What the Creative Agent already has, and what it lacks

Source inspection for this note: `src/tools.mjs`, `src/recipe-tool.mjs`, `src/contour-tool.mjs`, `src/prompt.mjs`, and the product plan. This is a source audit; it does not verify which build a running Krita instance has loaded.

| Area | Existing capability | Missing piece for this method |
|---|---|---|
| Native painting | `paint_pass`, `painting_toolbox`, layers, brushes, selections and saving | The execution primitive exists; a new MCP transport is not the main need |
| Reference access | `view_reference` delivers an attached image and dimensions | A structured reference sampler and persisted source-to-canvas transform usable by a local renderer |
| Sampling | `sample_canvas_colors` reads up to 16 destination points | Bulk reference sampling tied to an authorized attachment, with explicit color and alpha handling |
| Procedural authoring | `paint_recipe` expands a compact recipe locally and executes journaled chunks | It uses a supplied palette and does not sample references; it needs a separate reference-driven generator |
| Drawing | `paint_contours` fills model-supplied outlines | It does not discover anatomy, trace references or infer accurate contours |
| Scale and attention | The agent can plan stages and inspect canvas regions | A repeatable coarse-to-fine reconstruction recipe, with focal regions and quality controls |
| Critique | A stage reviewer and stronger construction instructions exist | The earlier run still passed bad silhouettes; reliable matched-image evaluation has not been demonstrated |
| Long runs | Recipe operation IDs, chunk journals, cancellation checks and fault handling exist | Integration of the new generator without losing these contracts or creating hundreds of visible layers |

The failed agent used generic geometry and texture where spatially accurate construction was needed. The successful renderer supplied that spatial accuracy computationally. More prompting or a different model might help judgment, but neither is evidence that the missing renderer exists. Likewise, reference reconstruction does not provide independent composition or anatomy skills.

## How an agent should perform this

The model should choose the objective, reference, target mapping, brush, scales, focal regions and review criteria. A deterministic local renderer should calculate the thousands of marks. Krita should render them. The critic should inspect the resulting images and identify the next concrete correction.

Proposed tool, **not implemented**: `paint_from_reference`.

Its compact request should contain an attached `reference_id`, a source rectangle, target transform, optional region mask, verified preset, sample step/brush controls, seed and pass name. The host should bind the document identity and revision. It should not accept arbitrary file paths from the model or require the model to output a giant coordinate list.

Suggested agent loop:

1. Establish whether the user wants faithful reference reconstruction, a stylized interpretation, or original invention. Infer from clear context; ask only when the distinction is unresolved and consequential. Make the selected method visible.
2. Read the reference and live target, establish the transform, and protect existing layers. Request an actual reference crop when needed; viewing a downscaled overview is insufficient for focal details.
3. Run a small representative preview on a reversible layer to verify brush behavior, mapping and expected texture. Then execute the approved task scope without asking permission for ordinary batches.
4. Render the coarse pass locally in bounded chunks. Observe the actual result. Continue to the fine pass when the mapping and coverage are correct; do not expect coarse dots to contain finished eyes.
5. Inspect matched reference/canvas closeups. Refine the focal regions and visible residual errors. Use image differences only as supporting evidence for a faithful reconstruction; they are not a beauty score and are inappropriate as a universal objective for original art.
6. Review pose, expression, hands, material texture and protected regions against the user's requirements. Distinguish a successful tool call from a successful image. Label reviewer approval as ready for user review.
7. Save the layered result and export, verify they agree, and record the method and remaining differences honestly.

## Integration work before shipping

Reuse the agent's native transaction and operation-receipt system. Do not simply expose the raw experimental scripts as a production tool. They check the filename only at startup, clear selection, have no controller cancellation hook, and save only at scale completion. A lost response cannot safely be retried from their stroke list alone. Their seeds make command generation repeatable, not every possible brush engine/preset bitwise deterministic.

Persist the reference content hash, transform, generator version, seed, brush configuration, stroke plan and acknowledged chunk IDs. Check the pinned target and allowed region before every chunk. Pause on a document switch, conflicting manual edit or unknown outcome. Restore selection state. A resumed operation must reconcile receipts rather than repaint an uncertain chunk.

Use one understandable pass group with recoverable chunk ownership. The current recipe creates a layer per chunk; applying that unchanged to 95,660 strokes would create roughly 374 layers. Preserve reversibility without overwhelming the layer stack. Show real stroke progress, pause state and elapsed time; do not equate stroke percentage with artistic completion.

Improve the prototype where useful: adaptive sampling around residual errors, meaningful edge estimates independent of sampling radius, feathered focal boundaries, fewer redundant strokes, validated color management, and brush-specific calibration. These are proposed improvements, not things the accepted run already did.

## Acceptance evidence to collect

- Run this method through the Creative Agent itself on a separate canvas, with no external script driver or manually supplied stroke list. Record model, loaded component builds and actual images.
- Confirm correct crop mapping, aspect ratio, region protection and preservation of original artwork.
- Test pause/resume, document switching, interrupted dispatch and recovery without duplicated strokes.
- Keep the rejected ellipse study as a negative review example: the critic must identify its missing construction rather than pass it for color placement. Review coarse/fine/focal results using the requirements of their actual stages.
- Try additional references before claiming generalization. Evaluate faithful reconstruction separately from original painting.
- Verify the final native file and export, and have the user assess the visual result. Documentation and unit tests alone do not establish this capability.

## Reminder for future Codex sessions

Read this note and the project's brief before repeating the method. Inspect the original, crop and live canvas; do not reuse these coordinates for unrelated artwork. The existing scripts are evidence, not an invitation to replay them onto the finished document. The finished file has a different name from their startup guard. Preserve the accepted artwork and conduct future agent evaluations on separate copies.

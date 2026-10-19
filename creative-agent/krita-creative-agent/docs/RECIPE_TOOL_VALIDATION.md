# Generated native painting recipes — candidate 021

13 September 2026. Implemented and installed build `d7eb8663c57b6188b0896bb7d4e711d25b407c125b86ef916162fbb76749e715`.

## Change

`paint_recipe` expands a compact, validated recipe into native cubic strokes with seeded placement, size/opacity/length variation, directional wander, cross-strokes and clustered overlap. It submits the generated curves through the existing `paint_pass` path, including document identity, operation IDs, saving, review records, stage constraints and Stop. Individual painting tools remain available. Parallel preparation workers may propose recipes too.

The generator produces commands locally; model output does not contain thousands of coordinates. Only the final image and compact batch receipts are returned to the model, while intermediate images update the panel. A broad stage region no longer overwrites a tighter requested painting region: the two are intersected.

This first version intentionally uses existing contribution semantics: up to 256 curves per saved batch, a new named layer for each, and one operation counted per batch. It does not implement a single layer across chunks, deferred saves, arbitrary code execution, reference sampling or a brush knowledge catalogue. Rectangle clipping can produce a visibly straight boundary; choose the region accordingly.

## Evidence

- Full Node test suite: **88 passed, zero failures**. Installed files for all six changed/new runtime modules match the tested source.

- Generator tests cover deterministic seeds, seed variation, valid native geometry, palette/range preservation, irregular placement, cross-strokes, small/asymmetric regions and invalid inputs.
- Tool tests cover 1,200 strokes in five batches, compact durable receipts, duplicate-call replay without repainting, Stop after the first batch, unknown results and Ask/Plan exclusion.
- A Pi SDK/controller regression invokes `paint_recipe`, dispatches all five native batches, performs one stage review and reaches completion. It verifies that the tighter recipe clipping region survives a broader stage region. The provider/native implementation is simulated in that test.
- A separate live native test used `scripts/evaluate-recipe.mjs` with the real Krita bridge and the same registered tool implementation. It made 1,200 native Chalk Grainy strokes on a separate 640 × 480 swatch document in **16,046 ms**, including all five native saves and previews. This time excludes model calls and is not a general performance guarantee.
- A second live execution requested 600 strokes and set Stop after the first native operation returned. Exactly 256 strokes completed; subsequent chunks were not dispatched. This exercises the tool's Stop flag at the native boundary, not a human pressing the panel button during painting.
- The saved preview changes 468,682 pixels. No changed pixels occur outside the requested rectangle plus a two-preview-pixel resampling margin. The output has uneven overlapping pigment, not regular horizontal rows; it is a functional swatch, not a finished artwork.
- [Rendered 1,200-stroke swatch](review-evidence/recipe-tool/native-1200-strokes.png) and [native execution record](review-evidence/recipe-tool/validation.json).

## Installation and artwork preservation

Built with the existing standalone Node 22.23.2 distribution and pinned dependency tree. The native plugin payload was taken from the existing installed plugin to retain the previously discovered installed-only `fill_selection` extension; this change does not remove or newly validate that extension. Release inventory hashes cover the resulting payload.

Installed through the existing release installer, which retained a backup. Activated the panel through Krita Scripter using the existing reload script, without restarting Krita. The live bridge reports the new build ID and Krita 5.3.3; the running companion process uses the matching new release. The refreshed panel is Ready in Ask mode with the original `warm_color_fields.kra` attached. Its document ID is unchanged and `modified` is false. The saved test document was closed and the artwork returned to the foreground.

Computer use: closed the saved test document and ran the existing panel-reload script through Tools → Scripts → Scripter. No model/provider request was made during the live native test or activation.

## Remaining validation

Test a real provider choosing and revising recipes from ordinary-language artistic instructions. Judge the artwork, not only execution counts. The current swatch and simulated SDK test establish native delivery and orchestration separately; they do not establish autonomous artistic completion through the panel.

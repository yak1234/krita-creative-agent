# Reference painting implementation — 14 September 2026

Implemented the requested reference generator, refinement workflow and large-pass execution. Critic behavior was not changed in this pass.

## Using it

After loading the updated plugin, attach a reference and ask Agent to reconstruct it with native brush strokes. Keep the reconstruction in one planned stage. The agent chooses source and target rectangles with matching aspect ratios, a verified brush preset and optional focal regions. It starts `paint_from_reference`, inspects its returned images, and calls `continue_reference_painting` until the job is complete. `list_reference_paintings` finds saved job IDs after a restart.

This is reference-assisted reconstruction, not independent drawing. It is separate from `paint_recipe`, which remains available for palette-based coverage and texture.

## Implemented behavior

- The host resolves an attached reference inside the study, hashes its bytes, and asks native Qt to decode it without opening or editing a document. Tagged inputs are converted to sRGB; untagged inputs are assumed sRGB. PNG/JPEG/GIF inputs use the decoder's first image, without automatic orientation transformation. Limits: 5 MB encoded file size and four million decoded pixels.
- A local generator produces seeded, jittered native brush curves from spatial reference samples. It averages premultiplied color/alpha, skips transparent samples, follows a local luminance-gradient tangent where available, and bounds geometry to the target. Source and target aspect ratios must agree.
- Defaults are source-pixel sampling steps `[6, 2.5, 1.2]`: coarse, fine and optional focal detail. Focal rectangles select sampling centers; brush footprints can overlap their edges. The target and stage region clip the complete footprint. Recipes are limited to 200,000 estimated samples.
- A generated stroke plan and manifest persist source hash, recipe, generator version, plan hash, scope, progress, layer identity, last canvas revision and any pending operation ID.
- Each dispatch contains at most 128 strokes and checkpoints through the existing native transaction path. The tool returns at a saved boundary after approximately 45 seconds or after a scale completes. The controller can continue without user confirmation for ordinary work. Stop/abort prevents the next chunk; it does not interrupt a native chunk halfway through.
- Each scale uses one owned paint layer inside the existing stage group. Continuations validate ownership, layer state, stage and region before reusing that layer. The visible pass list consolidates its chunks. Native chunk receipts omit redundant historical pass lists to keep recovery storage from growing quadratically.
- A stopped job continues from its persisted offset. For a dispatched chunk whose acknowledgement was lost, the host reads the authoritative native operation receipt first. A committed chunk is counted without repainting it. An absent receipt can be dispatched with its original ID after revision checks. A partial or uncertain receipt blocks continuation; it is never treated as permission to repaint.
- Resume checks source/plan hashes, dimensions, original planned stage and current canvas revision. A changed canvas is preserved and blocks that job; there is no automatic merge over manual edits. Changing the planned stage requires a new job rather than silently extending its scope.
- Each completed scale returns the actual canvas image for inspection before the next refinement scale. This uses the existing painter and reviewer; it does not add or validate a better critic.

## Source

- [Reference generator and schema](../src/reference-generator.mjs)
- [Persistent tools and execution](../src/reference-tool.mjs)
- [Native image decoding](../../krita-mcp/krita-plugin/kritamcp/creative_reference.py)
- [Native continuation and receipt handling](../../krita-mcp/krita-plugin/kritamcp/creative_tools.py)
- Registration and mode/controller integration: `src/tools.mjs`, `src/studio.mjs`, `src/runtime.mjs`, and painter guidance in `src/prompt.mjs`.

## Validation and release state

- 99 Node tests and 58 Python tests passed. The Node suite includes the full Pi/Studio reference-workflow test and recovery using a freshly constructed tool instance.
- Tests exercise spatial colors, deterministic generation, mapping, invalid geometry/work limits, transparent input, scale boundaries, same-layer continuation, cancellation, replay, committed lost acknowledgements, uncertain outcomes, changed references/canvases, read-only modes, native selection restoration and review ownership.
- The Pi integration test uses the real SDK/controller with simulated provider/bridge responses. It checks tool discovery, native revision propagation, four chunks across three scales, and review after reconstruction. It is not real-provider artistic validation.
- Installed release: `1cda2b8dabf4d1b23eefa55403161b4f06eb5afe24687535e4106cb4b1359c10`. Staged SDK import and release integrity checks passed. Backup: `~/Library/Application Support/krita/.creative-agent-backups/20260914T064740.806662Z`.
- The running Krita document had unsaved changes. It was not saved, closed, restarted or painted into during implementation. The installed update requires a Krita restart before the current UI/bridge can use it.
- An isolated `kritarunner` probe could not import the test module; this produced no native painting validation. Actual Qt image decoding and same-layer continuation in the updated live Krita bridge remain acceptance checks. No claim of a completed autonomous portrait is made.

Next live check: after the user saves their changes and restarts Krita, verify matching loaded build IDs, run a small reconstruction on a separate canvas, pause/resume it, inspect all scale images and verify the layer count and saved artifact. Then evaluate a realistic reference through the actual model route. Preserve the accepted faces-and-shawl artwork.

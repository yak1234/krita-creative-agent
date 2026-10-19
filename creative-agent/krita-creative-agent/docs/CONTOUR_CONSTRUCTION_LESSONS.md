# Direct Krita construction study — 14 September 2026

Historical checkpoint: the user rejected this manual result as unfinished. A later reference-sampled reconstruction was accepted. Read [the finishing method and agent gaps](REFERENCE_BRUSH_RECONSTRUCTION.md) for the current outcome; it does not validate independent contour drawing.

The moonlit-canal agent trial produced generic overlapping ellipses after 28 passes. Its stage reviewer approved the block-in from broad placement and values despite missing subject contours. The user rejected it. The run was stopped, preserved and subsequently shut down without restarting painting.

## Direct painting evidence

The manual checkpoint is preserved in [stage-04-light-edges.png](../../projects/moonlit-canal/.painting-process/stage-04-light-edges.png). Its six authored painting layers remain underneath the later reconstruction in the layered artwork. The `direct-painted-study.kra` and matching PNG were subsequently updated and are no longer snapshots of this manual-only checkpoint. Four process screenshots and all native commands are in the project's `.painting-process/`; crop coordinates and canvas mapping are in `reference-board/regions.json`.

For this historical manual checkpoint, authored contours and curves were rendered through Krita's native brushes without reference sampling. This statement applies only to layers 01–06, not the later finished reconstruction. Polygon selections filled with Basic-2 Opacity paths established silhouettes and planes. Curves established facial landmarks, hair, fingers and cloth; Airbrush Soft softened selected transitions.

Observed improvement: recognizable figures, explicit profiles/features, readable hand gesture and shawl/coat overlap. Remaining problems: graphic/stylized rather than realistic oil painting; edges too hard, hair highlights too ribbon-like, cloth pattern too regular, incomplete likeness. This is a construction demonstration, not the completed visual target or proof of autonomous agent improvement.

## Changes derived from the experience

- `paint_contours` takes 1–32 ordered outlines and colors, filled by native brushes in one reversible toolbox contribution. It removes selection/fill/clear plumbing; the model still supplies the drawing.
- Validates the whole request before dispatch: bounds, enclosed area, repeated points and crossing/touching nonadjacent edges. Uses existing toolbox operation IDs, saving, stage masks, selection restoration and unknown-outcome handling.
- Painter instructions distinguish structure from surface work and require reference-specific contour, axis and overlap relationships. Random recipes are not an anatomy tool.
- Reviewer instructions reject color/bounding-box matches as sufficient silhouette evidence and distinguish construction, current-stage development and requested finish. Later-stage detail deferral remains valid, but cannot excuse incorrect foundational geometry.

These reviewer changes are instructions, not a deterministic likeness detector. A new real-provider comparison on a separate study is required before claiming improved autonomous visual judgment.

## Validation

All 94 Node tests passed. Added coverage verifies concave contours, whole-request rejection, bounds, operation-ID forwarding, Ask/Stop restrictions and unknown outcomes without retry. Existing SDK discovery and stage/recovery checks also pass. The native selection-and-brush technique was exercised directly in the painting; live agent invocation of the new wrapper remains a separate pending acceptance check.

Installed candidate build `8fc248ef6246b5f349a9c1b61e6e0c866b5986e24dec73084b3d3d78571eebfb` with verified release installer and backup `~/Library/Application Support/krita/.creative-agent-backups/20260914T043428.431017Z`. Staged SDK import passed. Restart required; running Krita was not restarted.

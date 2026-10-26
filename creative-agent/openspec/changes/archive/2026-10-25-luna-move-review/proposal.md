## Why

In five clouds tests on New Moscow, Agent mode looked right halfway through a move and then made it worse before the
move ended: a flat rectangle over the clouds, a seam, and twice **the moon painted over** by a broad final pass. The
painter cannot see its own regressions, and Luna's before/after check, which already runs in Autopilot, never runs in
Agent mode: `afterPainting` returns before it. Method scores missed it too (clipped, blended strokes are not a
"stroke mass"), so tests need an image verdict as well.

## What Changes

- **Luna reviews every painting batch in Agent mode**: it compares the canvas before and after the batch with the
  request, with the existing artifact checks (hard join, flat block, stripes…) plus two new ones: a focal feature
  that is gone or covered, and texture laid over forms that were there before.
- **Focal features are protected areas.** The painter proposes one for each feature that must survive (the moon,
  the figures) with `propose_protection`; the artist keeps it in the panel, and kept areas already stop any pass from
  changing them. Luna also checks every kept area's feature by name after each batch.
- **A batch that made things worse is undone automatically** (Luna mode Guide), and the painter is told what was
  lost and where, then continues differently. Evaluate only records; Off does nothing.
- **The move card shows Luna's verdict** in one line ("Luna: moon kept, no new seams" or what it undid).
- **Tests read the verdict**: the test driver reports Luna's verdict per batch beside the tool-choice methods.

## Capabilities

### New Capabilities
- `luna-move-review`: Luna's per-batch review in Agent mode, focal features through protected areas, automatic
  undo of a regression, the verdict on the move card and in tests.

## Impact

- Companion: a Pi extension `extensions/luna-review.ts` (strict TypeScript, inline), new check questions in
  `visual-check-questions.json`, a typed check in `visual-checks.ts`, wiring and the move card verdict in
  `studio.mjs`, the painter prompt and skills (propose protection before broad passes).
- Test driver: the verdict in `creative_test_state`; a test-only way to keep a proposed protected area.
- No plugin change: undo uses `review_pass`, protection already enforces kept areas.

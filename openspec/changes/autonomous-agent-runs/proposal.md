## Why

The artist wants Agent runs to work through to a finished painting without human review mid-run. Luna's visual checks and automatic recovery now cover what the stops were for, and Stop is the backstop. Across 23 saved studies, stage gates were not where runs got stuck: 25 reviews passed and 173 failed, and the failures piled up inside a single stage (Twilight: 329 passes, never left stage 1; Victorian "Refine": one stage, 41 failed reviews). Stages added a review call per stage and several stopping points without fixing the stalls.

## What Changes

- **Plan steps become a suggested painting order.** No per-step review, `stop_after`, `max_operations` or step `region`. Saved plans carrying these fields load with them removed.
- **One independent review of the final requirements.** The host derives completion from the checks (all met → complete, otherwise continue). The `needs_input` verdict and deferral to later stages are removed.
- **No mid-run stops for the artist:**
  - the painter cannot ask questions while painting;
  - repeated failed reviews change strategy every third repeat instead of pausing at five;
  - uncertain actions in a row change strategy every third instead of pausing at five;
  - an outside canvas edit is recorded as a direction to keep it, instead of a pause;
  - the stage-boundary and stage-limit pauses and the "Next stage" button are removed.
- **Unchanged:** Plan-phase questions, Start painting, requirement-change acceptance, Stop, time and pass allowances, and pausing when the canvas cannot be observed after an uncertain action.
- **The panel's "Stages" editor becomes "Painting order"** (title, what it achieves, optional focus).

## Capabilities

### New Capabilities
- `autonomous-agent-runs`: Agent runs paint to completion without mid-run human review; plan steps are an order, not gates.

### Modified Capabilities
None (no archived specs exist yet). This supersedes the runaway pauses in the unarchived `luna-visual-decisions` change, whose spec text is updated to match.

## Impact

- `krita-creative-agent/src/studio.mjs`: brief schema and `normalizeBrief`, `validateReview`, run loop, reviewer, tools, prompts.
- `src/prompt.mjs`, `src/reference-tool.mjs` (job scope is the plan revision).
- `plugin/kritamcp/creative_docker.py`: plan editor, export, status labels, execute button.
- Tests: `tests/studio.test.mjs`, `tests/recipe.test.mjs`, `tests/ui_smoke.py`. README.

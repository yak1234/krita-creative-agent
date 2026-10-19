## 1. Companion

- [x] 1.1 Brief schema: steps are `{title, done_when, scope?}`; add `normalizeBrief` and apply it on load, plan edit and propose_plan
- [x] 1.2 Replace `validateStageReview` with `validateReview`: final checks only, host-derived verdict, no `needs_input` or deferral
- [x] 1.3 Reviewer: criteria are requirements plus completion checks; no stage crop or stage contract
- [x] 1.4 Run loop: remove stage advance, stop_after, stage limit, needs_input and five-repeat pauses; strategy change every third repeat
- [x] 1.5 Uncertain actions: strategy change every third in a row; remove the five-in-a-row pause
- [x] 1.6 Outside canvas edits become a recorded direction instead of a pause
- [x] 1.7 Disable `ask_question` during painting; update tool descriptions and prompts (studio, painter, reviewer, parallel workers)
- [x] 1.8 Reference jobs are scoped to the plan revision (older stage-scoped jobs still match)
- [x] 1.9 Remove `intersectPaintingRegions`

## 2. Krita panel

- [x] 2.1 "Stages" editor becomes "Painting order": remove region, stop and operation controls; drop retired fields on save
- [x] 2.2 Overview and export describe a painting order and final checks; remove "Next stage"; "Finished" status label

## 3. Tests and docs

- [x] 3.1 Update studio, recipe and UI smoke tests; add tests for one final review, legacy plans, no mid-run stops and repeated uncertain actions
- [x] 3.2 README: steps as order, no mid-run human review table
- [x] 3.3 Update `luna-visual-decisions` spec text for the removed runaway pauses
- [x] 3.4 Full suites pass; build and install the release candidate
- [ ] 3.5 Live: after a Krita restart, run an Agent plan on a disposable document to completion without any mid-run pause

Release candidate 037 `9ed4e5270fc8721b37fe2a635205b09e7e92d3ad963279a7bb49c40b36ff4e3a` installed 2026-10-09; plugin backup `~/Library/Application Support/krita/.creative-agent-backups/2026-10-09T08-57-27-997Z-69349`; source backup `krita-creative-agent/backups/pre-autonomous-runs/`. Suites: Node 129/129, UI smoke, Python 66, bridge 34.

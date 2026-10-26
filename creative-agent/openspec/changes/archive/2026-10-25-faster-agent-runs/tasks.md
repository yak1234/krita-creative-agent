## 1. Measure

- [x] 1.1 `scripts/benchmark-run.mjs <chat-id>` reports minutes per category, painter calls and tokens, and review results from Langfuse. Verified on chat `298709b6`: 76.2 painting minutes, 295 painter calls, 62.1 minutes of painter calls; saved to `docs/benchmarks/baseline-starry-night.json`.

## 2. Lean context and cheaper saves

- [x] 2.1 `modelResultText` and `keepRecentImages` in `src/tools.mjs`, with the transform wired in `src/runtime.mjs`. Verified by the "host bookkeeping" test and the updated layer-index test.
- [x] 2.2 Deferred checkpoints, the `checkpoint` operation and `end` flushes in `creative_tools.py`, plus companion flushes before review and at run end. Verified by `test_painting_actions_save_every_few_actions_not_every_action`.

## 3. Batching

- [x] 3.1 `paint_batch` in `src/tools.mjs`, enabled in Agent mode, with batch-first painter prompts. Verified by the paint_batch test: whole-batch validation, stop at the first failure, one image, operation ids within 100 characters.

## 4. Decision-model pacing

- [x] 4.1 `src/pacing.mjs` and `StudioRuntime.afterPainting`: step advance, host-called review, stall note, `route` decisions recorded, `record_progress` hidden in Guide mode. Verified by `tests/pacing.test.mjs` and the studio pacing test.

## 5. Acceptance

- [ ] 5.1 After a Krita restart, run Starry Night on a disposable document in Guide mode. Run the benchmark on that chat, and verify ≤ 20 painting minutes, ≤ 60 painter calls, and review results ≥ the baseline's best (5/11). Record the result in `docs/benchmarks/`.
- [ ] 5.2 In the same run, verify that batches appear in the pass history, Reject pass works, Stop is immediate, and the `.kra` has every action after the run ends.

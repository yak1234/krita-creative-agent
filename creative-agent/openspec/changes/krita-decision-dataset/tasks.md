## 1. Prove the row format in Unsloth on Colab first

- [ ] 1.1 Hand-write 3 sample rows: one `review-check`, one `pass-keep` with two images, and one `progress` `score`. In a Colab notebook (NVIDIA GPU, latest `unsloth` + `unsloth-zoo`), load them with `FastDecisionModel.build_dataset` on `unsloth/Qwen3.5-0.8B` as Clef. Verify 0 rows are skipped. Record the Unsloth versions in the change notes.
- [ ] 1.2 In the same notebook, check whether that Unsloth version passes row `images` on CUDA. Verify by inspecting `_clef_items` in `unsloth/models/decision.py`; on 2026-10-09 it calls `encode_record` without a processor or images. Record the result. If images are passed, the rows train with images; otherwise they train on text state only, and images stay in the export for later.
## 2. Decision recorder

- [x] 2.0 Artist confirmation in Langfuse, pulled forward at the artist's request. `scripts/dev/langfuse-annotation.mjs` creates the `artist-verdict` BOOLEAN score config and one annotation queue (the Hobby plan allows one), "Krita · confirm decisions". It fills the queue with 150 sampled review checks, balanced met/unmet, as `decide-review-check` traces with the canvas, plus Luna hard-graphic flags and as many unflagged passes, as `decide-pass-failures` traces with before and after images. Re-runs top up the queue; what was sent is tracked per project. Verified 2026-10-09 in Corpus_NLP / krita: 155 decision traces, all top-level, all with images, 155 queue items.

- [ ] 2.1 (Partly done for 2.0: ids, bounded state, `review-check` and hard-graphic builders, tests.) Complete `src/decision-records.mjs`:
  - deterministic decision ids;
  - the text-state builder (≤1,500 characters, per design §4);
  - image downscaling to a ≤1024 data URI;
  - question builders for `review-check` and `pass-keep`.

  Verify with unit tests for ids, the state cap and the question shapes.
- [x] 2.2 Add `recordDecision()` and `scoreDecision()` to `LangfuseTracing`: one `event` trace per decision via `createTraceId(decision_id)`, in the chat session, and `artist-verdict` BOOLEAN scores by recomputed trace id. Failures are swallowed and recorded in diagnostics. Verify with fake-Langfuse tests: same id → same trace id, and the session is set.

## 3. Record decisions in the Creative Agent

- [ ] 3.1 After each review, record one `review-check` decision per check: the canvas image, the check text, and the reviewer's answer (`answered_by: reviewer`). Verify with a studio test: a 2-check review yields 2 decisions with the reviewer's met values.
- [ ] 3.2 On each committed pass with before and after images, record a `pass-keep` decision (no answer yet). This happens in every Luna mode. Verify with a studio test with Luna Off.
- [ ] 3.3 On `pass_review` with `action: 'reject'`, score `artist-verdict = false` on that pass's `pass-keep` decision. Verify with a studio test: reject → score targets the recomputed trace id.
- [ ] 3.4 Record `pass-failures`, `route` and `progress` decisions from the existing Luna calls, with Luna's probabilities and `answered_by: luna`. Do this only when Luna is not Off. Verify with tests using a fake Luna client.
- [ ] 3.5 Run the full Node suite, the UI smoke test and the packaging tests, and verify they all pass.

## 4. Export

- [ ] 4.1 Add `scripts/export-decisions.mjs`:
  - reads `decide-*` observations and `artist-verdict` scores via `@langfuse/client`, for a time range or session ids;
  - resolves media to data URIs;
  - applies the gold precedence artist > reviewer > outcome > luna, with `label_agreement`;
  - splits by chat with a seed;
  - writes JSONL plus a report (rows per kind and split, skips with reasons, label balance, gold sources).

  Verify with a test on recorded fake data: precedence, outcome derivation, split by chat, and byte-identical re-runs.
- [ ] 4.2 Add `--no-images` and `--min-source` options. Verify with tests that rows match apart from `images`, and that `outcome` rows are excluded on request.

## 5. Backfill

- [ ] 5.1 Add `scripts/backfill-decisions.mjs`:
  - builds `review-check` rows from saved studies' `goal.json` reviews and preview images;
  - resolves check text from the brief revision in effect, and skips and counts unresolvable checks;
  - splits by study;
  - never modifies studies.

  Verify on a temp copy with a test, then run it on the real studies and report how many of the 2,306 checks became rows.

## 6. Live acceptance

- [ ] 6.1 After a Krita restart, run one short chat on a disposable document that includes a review and a Reject pass. Verify in Langfuse, via the CLI, that `decide-review-check` and `decide-pass-keep` traces are in that chat's session, and that the rejected pass has `artist-verdict = false`.
- [ ] 6.2 Export that chat plus the backfill. Load both files in the Colab notebook from 1.1 and verify 0 format skips. Run `FastDecisionModel.evaluate` before training as a baseline, and record the result and whether images were used in the change notes.
- [ ] 6.3 Update `krita-creative-agent/README.md` with the decision kinds, gold sources, export and backfill commands, and the image / text-only targets. Verify by reading the section against the specs.

## Why

A Starry Night run took 76 painting minutes. 62 of them were 295 painter model calls (12.6 s each, inputs averaging 41k tokens), one per small brush action. Native painting took 13.6 minutes, reviews 5, Luna 3.3 (baseline: `krita-creative-agent/docs/benchmarks/baseline-starry-night.json`). Each action also saved a full `.kra`, and returned the whole pass history (about 59k characters) plus an image to the model. About 41 painter turns went on progress and review bookkeeping. People should not wait an hour for a painting.

## What Changes

- **Batch painting:** a `paint_batch` tool runs 1–10 painting actions per model call. All actions are validated before anything paints; the batch stops at the first failure and returns one canvas image. The painter prompt makes batches the normal unit of work.
- **Lean tool results:**
  - the model no longer receives host bookkeeping (pass history, file paths, document ids);
  - non-observe results are capped at 2,000 characters, as valid JSON;
  - the layer index keeps its own budget;
  - only the two newest canvas images stay in the model context (the saved transcript is unchanged).
- **Fewer full saves:** painting actions save the `.kra` every 5 actions or 60 seconds, and always before a review, at run end, on `end`, and on the artist's pass-review actions. A new native `checkpoint` operation forces a save.
- **Decision-model pacing (Guide mode):** after each painting call, one Luna decision (`next`: continue / next step / request review; `progress`: 0–3) lets the host:
  - advance the plan step;
  - queue the independent review;
  - flag two low-progress decisions in a row.

  The painter is told in the tool result, and `record_progress` is hidden; `request_review` remains as a backstop. Each decision is recorded as a `route` decision for the decision-model dataset. With Luna Off or Evaluate, behaviour is unchanged.
- **A benchmark:** `scripts/benchmark-run.mjs <chat-id>` reports painter calls, minutes per category, tokens and review results from the chat's Langfuse session.

## Capabilities

### New Capabilities
- `faster-agent-runs`: batching, lean model context, deferred checkpoints and decision-model pacing for Agent runs, with a session-based benchmark.

### Modified Capabilities
<!-- None archived yet; autonomous-agent-runs and luna-visual-decisions are unchanged in their requirements. -->

## Impact

- **Companion:** `src/tools.mjs` (`paint_batch`, `modelResultText`, `keepRecentImages`), `src/runtime.mjs` (context transform), `src/studio.mjs` (pacing, checkpoint flushes, tool lists, prompt), new `src/pacing.mjs`, `src/prompt.mjs`, new `scripts/benchmark-run.mjs`.
- **Plugin:** `krita-plugin/kritamcp/creative_tools.py` (deferred checkpoints, `checkpoint` operation, `end` flushes).
- **Risk:**
  - a crash can lose up to 4 unsaved actions or 60 seconds of painting;
  - batches give the painter less feedback per action, mitigated by per-batch pacing and reviews.

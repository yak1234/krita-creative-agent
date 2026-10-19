## Context

- Every Krita chat is traced to Langfuse (`src/langfuse-tracing.mjs`). Tracing is mandatory, the session is the chat (study) id, and media upload is automatic for data-URI images.
- Typed decisions already exist in the code:
  - Luna questions in `src/visual-checks.mjs` and `src/routing.mjs`, in the Decisions API form;
  - reviewer verdicts per check, from `validateReview` in `src/studio.mjs`, with `{id, met, evidence}`.
- Every committed pass has `before_path` and `after_path` images in the study folder. The artist's **Reject pass** / **Reject step** reaches the companion as `pass_review` with `action: 'reject'` (`studio.mjs`, the pass review handler).
- Local history: 217 saved reviews with 2,306 per-check verdicts and evidence. Every review's preview image still exists.
- Unsloth (main branch, 2026-10-09):
  - rows are `state`, `questions`, `gold`, plus optional `images`;
  - Laya is text-only;
  - training will run on Google Colab (NVIDIA, the CUDA path);
  - on the CUDA path, `_clef_items` in `decision.py` encodes only `state` and `questions`. The vendored Clef `encode_record` accepts a processor and images, but Unsloth does not pass them, so **Colab training is text-only today**;
  - only the MLX path (`decision_mlx.py`) passes images, to a Clef with a vision tower.

## Goals / Non-Goals

**Goals:**
- Training rows that load unchanged in Unsloth's decision `build_dataset`, with images for Clef/MLX and the same rows usable text-only.
- Langfuse as the single labelled store: decisions, their images, answers given at the time, and later evidence, all in the chat's session.
- Labels that come from the artist and from outcomes, not only from another model.

**Non-Goals:**
- Training or serving the model, or switching the Creative Agent from Luna to it. That is a later change, once a model beats Luna on held-out rows.
- New painter decisions in a typed form (for example, choosing the next tool). The painter's free-form tool calls stay as they are.
- Labelling UI inside Krita. Artist annotation uses Langfuse's own score UI and annotation queues.

## Decisions

### 1. One small trace per decision, with a deterministic trace id
Each decision is its own trace in the chat's session: one `event` observation named `decide-<kind>`. Its input is `{state, questions, images}` and its output is `{answers, answered_by}`. The trace id is `createTraceId(decision_id)` from `@langfuse/tracing`. The decision id is deterministic:

- `<chat>:review-check:<review index>:<check id>`;
- `<chat>:pass-keep:<pass id>`;
- `<chat>:pass-failures:<pass id>`;
- `<chat>:route:<message id>`;
- `<chat>:progress:<review index>`.

**Why:** a later event (Reject pass, hours later, or after a restart) can attach a score without keeping a mapping, because the trace id can be recomputed from the decision id. Scores need exactly one target, and the trace is that target.

**Alternatives:**
- Nesting decisions inside the run's trace would need the run's trace and observation ids stored, and lost across restarts.
- Langfuse datasets were rejected as the primary store, because dataset items don't keep the session, scores and media links that tracing gives for free. A dataset can still be created from an export later.

### 2. Answers at the time are output; later evidence is a score
- The reviewer's verdict and Luna's probabilities are the decision's output, with `answered_by: reviewer | luna`.
- The artist's verdict is a BOOLEAN score `artist-verdict` on the decision trace. Reject pass writes it automatically (false); annotations in Langfuse write it by hand.
- The `outcome` label (never rejected, and the chat's last review passed) is derived at export from the decisions themselves, so nothing has to run when a chat ends.

**Why one decision per review check:** a single score name (`artist-verdict`) can then label any decision, which keeps Langfuse annotation simple (one score config, one annotation queue). Per-check rows also suit training: each row is one question about one canvas.

### 3. Images are referenced, not duplicated
Decision input holds images as data URIs (longest side ≤1024, as Luna already uses). Langfuse replaces them with media references and stores identical bytes once, so a canvas already uploaded for a generation is not stored twice. Export resolves references with `LangfuseClient.resolveMediaReferences({resolveWith: 'base64DataUri'})`.

### 4. Text state is always present
The state is built for every decision, capped at about 1,500 characters:

```
{objective, plan_step, check_text?, canvas: {width, height, layers: [name, visible, opacity], revision},
 recent_operations: [last 8 {kind, layer, rejected}], user_directions: [last 3], luna_findings?}
```

**Why:** on Colab the text state is all the model sees today, so it must describe the canvas, not just the plan. Where text evidence exists, it goes in the state:
- the reviewer's per-check evidence, for review checks;
- Luna's findings and the operation's kind, layer and region, for passes.

Images still go in every row, so the same export trains with images once Unsloth's CUDA path passes them. `--no-images` gives smaller files meanwhile.

### 5. Gold encoding
`gold[q] = {type, label, probabilities, confidence}`, plus `noul` (the probability of true) for `noul` and `score` (the expected level) for `score`, as in `LocalLLaMA/typed-decisions`.

- **Artist, reviewer, outcome:** hard labels (probability 1 on the label).
- **Luna:** its probabilities as returned.
- **`label_agreement[q]`:** `{sources, argmax_agree}` across whichever sources answered.

### 6. Split by chat
`split = test` when `sha256(chat id + seed)` falls in the lowest 10%, otherwise `train`. A chat never spans splits; the same leak-free rule Unsloth uses for its test set.

### 7. Export and backfill are offline scripts
- `scripts/export-decisions.mjs` uses `@langfuse/client` (`api.observations` v2 list filtered by name prefix `decide-` and time range or session ids; `api.scores` v3 list by trace) and writes JSONL. Unsloth loads it with `load_dataset('json', …)`.
- `scripts/backfill-decisions.mjs` reads `goal.json` reviews and preview PNGs directly. It writes the same row format, with `factors.backfilled = true`. It does not send anything to Langfuse, so history costs no ingestion.

## Risks / Trade-offs

- **[The reviewer is a model, not ground truth]** → Rows record `gold_source`, artist verdicts always win, and an annotation queue for the reviewer's failed checks lets the artist correct the labels that matter most.
- **[Old reviews' check text]** Older reviews store only `check-N` ids. → Backfill resolves the text from the brief revision in effect (`goal.revisions`). It skips and counts a check whose text cannot be resolved, and never guesses.
- **[`outcome` keep labels are weak]** An unrejected pass may simply not have been noticed. → Export lists them as source `outcome` with lower trust, and `--min-source` can exclude them.
- **[Class imbalance]** Reviews failed far more often than they passed (25 passed, 173 failed in the studies). → Export reports label balance per kind; balancing is left to training.
- **[Colab cannot use images yet]** → The text state carries the canvas evidence, and task 1.2 checks the installed Unsloth before training. If CUDA image support is still missing, there are two choices:
  - train text-only;
  - patch `_clef_items` in the notebook to pass the base model's processor and the row images to `encode_record`, which supports both. This is unsupported, so it is a fallback, not the plan.
- **[Text-only leaks the label]** For review checks, the reviewer's evidence often states the verdict ("the fence is missing"). → Export keeps evidence out of the state of the row it labels, and uses it only as context for other decisions. Otherwise a text-only model would learn to read the verdict instead of judging the canvas.
- **[Langfuse volume]** One decision per check and per pass adds about 10–20 small traces per review cycle. Images are deduplicated media. → Acceptable for one artist; revisit if ingestion units become a cost.

## Migration Plan

Additive. Existing traces are unchanged. Decisions start in the next release; history comes from backfill. Rollback: remove the recording calls. Recorded decisions remain harmless in Langfuse.

## Open Questions

- **Start with `unsloth/Qwen3.5-0.8B` on Colab, then compare with 2B on the held-out chats.**
  - Both bases have vision towers (0.8B: 12 vision layers; 2B: 24) and ship processor files.
  - The vision tower stays frozen during LoRA, so the 0.8B keeps its smaller vision features. Fine defects (hairline seams, faint stripes) may need the 2B.
  - The base doesn't affect the row format.

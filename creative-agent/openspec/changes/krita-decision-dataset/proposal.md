## Why

We want to train our own decision model (Unsloth Clef-style, on a Qwen3.5 vision backbone) on the decisions the Creative Agent makes in Krita, so that the decisions currently delegated to Luna can be made by a model that knows this artist's paintings. Every Krita chat is now traced to Langfuse, but traces hold free-form agent turns, not labelled decisions. Nothing yet produces training rows (state, images, questions, gold), and the labels that matter most — the artist's rejections and the reviewer's per-check verdicts — are not joined to the decision they judge.

## What Changes

- Record every typed Krita decision as a Langfuse observation with a fixed name and metadata: its text state, its canvas images, its questions (the Luna Decisions API types `noul`, `choice`, `score`) and the answer given at the time.
- First decisions, with gold from people and outcomes:
  - **review check met?** (`noul`, one per review check). Gold: the reviewer's verdict, overridden by an artist annotation when present.
  - **keep or reject this pass?** (`noul`, one per committed pass, with before and after images). Gold: the artist's Reject pass / Reject step; an unrejected pass in a chat whose final review passed is a weaker "keep".
- Also record the existing Luna decisions — pass failures (six `noul`), routing (`choice`), progress (`score`) — with Luna's probabilities as soft teacher gold, marked as such.
- Attach later evidence (rejections, review outcomes, artist annotations) to the decision observation as Langfuse scores, so Langfuse is the single labelled store.
- New `scripts/export-decisions.mjs`: reads decisions and scores from Langfuse, resolves media to data URLs, and writes typed-decisions rows with an `images` column, split by Krita chat.
- New `scripts/backfill-decisions.mjs` (optional): builds review-check rows from the 28 local studies' saved reviews and preview images.
- Each row always carries a short text state, so the same file also trains text-only models (Laya, or Unsloth's current CUDA path, which has no image support).

## Capabilities

### New Capabilities
- `krita-decision-dataset`: recording typed Krita decisions with their images in Langfuse, joining them to gold from the artist, the reviewer and Luna, and exporting Unsloth decision-model training rows.

### Modified Capabilities
<!-- None: the in-progress luna-visual-decisions and autonomous-agent-runs changes are unchanged; this change only observes their decisions. -->

## Impact

- **Code:** `krita-creative-agent/src/langfuse-tracing.mjs` (decision observations, decision scores), `src/studio.mjs` (record decisions at review, pass commit, pass review and Luna calls), `src/visual-checks.mjs` and `src/routing.mjs` (hand questions and answers to the recorder), new `src/decision-records.mjs`, new `scripts/export-decisions.mjs` and `scripts/backfill-decisions.mjs`, tests.
- **Langfuse:** more observations and scores per chat; canvas images are already uploaded as media, and a decision references the same media.
- **Dependencies:** none new in the companion (uses `@langfuse/client` 5.13.1, already installed). Training happens outside this repo with Unsloth (MLX path for images, which needs a recent `unsloth-zoo`).
- **Privacy:** no new data leaves the machine; decisions reuse prompts and images already sent to Langfuse. The exported files contain the artist's images and must stay local unless the artist chooses to publish them.

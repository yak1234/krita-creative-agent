## Purpose

Turns the decisions the Creative Agent makes while painting in Krita into labelled training rows, with their canvas images, for fine-tuning a decision model in Unsloth's typed-decisions format.

## ADDED Requirements

### Requirement: Typed decisions are recorded in the chat's trace
Each typed decision SHALL be recorded in Langfuse inside the Krita chat's session, as one observation per decision, with:

- a stable name per decision kind;
- a short text state;
- references to its canvas images;
- its questions in the Decisions API form (`noul`, `choice` or `score`, with instructions and criteria);
- the answer given at the time, if any;
- a decision id that is stable for that decision.

The decision kinds are:

| Kind | Questions | Images |
|---|---|---|
| `review-check` | one `noul`, "this check is met" (one decision per check) | the reviewed canvas |
| `pass-keep` | one `noul`, "this pass should be kept" | before and after the pass |
| `pass-failures` | six `noul`, one per known failure type | before and after the pass |
| `route` | operation `choice` and brush `choice` | the canvas, when one was attached |
| `progress` | one `score` per repeated failing check | the previous and current review canvases |

Recording SHALL never delay or interrupt painting. A failure to record SHALL be noted in diagnostics.

#### Scenario: A review records one decision per check
- **WHEN** a review of 5 checks completes
- **THEN** the chat's session contains 5 `review-check` decisions. Each has the check text in its state, the reviewed canvas image, and the reviewer's met / not-met answer

#### Scenario: A committed pass records a keep decision
- **WHEN** a paint pass is committed with before and after images
- **THEN** a `pass-keep` decision with both images is recorded, with no answer yet

#### Scenario: Luna off
- **WHEN** Luna decisions is Off
- **THEN** `review-check` and `pass-keep` decisions are still recorded, and no `pass-failures`, `route` or `progress` decision is recorded

### Requirement: Gold labels come from the artist, the reviewer and Luna, in that order of trust
Each decision has its own answer, recorded with it at the time: the reviewer's verdict, or Luna's probabilities. Later evidence is attached as Langfuse scores:

- the artist's verdict, from Reject pass, Reject step or an annotation in Langfuse, is attached as an `artist-verdict` score on the decision;
- the `outcome` label is derived at export: a pass that was never rejected, in a chat whose last review passed.

The gold sources are `artist`, `reviewer`, `outcome` and `luna`. When several label one question, export SHALL use, in order: artist, reviewer, outcome, luna. It SHALL record which sources agreed.

#### Scenario: The artist rejects a pass
- **WHEN** the artist presses Reject pass on a committed pass
- **THEN** that pass's `pass-keep` decision receives an `artist-verdict` score of false, and export labels it false with source `artist`

#### Scenario: The artist overrides the reviewer
- **WHEN** the reviewer marked a check met and an artist annotation marks it not met
- **THEN** export labels that check not met, and records that the reviewer disagreed

#### Scenario: A pass survives to a passing review
- **WHEN** a chat's last review passed and a pass in it was never rejected
- **THEN** export labels that pass's `pass-keep` decision true, with source `outcome`

#### Scenario: Only Luna answered
- **WHEN** a `pass-failures` decision has only Luna's answer
- **THEN** export uses Luna's probabilities as soft gold and marks the row's source as `luna`

### Requirement: Export writes Unsloth typed-decisions rows with images
An export command SHALL read decisions and their scores from Langfuse for a time range or a list of chats. It SHALL write one row per decision with these fields:

- `id`, `workflow`, `split`, `n_questions`;
- `state` (JSON text);
- `questions`, as JSON text;
- `gold`, as JSON text: for each question, `type`, `label`, `probabilities` and `confidence`, plus `noul` for `noul` questions and `score` for `score` questions;
- `factors`, as JSON text: decision kind, gold sources, chat, plan revision and model;
- `label_agreement`, as JSON text;
- `images`: data URLs, in the order the decision recorded them.

Questions without gold SHALL be left out of a row, and decisions with no labelled question SHALL be skipped and counted. Every row of a chat SHALL go to the same split. Export SHALL report:

- rows per decision kind and split;
- skipped decisions, with their reasons;
- gold sources used.

#### Scenario: Rows load in Unsloth
- **WHEN** an exported file is passed to Unsloth's decision `build_dataset` for a Clef model on Colab
- **THEN** no row is skipped for format reasons

#### Scenario: Images are kept even when unused
- **WHEN** the Unsloth version in use does not pass images on its GPU path
- **THEN** rows still carry their images, and the text state alone describes the canvas well enough to train on

#### Scenario: Split by chat
- **WHEN** a chat has 40 decisions
- **THEN** all 40 rows are in the same split

#### Scenario: A text-only target
- **WHEN** export runs with images excluded
- **THEN** rows are identical except that the `images` column is empty, and each row's text state still describes the canvas facts

### Requirement: Export is reproducible and private
Export SHALL be deterministic for the same Langfuse data and seed. It SHALL write only to a local path the user names. API keys SHALL never appear in rows, logs or reports. Export SHALL read only the configured Langfuse project.

#### Scenario: Re-running export
- **WHEN** export runs twice on unchanged data with the same seed
- **THEN** both runs produce byte-identical files

### Requirement: History can be backfilled from local studies
A backfill command SHALL build `review-check` rows from saved studies. It SHALL use each saved review's checks, evidence text and preview image, with the reviewer as the gold source. It SHALL skip reviews whose image file is missing, and SHALL split by study. Backfill SHALL NOT modify the studies.

#### Scenario: Backfilling the saved studies
- **WHEN** backfill runs over the studies folder
- **THEN** it writes one `review-check` row per saved review that has an image, and reports reviews skipped for a missing image

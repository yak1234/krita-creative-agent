## Purpose

Gives the Creative Agent fast, image-based decisions from GPT-6 Luna Decisions on OpenRouter: routing informed by the canvas, detection of known failure types introduced by a paint pass, and measurement of whether repeated corrections actually improve the failing area. These decisions inform the painter and the stall rules; they never grant permissions, mark a painting complete, or replace the independent review.

## ADDED Requirements

### Requirement: Single Luna decisions setting
The companion SHALL provide one setting, "Luna decisions", with values Off, Evaluate only and Guide agent, stored under the existing `routing` execution-setting key with values `off`, `evaluate`, `guide`. Off SHALL make no Luna requests. Evaluate only SHALL run routing, the per-pass check and the progress check, record and display them, and leave the painter context and the loop's decisions unchanged. Guide agent SHALL additionally apply them as specified below.

#### Scenario: Off
- **WHEN** the setting is Off and the agent paints and reviews
- **THEN** no request is sent to OpenRouter's Decisions API

#### Scenario: Evaluate only does not change behavior
- **WHEN** the setting is Evaluate only and a pass is flagged
- **THEN** the finding appears in diagnostics and the panel, but not in the painter's context, and the stall rules behave as with Off

### Requirement: OpenRouter Luna client and credentials
All Luna decisions SHALL use `openai/gpt-6-luna-decisions` through OpenRouter's Decisions API. They SHALL authenticate with the OpenRouter API-key credential already configured for the painter, falling back to `OPENROUTER_API_KEY`. With neither available, every decision SHALL fall back with reason `not_connected` and painting SHALL continue. Images SHALL be sent in a form the model actually receives. No TypeSafe service, SDK or credential SHALL be used, and an existing saved TypeSafe key SHALL be left untouched. API keys SHALL never appear in requests' state, diagnostics, status messages or artwork.

#### Scenario: Painter already connected to OpenRouter
- **WHEN** OpenRouter is connected for the painter and the setting is turned on
- **THEN** Luna decisions work without entering another key

#### Scenario: Image actually reaches the model
- **WHEN** the live acceptance check sends two control images differing only in color
- **THEN** Luna's answers differ accordingly

### Requirement: Routing uses the attached canvas
Routing SHALL request one operation choice and one brush choice from the existing operation and brush sets. It SHALL include the attached canvas snapshot (longest side at most 1024 px) with the bounded, redacted text state when the canvas is attached, and text only otherwise. In Guide agent mode, routing advice SHALL be given only when operation confidence is at least 0.8, the operation is not `mixed_unknown`, and the required capability is available. Advice SHALL NOT change tool permissions or Ask read-only behavior.

#### Scenario: Canvas attached
- **WHEN** routing runs with the canvas attached
- **THEN** the request contains the canvas image plus the text state

#### Scenario: Low confidence
- **WHEN** Luna returns an operation with confidence 0.7
- **THEN** no routing advice is given

#### Scenario: Held-out accuracy
- **WHEN** the routing evaluation runs text-only on the 26-case held-out fixture
- **THEN** at least 24 cases match their expected route

### Requirement: Per-pass known-failure check
After each committed paint pass that has before and after images, the companion SHALL ask Luna, in one request with both images, whether the pass introduced each of these failures:

- a hard horizontal or vertical join with misaligned content;
- a repeated or duplicated band of content;
- a flat or speckled rectangular block;
- mechanical, evenly spaced stripes;
- pasted flat hard-edged ellipses;
- a hard graphic, poster-like look replacing painted transitions.

For each failure judged present with probability at least 0.7 and absent from the before image, the finding SHALL include its type, probability and location as one cell of a 3×3 grid of the canvas. In Guide agent mode, findings SHALL be returned to the painter with the pass result, as evidence it may act on. In every mode they SHALL be recorded in diagnostics and shown in the panel. The check SHALL NOT hide, reject or undo a pass, and SHALL NOT block the next pass.

#### Scenario: Transfer pass creates a join
- **WHEN** a pass adds a straight horizontal seam with misaligned content in the lower third
- **THEN** a finding `splice` with a lower-row location is recorded and, in Guide agent mode, returned to the painter with that pass's result

#### Scenario: Clean pass
- **WHEN** a pass adds ordinary brushwork with none of the listed failures
- **THEN** no finding is reported

#### Scenario: Failure already present before
- **WHEN** stripes existed in the before image and remain after the pass
- **THEN** the pass is not reported as introducing stripes

### Requirement: Review-to-review progress scoring for stalls
When the independent review fails the same checks it failed at the previous review, the companion SHALL ask Luna to score, from the previous and current review images, how much each repeated failing check improved. The scale is: no improvement, slight, clear, resolved. Scores SHALL be recorded with the review. In Guide agent mode:

- three consecutive repeated-failure reviews whose mean progress score is below "slight" SHALL trigger the existing change-of-strategy recovery;
- a repeated-failure review with mean progress at or above "clear" SHALL NOT count toward that rule.

Without a progress score (Off, Evaluate only, or a fallback), the existing check-ID rule SHALL apply unchanged.

#### Scenario: Stalled corrections
- **WHEN** in Guide agent mode the same façade check fails at three consecutive reviews and each progress score is "no improvement"
- **THEN** the change-of-strategy recovery runs with the progress evidence in its reason

#### Scenario: Real progress despite the same failed check
- **WHEN** the same check fails again but Luna scores the change "clear"
- **THEN** that review does not count toward the stall rule

#### Scenario: Progress unavailable
- **WHEN** the progress request times out
- **THEN** the existing check-ID stall rule is used for that review

### Requirement: Failures fall back without blocking painting
A refused question, malformed or incomplete answer, HTTP error, timeout (4 s per request) or cancellation SHALL produce a recorded fallback with a reason (`refused`, `service_or_response_error`, `timeout`, `cancelled`, `not_connected`), and the painting turn, pass or review SHALL continue as if the decision were Off. A result whose document, revision, stage or pass no longer matches the current state SHALL be discarded.

#### Scenario: Provider refuses
- **WHEN** OpenRouter answers 502 "refused to answer question"
- **THEN** that decision falls back with reason `refused` and painting continues

#### Scenario: Late routing result
- **WHEN** the canvas revision changes while a routing request is in flight
- **THEN** the late result is discarded

### Requirement: Panel disclosure and display
The Krita panel SHALL label the setting "Luna decisions" with Off, Evaluate only and Guide agent. It SHALL state that, when on, the canvas and pass images and the artist's direction are sent to OpenRouter and OpenAI, and SHALL NOT offer a separate key field. Per-pass findings and progress scores SHALL be visible in the activity or pass history with their type, location and score.

#### Scenario: Settings view
- **WHEN** the artist opens the execution settings
- **THEN** they see "Luna decisions", its three modes, the data-flow note and no TypeSafe key field

### Requirement: Labelled visual-check evaluation
The repository SHALL include an evaluation, using paired clean and defective images with known labels, that reports detection rate, false-positive rate and location accuracy for each per-pass failure type. It SHALL also report rank agreement for progress scores across graded corrections. A release with Luna decisions SHALL record this evaluation's results.

#### Scenario: Evaluation run
- **WHEN** the evaluation runs
- **THEN** it saves per-type detection, false-positive, location and progress-ordering results with the images used

### Requirement: Uncertain actions recover automatically
In an active Agent run, when a painting action ends with an uncertain outcome (`outcome_unknown`, `partial_change` or `checkpoint_failed`), the companion SHALL NOT pause for inspection. Instead it SHALL:

1. observe the current canvas;
2. acknowledge the native uncertain state for that exact revision;
3. return to the painter the action's real error, the fresh canvas and, when Luna decisions is not Off, Luna's findings comparing the canvas before the action with the current canvas;
4. continue the run.

The painter SHALL be told to verify the canvas before repeating the action, and the companion SHALL never repeat it automatically. Every third consecutive uncertain action without a successful action between them SHALL trigger the change-of-strategy recovery; the run SHALL NOT pause for repeated uncertain actions (see `autonomous-agent-runs`). The artist's Stop SHALL always pause immediately. If observation or acknowledgement fails, the previous pause-for-inspection behavior SHALL apply.

#### Scenario: Smart Patch fails mid-contribution
- **WHEN** a toolbox contribution fails with `partial_change` during an active Agent run
- **THEN** the run continues; the painter receives the real error, the fresh canvas and any Luna findings, and no "Paused for inspection" state is shown

#### Scenario: Repeated uncertain actions
- **WHEN** three actions in a row end uncertain
- **THEN** the change-of-strategy recovery runs, and again at six in a row; the run does not pause

#### Scenario: Recovery itself fails
- **WHEN** the canvas cannot be observed after an uncertain action
- **THEN** the run pauses for inspection as before

### Requirement: Failed contributions report their real error
When a native toolbox contribution fails and its contribution layer is removed, the reported error SHALL be the original failure (for example the Smart Patch error). The removed layer SHALL NOT be referenced by the result or recorded as a pass. A failure while writing the pass record SHALL be appended to, not replace, an existing error.

#### Scenario: Removed contribution layer
- **WHEN** Smart Patch fails and the projection layer is removed during cleanup
- **THEN** the result carries the Smart Patch error, has no `layer_id`, and no "That layer is no longer in this painting" error appears

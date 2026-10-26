## Purpose

Makes autonomous Agent runs fast enough that a full painting takes minutes, not an hour, by cutting model round trips, model context size and per-action save cost, and by pacing runs with a decision model.

## ADDED Requirements

### Requirement: Painting actions can be batched
In Agent mode the painter SHALL be able to submit 1–10 painting actions (`paint_pass`, `paint_recipe`, `paint_contours`, `adjust_layer`, `painting_toolbox`) in one call. Each action takes exactly that tool's arguments.

Every action SHALL be validated before any of them paints. Actions SHALL run in order, through the same path as a single call. The batch SHALL stop at the first failed action and report which actions ran. An uncertain outcome SHALL follow the existing recovery or pause behaviour. The result SHALL contain one canvas image.

#### Scenario: One invalid action
- **WHEN** a batch of 4 actions has an invalid second action
- **THEN** nothing is painted, and the error names action 2

#### Scenario: A failure mid-batch
- **WHEN** the third of four actions fails
- **THEN** actions 1–2 remain painted, action 4 does not run, and the result reports action 3's error and one not-run action

### Requirement: The model receives lean results
Painting tool results sent to the model SHALL NOT contain the pass history, file paths, document ids or checkpoint details; the panel still receives them.

Non-observe results SHALL be valid JSON of at most about 2,000 characters, apart from a layer index of at most 8,000 characters. When the layer index is over budget, its newest layers are kept.

Only the two newest canvas images in tool results SHALL be sent to the model; older ones SHALL be replaced by a short note. The saved transcript SHALL keep every image.

#### Scenario: A long run
- **WHEN** a painting has 170 passes and 158 layers
- **THEN** a paint result sent to the model has no pass list, lists all 158 layers by id and name, and stays within budget

### Requirement: Full saves are deferred between painting actions
Painting actions SHALL save the working `.kra` on the first action, then at least every 5 actions or 60 seconds. In between, an action SHALL only re-read the canvas.

A save SHALL always happen:
- before an independent review;
- when an Agent run ends;
- when the study ends;
- on the artist's pass-review actions.

#### Scenario: Ending a chat with unsaved actions
- **WHEN** 3 actions are unsaved and the chat ends
- **THEN** the painting is saved before the study is released

### Requirement: A decision model paces Guide-mode runs
With Luna decisions set to Guide, after each painting call in an Agent run (a batch counts once), the host SHALL ask one typed decision with the current canvas:

- `next`: continue the step, move to the next step, or request review;
- `progress`: 0–3 for the current step.

With confidence of at least 0.6 the host SHALL:
- move to the next plan step (never past the last);
- or queue the independent review, if at least 3 actions have run since the last review and the painting changed.

After two low-progress decisions (below 1) in a row on the same step, the host SHALL tell the painter to change method. The painter SHALL be told of every action in the tool result.

In Guide mode `record_progress` SHALL NOT be offered, and `request_review` SHALL remain available. A failed or uncertain decision SHALL change nothing. Off and Evaluate modes SHALL behave as before. Each decision SHALL be recorded for the decision-model dataset when tracing is on.

#### Scenario: The host calls the review
- **WHEN** Luna answers `request_review` with confidence 0.9 after 4 actions since the last review
- **THEN** the review runs after the current turn without the painter requesting it

#### Scenario: Luna unavailable
- **WHEN** the pacing decision times out
- **THEN** nothing changes, and the painter can still request review itself

### Requirement: Run speed is measurable
A benchmark command SHALL report, from a chat's Langfuse session:
- painting minutes;
- painter calls and their mean duration and input tokens;
- minutes per category (painter calls, painting tools, reviews, Luna, preparation);
- review results.

#### Scenario: Baseline
- **WHEN** the benchmark runs on the baseline Starry Night chat
- **THEN** it reports 76.2 painting minutes and 295 painter calls

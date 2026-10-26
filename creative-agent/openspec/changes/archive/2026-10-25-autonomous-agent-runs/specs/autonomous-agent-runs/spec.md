## ADDED Requirements

### Requirement: Plan steps are a painting order
A plan's steps SHALL describe a suggested painting order with a title, what the step achieves and an optional focus. Steps SHALL NOT gate painting: there is no per-step review, step stop, step operation limit or step region. A saved plan containing `stop_after`, `max_operations` or `region` on a step SHALL load and save with those fields removed.

#### Scenario: Two-step plan
- **WHEN** an Agent run executes a plan with two steps
- **THEN** the painter works through both steps without a review or pause between them, and one review checks the finished painting

#### Scenario: Legacy plan
- **WHEN** a saved conversation whose plan has `stop_after: true` and `max_operations: 3` is restored
- **THEN** it loads, and those fields are absent from the plan

### Requirement: One final review decides completion
The independent review SHALL check every requirement and final visual check of the brief. The host SHALL mark the painting complete when every check is met and continue painting otherwise, whatever verdict the reviewer states. The reviewer SHALL NOT defer a check or return a verdict that hands the run to the artist.

#### Scenario: Verdict contradicts checks
- **WHEN** the reviewer says "continue" but marks every check met
- **THEN** the painting is complete after that single review

#### Scenario: Reviewer asks for input
- **WHEN** the reviewer submits a `needs_input` verdict
- **THEN** the review is rejected as invalid and the run does not wait for the artist

### Requirement: No mid-run human review
During an active Agent run the companion SHALL NOT pause or wait for the artist except when the artist presses Stop, a time or pass allowance is reached, the canvas cannot be observed after an uncertain action, or the model or connection fails. In particular:

- the painter SHALL NOT be able to ask the artist a question while painting, and SHALL be told to decide within the brief;
- repeated failed reviews SHALL trigger the change-of-strategy recovery on every third consecutive repeat (subject to Luna progress in Guide mode), never a pause;
- consecutive uncertain actions SHALL trigger the change-of-strategy recovery on every third in a row, never a pause;
- a canvas change made outside the run SHALL be recorded as a direction to keep the artist's edits, and the run SHALL continue.

#### Scenario: Seven reviews fail the same check
- **WHEN** the same check fails at seven consecutive reviews after painting each time
- **THEN** the run changes strategy at the third and sixth, never pauses, and continues until the check passes

#### Scenario: Artist edits mid-run
- **WHEN** the canvas revision changes between cycles without the Agent painting
- **THEN** the latest directions include keeping the artist's edits, and painting continues

#### Scenario: Stop
- **WHEN** the artist presses Stop at any point
- **THEN** the run pauses immediately

### Requirement: Approval before painting is unchanged
Plan-phase questions, starting a plan with Start painting, and accepting a requested change to a locked requirement SHALL keep requiring the artist.

#### Scenario: Locked requirement change
- **WHEN** the artist asks to change a locked character requirement
- **THEN** the exact before/after change is shown for acceptance before it applies

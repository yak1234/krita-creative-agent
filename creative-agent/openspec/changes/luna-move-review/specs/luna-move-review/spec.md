## ADDED Requirements

### Requirement: Luna reviews each painting batch in Agent mode
In Agent mode, with Luna set to Guide or Evaluate, every painting call that changes the canvas SHALL be reviewed by
Luna comparing the canvas before and after it, with the artifact checks and the covered-feature and
texture-over-forms checks. Calls that only change layer settings SHALL NOT be reviewed.

#### Scenario: The moon painted over
- **WHEN** a batch covers the moon that the canvas showed before it
- **THEN** Luna reports a covered feature located at the moon

### Requirement: A regression is undone in Guide mode
With Luna set to Guide, a batch with a finding SHALL be undone and the painter SHALL be told what was lost and where.
At most two batches per move SHALL be undone automatically; after that the move SHALL stop for the artist with the
finding. With Luna set to Evaluate, findings SHALL only be recorded.

#### Scenario: Undo and continue
- **WHEN** Luna finds the moon covered by a batch in Guide mode
- **THEN** that batch's passes are rejected, the painter is told "the moon was covered", and the move continues

#### Scenario: No undo loop
- **WHEN** a third batch in the same move has a finding
- **THEN** it is not undone; the move stops for the artist with Luna's finding

### Requirement: Focal features are protected areas
The painter SHALL propose a named protected area for a focal feature before a broad pass over it. Luna's
covered-feature check SHALL use the names of kept and proposed protected areas.

#### Scenario: The artist keeps the moon
- **WHEN** the artist keeps the proposed area "Moon"
- **THEN** no later pass changes the moon's pixels, and Luna checks "Moon" after each batch

### Requirement: The verdict is visible and testable
Each Agent move SHALL carry Luna's verdict (kept, undone or warned, with findings), shown in one line on the move
card and returned by the test driver's state as a runtime verdict.

#### Scenario: A clean move
- **WHEN** a move's batches have no findings
- **THEN** the move card shows Luna's verdict as kept

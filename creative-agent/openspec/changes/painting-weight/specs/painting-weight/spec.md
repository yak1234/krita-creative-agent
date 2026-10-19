## ADDED Requirements

### Requirement: The plugin measures a painting's weight
Every observation SHALL carry `weight`:
- node, group, paint-layer and filter-mask counts;
- expensive filters by name;
- the agent's hidden leftovers;
- an estimated memory size in MB;
- a level (`ok`, `heavy`, `too_heavy`), with reasons and fixes.

It SHALL be computed from layer metadata only, never from pixels.

#### Scenario: New Moscow
- **WHEN** a painting at 6000×4500 has 147 groups and a wavelet noise reducer filter mask
- **THEN** its level is `too_heavy`, and a reason names the wavelet noise reducer

### Requirement: The painter is told what makes the painting heavy
When the level rises, or an operation takes over 60 seconds on a painting that is not `ok`, the painter's tool result
SHALL carry one `painting_weight` line naming the cause and how to work with it. The same line SHALL NOT repeat within
a chat.

#### Scenario: A slow observe
- **WHEN** an observe takes 900 s on a `too_heavy` painting
- **THEN** the result says the filter masks recomposite on every refresh

### Requirement: The artist is told once, with the fixes
A chat on a painting whose level is not `ok` SHALL show the artist one notice with the reasons and the fixes (tidy,
merge kept moves, bake filter masks). The monitor SHALL NOT change the painting.

#### Scenario: Opening New Moscow in a chat
- **WHEN** the first observation of a chat reports `too_heavy`
- **THEN** the artist sees one notice naming the groups and the filter masks, with "merge kept moves" and "bake filter
  masks" as the fixes, and the painting is unchanged

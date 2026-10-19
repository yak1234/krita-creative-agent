## Purpose

The agent works inside Krita the way a skilled Krita user does: it can reach Krita's own features for the job and
chooses them over strokes when they fit.

## ADDED Requirements

### Requirement: Clone layers
The agent SHALL be able to create a clone layer of any layer in the painting, as a live copy in its own stage, with
name, blend mode, opacity, clip and offset. The source layer SHALL NOT change. A clone SHALL be one reversible pass and
SHALL be hidden inside protected areas.

#### Scenario: Repeating a lamp post
- **WHEN** the agent clones its lamp-post layer with offset [400, 0]
- **THEN** a second lamp post appears 400 px to the right and follows later edits to the first

#### Scenario: Cloning the artist's layer
- **WHEN** the agent clones an artist layer
- **THEN** the artist layer's pixels and settings are unchanged, and rejecting the pass removes only the clone

### Requirement: Split by colour
The agent SHALL be able to split the visible painting or one layer into its main colour regions (2 to 24), each saved
as a named selection with its colour and share of the canvas, optionally also as one agent layer per colour. Small
regions under a minimum area SHALL be dropped. It SHALL take seconds, not minutes, on a 6000×4500 painting.

#### Scenario: Finding the sky
- **WHEN** the agent splits New Moscow into 8 colours
- **THEN** it gets saved selections such as "Split 1 · #1a2440 · 31%", and can fill the sky through one of them

#### Scenario: Layers on request
- **WHEN** the agent splits with as_layers true
- **THEN** one agent layer per colour holds a copy of those pixels, and rejecting the pass removes them all

### Requirement: Colour to alpha
The agent SHALL be able to make a chosen colour transparent on one of its layers or a copy, so line art lifts off
white paper or a glow off black. The artist's layers SHALL NOT be changed.

#### Scenario: Lifting line art
- **WHEN** the agent applies colour to alpha with white to a copy of a scanned sketch
- **THEN** the paper becomes transparent and the lines remain

### Requirement: Vetted Krita actions
The agent SHALL be able to run Krita menu commands from a vetted list only. An action SHALL be on the list only after
an audit on the installed Krita shows it opens no dialog, leaves Krita responsive, and is undone by Reject.
Pixel-changing actions SHALL act on agent layers only and SHALL respect protected areas. Selection actions SHALL change
the agent's working selection, never the artist's. Actions that change the canvas size SHALL NOT be on the list.

#### Scenario: Mirroring a layer
- **WHEN** the agent runs the mirror-horizontally action on its car layer
- **THEN** the car is flipped, and Reject restores it

#### Scenario: An action not on the list
- **WHEN** the agent asks for an action that is not on the vetted list
- **THEN** the request is refused with the list of available actions, and nothing changes

#### Scenario: An unaudited Krita version
- **WHEN** the installed Krita version has not been audited
- **THEN** no actions are offered

### Requirement: Choosing the right tool
The painter prompt SHALL guide tool choice in a named section, with worked examples in on-demand skills that the
prompt names, and SHALL NOT grow. The agent SHALL name the Krita method in its progress line before each painting
call. After four looks at the canvas in a row with no change, the next observation SHALL suggest selecting the area
and acting; this and other tool-result hints SHALL come from a Pi extension shipped with the companion, and only
extensions shipped with it SHALL load.

#### Scenario: Repainting a sky
- **WHEN** the artist asks to repaint the sky of New Moscow
- **THEN** the agent selects the sky with a seed or split by colour and fills it with a gradient or fill layer, not
  with stroke passes over the area

#### Scenario: Looking too long
- **WHEN** the agent observes the canvas four times in a row without changing it
- **THEN** the next observation carries the suggestion to select and act

### Requirement: Tool choice is measured
A tool-choice test set of about 10 requests on 3 paintings SHALL run each request three times and report, per
request, how many runs used each method, the mean score against the methods a good run uses, and any run that
changed nothing, saved so builds can be compared.

#### Scenario: Comparing builds
- **WHEN** the test set runs on the old build, the new build without loop guards, and the new build in full
- **THEN** the report lists per request the method counts and scores side by side, and a difference seen in only
  one run of three is marked as noise

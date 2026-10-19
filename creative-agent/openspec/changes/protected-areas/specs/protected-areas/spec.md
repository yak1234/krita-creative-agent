## Purpose

The artist marks areas of the painting the agent must never change. The plugin enforces it on every operation and
reports each time the agent runs into one.

## ADDED Requirements

### Requirement: Protected areas are the artist's
A protected area SHALL be a named area of the painting saved in the document. The artist SHALL be able to add one by
asking the agent, by painting over it, or from the current selection, and to show or remove it in the panel. An area
the agent proposes SHALL protect nothing until the artist keeps it. The agent SHALL NOT remove or change a protected
area. Locked layers SHALL be protected automatically.

#### Scenario: Asking the agent
- **WHEN** the artist writes "Protect the woman and the car"
- **THEN** the agent marks the area, it is shown in red, and the chat offers Keep, Adjust and Discard
- **AND** the area protects nothing until the artist presses Keep

#### Scenario: Painting over it
- **WHEN** the artist chooses Paint over it, paints over the car and presses Done
- **THEN** a protected area covering the painted strokes is listed, and the painting's pixels are unchanged

#### Scenario: The agent cannot remove protection
- **WHEN** the painter tries to change or remove a protected area
- **THEN** the request is refused

### Requirement: Nothing the agent does changes a protected pixel
After every operation that changes the painting, no visible pixel inside an active protected area SHALL differ from
before the operation. Whatever the agent painted there SHALL be removed; a change that cannot be removed SHALL fail
the operation.

#### Scenario: A brush pass into a protected area
- **WHEN** a stroke pass crosses "Woman and car"
- **THEN** the projection inside that area is identical before and after, and the rest of the pass remains

#### Scenario: A filter or fill layer
- **WHEN** the painter adds a blur filter layer or a colour fill over the whole canvas
- **THEN** the protected area looks exactly as before

#### Scenario: The artist's layer settings
- **WHEN** the painter changes the opacity of an artist layer that has pixels inside a protected area
- **THEN** the change is refused with a message naming the area

### Requirement: Each hit is reported right away
When an operation reaches into a protected area, the artist SHALL see a chat line naming the area and how much was kept
out, and the painter SHALL be told in the operation's result.

#### Scenario: A hit during Autopilot
- **WHEN** a pass in Autopilot paints 4% of its strokes into "Woman and car"
- **THEN** the chat shows that "Woman and car" was kept untouched, and the run continues

### Requirement: Protection replaces the transfer size guard
On a painting with at least one active protected area, reference transfers SHALL NOT be refused for their size on an
existing painting or after an earlier transfer.

#### Scenario: Repainting the sky of New Moscow
- **WHEN** "Woman and car" and "Buildings" are protected and the painter transfers a sky covering a third of the canvas
- **THEN** the transfer runs, and the protected areas are unchanged

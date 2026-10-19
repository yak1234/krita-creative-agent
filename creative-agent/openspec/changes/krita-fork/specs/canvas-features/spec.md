## ADDED Requirements

### Requirement: A painting has named features
A document SHALL hold a list of features, each a named region of the painting: a mask, a name, a kind (for example
sky, building, figure), an author (artist or agent), a state (proposed or kept) and measured properties (bounds, area,
mean colour). Features SHALL be saved in the `.kra`, and stock Krita SHALL still open the file and ignore them. A
feature SHALL describe the painting, not hold its pixels: it can span several layers, and adding, changing or removing
one SHALL NOT change any pixel.

#### Scenario: New Moscow reopened
- **WHEN** the artist saves New Moscow with features "Sky", "Moon" and "Tower 3", closes it and opens it again
- **THEN** the three features are there with the same masks, names and properties

### Requirement: Features are built with Krita's own selection tools
Scripts SHALL build a feature's mask with the tools Krita already has for people:
- from the current selection;
- by similar colour, and by contiguous region from a seed point;
- by a rough outline that snaps to edges in the painting (the magnetic selection tool's edge tracing);
- by segmentation from hint strokes (the colorize mask's lazy-brush), which splits an area into regions.

The agent SHALL be able to propose a feature, which the artist keeps, adjusts or discards before it counts.

#### Scenario: Contiguous selection at native speed
- **WHEN** the agent builds the New Moscow sky from 8 seed points at 6000×4500
- **THEN** it takes under 1 second, where the plugin's Python flood fill took 22 seconds

#### Scenario: Seams baked into the painting
- **WHEN** the plugin's seam finder and Luna confirm a straight join of a pasted panel, such as the vertical edge at
  x 996 in New Moscow's sky
- **THEN** it is proposed as a feature of kind `seam`, which the painter repairs before painting near it and the artist
  sees outlined on the canvas

#### Scenario: The skyline from a rough outline
- **WHEN** the agent outlines the New Moscow skyline with 20 rough points
- **THEN** the feature's edge follows the buildings' edges in the painting, and no band of old sky is left along it

### Requirement: Spatial questions about the painting
Scripts SHALL ask:
- which features contain a point;
- which features overlap or touch a feature or rectangle;
- a feature's bounds, area and mean colour;
- a selection combined from features by name (union, intersection, difference).

Answers SHALL use the stored masks, not a new analysis of the pixels.

#### Scenario: Paint the sky but not the moon
- **WHEN** the agent asks for the selection "Sky minus Moon"
- **THEN** it gets that selection without colour picking, and a pass inside it leaves the moon unchanged

### Requirement: Protection is a feature property
A feature SHALL be markable as protected. Krita SHALL refuse agent writes inside a protected feature at the
paint-device level, and the pass result SHALL name each protected feature it was kept out of. This replaces the
plugin's protected-area masks and its erase-after enforcement.

#### Scenario: Leave the buildings alone
- **WHEN** the artist says "leave the buildings alone" and the agent's pass covers the whole canvas
- **THEN** no pixel inside any protected building feature changes, and the result lists the buildings it was kept out of

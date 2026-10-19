## Purpose

The artist makes a part or a crop of an attached reference with Krita's selection tools, so the agent follows one
thing at a time and paints only that part.

## ADDED Requirements

### Requirement: Making a part of a reference
The reference preview SHALL offer Select a part in Krita and Crop in Krita. Either SHALL open the reference as a
temporary Krita document, offer Use this part and Cancel in the panel, and close the temporary document without saving
afterwards, returning to the painting. The artist's painting and reference files SHALL NOT be changed.

#### Scenario: The sky of New Moscow
- **WHEN** the artist chooses Select a part, selects the sky with similar colour select and presses Use this part
- **THEN** a reference named "Sky (part)" is added beside the original, the size of the original and see-through
  outside the sky, and the temporary document is closed

#### Scenario: A crop
- **WHEN** the artist chooses Crop and selects the woman's head
- **THEN** a reference of that rectangle is added, named "<name> (crop)"

#### Scenario: Nothing selected
- **WHEN** the artist presses Use this part with nothing selected
- **THEN** the panel says to select the part first, and the document stays open

### Requirement: The agent paints only the part
A part SHALL be sent to the painter with the original it came from and where it sits. A transfer from a part SHALL
paint only where the part is opaque, and SHALL NOT be refused for its size, because the artist drew its boundary.
Protected areas SHALL still apply inside a part.

#### Scenario: Painting the sky from the part
- **WHEN** the artist asks Agent mode to paint the sky from "Sky (part)" on `new_moscow.kra`
- **THEN** only the sky changes, and no building, spire or tower top does

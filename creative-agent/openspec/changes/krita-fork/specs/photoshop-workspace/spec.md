## ADDED Requirements

### Requirement: Krita-Revamp's interface changes are in the fork
The fork SHALL include Krita-Revamp's changes, ported to master and Qt6, each as its own commit:
- clipping masks;
- folder-style groups;
- brush stroke previews;
- scrubby zoom;
- an instant overview;
- toolbar sizing and the smoothing slider;
- preset persistence.

#### Scenario: Clipping a shadow
- **WHEN** a Photoshop user Alt-clicks between two layers (or uses the clipping-mask action)
- **THEN** the upper layer is clipped to the one below, as in Photoshop

### Requirement: A Photoshop-like default for new installs
A new install SHALL default to Krita's Photoshop shortcut scheme and a workspace with layers, brushes and the agent
panel placed as in Photoshop. Existing Krita settings SHALL NOT be migrated without the artist's choice.

#### Scenario: First launch
- **WHEN** the fork starts for the first time
- **THEN** Photoshop shortcuts work (B brush, E eraser, Ctrl/Cmd+J duplicate layer), and the agent panel is docked

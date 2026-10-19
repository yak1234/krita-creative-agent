## ADDED Requirements

### Requirement: Scripts make brush tips and presets without a restart
Scripts SHALL create a brush tip from an image, and a preset using it, registered in Krita's resource database and
usable immediately.

#### Scenario: A cloud brush from the sky
- **WHEN** the plugin creates a tip from a material's cloud tip and a preset from it
- **THEN** the preset paints at once, with no restart, and appears in the brush list under the agent's tag

### Requirement: Merge and bake are Krita operations
Scripts SHALL merge groups exactly by projection, and bake a filter mask into its layer, each as one undo step.

#### Scenario: New Moscow's kept work
- **WHEN** the 73 kept agent groups and 10 filter masks are merged and baked
- **THEN** the canvas looks the same (difference at most 1/255), and one Undo restores them

### Requirement: Krita's painting tools are callable functions
Scripts SHALL run bucket fill and enclose-and-fill, gradients, smart patch, undoable moves, and perspective, warp and
liquify transforms on a layer or selection, each as one named, undoable step, through the same core code the tools use.

#### Scenario: Repairing a seam with smart patch
- **WHEN** the agent smart-patches a selection around a baked-in seam in New Moscow's sky
- **THEN** the join is filled from the surrounding paint in one undo step, with no tool or dialog opened

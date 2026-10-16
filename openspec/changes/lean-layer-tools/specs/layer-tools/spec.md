## Purpose

Makes layer housekeeping (hiding failed passes, finding overpaint, grading, selecting) cheap and hard to get wrong, so it takes one action instead of many and doesn't stop a batch over a layer that is already gone.

## ADDED Requirements

### Requirement: Layer settings apply to several layers in one call
`set_layer` SHALL accept `layers`: 1–50 entries. Each entry names a layer and sets any of `visible`, `opacity`, `blend_mode`, `alpha_lock`, `clip`, `name` or `style`.

Every entry SHALL be validated before any layer changes. Opacity and visibility SHALL be allowed on any unlocked layer; the other settings only on layers the agent created. A call SHALL be one pass with one canvas image, and rejecting it SHALL restore every setting it changed.

`adjust_layer` SHALL NOT be offered to the painter. An `adjust_layer` call in a resumed transcript SHALL run as a one-entry `set_layer`.

#### Scenario: Hiding ten failed passes
- **WHEN** the painter calls `set_layer` with ten entries, each `visible: false`
- **THEN** all ten are hidden as one pass, and the result has one image

#### Scenario: One invalid entry
- **WHEN** entry 3 sets `blend_mode` on an artist layer
- **THEN** no layer changes, and the error names entry 3

#### Scenario: Rejecting a bulk hide
- **WHEN** the artist rejects that pass
- **THEN** all ten layers are visible again, with their previous opacity

### Requirement: Layers can be referenced by id or exact name
A layer reference SHALL resolve as a layer id first, then as an exact layer name. A name shared by two or more layers SHALL be refused, with their ids listed.

When an entry only hides a layer (`visible: false` or `opacity: 0`) and the layer is not found, the entry SHALL be reported as `already_gone` and SHALL NOT fail the call or the batch. Any other unknown reference SHALL fail with up to five current layer names that share a word with it.

#### Scenario: A stale id in a cleanup batch
- **WHEN** a batch hides layers A, B and C, and B was removed earlier
- **THEN** A and C are hidden, B is reported `already_gone`, and the batch continues

#### Scenario: A layer named instead of an id
- **WHEN** `layer` is "Cockpit lower edge · Edge refinement" and exactly one layer has that name
- **THEN** that layer is changed

#### Scenario: An unknown layer to show
- **WHEN** an entry sets `visible: true` on a reference that matches nothing
- **THEN** the call fails without changes, and the error lists nearby layer names

### Requirement: The painter can view layers by themselves
`view_layers` SHALL return one image of up to 12 layers, each rendered alone over a checkerboard and labelled with its name and id. The image SHALL be at most 1568 px on its long side. For each layer it SHALL also return its bounds and its share of the canvas. Without arguments it SHALL show the 12 newest layers.

It SHALL NOT create a pass, save a checkpoint or change visibility.

#### Scenario: Finding overpaint
- **WHEN** the painter calls `view_layers` with four layer ids
- **THEN** it gets one labelled contact sheet of those four layers, and the pass history is unchanged

### Requirement: Filter settings and selection shapes are coerced, not rejected
`apply_filter` SHALL coerce each config value to the type Krita reports for that setting: round to int, `"true"`/`"false"` to booleans, numeric strings to numbers. The result SHALL list the coerced keys. A value that can't be coerced SHALL still fail.

Selection shapes in `select`, `fill_region` and `apply_filter` SHALL be clipped to the image. A shape that is empty after clipping SHALL fail.

#### Scenario: A fractional blur radius
- **WHEN** `apply_filter` gets `gaussian blur` with `horizRadius: 2.5`
- **THEN** the filter applies with radius 3, and the result notes `horizRadius` was coerced

#### Scenario: A polygon past the canvas edge
- **WHEN** a selection polygon has points at x = -40 and x = 6100 on a 6000 px canvas
- **THEN** the selection is the polygon clipped to the canvas

### Requirement: Filtering an artist layer uses a copy
When `apply_filter` targets an artist layer, it SHALL run in `copy` mode: it filters a copy the agent owns and hides the original. The result SHALL say so. Rejecting the pass SHALL remove the copy and restore the original's visibility. The artist's layer pixels SHALL never change.

#### Scenario: Grading the artist's sky
- **WHEN** the painter applies `hsvadjustment` to an artist layer
- **THEN** a filtered copy appears above it, the original is hidden, and the result says `mode: copy (artist layer)`

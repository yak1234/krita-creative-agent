## ADDED Requirements

### Requirement: The painter makes a material from any source
`make_material` SHALL make at most 8 greyscale tips from an area of the painting, a layer (read only), or an attached
reference or asset. It SHALL save them with the chat and return a contact sheet image. A tip SHALL NOT be cut from
inside a protected area, and the source SHALL NOT change.

#### Scenario: Clouds from New Moscow
- **WHEN** the painter makes a `light` material from the sky band of New Moscow, where the Moon is protected
- **THEN** it gets 6 soft round tips of cloud light, none cut from the Moon, and the painting is unchanged

### Requirement: Stamping is one reversible pass inside its area
`stamp_material` SHALL stamp at most 2000 dabs of a material into the given area, on one new agent layer, recorded as
one pass. Nothing SHALL land outside the area's selection. Protected areas SHALL be erased from the layer as for any
pass. The same arguments and seed SHALL give the same layer.

#### Scenario: Sky only
- **WHEN** the painter stamps 500 dabs into a selection of the sky that excludes the towers
- **THEN** no tower pixel changes, and Undo removes the stamp with its move

### Requirement: Stamped colour comes from the painting
Each dab's colour SHALL come from the canvas under it, optionally shifted toward a tint, more strongly toward the top
of the area when asked. The stamp SHALL be composited with premultiplied alpha at each dab's opacity.

#### Scenario: Moonlit tops
- **WHEN** the painter stamps with tint `#cdd7eb`, amount 0.4, toward `top`
- **THEN** the dabs near the top of the area are lighter and cooler than the dabs near its bottom, and every dab stays
  within the sky's own hue range

### Requirement: Krita needs no restart and no resources change
Materials and stamps SHALL NOT write Krita brush tips, presets or resource files.

#### Scenario: After a chat
- **WHEN** a chat made two materials and stamped them
- **THEN** Krita's brush presets and resource folders are as they were, and the materials are in the chat's folder

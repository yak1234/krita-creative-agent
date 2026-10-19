## ADDED Requirements

### Requirement: The agent is there from launch
The agent panel SHALL load with the main window. With no painting open it SHALL offer new-painting chats, which create
the `.kra` and its assets.

#### Scenario: A blank start
- **WHEN** the artist opens the fork and types "a winter street in Moscow at night" with no painting open
- **THEN** the agent creates a new painting and starts on it

### Requirement: A project view
A docker SHALL list the project folder's paintings, references, brushes, materials and generated assets with
thumbnails, and open any of them with one click.

#### Scenario: Back to a painting
- **WHEN** the artist clicks new_moscow_finished in the project view
- **THEN** it opens, and its chats are listed in the agent panel

### Requirement: Agent overlays on the canvas
The canvas SHALL draw proposed and kept protected areas, Luna's finding locations and the move in progress as
overlays, never as layers. They SHALL disappear when the move is kept or undone.

#### Scenario: A proposed moon
- **WHEN** the painter proposes protecting the Moon
- **THEN** its outline appears on the canvas until the artist keeps or discards it, and the layer stack is unchanged

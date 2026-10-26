## Purpose

The artist decides, before a run, how many AI-generated images the painter may make in a chat. The tool enforces the
number; nothing the painter or a message says can exceed it.

## ADDED Requirements

### Requirement: An AI image allowance per chat
Each chat SHALL have an AI image allowance: a whole number from 0 to 20, or no limit, set beside the time and pass
allowances and saved with the chat. A new chat SHALL take the Settings default, which SHALL be 0 on a new install. A
chat saved before the allowance existed SHALL take the Settings default when loaded.

#### Scenario: A new install
- **WHEN** an artist starts their first Autopilot chat without changing any setting
- **THEN** its AI image allowance is 0

#### Scenario: Raising it before the run
- **WHEN** the artist sets the allowance to 2 in the plan dialog and approves the plan
- **THEN** the painter may make up to 2 AI images in that chat

### Requirement: The current chat's allowance is changed in the panel
The panel SHALL show the open chat's AI image allowance and how many are used, in every mode, and SHALL let the artist
change it for that chat while the painter is not busy. The change SHALL apply from the next model request. The Settings
default SHALL NOT change a chat that is already open.

#### Scenario: Raising it in an Agent chat
- **WHEN** an Agent-mode chat with no plan has allowance 0 and the artist sets AI images to 1 in the panel
- **THEN** the painter's next move may make one AI image

#### Scenario: Changing it while painting
- **WHEN** the painter is busy
- **THEN** the control is disabled and says to pause first

### Requirement: make_asset enforces the allowance
`make_asset` SHALL refuse, before calling any image model, when the chat's allowance is 0 or used up, with an error that
says paint by hand and where the artist can raise the allowance. Each successful `make_asset` SHALL count one image.
References the artist attaches and skill scripts that process an existing image SHALL NOT count.

#### Scenario: Allowance 0
- **WHEN** the painter calls `make_asset` in a chat whose allowance is 0
- **THEN** no image model is called, nothing is charged, and the painter receives the refusal

#### Scenario: Allowance used up
- **WHEN** the allowance is 1 and one AI image has been made
- **THEN** the next `make_asset` call is refused

### Requirement: A message does not raise the allowance
A message asking for an AI image SHALL NOT change the allowance. Above the allowance, the painter SHALL tell the artist
that AI images are off or used up and where to raise the allowance, and continue by hand.

#### Scenario: Asking in chat at 0
- **WHEN** the allowance is 0 and the artist writes "use an AI image for the sky"
- **THEN** no AI image is made, and the reply says the allowance is 0 and how to raise it

### Requirement: The painter knows its allowance in every mode
The painter's instructions SHALL state the allowance and what is left in every mode that plans or paints, Autopilot
included. Skills that make assets SHALL have a hand-painted route used when no AI image is available.

#### Scenario: A sky in Autopilot at 0
- **WHEN** an Autopilot plan includes a sky and the allowance is 0
- **THEN** the sky is painted with the painting tools and no `make_asset` call is made

### Requirement: The plan shows planned AI images
A plan step that would use an AI image SHALL say so, and the plan dialog SHALL show the allowance and how many images
the chat has used.

#### Scenario: Reviewing a plan
- **WHEN** a plan's sky step would use an AI image and the allowance is 1
- **THEN** the step's text names the AI image, and the dialog shows "AI images: 1 allowed, 0 used"

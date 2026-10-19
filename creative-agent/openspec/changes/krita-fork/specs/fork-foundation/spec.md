## ADDED Requirements

### Requirement: The plugin runs on PyQt6 and PyQt5
Every plugin module SHALL import Qt through `qt_compat.py` and use scoped enum names. The Python suite SHALL pass under
both PyQt5 and PyQt6. The plugin SHALL keep working in stock Krita 5.3.3 only while the artist still paints there;
new features MAY require the fork.

#### Scenario: Both bindings
- **WHEN** the suite runs with PyQt5, and again with PyQt6
- **THEN** both runs pass, and no plugin file imports PyQt5 directly

### Requirement: The fork never touches the artist's Krita
The fork SHALL use its own application id and settings folder. Installing or running it SHALL NOT change stock
Krita's settings, resources or installed plugins.

#### Scenario: Side by side
- **WHEN** the fork is installed and run on a Mac that also has Krita 5.3.3
- **THEN** Krita 5.3.3 starts with its settings, workspace and plugin unchanged

### Requirement: Releases are GPL compliant
Every fork release SHALL publish the exact source it was built from, under GPL-3.0-or-later, with Krita's,
Krita-Revamp's and the bundled packages' licence notices, and the MIT notices of included MIT code.

#### Scenario: A release
- **WHEN** a macOS build is published
- **THEN** the source of that build is published with it, and the app's About box names the licences

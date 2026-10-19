## Purpose

Keeps every canvas change on the plugin's journalled, reversible operations, with no path that operates Krita's window directly.

## ADDED Requirements

### Requirement: The painter has no computer-use tools
The companion SHALL NOT offer tools that operate Krita's window, such as screenshots, clicks, drags, key presses or typing. It SHALL NOT ship the computer-use helper app or depend on `codex-computer-use-mcp`. The panel SHALL NOT show a Computer use option.

#### Scenario: Listing painter tools
- **WHEN** the painter's tools are listed in any phase and mode
- **THEN** none of `krita_screen`, `krita_click`, `krita_drag`, `krita_scroll`, `krita_press_key`, `krita_type_text`, `krita_set_value` or `krita_secondary_action` is present

### Requirement: A saved computer-use setting is ignored
Execution settings that contain `computer_use` SHALL load without error, and the key SHALL be dropped. No run SHALL stop because of computer use.

#### Scenario: Settings saved before this change
- **WHEN** saved settings contain `computer_use: true`
- **THEN** they load, the setting is dropped, and painting proceeds

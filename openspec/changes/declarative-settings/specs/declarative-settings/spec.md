## Purpose

Execution settings are declared once. Their defaults, validation and the panel's controls all come from that declaration, so a new setting needs no hand-written panel code.

## ADDED Requirements

### Requirement: One declaration per setting
Each execution setting SHALL be declared once in the settings schema, with:
- a key and a type (`choice` or `boolean`);
- a default;
- for a choice, its options, each a value with a label;
- a label, an accessible name, an optional tooltip and note, and an error message;
- how the panel shows it: `generic`, `custom` or `hidden`.

`executionSettings()` SHALL take its defaults and validation from the schema. It SHALL reject a value outside a choice's options, or a non-boolean for a boolean, with that setting's error message. Keys the schema does not declare SHALL be dropped.

#### Scenario: A value outside the options
- **WHEN** settings contain `assets: 'dall-e'`
- **THEN** validation fails with the image-assets error message

#### Scenario: A setting saved by an older build
- **WHEN** saved settings contain a key the schema no longer declares
- **THEN** they load, and the key is dropped

### Requirement: The panel builds generic settings from the schema
The companion SHALL send the generic settings' declarations to the panel in a `settings_schema` event before it sends the settings. For each one, the panel SHALL build a labelled combo box with that setting's options, accessible name, tooltip and note.

The settings the panel sends, how it restores saved settings, and when the controls are enabled SHALL all follow the schema. Custom settings (reasoning) keep their own controls, and hidden settings are not shown.

#### Scenario: A new setting
- **WHEN** a choice setting is added to the schema as `generic`
- **THEN** the panel shows it, sends its value when changed and restores it from saved settings, with no panel code change

#### Scenario: Restoring settings
- **WHEN** the panel receives `execution_settings` with `move_size: 'quick'`
- **THEN** the move-size control shows Quick, and no settings change is sent back

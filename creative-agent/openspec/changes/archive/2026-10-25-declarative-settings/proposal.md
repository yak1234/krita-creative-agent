## Why

Adding one execution setting (`assets`, the image-asset backend) meant editing five places:
1. defaults and validation in `execution-settings.mjs`;
2. building the panel's combo box in `creative_docker.py`;
3. connecting its signal;
4. adding it to the settings the panel sends;
5. restoring and enabling it, plus updating the smoke test.

Each new policy knob repeats this, and the panel file is already the worst-rated file for code health (1.0/10). Shortcut-Composer's config system shows the alternative: declare a setting once (`Field`), and get its type, default, parsing, change callbacks and settings UI from that declaration. Policy choices are enums whose values double as UI labels.

## What Changes

- **One schema** (`src/settings-schema.mjs`) declares each execution setting once: key, type (`choice` or `boolean`), default, options with labels, label, accessible name, tooltip, note, error message, and how the panel shows it (`generic`, `custom` or `hidden`).
- **Companion:** `executionSettings()` takes its defaults and validation from the schema. The `decisions` object keeps its own validation. Unknown keys are dropped, as before.
- **Panel:** at startup the companion sends a `settings_schema` event with the generic settings. The panel builds one labelled combo box per setting from it. Building the settings it sends, restoring saved settings and enabling the controls all loop over the schema. Reasoning stays custom (its levels depend on the model), and `native_craft` stays hidden and always true.
- Adding a setting becomes **one schema entry**, with no panel edit.

## Capabilities

### New Capabilities
- `declarative-settings`: execution settings are declared once; validation, defaults and the panel's controls come from the declaration.

## Impact

- **Companion:** new `src/settings-schema.mjs`; `src/execution-settings.mjs`; `src/studio.mjs` (emits `settings_schema`).
- **Plugin:** `creative_docker.py`: generic settings widgets built from the schema (`setting_widgets[key]`) replace the hand-written combo boxes for concurrency, move size, merge, image assets and decision checks.
- **Tests:** `execution-settings.test.mjs`, `ui_smoke.py` (widgets addressed through `setting_widgets`).
- **Risk:** the panel shows these settings only once the companion has started. They were already disabled until then.

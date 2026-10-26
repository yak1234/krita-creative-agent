## 1. Schema and companion

- [x] 1.1 `src/settings-schema.mjs`: declarations for concurrency, reasoning (custom), move_size, merge_kept, assets, routing (generic) and native_craft (hidden), with today's labels, notes and error messages.
- [x] 1.2 `executionSettings()` validates and defaults from the schema; `decisions` is unchanged. Test: rejected values give each setting's message, unknown keys are dropped, and the defaults are unchanged.
- [x] 1.3 The studio emits `settings_schema` (generic fields only) before `execution_settings` at startup.

## 2. Panel

- [x] 2.1 `creative_docker.py`: build `setting_widgets[key]` from `settings_schema`; sending, restoring and enabling loop over the schema; remove the five hand-written combo boxes.
- [x] 2.2 `ui_smoke.py`: drive settings through `setting_widgets`, and check that a schema with an extra setting gets a working control with no panel change.

## 3. Ship

- [x] 3.1 Unit, packaging and UI smoke tests; build and install. Verified: 255/255 unit, 7/7 packaging, ui_smoke (including a schema-only setting the panel shows, sends and restores); build `d1e1e671` installed.
- [ ] 3.2 After a Krita restart, check that the Agent execution settings appear and that a change is saved and restored across chats.

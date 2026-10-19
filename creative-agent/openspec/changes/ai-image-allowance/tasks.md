## 1. Allowance and default

- [x] 1.1 `settings-schema.mjs`: `ai_images` choice (`0`, `1`, `3`, `5`, `unlimited`), default `0`. Test: the default is
  0, unknown values are rejected with the setting's message.
- [x] 1.2 `studio.mjs`: `goal.limits.ai_images` (0–20 or null) and `goal.ai_images_used`; a new chat starts from the
  default; an older chat without the field takes the default on load; `setLimits` validates it. Tests for each.

## 2. Enforcement

- [x] 2.1 `assets.mjs`: `make_asset` refuses at 0 or when used up, before any image model call, with the message from
  the design; a successful call counts one. Tests: refusal at 0 makes no backend request; the second call at allowance 1
  is refused; a failed generation does not count.

## 3. What the painter is told

- [x] 3.1 Replace `assetGuidance` with `aiImageGuidance(allowance, used, backend)`, added in Agent moves, Autopilot runs
  and planning. Test: an Autopilot run's prompt states the allowance; at 0 it says not to call `make_asset`.
- [x] 3.2 Skills: a first line and a hand-painted route in `paint-sky`, `paint-scene`, `place-subject`, `fix-region` and
  `image-asset`, using only tools available without an AI image.

## 4. Panel

- [x] 4.1 Plan dialog: an AI images spin box in the allowance row ("No AI images" at 0, "No limit" option), "AI images
  used" beside passes and minutes; `set_limits` sends it. `ui_smoke.py`: set, send and restore it.
- [x] 4.2 Panel: an "AI images" control for the open chat in every mode ("AI images: 1 of 3 used"), disabled while busy,
  sending `set_limits`; kept in step with the plan dialog. `ui_smoke.py`: an Agent chat with no plan raises it from 0
  to 1, and the next request's prompt states the new allowance.

## 5. Ship

- [x] 5.1 Unit, packaging and UI smoke tests on the managed Node runtime; build, install, reload. Build `2452691d`
  live after a Krita restart (the panel changed); the owner's default is set to No limit.
- [ ] 5.2 Live: an Autopilot sky at allowance 0 is painted with no `make_asset`; at 1, exactly one AI image is made; at 0,
  "use an AI image for the sky" gets the allowance reply. Check each in Langfuse (`make_asset` count per chat).

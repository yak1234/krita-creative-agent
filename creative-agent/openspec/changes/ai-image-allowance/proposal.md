## Why

Other artists will install this plugin, and AI-generated images are a choice an artist must make, not a default the
painter makes for them. Today nothing lets them make it:

- **The backend decides the policy.** The only image setting is the backend (ChatGPT/Codex or OpenRouter). With Codex,
  Agent mode is told to "use make_asset freely for any subject, background or region that would be hard to construct
  by hand (a sky, a tree, a figure, a building)"; with OpenRouter, "only when the artist asks". Who pays has become what
  the artist wants.
- **Autopilot gets no asset guidance at all**, yet `make_asset` is offered in its plan and painting phases.
- **Skills require assets.** `paint-sky` step 2 is "Make the sky asset", with no hand-painted route; `paint-scene`,
  `place-subject`, `fix-region` and `image-asset` also call `make_asset`.

Langfuse (1 October onward) shows 3 `make_asset` calls in 1,588 tool calls, two of them a blood-moon sky made because
the `paint-sky` skill said so. Usage is low only because recent subjects (colour fields) needed none: an artist asking
for skies, trees and buildings in Autopilot would get AI images at every step without choosing them.

## What Changes

- **An AI image allowance per chat**: how many AI images the painter may make, 0 meaning hand-painted only. It is
  set beside the time and pass allowances in the plan dialog, and in the panel for the open chat in every mode.
- **A default in Settings** for new chats, declared once in the settings schema: **0 for a new install**. The project
  owner sets theirs to no limit.
- **Enforced by the tool.** `make_asset` refuses once the allowance is used, before calling any image model, and says
  how to raise it. A message in chat ("use an AI image for the sky") does not raise it: only the allowance does.
- **The painter knows its allowance** in every mode, through one instruction that replaces the backend-based guidance;
  skills take a hand-painted route when no AI image is available.
- **The plan shows where AI images would be used**, so approving a plan with an allowance is an informed choice.

## Capabilities

### New Capabilities
- `ai-image-allowance`: the artist decides, before a run, how many AI images the painter may make; the tool enforces it.

## Impact

- **Companion:** `src/settings-schema.mjs` (default), `src/studio.mjs` (allowance in `goal.limits`, `setLimits`,
  painter instruction replacing `assetGuidance`, plan steps), `src/assets.mjs` (`make_asset` enforcement and count).
- **Panel:** `creative_docker.py` plan dialog: one more spin box in the allowance row; `set_limits` sends it.
- **Skills:** `paint-sky`, `paint-scene`, `place-subject`, `fix-region`, `image-asset`: a hand-painted route.
- **Not changed:** the backend setting; references the artist attaches; skill scripts that process an existing asset.
- **Risk:** existing chats have no AI image allowance saved; they take the Settings default when loaded.

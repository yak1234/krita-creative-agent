## Decided with the project owner

- The control is an **allowance set before a run**, beside time and passes, not a policy menu. 0 = hand-painted only.
- **New installs default to 0.** The owner keeps no limit.
- **Only the allowance grants permission.** An artist's message asking for an AI image does not override it; the painter
  replies that the allowance is used up or 0, and says where to raise it.
- The concern is mainly **Autopilot**, where the artist is not watching each move; the same allowance applies in Agent.
- **The current chat's allowance can be changed in the panel**, in every mode, not only in the plan dialog: Agent chats
  usually have no plan, and the Settings default only applies to new chats.

### The panel control
- A compact "AI images" control in the Creative Agent panel, shown whenever a chat is open (Ask, Plan, Agent,
  Autopilot), reading for example "AI images: 0" or "AI images: 1 of 3 used". Changing it sends `set_limits` for the
  current chat and applies to the next model request. Like the other allowances it is disabled while the painter is
  busy ("Pause to change"), because `setLimits` refuses then.
- The plan dialog's allowance row shows the same value; changing either updates both.
- When `make_asset` is refused, the painter's reply points to this control ("raise AI images in the panel").

## How it works

### The allowance
- `goal.limits.ai_images`: an integer, 0–20, or `null` for no limit. It lives with `minutes` and `passes`, is set through
  `set_limits`, and is saved with the chat. `setLimits` validates it with the others and still refuses while busy.
- A chat without the field (made before this change) takes the Settings default when loaded.
- `goal.ai_images_used` counts images made in this chat; it is shown next to "passes · minutes used".

### The default
- One entry in `settings-schema.mjs`: key `ai_images`, a `choice` (the schema has no number type) with options
  `0` "None (hand-painted only)", `1`, `3`, `5`, `unlimited` "No limit"; default `0`. The panel builds its control from
  the schema, as for every generic setting.
- A new chat's `goal.limits.ai_images` starts from this default. Changing the default does not change existing chats.

### Enforcement
- In `make_asset`'s `execute`, before any image model is called: if `ai_images` is not `null` and
  `ai_images_used >= ai_images`, throw an error the model sees: "AI images are not allowed in this chat (allowance 0)" or
  "This chat's AI image allowance (3) is used up", followed by "Paint this by hand. The artist can raise AI images for
  this chat in the panel." Nothing is generated and nothing is charged.
- Each successful `make_asset` (`generate`, `draft` or `edit`) adds one to `ai_images_used`. A failed call does not.
- Not counted: references the artist attaches, and `run_skill_script` results (they process an existing image).
- The tool stays offered when the allowance is 0, so the refusal is explicit and the model learns why; the instruction
  below tells it not to try.

### What the painter is told
- `assetGuidance(backend)` is replaced by `aiImageGuidance(allowance, used, backend)`, added to the prompt in **every
  mode that can paint or plan** (Agent moves, Autopilot runs, planning), so Autopilot is no longer left out:
  - allowance 0: "AI images are off for this chat: paint every subject by hand. Do not call make_asset."
  - allowance left: "You may make up to N more AI images in this chat. Use one only where hand painting would fall short;
    a sky, a colour field or a background is usually better painted." plus the backend's cost note (OpenRouter costs
    money; Codex is included in the plan).
  - no limit: today's Codex wording.
- When the artist asks for an AI image above the allowance, the painter answers in chat (from the refusal) and continues
  by hand; it does not ask again for the same request.

### Skills
- Each skill that calls `make_asset` gets a first line: "If AI images are off or used up for this chat, use the
  hand-painted route", and a hand-painted route built from the existing tools: `paint-sky` uses gradient fills, clipped
  layers and `paint_recipe` strokes for clouds, then blending; `place-subject` and `paint-scene` construct subjects with
  `paint_contours` and layers; `fix-region` repaints with strokes. The asset route stays as it is for when an image is
  allowed.

### The plan
- When planning, a step that would use an AI image says so in its text ("Sky: 1 AI image, repainted with brushes"). The
  plan dialog shows the allowance beside the plan, so the artist can raise or lower it before approving.

## Calls made in the write-up (not decided by the owner)
- **Existing installs also get 0.** Saved settings have no `ai_images` key, so they take the new default; an install
  cannot be told apart from a fresh one. The owner sets "No limit" in Settings once after updating.
- **Settings offers choices, the plan dialog any number.** The settings schema has no number type, so the default is a
  choice (None, 1, 3, 5, No limit); the plan dialog's spin box takes 0–20 or no limit.
- **The tool stays offered at 0**, so a call gets an explicit refusal the model can relay, instead of a missing tool.

## Left to the builder
- Wording of panel labels and messages, within the meanings above.
- How each skill's hand-painted route is written, as long as it uses only tools available with no AI image.
- Whether the Settings control is a combo box (from the schema) and the plan dialog control a spin box.

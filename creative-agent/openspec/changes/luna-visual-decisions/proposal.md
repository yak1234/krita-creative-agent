## Why

The Creative Agent's only fast decision model (TypeSafe Jev) is text-only. The run log shows two expensive failures that no text-only check could catch:

- **Passes that damaged the painting went unnoticed until a full review.** The house run's 3,408-stroke transfer made a hard join and duplicated the architecture.
- **The loop kept painting without improving.** It ran 238 passes and 41 "continue" reviews without fixing the lower façade. The stall counter only compares failed-check IDs, and the 23 Sep notes record that pixel change is not progress.

GPT-6 Luna Decisions on OpenRouter answers typed questions about images in about 0.3–0.7 s for well under $0.001. Tests on 2026-10-09 support three uses:

- **Recorded failures in real crops of your finished paintings:** it detected the join, flat block, stripes and ellipses 12/12 each, with 0/12 false alarms.
- **The image features each use needs (synthetic tests):**
  - telling two images apart, 8/8;
  - finding where a flaw is in a 3×3 grid, 9/9;
  - grading partial improvement, which only the score question separates;
  - naming the main difference from a reference, 4/4.
- **It is weak in two places,** both of which the design avoids relying on:
  - general quality and "reject" questions (59% on the planted flaws);
  - choosing the next step.

## What Changes

- **BREAKING:** Remove TypeSafe:
  - the `@typesafe-ai/sdk` dependency;
  - `typesafe-routing.mjs` and `typesafe-credentials.mjs`;
  - the `configure_typesafe` command and the `typesafe_doppler` config key;
  - the TypeSafe key field and button in the Krita panel.

  Any key already saved in Keychain is left untouched and unused.
- Add one shared Luna Decisions client for OpenRouter (`openai/gpt-6-luna-decisions`). It authenticates with the OpenRouter credential the painter already uses, falling back to `OPENROUTER_API_KEY`. It sends images in the format the model actually receives, and maps refusals and errors to reasons for falling back.
- **Routing with the canvas:** the same operation and brush choices and gating as before, now with the attached canvas snapshot added to the text state.
- **Per-pass failure check (new):** after each paint pass, Luna compares the pass's before and after images against a checklist of recorded failure types. Each flaw it finds comes with its position on the canvas.
- **Stall check from progress (new):** when the reviewer fails the same checks again, Luna scores how much each failing check improved between the previous and current review image. That score becomes the evidence for changing strategy, instead of check IDs alone.
- One setting, renamed **Luna decisions**, controls all three: Off, Evaluate only (record and show; loop unchanged), and Guide agent (findings go to the painter, and progress scores drive the strategy-change rule).
- The panel's privacy note says that the canvas and pass images and the direction are sent to OpenRouter and OpenAI.
- The evaluation and live acceptance scripts are moved to Luna. A labelled evaluation with known answers is added for the failure checklist and progress scoring.

## Capabilities

### New Capabilities
- `luna-visual-decisions`: Fast image-based decisions for the Creative Agent — provider and credentials, routing with canvas, per-pass known-failure detection, review-to-review progress scoring, modes, gating, fallbacks and privacy disclosure.

### Modified Capabilities
<!-- None: no existing specs under openspec/specs/. -->

## Impact

- `krita-creative-agent/src/`:
  - new `luna-decisions.mjs` (client) and `routing.mjs` (moved neutral routing code plus the Luna router);
  - new checks in `visual-checks.mjs`;
  - `studio.mjs`: router construction, the pass hook after native mutations (around `:803`), the review stall logic (around `:1011`), status and diagnostics events, and removal of `configureTypeSafe`;
  - `main.mjs` and `execution-settings.mjs`.
- `krita-creative-agent/package.json` and lockfile; `scripts/build-release.py`, `install.py`, `install-release.mjs`.
- `krita-creative-agent/tests/`: routing, studio, new visual-check tests and a UI smoke test.
- `krita-creative-agent/scripts/`: the routing evaluation and live acceptance move to Luna, and the labelled visual-check evaluation (building on `evaluate-luna-defects.py`) is added.
- `krita-mcp/krita-plugin/kritamcp/creative_docker.py`: setting label, note, display of findings, and removal of the key field. Needs install and a Krita restart.
- **Data flow:** with the setting on, the canvas snapshot, the before/after images of each pass and the review images go to OpenRouter / OpenAI. Expected cost is around $0.0003–0.001 per pass, and the default is Off.
- Historical TypeSafe docs and evidence are kept as a record.

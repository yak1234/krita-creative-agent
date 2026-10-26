## Why

The goal is to be the Cursor of agentic painting. Today there is one painting mode, and it is fully self-driving. That's great for "paint this until it's done", but some artists want to steer: see a substantial move, keep it or undo it, and say what to change. The other way is to approve every stroke, which nobody wants.

Two connection problems also block a reliable product:
- Pi's Codex sign-in lapsed and broke chats. OAuth logins are not reliable here; API keys are.
- Decision models are hard-wired to one model (GPT-6 Luna Decisions) on one endpoint (OpenRouter). Meanwhile OpenRouter lists 19 decision models (5 read images), OpenAI serves its Decisions API directly, TypeSafe serves Jev, and Unsloth Studio serves your own trained model.

## What Changes

- **Modes become Ask · Plan · Agent · Autopilot.** **BREAKING** (internal mode ids; saved chats are migrated).
  - **Autopilot** is today's self-driving Agent mode, unchanged: plan, Start painting, paint until review passes or Stop.
  - **Agent** is new and collaborative. Each turn the painter makes one substantial move: a `paint_batch` sized to the request (for example about 200 swirl strokes for Starry Night's sky). It paints immediately on reversible layers, then stops and presents the move with **Keep**, **Undo** or a typed correction (**Refine**).
    - Keep continues to the next move.
    - Undo rejects every pass of that move, and the agent tries a different approach.
    - Refine paints the correction as the next move.

    Agent works straight from the chat request; an accepted plan, if any, guides it.
- **Decision endpoints.** Decisions go through endpoints, each defined by a protocol (System One or OpenAI native), a base URL, a key and a model list.
  - Built in: OpenRouter (all its decision models, listed live with their image support), OpenAI Decisions (`gpt-6-luna`) and TypeSafe (`jev-latest`).
  - Any System One–compatible endpoint can be added (for example Unsloth Studio serving your own model).
  - The artist picks the endpoint and model.
  - Visual decisions (per-pass checks, review progress, pacing) need a model that reads images, as declared by the endpoint or proven by a two-image check. Text-only models can route requests.
- **API keys only.** Chat model providers and decision endpoints are listed only when connected with an API key. OAuth logins (such as Codex) are not offered. A chat saved with an OAuth model asks for a key-based model when reopened.

## Capabilities

### New Capabilities
- `agent-modes-and-decision-endpoints`: the collaborative Agent mode, the Autopilot rename, configurable decision endpoints and models, and API-key-only connections.

### Modified Capabilities
<!-- None archived. The luna-visual-decisions and faster-agent-runs changes keep their behaviour, now running on the selected decision endpoint instead of only Luna. -->

## Impact

- **Companion:**
  - `src/studio.mjs`: modes, the Agent turn loop, Keep/Undo/Refine, migration;
  - `src/luna-decisions.mjs`, replaced by `src/decisions/` (endpoints, protocols, models, image check);
  - `src/routing.mjs`, `src/visual-checks.mjs` and `src/pacing.mjs`, which call the selected endpoint;
  - `src/runtime.mjs`: API-key-only provider lists;
  - `src/execution-settings.mjs`: the decision endpoint and model.
- **Panel:** `creative_docker.py`: the mode selector, the move card with Keep/Undo/Refine, and decision endpoint settings.
- **Keys:** OpenAI and TypeSafe keys come from the panel settings, `.env` (`OPENAI_API_KEY`, `TYPESAFE_API_KEY`) or the Keychain; OpenRouter reuses the painter's key.

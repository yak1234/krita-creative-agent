## Purpose

Offers both collaborative and self-driving agentic painting, and lets the artist choose decision models across endpoints, using only reliable API-key connections.

## ADDED Requirements

### Requirement: Four modes
The panel SHALL offer Ask, Plan, Agent and Autopilot:
- **Ask** and **Plan** SHALL keep their read-only behaviour.
- **Autopilot** SHALL behave as the former Agent mode: an accepted plan, Start painting, then painting until the review passes, the artist stops, or an allowance is reached.
- **Agent** SHALL be collaborative, as specified below.

A saved chat whose mode was the former Agent mode SHALL reopen in Autopilot.

#### Scenario: Reopening an older chat
- **WHEN** a chat saved before this change in the former Agent mode is reopened
- **THEN** it opens in Autopilot, with its plan and history intact

### Requirement: Agent mode makes one substantial move per turn
In Agent mode, each message SHALL produce at most one move: one painting call (usually a `paint_batch`) sized to accomplish the request's next visible step. Then the turn SHALL end.

The move SHALL NOT be split into per-stroke confirmations, and the painter SHALL be instructed to size it substantially. For example, a sky block-in uses recipes of a hundred or more strokes, not single strokes.

After a move, the panel SHALL show a move card with its title, its passes and the canvas, and offer:
- **Keep:** the move stays, and the agent proceeds to the next move of the request;
- **Undo:** every pass of the move is rejected (hidden, reversible), and the agent proposes a different approach;
- **Refine:** the artist's text becomes the instruction for the next move.

Agent SHALL work from the chat request; an accepted plan, when present, guides the moves. Agent SHALL NOT run the independent review automatically. The artist may ask for a review.

#### Scenario: A sky in one move
- **WHEN** the artist asks "paint the swirling night sky" in Agent mode
- **THEN** one move paints the sky as a batch of several actions with many strokes, the turn ends, and a move card offers Keep, Undo and Refine

#### Scenario: Undo a move
- **WHEN** the artist presses Undo on a move of 4 passes
- **THEN** all 4 passes are rejected, the canvas shows the state before the move, and the next turn tries a different approach

#### Scenario: Refine
- **WHEN** the artist types "less yellow, bigger swirls" after a move
- **THEN** the next move applies that correction, and no new plan is required

### Requirement: Decision endpoints and models are configurable
Decisions SHALL be sent to an endpoint chosen by the artist. Each endpoint has:
- a protocol: `systemone` (`state` plus questions keyed by name: `noul`, `choice` with `criteria`, `score`) or `openai` (`input` plus a question array: `predicate`, `choice` with `choices`, `score` with `levels`);
- a base URL;
- an API key;
- a way to list models.

Built-in endpoints SHALL be:
- **OpenRouter:** `systemone` at `https://openrouter.ai/api/alpha/decisions`. Models are listed from `GET /api/v1/models?output_modalities=decisions`, with image support read from `input_modalities`. It uses the painter's OpenRouter key.
- **OpenAI:** `openai` at `https://api.openai.com/v1/decisions`, model `gpt-6-luna`, reading images.
- **TypeSafe:** `systemone` at `https://api.typesafe.ai/v1/systemone`, model `jev-latest`, text only.

The artist SHALL be able to add a `systemone` endpoint by base URL and key (for example a local Unsloth Studio). Both protocols SHALL produce the same internal answer form, so routing, per-pass checks, progress and pacing are unaware of the endpoint. Fallback, timeout and stale-result behaviour SHALL be unchanged.

#### Scenario: Choosing a cheaper image model
- **WHEN** the artist selects `cloudflare/clef-flash` on OpenRouter
- **THEN** per-pass checks, progress and pacing use it, and their answers have the same form as before

#### Scenario: OpenAI direct
- **WHEN** the artist selects OpenAI with an OpenAI key
- **THEN** decisions are sent as OpenAI-native requests, and `predicate` answers are used as `noul` probabilities

### Requirement: Visual decisions require image-capable models
Per-pass checks, review progress and pacing SHALL run only with a model that reads images: one declared by its endpoint, or one that passed the two-image check (two images differing only in colour must change the answer).

A text-only model SHALL be usable for routing. Selecting it SHALL turn visual decisions off, with a visible note, not send them without the canvas.

#### Scenario: Text-only model selected
- **WHEN** the artist selects `typesafe/jev-latest`
- **THEN** routing uses it, visual decisions are off, and the panel says they need an image-capable model

### Requirement: Only API-key connections are offered
Chat model providers and decision endpoints SHALL be offered only when connected with an API key. OAuth-authenticated providers SHALL NOT be listed or used. Keys SHALL never appear in traces, logs or diagnostics.

#### Scenario: A lapsed OAuth login
- **WHEN** Pi has an OAuth login for a provider (for example Codex)
- **THEN** that provider's models are not offered, and a chat saved with one asks the artist to choose a key-based model when reopened

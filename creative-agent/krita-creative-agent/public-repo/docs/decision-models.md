# Decision models

Some choices in a run are better made by a fast classifier than by a chat model writing text. Examples: *did this pass introduce a seam?*, *is this plan step done?*, *which operation fits this request?*. These use a **decision model**: given a state (text and images) and typed questions, it returns calibrated probabilities instead of prose.

## Question types

The format is shared by OpenRouter's Decisions API and Unsloth decision models:

| Type | Answer | Example |
|---|---|---|
| `noul` | probability that a statement is true | "AFTER newly looks hard-edged or poster-like" |
| `choice` | one option from a fixed set, with probabilities | `next`: `continue_focus` / `next_step` / `request_review` |
| `score` | a level on an ordered rubric | progress 0–3 on the current step |

## Endpoints and models

Choose them in the panel under **Decision endpoint** and **Decision model**.

| Endpoint | Protocol | Models | Key |
|---|---|---|---|
| OpenRouter | System One, `https://openrouter.ai/api/alpha/decisions` | Live from `GET /api/v1/models?output_modalities=decisions` (19 models, 5 declaring image input, as of October 2026) | The painter's OpenRouter connection |
| OpenAI | OpenAI native, `https://api.openai.com/v1/decisions` | `gpt-6-luna` | `OPENAI_API_KEY` in `.env`, or **Set key…** |
| TypeSafe | System One, `https://api.typesafe.ai/v1/systemone` | `jev-latest` (text only) | `TYPESAFE_API_KEY` in `.env`, or **Set key…** |
| Custom | System One, any HTTPS or local URL (e.g. Unsloth Studio `http://localhost:8888/v1/systemone`) | From its `/models` list | Optional |

`src/decisions/protocols.mjs` translates OpenAI's format (`predicate`, `choice` with `choices`, `score` with `levels`, answers as an array) into the System One form, so the code that uses decisions never knows which endpoint answered.

**Image support is measured, not assumed.** Before a model is used for visual decisions, the companion sends two images that differ only in colour, and the answer must change. On OpenRouter in October 2026:
- **Pass:** `openai/gpt-6-luna-decisions`, `perplexity/pplx-decider-v1.1-27b`, `cloudflare/clef-omni`.
- **Fail:** `cloudflare/clef` and `cloudflare/clef-flash` declare image input but answer identically.

Models that fail, and text-only models, can still route requests; visual checks and pacing turn off for them.

## Where they are used

| Use | Module | Questions | Effect in Guide mode |
|---|---|---|---|
| Routing | `routing.mjs` | operation and brush `choice` | Advice to the painter, at confidence ≥ 0.8 |
| Per-pass defects | `visual-checks.mjs` | 6 × `noul` (seam, duplicate band, flat block, stripes, pasted ellipses, hard graphic) + location `choice` | Findings returned with the pass |
| Review progress | `visual-checks.mjs` | `score` per repeated failing check | Strategy change when progress stalls |
| Pacing | `pacing.mjs` | `next` `choice` + `progress` `score` | Host advances steps and calls reviews |

The setting **Luna decisions** has three values:
- **Off:** no requests;
- **Evaluate only:** record and display, change nothing;
- **Guide agent:** act on the decisions.

Every decision has a 4-second timeout and falls back to "change nothing".

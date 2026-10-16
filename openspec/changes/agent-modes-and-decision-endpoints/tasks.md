## 1. API keys only

- [x] 1.1 `listModels`/`listProviders` and model selection skip providers whose credential is not an API key. A saved chat on such a model reopens asking for a key-based model. Verify with a test using a fake model runtime holding an OAuth credential.

## 2. Decision endpoints

- [x] 2.1 `src/decisions/protocols.mjs`: `systemone` and `openai` request builders and answer normalizers (predicate → noul, choices → choice with probabilities, levels → score). Verify with unit tests over recorded request and response shapes.
- [x] 2.2 `src/decisions/endpoints.mjs`: built-in OpenRouter, OpenAI and TypeSafe endpoints plus custom `systemone` endpoints; key resolution (painter key, `.env`, environment, Keychain); live model listing with image support; a two-image check. Verify with tests using a fake fetch.
- [x] 2.3 Replace `LunaClient` with a `DecisionClient` for the selected endpoint and model. Routing, checks, progress and pacing are unchanged apart from the client, and image-requiring decisions turn off for text-only models. Verify that the existing Luna tests pass on OpenRouter, plus new tests for OpenAI and a text-only model.
- [x] 2.4 Panel settings: endpoint and model pickers (live list, "reads images" or "text only" labels), key field per endpoint, and the image check. Verify with the UI smoke test.
- [x] 2.5 Live check (2026-10-10). Two-image check on OpenRouter: Luna, pplx-decider and clef-omni read images; clef and clef-flash declare image input but answer identically for orange and green, so visual decisions now need a passed check. OpenAI direct: gpt-6-luna reads images, and choice and score answers normalize correctly. TypeSafe jev-latest routes text ("move", confidence 1.0) and is refused visual decisions. Original task: one decision on each built-in endpoint that has a key (OpenRouter Luna and clef-flash, and OpenAI if an OpenAI key is set), plus the two-image check on the image models.

## 3. Modes

- [x] 3.1 Rename the self-driving mode to `autopilot` throughout; migrate saved `agent` chats on load. Verify that all existing tests pass with the rename and a migration test.
- [x] 3.2 Agent mode: one move per turn (the turn ends after the first painting call), move records (`goal.moves`: id, title, pass ids, status), Keep / Undo (reject the move's passes) / Refine, and batch-sizing instructions. No automatic review. Verify with studio tests for each action.
- [x] 3.3 Panel: mode selector Ask · Plan · Agent · Autopilot, and a move card with Keep, Undo, Refine. Verify with the UI smoke test.
- [ ] 3.4 Live check on a disposable document: an Agent move for a night sky is one batch with 100+ strokes; Undo hides it; Refine changes the next move.

# Validation record

This document records the earlier **0.1 live prototype**, including its defects and fixes. It does not verify the 0.2 product redesign. Current candidate, model, test and live-build evidence is tracked in [PRODUCT_GOAL_PROGRESS.md](PRODUCT_GOAL_PROGRESS.md).

Date: 2026-09-11. Target: macOS, Krita 5.3.3 (git 858d352), existing bridge 2.3.0, Pi coding-agent SDK 0.84.3.

## Automated checks

- Six Node tests passed, including a real Pi SDK tool loop against a local simulated image-capable provider. Image-bearing messages and tool results were verified; no real provider credits were used for this test.
- Eight native policy tests passed: wrong-document and wrong-session rejection, whole-pass validation before mutation, unknown fields, duplicate requests, changed arguments under a reused operation ID, original-layer protection, and preservation of partial-failure status.
- Python modules and Node entry points passed syntax checks.

## Live activation findings

- Creative bridge health responded from the running Krita instance after adding the creative methods: version 0.1.0, native paths enabled, Krita 5.3.3.
- Registering a new docker factory did not populate the already-open window's docker menu. The activation script was extended to instantiate a docker in that window; normal restart uses factory registration.
- The first panel class accidentally named its incoming-message method `event`, conflicting with Qt's virtual event method. Loading it opened a Python exception dialog and left the application unresponsive. The method was renamed to `handle_event` in both workspace and installed source.
- The canvas captured before activation was blank. A restart was not attempted without confirmation because other unsaved documents could not be verified while the application was unresponsive.

## Restart and live panel verification

- The user authorized restarting Krita. After the restart, the installed **Creative Agent** docker appeared under **Settings → Dockers**. Krita disables this menu on its welcome screen; opening a scratch canvas enabled it.
- The corrected panel also passed a separate offscreen PyQt5 construction check, model selection, transcript updates, and busy/idle control checks (`tests/ui_smoke.py`).
- The actual native sidebar was opened on the right of Krita. **Start assistant** connected successfully to the Pi companion and populated models using the existing Pi authentication file. DeepSeek V4.1 Flash through OpenRouter was selected.

## Live DeepSeek painting run

Study: `output/01c7851b-e487-421b-bfad-3805f337d152/`, started 2026-09-11 at approximately 05:41 UTC. Provider/model: `openrouter` / `deepseek/deepseek-v4.1-flash`.

The prompt requested a short Rothko-inspired color-field study and explicitly limited the agent to two painting passes. It did not supply stroke coordinates or a reference image. The agent selected `b) Airbrush Soft`, painted six curves for an upper field and four for a lower field, received a canvas image after each pass, and described visible shortcomings before finishing. The panel streamed the conversation and returned to **Ready for your next direction**, with **Send direction** enabled.

- `checkpoint-001.kra`: initial canvas, two layers.
- `checkpoint-002.kra`: upper field, three layers.
- `checkpoint-003.kra`: lower field added, four layers.
- All three `.kra` archives passed ZIP integrity checks and contained `maindoc.xml`, expected layer names, and a merged image.
- The persisted Pi session records the initial image, an observation image, and both painting-result images as image content. No tool error appeared in the run.
- A separate fresh observation through the existing artist MCP showed both painted layers. Its configured painting-name label was stale from a previous project; the canvas image and layer IDs were used to identify the actual study.

Observed result: two legible stacked fields with a gap, but very blurred edges, horizontal banding, low saturation, and a cream ground instead of the requested stronger ochre. DeepSeek noticed several of these problems. The two-call limit intentionally left them unresolved.

This verified the first native UI → Pi → provider → MCP → brush → saved checkpoint → visual feedback path. At that checkpoint, the Stop button's live behavior was untested and the compact sidebar needed layout refinement. The paired guided-versus-independent artistic experiment remains pending.

## Chat interface and single working file update

The user reported an apparent save stall during study `88f89b15-4bdd-444f-a27d-75931c4dea84`. Its last paint call was recorded at 06:06:12.187 UTC and its successful tool result at 06:06:12.699 UTC: about half a second for the complete paint/save/observation round trip. The sidebar still showed **Painting and saving a pass…** several minutes later because the previous runtime did not update that label after tool completion or display thinking activity. The evidence establishes a stale status label; it does not establish whether the provider was silently reasoning or stalled. Clicking Stop ended the run promptly, preserving the painting.

Changes installed in the running Krita window without restarting the application:

- Chat now occupies most of the sidebar, with separate labeled messages, a clear composer, Enter-to-send, Shift+Enter for a newline, and Send/Stop together.
- Painting setup and API settings are in a collapsible, scrollable Options area. The duplicate canvas preview was removed. Message wrapping and card sizing were checked offscreen and in the live window.
- Activity distinguishes waiting, thinking, writing, preparing a tool call, painting strokes, saving, and reading the updated canvas. Completed painting actions get a short conversation entry. Elapsed activity time and the last save time are visible.
- A 90-second model-silence watchdog stops a request with a visible explanation. Incoming model updates reset it; native operations are excluded. The existing ten-minute run limit remains. Provider errors are preserved rather than replaced with a ready message.
- Saves now update one `painting.kra` per study; observations are stored in hidden `.previews`. Existing numbered checkpoints remain intact. Krita's normal backup behavior can still retain a backup of the working file.
- Saved conversations can be rebound to the matching open study. The update restored the user's existing Pi conversation and document, then continued with a read-only live model request.

Verification: nine Node tests and nine native policy tests passed. The Node tests cover silence timeout, native-operation exclusion, error preservation, actual Pi image/tool flow, and restoring a saved conversation without making a model request. The Qt smoke check covers message visibility, no horizontal overflow, chat area allocation, controls, and saved-file status.

In live Krita, the restored DeepSeek conversation answered a two-sentence request to inspect the canvas without painting and returned to **Ready for your next message**. Two further native saves using unchanged layer opacity returned the same `painting.kra` path. The `.kra` file list was identical before and after those saves. ZIP integrity passed, and the saved merged PNG was byte-identical to the user's previous `checkpoint-004.kra`. Evidence: `output/single-file-live-check.json`.

The model watchdog was tested with a short configured timeout in an isolated harness; no deliberate 90-second paid-provider stall was induced. Goal mode remains a research proposal and is not enabled by this UI update.

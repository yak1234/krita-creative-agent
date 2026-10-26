## 1. Companion

- [x] 1.1 `auto_approve` setting in `settings-schema.mjs` (Off · Immediately · 10 · 30 · 60 s), validated and in the panel schema. Verify: `auto-approve.test.mjs`, `execution-settings.test.mjs`, `ui_smoke.py`.
- [x] 1.2 `src/auto-approve.ts` (strict): delays, card kinds, `autoApproveRecord`; `main.mjs` `auto_approved` → `StudioRuntime.recordAutoApprove` → diagnostics row `auto_approve`. A malformed record is ignored, never an error (an error would give a card back).
- [x] 1.3 `recommended` on the choice cards where a default is safe: the stage card (The whole plan), a close-up (Use the close-up there), the painter's `ask_question` (You decide), the select-area card (Find it for me; Use this once the shapes model found the outline). Verify: plan-stages, closeups, paint-only-here and studio tests.

## 2. Panel

- [x] 2.1 `kritamcp/auto_approve.py`: one countdown at a time, injectable clock, owner held weakly; `cancel` (artist action: the card is declined), `drop` (the card went or the setting is Off), at most two answers per card (a refused Met is offered once more).
- [x] 2.2 `creative_docker.py`: offers for a finished plan step, a move, the Sharpen offer and review, a question or close-up with a recommended option; the countdown on the Now card, the move card, the chat card and the status line; cancel hooks on Undo, Keep, Redo (plan list), Stop, typing, sending, card buttons, editing the plan, Start painting, protection and shapes-model answers; Met and Keep wait while the agent paints and count again after.
- [x] 2.3 Quick switch beside the status line; while painting it applies at once and is saved at the next pause.
- [x] 2.4 `tests/ui_panel_auto_approve.py` under PyQt5 and PyQt6 (in `agent/ci.sh`).

## 3. Live

- [ ] 3.1 New Moscow copy, Auto-approve 10 s: Start painting, then hands off to the end; Undo during a countdown leaves the card waiting; Diagnostics show one `auto_approve` row per answer.

## Notes: every card that waits, and whether it auto-answers

| Card | Where | Auto-answer |
|---|---|---|
| Finished plan step "Finished · keep it?" (Met / Redo), also after a move's size limit | plan_steps.py, plan-steps.ts | **Met** |
| Move card outside a plan (Keep / Undo), also "reached its size limit" | creative_docker.py move bar | **Keep** |
| Sharpen goal offer (Sharpen / Use as is) | goal-sharpen.ts | **Sharpen** |
| Sharpen review (Use sharpened / Keep original) | goal-sharpen.ts | **Use sharpened** |
| Painter's question (`ask_question`) | studio.mjs | **You decide** (recommended) |
| Stage card "Which stages should the plan hold?" | plan-stages.ts STAGE_CARD | **The whole plan** (recommended) |
| Close-up question (Use the close-up there / Not this close-up) | closeups.ts | **Use the close-up there** (recommended) |
| Select-area card on a step (Find it for me / Select with Freehand / Use my selection / Paint everywhere) | paint-only-here.ts | **Find it for me** (recommended); with a found outline **Use this** |
| Start painting / Resume | panel | never: the artist starts the run |
| "What next?" at the end of a folder plan | studio.mjs refineNextQuestion | no: a line in the chat with no buttons (typed answer) |
| "Add a step for … to the plan?" (Add the step / Not now) | studio.mjs | no: a keyword guess at what the artist typed |
| "PLAN.md was edited … Follow the edited plan?" | studio.mjs | no: replaces the plan state |
| Requirement change "Change X to Y?" | studio.mjs | no: needs explicit acceptance |
| paint_accents past 150 accents | studio.mjs askAccents | no: a deliberate confirmation |
| Protected area proposed (Keep / Adjust / Discard) | creative_docker.py | no: the artist's protection |
| Shapes model download (Download / Not now) | shapes/chat.ts | no: a download outside model calls |
| Folder study of a big folder | folder_study_panel.py | no: spending outside painting |
| Inspect result / Continue after inspection (uncertain operation) | creative_docker.py | no: the artist checks the canvas |
| Locate painting (needs relink), Use this canvas, Redo's "what to change" field | creative_docker.py | no |

# Plans for a single goal image

Status: approved by the artist (2026-10-25), built on branch `agent/single-plans`; the live check is open.

## Why

Live test, 2026-10-25 (6000x4500): one goal image attached (no project folder) and the request "Paint this scene from
the goal image: an underpainting, the finish, then refine it to the goal. Then add to it: falling snow over the whole
scene, and fresh snow settled on the shoulders, hats, the posts and the rooftops". The agent never proposed a plan: it
painted one stage per message, needed "continue" each time, skipped refine-to-goal and forgot the snow. Folder plans work
well (the plan card, Met / Redo / Skip, auto-approve).

The artist: "Should plans work differently for single" → single images get plans too; "Should Luna decide if it's a
thing request or multipart request" → "Yes".

## Goals

1. **Luna decides plan or not.** Every Agent message already gets one Luna reading (`message-reading.ts readMessage`).
   In a single-image chat it also answers one choice, `plan_steps`: one thing, or several steps (stages and/or
   additions)? Same call, no new request. The policy is the stage policy's (`plan-stages.ts planOrNot`): Luna acting
   (Decision checks on Guide) and sure (0.7) decides; otherwise the keywords (`severalNamed`: two stages or the whole
   painting, "then" / "after that", a list of two or more, a stage or part with an addition, two additions); Luna acting
   but unsure and no keyword → a small card "Plan it step by step" / "Just do it", recommended "Plan it step by step"
   (Auto-approve takes it). Luna off or not acting and no keyword → one move, as before.
   - "make the sky warmer" → one thing (keywords name nothing; Luna sure "one").
   - the request above → a plan (two stages and "then", two additions).
   - "add a little snow" → one thing (one addition).
2. **A plan for a single goal image**, the same machinery as a folder plan: a planning turn (`propose_plan`, the
   Planner model), the plan card, Start painting, Met / Redo / Skip, auto-approve. Its stages are the ones the request
   names, with the folder plan's kinds and order rules (Underpainting, Finish, Refine to the goal, Accents). No
   "Refine: <parts>" groups by default (no element files); a part the request names ("refine the face and the soldiers")
   becomes a "Refine: <part>" step, found with Find it on the goal image (the existing refine-part path, the part's name
   as the step's part).
3. **Additions:** a new step kind `addition`, "Add: <thing>", for content the goal does not have (falling snow, settled
   snow, a bird): after the copy stages, before Accents. The painter chooses its tools; an Add step may name any known
   painting tool (a `paint_snow` tool once the snow tool lands: checked against the known tool list as `stepTool` does).
   Its done_when restates the addition ("Added as the artist asked: ..., painted fully ..., not a token few marks"), and
   the host keeps every addition the request named even when the planner forgets one.

## Where it lives

- `message-reading.ts`: the `plan_steps` question (only when `plan: true`), `Reading.plan`.
- `plan-stages.ts`: `planOrNot`, `severalNamed`, `additionsNamed`, `refinePartsNamed`, `additionStep`, `PLAN_CARD`;
  `folderPlanSteps(stages, groups, {additions})`; `shapePlan(..., {single})` keeps and restates additions.
- `project-folder.ts`: the `addition` kind (also read from an "Add:" title).
- `studio.mjs`: `singlePlanTurn` (before the move), `planSingle` (the planning turn, as `planFolder`), `SINGLE_PLAN`
  (the planner's instructions with `single_plan_draft`), the Add step's move instructions.
- **Storage:** the plan lives on the chat's goal (`goal.brief`, `goal.plan_stages`, `goal.single_plan` with the request,
  its parts and additions), saved with the chat like any plan. Its steps carry ids (`withStepIds`), so Met, Redo and
  Skip follow them. No PLAN.md: without a project folder there is no artist folder to write it in, and writing next to the
  goal image would put files in the artist's folders unasked. (A folder without elements keeps its PLAN.md as before.)

## Non-goals

- No snow tool here (branch `agent/snow` builds it); an Add step only names a tool when it exists.
- Start painting is still the artist's (auto-approve never presses it).
- No stage card for a single image: a planned request naming no stage gets the full plan (or only its parts and
  additions on a canvas already underpainted); the artist sees the plan before Start painting.
- No panel change: the plan-or-not card is the existing question card.

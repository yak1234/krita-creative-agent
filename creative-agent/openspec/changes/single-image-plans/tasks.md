# Tasks: single-image plans

## 1. Plan or not

- [x] 1.1 `readMessage({plan: true})` adds the `plan_steps` choice (one / several) to the same decision; `Reading.plan`. Verify: `single-image-plans.test.mjs` (one call, criteria).
- [x] 1.2 `planOrNot`: Luna acting and sure decides, the keywords (`severalNamed`) otherwise, `PLAN_CARD` when unsure with no keyword; one move with Luna off and no keyword. Verify: the three examples and the fallbacks.
- [x] 1.3 The card: "Plan it step by step" (recommended, for Auto-approve) / "Just do it" (paints the held request). Verify: `studio.test.mjs` single goal image tests.

## 2. The plan

- [x] 2.1 `singlePlanTurn` in Agent mode on a goal image without a folder plan: plan, ask, or paint as before; a draft is revised by the next message; a plan in progress takes messages as corrections. Verify: studio tests.
- [x] 2.2 `planSingle`: the planning turn with `single_plan_draft`, the host's draft when the planner proposes nothing, stored on the goal with step ids and no PLAN.md. Verify: studio tests.
- [x] 2.3 Start painting approves a single plan and paints its first step; Met / Redo / Skip as for any plan with ids. Verify: studio test.
- [x] 2.4 Parts named to refine become "Refine: <part>" steps, found with Find it by the part's name (`refinePartArea`). Verify: `single-image-plans.test.mjs`; live check open.

## 3. Additions

- [x] 3.1 The `addition` kind, "Add: <thing>", before Accents; `additionStep` restates the addition in done_when. Verify: unit tests.
- [x] 3.2 `shapePlan` keeps every addition the request named (a forgotten one comes back), restates a token done_when, keeps the planner's words and tool. Verify: unit and studio tests.
- [x] 3.3 An Add step's move: the artist's request, its tool when known (`paint_snow` once it exists), else the painter's choice. Verify: studio test.

## 4. Live check (open)

- [ ] 4.1 The Dostoevsky request on one goal image: the plan card shows Underpainting, Finish, Refine to the goal, Add: falling snow ..., Add: fresh snow settled ...; Start painting runs it hands-free with Auto-approve.
- [ ] 4.2 "make the sky warmer" paints at once; "add a little snow" paints at once; an unsure message shows the card.
- [ ] 4.3 "refine the face" in a planned request: its step finds the face on the goal image.

# The plan follows the request: tasks

## 1. Stages from the request — branch agent/plan-request
- [x] 1.1 Luna's message reading (the same single call) answers the plan's stages when a folder plan is made: the whole painting, only some stages, or neither; and for each of underpainting / finish / refine / accents whether it is asked for
- [x] 1.2 Keyword fallback (negated clauses ignored); when Luna is on Guide and unsure and the keywords name no stage, the plan card asks (Underpainting only / Underpainting and finish / The whole plan)
- [x] 1.3 The host builds the steps from the answer with the order rules (an underpainting before anything that needs one, Refine only after a whole-picture Finish, Accents last); "paint the underpainting" -> one step; "paint it like the goal" -> the full plan
- [x] 1.4 A later request adds the next stages to an approved plan ("now the finish"); the end of a plan offers the stages not yet in it

Builder's notes (section 1): `message-reading.ts` readMessage takes `stages: true` while a folder plan is made and adds five
questions to the same decision: `plan_scope` (whole / stages / neither) and a noul a stage. `plan-stages.ts` stagePolicy: on
Guide and sure (SURE 0.7) Luna decides (whole -> every stage; stages -> those it is sure of); neither, or Luna off, failed or
on Evaluate: the keywords (stagesNamed: underpaint/block-in/lay-in, finish/blend (not "start to finish"), refine/detail,
accents/highlights/glints; whole thing / like the goal / everything / full plan; a clause with no/don't/skip/later names
nothing), and a message naming no stage gets the full plan as before (nothing paints before Start painting). Only Guide +
unsure + no keyword shows the plan card (STAGE_CARD: The underpainting only / Underpainting and finish / The whole plan),
answered through the existing goal.question path (`plan_stages`). orderStages adds an underpainting before any other
stage and a Finish before Refine unless already ticked in this chat, and says why in the status line. propose_plan in a
folder turn is shaped by the host (shapePlan): only the draft's stages, in order, the planner's titles kept when they still
read as the same kind, element steps after the stages, a guides step after the underpainting. A later message on an
approved plan (studio folderStageRequest) adds the stages the plan lacks ("Now the finish."), approved since asked for; a
message that names an element ("Refine the Kremlin towers") is the element request, not the refine stage. The end of a plan
offers the stages not in it, then the elements.

- [x] 2.1 The full plan: after Finish one "Refine: <group>" step per group of the folder's elements, then Accents; grouping rule documented
- [x] 2.2 Steps carry `kind` (and `parts`, `tool`); folderStepKind reads the kind first, titles second (old PLAN.md files keep working; "Refine: ..." titles are refine-part steps)
- [x] 2.3 A refine-part step finds its area (Find it on each part's name, the union) and runs refine_to_goal there; when Find it fails the card asks for a selection (Freehand) instead of refining the whole picture

Builder's notes (section 2): `refine-parts.ts`. Grouping rule: the numbered elements in their folder order, neighbours
together: up to 4 elements one group each, more ceil(n/2) groups clamped to 4-7, earlier groups one larger (12 -> 6 pairs,
17 -> 3,3,3,2,2,2,2). The planner may regroup by meaning in its proposal; kept only when every element is in exactly one of
1-7 groups. Steps carry `kind`, `tool`, `parts` (briefSchema, normalizeBrief, briefFromPlan by identity); folderStepKind
reads `kind` first, then "Refine: ..." titles (refine_part), then the old title rules, so older PLAN.md files keep their
kinds. A refine_part step with no area: studio refinePartArea runs proposeArea (Find it) on each part's name, joins the
outlines (unionFound, a found-<hash>.png in .shapes) and adopts it as the step's own area (auto: cleared at the next
prompt, as Autopilot's); any part not found -> the selection card (no proposal: Find it for me / Select with Freehand / Use
my selection / Paint everywhere); Paint everywhere is the artist's choice and then refines the whole picture. Not built:
Autopilot does not run refine_part areas (it paints the step without an area; Agent mode is what the plan targets).

Builder's notes (section 3): `tool-catalogue.ts`; painting_tool_help takes an optional `name` and is offered in plan turns.
No name while planning: the four stages with tool, does, needs, rough time and the other tools in one line; no name while
painting: the plugin's toolbox help as before; a name: description, parameters, stage and the skills whose SKILL.md names
the tool. Times scale the New Moscow measurements (27 MP) by pixel count: underpainting 4.5-10 min (live), Finish 60-72 s,
Refine to the goal 5-7 min whole (6 min live, 161 regions) and per part by its share plus Find it 1.7-5.8 s, accents
15 s-1 min. Lookups are recorded (`planner_tool_help`). Each step's tool is checked in shapePlan (stepTool: must be one of
the painter's tools and fit the kind, else the kind's own tool; notes in `folder_plan_shaped`).

Builder's notes (section 4): `planner_model` (settings-schema type 'model': 'painter' or a provider/model route; the
panel's options come from panelSchema({models}): connected interactive models measured in model-resolutions.json or the
artist's resolution-probe.json, the painter's, and the saved value). Plan turns (planFolder and Plan-phase turns, not
Ask) run in the same painter session switched with Pi's `session.setModel` and switched back in a finally; the session
keeps one transcript. The tool list and reasoning level follow the session's current model; a text-only planner gets no
images. An unconnected route plans on the painter with one status line. tests/ui_smoke.py lists the new generic setting.

- [x] 3.1 painting_tool_help in plan turns: without a name a catalogue of the stages and tools (what each does, rough time on this canvas from measured numbers, what it needs); with a name the full description and skill text
- [x] 3.2 The planning prompt asks the planner to look up the stages it uses; each step records `tool`, checked by the host (exists and fits the step's kind, else the kind's own tool)

## 4. Planner model setting
- [x] 4.1 Settings: Planner model (default: the painter's); plan turns (planFolder, Plan-phase turns) use it, painting turns keep the painter

## 5. Comparison by model
- [x] 5.1 Tool-calling check (propose_plan, painting_tool_help), the resolution probe (model-resolutions.json) and one real New Moscow planning turn for "paint the underpainting" and "paint it like the goal" each, for deepseek-flash (the painter now), deepseek/deepseek-v4.1-flash, z-ai/glm-5.3-flash and qwen/qwen3.8-flash; comparison page and raw JSON

Builder's notes (section 5): `scripts/planner-comparison.ts` drives the real StudioRuntime (fake bridge, empty 6000 x 4500
canvas, a copy of `benchmark-runs/test-assets/moscow-painting-assets`, Decision checks off so the keywords give the stages)
with painter deepseek/deepseek-flash and the Planner model set to each candidate; plus the app's route check
(ModelCapabilities.verify, forced) and a Plan-mode tool check (painting_tool_help paint_finish, then propose_plan). Probes
recorded in src/model-resolutions.json: deepseek-v4.1-flash 1536 (crops 1536), glm-5.3-flash 1024 (it failed 1536 and
2048), qwen3.8-flash 2048 (crops 1536). Every candidate passed the route check and made both plans itself with the
expected stages: 1 step for "paint the underpainting", 9 for "paint it like the goal" (underpainting, Finish, 6 refine
pairs, Accents); the host corrected nothing; no planner regrouped the parts. Two turns each: deepseek-flash 36 s $0.021,
deepseek-v4.1-flash 63 s $0.014, glm-5.3-flash 70 s $0.004, qwen3.8-flash 143 s $0.016. Fix from it: deepseek-v4.1-flash
wrote a sentence as a step's tool and was refused 14 times by a 60-character limit; the limit is 400 now (the host keeps
only a painting tool's name), and its re-run tool check passed first time. Recommendation (comparison page): glm-5.3-flash
as planner (most specific per-part done_when, cheapest), to be confirmed on a live plan; the shipped default stays "Same as
the painter".

- [ ] 6.1 Live in Toska on a copy (lead): "paint the underpainting" plans one step; "paint it like the goal" plans the full plan with a refine step per part; the planner's lookups in the diagnostics; the Planner model setting in the panel; send the comparison

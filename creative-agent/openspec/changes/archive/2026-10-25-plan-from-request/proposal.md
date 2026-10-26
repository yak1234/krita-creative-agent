# The plan follows the request: chosen stages, a refine step per part, a planner that knows the tools

Status: APPROVED by the artist (2026-10-24: "yes please and send model comparison by model").

## Why

A project folder always gets the same four steps (underpainting, Finish, Refine to the goal, Accents), whatever the
artist asks: "paint the underpainting" still queues Finish, Refine and Accents. The painter only rewords a fixed draft
(FOLDER_PLAN, defaultFolderSteps) and, in its planning turn, cannot see what the painting tools do (their descriptions
are only offered in painting turns). Refine to the goal is one 6-minute step the artist cannot judge part by part. The
planning model is the painter model (deepseek-flash), a small model; the artist wants to try stronger planners
(z-ai/glm-5.3-flash, qwen/qwen3.8-flash) for planning only.

## Goals

1. **Stages from the request.** Which stages the plan holds follows what the artist asked: "paint the underpainting" ->
   Underpainting only (then the host asks what next); "underpainting and finish" -> those; "paint the whole thing / like
   the goal" -> the full plan. Luna (the decision model, already reading each message) answers typed questions about the
   stages asked for, the parts named and whole-painting vs one step; keyword rules are the fallback; when unsure the plan
   card asks. The host keeps the order rules (Refine only after a whole-picture Finish, Accents last, etc.).
2. **A refine step per part** in the full plan: after Finish, one "Refine: <part>" step per group of the folder's
   elements (e.g. sky and moon; historic buildings and domed church; Kremlin towers; modern skyline; bridge and river;
   street, car and woman), each finding its area (Find it) and running refine_to_goal there, then Accents. Each step has
   Met / Redo / Skip.
3. **The planner looks up the tools.** In plan turns the planner gets painting_tool_help: without a name, a catalogue of
   the painting stages and tools (what each does, rough time on this canvas, what it needs); with a name, the tool's
   full description and skill text. The planning prompt tells it to look up the stages it uses; each step records the
   tool it will use, and the host checks it exists and fits.
4. **A planner model setting.** Plan turns can use a different model than painting (Settings: Planner model, default
   the painter model).
5. **Comparison by model.** Before choosing a default: a tool-calling check, the resolution probe and one real New
   Moscow planning turn each for deepseek-flash (current), deepseek/deepseek-v4.1-flash, z-ai/glm-5.3-flash and
   qwen/qwen3.8-flash through OpenRouter; the plans side by side with time and cost, sent to the artist.

## Done when

On a copy of New Moscow in Toska: "paint the underpainting" plans one step; "paint it like the goal" plans the full
plan with a refine step per part; the planner's tool lookups show in the diagnostics; the comparison is sent.

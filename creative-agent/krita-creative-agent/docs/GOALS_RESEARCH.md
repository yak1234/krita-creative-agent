# Goals for the Krita Creative Agent

Researched 2026-09-11. Recommendation: adapt the already-installed `pi-goal-x` as an optional goal mode in the native panel. It can improve continuity and completion discipline; improved painting quality remains an experimental question.

## What is installed and active

- Pi's user settings list `npm:pi-goal-x`.
- The installed package is `pi-goal-x` **0.27.4**, a fork of `@capyup/pi-goal`. Its entry point is `~/.pi/agent/npm/node_modules/pi-goal-x/extensions/goal.ts`.
- The Krita companion uses Pi SDK **0.84.3**. Its resource loader deliberately excludes ambient extensions and currently has no explicit goal extension path. Global installation does not activate goals in this companion.
- An isolated loader probe with the companion's actual SDK loaded the installed extension successfully, with zero extension errors. It registered goal tools, slash commands, and lifecycle handlers. No goal was created, no model request was made, and no running Krita session was changed. Loading is narrower evidence than a complete integration test.
- The installed extension declares Pi peers `>=0.83.0 <0.85.0`, matching our SDK, and TypeBox `^1.3.11`. The companion pins TypeBox 1.3.7; the global extension environment has 1.3.29. Align dependency versions before packaging instead of relying on this machine's mixed resolutions.

The user-supplied `pi install npm:@capyup/pi-goal` command identifies the upstream package. Installing that alongside the existing fork is unnecessary for this proposal and could introduce duplicate command/tool registrations if both are loaded.

## What goals add

The upstream extension provides a durable objective, lifecycle controls, automatic continuation, and disk-backed goal records. Regular mode lets the agent choose its approach; Sisyphus mode emphasizes an ordered process. The fork adds structured task tracking and completion verification features. See the [upstream documentation](https://github.com/capyup/pi-goal) and [fork documentation](https://github.com/tmonk/pi-goal-x).

Our current painting session already loops through tools, receives images, and can revise without a goal extension. Its first live demonstration stopped after two passes because the prompt explicitly imposed that limit. That run is not evidence that the current loop cannot continue.

Goals would add an explicit record of the intended result and unfinished work, continuation after the model ends a response, progress across context changes, and a defined completion review. They do not teach brush behavior or improve the model's underlying visual ability. Repeatedly continuing an ineffective correction can consume more time without improving the image.

For free painting, start with a regular goal. Use ordered mode for a deliberately staged exercise, such as establishing proportions, checking value relationships, then working on edges. An ordered checklist is not itself proof of visual success.

## Findings from the installed source

| Area | Observed behavior | Consequence for Krita |
| --- | --- | --- |
| Continuation | `goal-events.ts` handles `agent_end` and `agent_settled`; `goal-runtime.ts` queues another message for the focused active goal. | Integrate at session lifecycle boundaries, including automatic turns that start after the original prompt resolves. |
| Persistence | Goals live in `.pi/goals/`; session entries preserve focus, and compaction hooks restore goal context. | Store goal state with the study, and explicitly reconnect the saved goal, conversation, checkpoint, and live document on resume. Goal persistence does not reopen Krita by itself. |
| Tool surface | The execution profile adds three core tools or five with tasks, preserving existing work-tool selection. | The painting tools can remain the agent's work tools. |
| Progress detection | `GOAL_PROGRESS_TOOL_NAMES` contains goal and coding tools, but does not include `paint_pass` or `adjust_layer`. | Adapt progress accounting and test it with painting tools. This does not prove all continuation fails: the settled-event path also schedules continuation. |
| Interface | Widgets and several proposal/task dialogs use terminal components and `ctx.ui.custom`. | Implement native goal controls and proposal displays in Qt. Loading the package does not render its terminal dashboard inside Krita. |
| Completion reviewer | `goal-auditor.ts` launches an isolated Pi session with `read`, `grep`, `find`, `ls`, `bash`, and a progress tool. It defaults to the selected model unless configured otherwise. | Replace the repository-oriented reviewer with a restricted visual review that receives the reference and final canvas directly. |
| Image capability | Pi's `read` tool can return image attachments, so the stock reviewer is not inherently text-only. | Nonetheless, it does not automatically obtain a fresh Krita canvas or our painting-specific evidence. Supply those explicitly. |
| Budgets | Optional token accounting transitions an active goal to `budget_limited` after observed usage reaches the limit. | This is not an exact price ceiling. Bound the entire painting goal, including reviewer calls and continuations, with application-level limits. |

The fork exposes a `runCompletionAuditor` dependency in its entry point. This is a useful adaptation point for a visual reviewer. Goal state and UI also have separate modules, although these internals should be treated as version-specific integration points rather than a promised stable library API.

Pi's documented SDK supports explicitly selected extension paths through `DefaultResourceLoader` and host UI bindings. Context7 returned Pi SDK and extension documentation, but did not resolve a dedicated `pi-goal` documentation library. The installed package source was therefore the authority for exact installed behavior. See [Pi SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md) and [extension UI documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md).

## Proposed painting experience

Add a **Work toward a goal** option to Creative Agent. The user provides an artistic brief and visible completion criteria, with a compact goal card showing the current focus, unresolved issues, elapsed use, and Pause/Resume controls. An explicit Start goal action can authorize an already-complete brief; there is no need to ask for approval between ordinary painting passes.

Example brief: create a color-field study with a deep burgundy upper field and dark plum lower field, preserve a quiet gap, reduce repeated horizontal banding, and give the edges visible brush character rather than uniform airbrush blur.

Each cycle should inspect the latest image, choose one concrete correction, paint, save, and compare before/after. Before completion, a separate review session should receive the reference (when present), latest canvas, selected detail crops, and the user's criteria. Its report should distinguish observed improvements, remaining defects, and subjective judgments. A reviewer may use the same or another compatible vision model; a second session is not automatically an expert art judge.

Keep the user's requested stopping point, Stop button, document identity checks, fault pauses, and checkpoints authoritative. In particular, the current runtime clears its timer and reports idle when `session.prompt()` returns. Extension continuations can occur later, so the goal integration must own a goal-wide timer and update busy state for every run. Pause must cancel both future continuation and model work while letting an already-running native pass settle and save.

## Experiment to establish whether it helps

Compare ordinary autonomous painting with goal mode under the same model, starting canvas, tools, brief, and total allowance. Do not retain the earlier two-pass demonstration limit for this comparison.

Evaluate visible color relationships, field proportions, gap and margins, brush edge character, and banding. Also record premature stopping, useful corrections, regression, model/reviewer use, and saved-artifact validity. Review matched final images and before/after pairs. Repeat before claiming that goal mode reliably improves quality.

A useful integration would preserve the current MCP painting engine and add goal management plus visual completion review around the existing Pi session. No live goal-mode painting, Stop/resume test, or quality comparison was performed during this research.

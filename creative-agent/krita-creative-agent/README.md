# Krita Creative Agent

A macOS painting assistant inside Krita, powered by **Agent Pi**. Discuss a canvas, develop a painting plan, and let Agent execute it with native brushes and editable layers. Connect models through Pi instead of tying the painting experience to one provider.

**The product goal is simple: give Agent a painting task and let it work through to completion.** The artist should be able to watch, guide it, or press Stop. They should not need to manage tool permissions, repeat Resume after ordinary progress, or manipulate an internal stage number.

**Version 0.2 is still a development candidate.** We have demonstrated native painting, saving, stage advancement and recovery in live Krita. We have not yet demonstrated consistently finished, professional-quality artwork. Tool execution, a passing test suite and a model declaring success are different from a convincing painting. [Product progress](docs/PRODUCT_GOAL_PROGRESS.md) records the evidence and remaining gaps; the [redesign plan](../CREATIVE_AGENT_PRODUCT_REDESIGN_PLAN.md) defines the broader product requirements.

## Native painting craft — 11 October 2026 (build `d68f840d…`)

The painter now builds areas with Krita itself instead of only brush strokes. It works layer-first: flats, then form on clipped layers, then filters, with strokes last. Each step is one reversible pass.

| Tool | What it does |
| --- | --- |
| `fill_region`, `select` | Flats, gradients and patterns in exact shapes or saved selections |
| `colorize_flats` | Flat colours from closed line art, with Krita's colorize mask |
| `create_layer`, `set_layer` | Blend modes, alpha lock, clipping (masks when clipping to the artist's layers), layer styles (shadow, glow, outline) and live gradient fill layers |
| `apply_filter` | Filter masks, filter layers or filtered copies; fading a mask works |
| `transform_layer` | Move, scale or rotate one of the agent's layers with a transform mask |
| `composition_guides` | Thirds, centre or horizon guides; the artist's own guides come back when the chat ends |

- **Following the artist.** Observations include the artist's selected layers and current colours.
- **On-canvas progress.** A short message shows on the canvas when each operation starts.
- **Always on.** The panel no longer offers a strokes-only mode; scripts can still pass `native_craft: false` for comparisons.
- **Hot reload.** The bridge's `reload` command loads a new build without restarting Krita.

The rules for the artist's layers are in [safety](docs/safety.md), and the modules are described in [architecture](docs/architecture.md).

**Live evidence (Krita 5.3.3):**

- **Lit sphere.** `deepseek-flash` in Autopilot made a sphere with a cast shadow in 5 `fill_region` calls with no strokes. Painting took 0.8 minutes, and the independent review met 5 of 5 checks.
- **Colorize flats.** Three regions came out in their exact colours, and the line art was unchanged.
- **Groups 1–4 and 8.** Every live check passed.

**Speed benchmark: incomplete.**

| Starry Night, `deepseek-flash`, 20-minute cap | Craft on | Strokes only |
| --- | --- | --- |
| Passes (craft / `paint_pass`) | 92 (37 / 38) | no valid run |
| Strokes | 5,992 | — |
| Review | not reached (stopped at the cap) | — |

Both strokes-only attempts were cut short. One stalled on the provider, and in the other the active Krita document changed. Rerun them with `scripts/live-craft-acceptance.mjs --scenario starry --craft on|off --idle-seconds 300`, and don't switch documents during the run. Until then, craft has no measured speed advantage.

## Luna decisions — 9 October 2026 (candidate `ff04b944…`)

TypeSafe routing has been replaced by **Luna decisions**: fast, image-based checks from GPT-6 Luna Decisions (`openai/gpt-6-luna-decisions`) on OpenRouter's Decisions API. A single setting, **Luna decisions**, controls all three checks:

- **Off.** No requests.
- **Evaluate only.** Checks run, are recorded in diagnostics and are shown in the panel. The painter and the loop are unchanged.
- **Guide agent.** Results also reach the painter and drive the stall rules.

The three checks:

- **Routing.** The same operation and brush advice as before, now with the attached canvas image. It gives advice only at ≥ 0.8 confidence.
- **Per-pass check.** After each paint pass, compares that pass's before and after images for six recorded failure types: hard join, duplicated band, flat block, mechanical stripes, pasted ellipses and hard graphic look. Each finding comes with its location on a 3×3 grid. It never hides or undoes a pass.
- **Progress check.** When the reviewer fails the same checks again, it scores how much they improved (0–3). In Guide mode, clear progress ends a stall run, and three reviews without real improvement trigger the change of strategy.

Luna can't mark a painting complete or skip a review. Any refusal, timeout or error falls back to the behaviour without Luna.

**Credentials and data.** Luna uses the OpenRouter key you already connected for the painter, falling back to `OPENROUTER_API_KEY`. There is no separate key field. When the setting is on, the canvas and pass images and your direction are sent to OpenRouter and OpenAI. A typical cost is about $0.0003 per pass check. A TypeSafe key saved earlier in macOS Keychain is left in place and no longer used.

**Evaluation (9 Oct, OpenRouter):**

- Routing held-out: 26/26, the same as the previous router.
- Labelled visual checks on crops of finished paintings (detection rates are for injected failures):
  - join, flat block, stripes, ellipses and graphic look: 12/12 each;
  - duplicated band: 7/12;
  - false flags on unchanged, ordinary-brushwork and already-present-flaw passes: 0/36;
  - progress ordering unchanged < half-fixed < fixed: 12/12.

Injected failures are more obvious than real ones, so run **Evaluate only** before using Guide. Evidence: `output/routing-eval/`, `output/visual-checks/`. Evaluate with `doppler run -- node scripts/evaluate-routing.mjs` and `doppler run -- uv run scripts/evaluate-visual-checks.py`.

## History: TypeSafe candidate and live acceptance — 23 September 2026

*Superseded by Luna decisions above; kept as a record.*


Optional TypeSafe routing supports Off, Evaluate only, and Guide agent. It advises the existing vision painter; it cannot authorize edits or replace visual review. The official SDK is pinned to 0.6.0. Credentials can come from `TYPESAFE_API_KEY`, macOS Keychain, or an explicitly configured `typesafe_doppler` project/config. The current local connection uses Doppler `secrets/dev`; keys are not copied into artwork or reports.

**Live results:** 26/26 held-out intent cases matched using the real Jev API. Separate full-agent runs demonstrated Gradient and Smart Patch on the installed bridge, with pixel confinement and saved-art checks. A live document-switch check prevented mutation of either tab; a real rejection restored the test defect. These are specific workflow checks, not proof of finished artistic quality. The matched Off/Guide Smart Patch runs chose the same tool, so routing has not demonstrated a tool-choice improvement on that task.

The 23 September inspect-loop fix makes an Agent inspection hint a one-time preliminary step. It was included in the previous `55ae42f6…` release; its behavior during a resumed painting run still needs live confirmation. See [live test instructions and evidence](docs/TYPESAFE_LIVE_ACCEPTANCE.md).

The latest `test.kra` run had TypeSafe routing **Off**. Its main measured delays were macOS idle sleep and repeated large layer metadata, rather than native brush execution. The previous `55ae42f6…` release added an Agent-only Mac wake hold and reduced duplicate layer metadata in model context and mutation receipts. See the [performance evidence and limits](docs/PERFORMANCE_2026-09-23.md). Live speed improvement is not yet verified.

`npm test` and `npm run test:live` now run the live acceptance entry point and require explicit target/output arguments. Missing credentials, missing Krita, mismatched builds, and unrun scenarios report **blocked** (exit 2), not passed. `npm run test:unit` runs the separate unit/regression suite; its totals are not evidence of real API or canvas behavior.

## Lower-house recovery update — 23 September 2026

The installed and loaded build is now `1ca04445…`. The Agent records accepted requirement corrections separately and gives the latest artist direction precedence during visual review, including when an older stage check or reference geometry conflicts. Repeated failures of the same review checks trigger a strategy change after three changed passes and pause after five; a new user direction starts a fresh review window. Historical reviews do not consume this window when an old conversation is restored. This prevents an unlimited run from mistaking small pixel changes for progress. It does not guarantee the reviewer or painter will make the right artistic judgment.

`painting_toolbox` now accepts `projection_region` and optional `projection_feather` to copy a bounded area of the **visible composite** onto a new reversible top layer. It intersects the mask with an existing selection and the stage region, then supports selection-aware brush, eraser, gradient, and Smart Patch commands. The source document and underlying layers stay intact. The first version requires RGBA/U8, opaque source pixels and at most two million pixels per contribution; whole-layer transforms and filled shapes are rejected in this mode.

Live acceptance on a separate copy of `test.kra` ran a brush stroke across the mask edge on this loaded build: 540 pixels changed inside the region, zero outside, and rejecting the pass restored the copy's merged image exactly. The original `test.kra` remained saved and unchanged. This validates the native retouch and rejection path on Krita 5.3.3, **not** an autonomous finish of the Victorian house. [Recovery notes and remaining artistic work](docs/LOWER_HOUSE_RECOVERY_2026-09-23.md).

## Earlier reference-workflow milestone

At the **14 September 2026** milestone, reference-driven stroke generation, coarse/fine/focal refinement and resumable execution were implemented; 99 Node tests and 58 Python tests passed. That milestone used release `1cda2b8dabf4d1b23eefa55403161b4f06eb5afe24687535e4106cb4b1359c10`. The currently loaded release is `1ca04445…`, as recorded above.

The new reference workflow has passed automated generator, native-policy and real Pi SDK/controller tests with simulated provider/bridge responses. Its updated native bridge and real-provider painting still need live validation. Installation, loaded component versions and artistic quality are separate checks. See [implementation and validation status](docs/REFERENCE_PAINTING_IMPLEMENTATION.md).

The [accepted faces-and-shawl study](../projects/moonlit-canal/faces-and-shawl-finished.png) demonstrates the reference-sampled method under Codex direction using a local script. It was not painted by the Creative Agent. [Working notes](docs/REFERENCE_BRUSH_RECONSTRUCTION.md) preserve the exact method and limitations. The [13 September capability review](docs/PAINTING_CAPABILITY_REVIEW_2026-09-13.md) is historical: procedural stroke generation and reference reconstruction have since been implemented; a reusable calibrated brush catalogue remains incomplete.

## Using it

1. Open your painting and the **Creative Agent** docker. **Current canvas** is the default target. Choose **New painting** or **Copy current painting** only when you want a different document.
2. Choose a **provider and model**. The composer displays both: an official provider and a route through OpenRouter are distinct connections, even when the displayed model names resemble each other.
3. Use **Ask** to learn how to paint it: a step-by-step Krita lesson that stays open beside the plan in every mode, without changing the canvas. Use **Plan** to develop an editable brief from ordinary language and reference images. State character requirements, things to preserve and creative freedom in the plan.
4. Start **Agent**. It paints coherent batches, sees the resulting canvas, works through the plan's steps in order and requests one independent review when the whole painting meets the final checks. It does not stop between steps or wait for your approval mid-run.
5. Guide it through the composer or use **Stop**. An already dispatched brush operation settles and saves before execution stops. Stop prevents subsequent painting; it is not a destructive interruption of Krita’s brush engine.

Canvas thumbnails identify what is included with a message. **＋** attaches the current canvas, references or a rectangular crop of a selection. Ask and Plan remain read-only. Once painting starts, the conversation stays bound to that artwork; switching tabs does not silently redirect the agent to another document.

**New runs have no default time or pass limit.** The plan editor represents unlimited allowance as **No time limit / No pass limit**. Optional nonzero time and pass allowances remain supported; per-stage stops and operation limits were removed. Older conversations can retain their saved limits; inspect the plan instead of assuming an update changed every previous conversation.

Artwork stays in an ordinary `.kra` file. **Show file** reveals it; **History** restores a conversation. Restored conversations stay paused until started, so merely opening history cannot paint. If a file moves, **Locate painting** relinks it rather than recreating the obsolete location.

## Choose the painting workflow

| What you want | Agent approach | Example request |
| --- | --- | --- |
| Faithfully reconstruct an attached image | Sample the reference locally and render native strokes through coarse, fine and focal passes | “Reconstruct this reference on a new canvas. Preserve its proportions and refine the faces and hands.” |
| Add a field of colour, scumble or texture | Generate strokes from a region, palette and brush recipe | “Add irregular dry texture to the selected field while preserving its colour relationships.” |
| Invent or deliberately change a composition | Plan and author contours, curves and native edits | “Design a new scene with these two characters in different poses.” |

Reference reconstruction transfers the source's spatial colour information. It does not invent new anatomy or composition. For a freely interpreted painting, the agent must choose authored tools and evaluate the result accordingly. Use a new canvas or a copy for reference experiments unless the user requests edits to existing artwork.

For reconstruction, the agent keeps coarse/fine/focal refinement within **one plan step**; each scale is a visual checkpoint inside that job. It inspects the returned canvas before continuing. The user describes the desired result in ordinary language; the agent handles coordinates, tool arguments and job IDs.

## What automatic execution means

The intended loop is:

```text
Read the brief and current canvas
  → paint substantial batches, working through the plan's steps in order
  → observe the returned previews and correct as needed
  → review the finished painting against the final requirements
  → correct and review again until it passes, or until you press Stop
```

**Steps are a suggested order, not stages.** A plan lists a few steps (for example block-in, forms, detail) so the painter builds coarse-to-fine. There is no per-step review, step stop, step operation limit or step region. One independent review checks the requirements and final visual checks, and the host decides completion from those checks: every check met means finished, any check unmet means keep painting. The reviewer cannot defer a check or hand the run to the artist.

Past runs motivated this: across 23 saved studies, 25 reviews passed and 173 failed, and the failures piled up inside a single stage rather than at stage boundaries. Stage gates added a review call per stage and stopping points without fixing the stalls.

A normal progress message, a small stroke count or an internal scheduling yield is not a review boundary. Batch capacity is **256 curves per paint_pass** or **256 commands per painting_toolbox call**. The agent chooses how many are useful; a capacity of 256 does not mean every call should make 256 marks.

**No mid-run human review.** During a run the Agent never stops for the artist:

| Situation | Before | Now |
| --- | --- | --- |
| Painter wants a preference | Question, run waits | Painter decides within the brief; the artist can redirect at any time |
| Reviewer unsure | `needs_input`, run waits | Not a valid verdict; completion follows the checks |
| Same checks fail again and again | Strategy change at 3, pause at 5 | Strategy change every third repeat (Luna progress can defer it) |
| Uncertain painting actions in a row | Strategy change at 3, pause at 5 | Automatic recovery; strategy change every third in a row |
| Artist edits the canvas mid-run | Pause | Recorded as a direction to keep those edits; the run continues |
| Stage finished / stage limit | Pause for “Next stage” | Removed |

Questions, plan approval (**Start painting**) and requirement-change acceptance still happen in Plan, before painting. **Stop** always pauses immediately, and time or pass allowances still end a run. A run still pauses when Krita cannot show the canvas after an uncertain action, or the connection or model fails.

The controller must recover from ordinary model hesitation itself. Source changes now refresh a stuck execution session while retaining the brief, recent findings, original painting and operation journal. They replace automatic pauses after repeated idle replies or unchanged attempts with another approach.

Real connection failures, uncertain native operations, changed painting targets and explicit artist stops still require truthful handling. Automatic execution must not replay an operation whose outcome is unknown or declare an unfinished painting complete to escape a loop.

## Provider, reasoning and parallel preparation

The composer has separate **Provider** and **Model** selectors. Selecting DeepSeek shows only models registered under the DeepSeek provider; OpenRouter routes remain under OpenRouter. The controls use the same Pi registry and credentials as the companion. Unconnected providers remain discoverable, and noninteractive batch models are labelled and disabled. A failed model switch restores the accepted provider and model before another message can be sent.

Open **Settings → Agent execution** for:

- **Single painter** (default): the normal painting loop.
- **Parallel preparation · 2 workers**: two concurrent requests to the selected provider/model prepare broad construction and material suggestions from the same stage snapshot. They submit proposals only. One painter reconciles them and applies native Krita commands sequentially. Preparation happens once per stage/model/plan revision, not after each stroke batch. Failed preparation falls back to the painter; suggestions are discarded when the snapshot changes. Stop cancels both workers.
- **Reasoning**: Auto, Off, Minimal, Low, Medium, High, Extra high or Maximum. Auto chooses Low for reasoning-capable models and Off otherwise. Pi clamps unsupported levels; settings show the effective session level. This setting reaches the painter, preparation workers and stage reviewer, and does not change the context-window budget.

Execution settings persist with each conversation and as defaults for new conversations in the project. Restoring a conversation restores its settings while leaving painting paused. Change provider, model or execution settings while idle; changing settings does not start painting.

Parallel preparation is optional because it adds model requests and can increase latency for simple paintings. It does not make a single model generate tokens faster or allow competing writers to the canvas. A measured speed improvement on this painting is not yet established.

## Models, large context windows and memory

Large-context models are welcome. The integration uses Pi’s model registry and authentication, rather than a fixed list of model brands. Prefer routes that support **both image input and interactive tool calls**. A large text window alone does not establish either capability or painting skill.

Do not document a universal “one million tokens” for a model nickname. Context limits can differ by exact model ID, provider, endpoint and account. Use the configured route’s `contextWindow` metadata, and verify provider documentation when publishing a supported-model matrix. The manually configured OpenAI-compatible route currently uses a 64,000-token declaration; it does not automatically discover a custom endpoint’s true capacity.

There are three separate kinds of memory:

| Memory | Purpose | Current behavior |
| --- | --- | --- |
| Model context | What the provider sees in one request | Recent conversation, relevant images, tools and the current painting brief |
| Durable project state | What must survive compaction, restart and model changes | Brief, requirements, character facts, painting order, references, progress, reviews and operation records |
| Reusable brush knowledge | What should transfer between painting conversations | Incomplete: observations exist in journals and conversations, but there is no finished shared, calibrated brush catalogue |

### Current compaction policy

The companion currently compacts around a **64k-token working context**, even when a provider advertises a much larger window. This is a latency-oriented implementation choice, not the model’s maximum capacity. The Pi configuration reserves `max(16,384, contextWindow − 65,536)` tokens and retains a recent window of approximately 12k tokens. Actual thresholds also depend on Pi’s context accounting and the route’s available capacity.

This policy came from a live run where requests grew to roughly 381k tokens and a subsequent compacted request was roughly 28k. That observation motivated reducing repeated history; it is not a controlled speed benchmark or proof that 64k is best for every provider.

**A selectable context policy is still needed.** An artist choosing a large-context route should be able to favor more history, faster responses or the provider’s available window, with the effective budget visible. Do not silently present a 64k working budget as full use of a million-token model. Conversely, do not fill a large window with duplicate screenshots, raw preset XML and repeated failed reasoning simply because there is room.

The durable brief is supplied again during execution, so compaction must not erase a character’s identity, a protected colour relationship or a user correction. Large context does not replace durable state. The displayed cumulative token count includes repeated input and cache accounting across requests; it is not the size of the current context or a count of newly generated words.

## Brush knowledge: known tools, verified behavior

The agent should know the available tools and use a reusable brush reference. It should not rediscover the same preset pitfalls in every painting conversation. Today it can list installed preset names, inspect the current preset’s settings and observe the actual results. That is useful discovery, but it is not yet a reliable visual vocabulary of every installed brush.

We already have useful evidence in the [painting experiment journal](../PAINTING_AGENT_EXPERIMENT_JOURNAL.md): some presets deposit strongly, some blend or barely deposit in particular conditions, and identical-looking parameter names can mean different things. Those observations need to become structured knowledge instead of remaining buried in transcripts.

A useful brush record should include:

- Exact preset identity, brush engine, preset fingerprint and Krita version.
- Plain-language purpose and relevant enabled settings, including dynamics and colour behavior.
- Actual swatch images at documented size, opacity, flow and pressure, on both plain and two-colour backgrounds.
- Observed strengths, failure cases and tested adjustments, with links to their evidence.
- Confidence and provenance: preset metadata, documented behavior, model hypothesis or visually verified result.

Records should be reused across chats and models. Recalibrate when the preset, relevant settings or rendering conditions change—not after every ordinary pass. Keep calibration off the artist’s painting unless they intentionally request a test layer. Stored knowledge improves the next prompt; **it does not train the model’s weights**.

### An actual misdiagnosis

The agent read `MixValue=1`, a pressure sensor and mirroring fields, then claimed that Dry Bristles must be picking cream paint up from the canvas. That conclusion was unsupported. The inspected preset also reported `PressureMix=false`.

Krita’s Pixel brush **Mix** option selects between foreground/background colours, or along the source gradient. Canvas smudging is a different mechanism. **Mirror** reflects the brush tip mask; it does not mean the whole canvas is mirrored. Stored values and sensor curves do not, by themselves, establish that an option is enabled. See [Krita’s brush option reference](https://docs.krita.org/en/reference_manual/brushes/brush_settings/options.html) and [Color Smudge engine](https://docs.krita.org/en/reference_manual/brushes/brush_engines/color_smudge_engine.html).

Source prompting now includes these distinctions. The larger fix is a documented brush interface and evidence-backed catalogue. A confident explanation is not a calibration result; changing a parameter without a visible improvement does not prove the original diagnosis.

## Painting tools and reversibility

### Reference-driven painting

- `paint_from_reference`: start a saved reconstruction job from an attached reference, source crop, target rectangle, preset and optional focal regions.
- `continue_reference_painting`: continue the job from its saved boundary, after inspecting the latest image.
- `list_reference_paintings`: read saved job IDs and progress for the current conversation, including after restart.

The renderer computes the marks locally; the model does not write thousands of coordinates. Defaults are source-space sampling steps `[6, 2.5, 1.2]`. Source and target must have matching aspect ratios. Reconstruction accepts reference files up to **5 MB** and **four million decoded pixels**, with at most **200,000 estimated samples** per recipe. These limits are narrower than the general attachment limits below. Focal regions select sample centers; strokes may overlap their edges. Target and stage masks clip the full brush footprint.

Each scale uses **one editable layer** inside its plan-step group, even across many chunks. Chunks contain at most **128 strokes**, use native checkpoints, and count toward explicit operation allowances. The tool yields a saved result after roughly 45 seconds or when a scale finishes. A chunk yield is not artistic completion and ordinarily does not require the user to press Resume. The agent continues the saved job until the planned work is complete or a genuine stop condition occurs.

**Stopping and recovery:** Stop lets the current chunk settle and prevents the next. Resume uses the same job ID. A lost acknowledgement is checked against Krita's operation receipt before any further painting; committed strokes are not repeated. Partial or uncertain results block continuation. If the canvas, source reference or planned stage has changed, the job preserves those changes and refuses automatic continuation. Inspect and resolve the discrepancy; do not delete receipts or restart the recipe blindly. See [full behavior and limitations](docs/REFERENCE_PAINTING_IMPLEMENTATION.md).

### Drawn contours

`paint_contours` fills up to 32 deliberately drawn polygon outlines in back-to-front order using native brushes, as one editable contribution. The model supplies the geometry; this does not infer likeness or trace references. It validates outlines before dispatch and uses existing selection restoration, stage restrictions, saves and operation recovery. Painter and reviewer guidance now distinguishes recognizable construction from the requested finish. See [direct-painting lessons and limitations](docs/CONTOUR_CONSTRUCTION_LESSONS.md).

### Generated painting recipes

Agent can use **`paint_recipe`** to generate native brush strokes locally from a compact description. It accepts a named preset, rectangular region, palette, stroke count, size/opacity ranges, direction, irregularity and seed. Optional length, flow and layer opacity provide more control. Existing precise painting tools remain available. Ask/Plan cannot paint recipes.

For example, ask Agent: “Use a painting recipe to scumble this field with irregular overlapping marks. Keep these colours and inspect the result after the pass.” The model chooses the arguments; you do not have to paste JSON.

The first implementation supports up to 20,000 generated curves per request, executed in existing saved batches of at most 256. **Each batch still creates a named layer and counts toward any explicit operation allowance.** Stop prevents the next batch; the current batch finishes and saves. Recipe parameters, generator version and batch receipts live under the conversation's `recipes/` directory. Interrupted recipes do not automatically replay. The rectangular region clips the entire brush footprint and is intersected with any explicit stage region.

This is a deterministic parameterized generator, not arbitrary script execution or automatic reference sampling. Irregularity varies placement, overlap, direction and curvature; brush behavior still needs visual assessment. Identical seeds reproduce the generated command plan, not a guarantee of identical pixels across changed presets or Krita versions.

Historical validation of candidate 021: a real Krita test produced **1,200 strokes in five saved batches in 16.0 seconds**, excluding model latency, and Stop prevented a second batch in a separate test. See [validation](docs/RECIPE_TOOL_VALIDATION.md). End-to-end artistic performance through a real provider remains a separate evaluation.

Agent has access to native curves and pressure strokes, brush selection/settings, shapes, selections and selection modification, erasing, layer movement/transformation, blending, opacity/visibility, colour selection, circular fills, solid-colour clearing and imported brush textures. `painting_tool_help` provides the implemented command formats.

This is broad painting access, **not a claim that every Krita UI action has an API wrapper**. The reviewed toolbox exposes both circular `fill` and a separate contiguous `flood_fill`; their parameters and behavior differ. Whole-contribution solid fill and some raw-pixel shape operations do not honor selections. The tool descriptions must expose these distinctions instead of letting the model guess.

Each contribution uses a named layer or an editable copy of existing paint. Locked paint layers can be copied to an unlocked working contribution while retaining the original pixels. Before/after review, visibility, strength adjustment and rejection use recorded contributions. Later manual edits prevent automatic reversal from overwriting them.

Native operation IDs prevent duplicate painting after a retry. Cheap argument checks and document identity checks are not model-driven visual audits; removing them would create malformed strokes or edits on the wrong artwork without making the painter more capable.

## Architecture and files

### Troubleshooting through MCP

The Creative Agent, general Krita and Krita Artist MCP servers expose three diagnostic tools:

- `creative_inspect_state`: current companion mode, activity, stage, target, pending tools/native requests, stop/error state, and last reported UI/bridge build metadata.
- `creative_recent_events`: a timestamped, bounded timeline with model turn, tool-call, native request and operation IDs. Pass `after` to continue reading; reset it when the returned process `instance` changes. Native progress and checkpoint receipts distinguish painting/saving from waiting and review. A returned checkpoint can be an existing save; a receipt alone does not establish new pixels were saved.
- `creative_collect_report`: export the existing local report with live state, timeline, the chat's plugin journal (operations and passes), its record and chat log from the database, and Python errors. Returns the saved path. No upload or model request.

Tools discover the installed plugin configuration (its `output` is the agent data folder, `~/Library/Application Support/Creative Agent/data`), or accept `state_directory` pointing to that folder. `KRITA_CREATIVE_CONFIG` overrides config discovery. The updated companion exposes a private Unix socket, with its descriptor in that state directory. It inspects the existing runtime without starting another painter. Restart Krita after installing this update and reconnect the MCP server to discover the new tools.

The live ring retains 500 events; a rotating local event journal survives companion exits. Local model turn identifiers are correlation IDs, not provider request IDs. Raw prompts, token deltas and tool arguments are omitted from this timeline. Existing report sanitization redacts credentials and removes image payloads. UI and bridge metadata are explicitly last-reported snapshots, not fresh visual inspections. If the companion is unavailable, tools return available previous report/journal paths labelled as non-live evidence. They never retry an uncertain painting operation or restart Krita.

Validation and installed-build status: [diagnostic MCP validation](docs/DIAGNOSTIC_MCP_VALIDATION.md).

```text
Krita Python/Qt panel
  ↕ local JSON messages
Node companion: Pi AgentSession + ModelRuntime
  ↔ selected provider/model
  ↕ local HTTP
Krita native bridge + document-bound painting tools
  → native brush paths, editable layers, observations and saves
```

One painting controller owns continuation. Pi supplies model sessions, streaming, tools and compaction. The terminal goals extension is not loaded as a competing scheduler. The MCP endpoint remains available to external assistants; the in-Krita companion calls the native bridge directly.

### Where your data lives

Since 12 October 2026 (storage-layout, `openspec/changes/storage-layout`), only artwork stays in your painting folder. Agent records live in one SQLite database in the app's data folder, and nothing large or frequently rewritten is written next to your paintings (safe for iCloud Drive and Dropbox).

```text
Your painting folder/
  painting.kra                 ordinary editable artwork
  .creative-agent/
    project.json               this project's id (under 1 KB); a moved project keeps its chats

~/Library/Application Support/Creative Agent/data/
  records.sqlite               every chat: plan, painting link, chat log, images (each once), references
  chats/<conversation-id>/
    journal.sqlite             the plugin's operation receipts and passes; preserve for recovery
    .progress.json             live painting status
    .previews/                 scratch canvas pictures, deleted when the chat closes
    reference-*.png            copies of the chat's references, recreated from the database on open
  model-connections.json, execution-settings.json, capabilities/, diagnostics/
```

- **records.sqlite** holds each chat's record, its model conversation (the Pi SDK session, stored through an adapter) and every image once by content hash. Searching the chat list uses its full-text index.
- **journal.sqlite** is written only by the Krita plugin, one small transaction per action, so an action interrupted by a crash is reported as uncertain and never painted twice.
- **Previews** are scratch: the picture the model saw is already in the database. A closed chat keeps only its thumbnail.
- **Old layouts migrate automatically** on the first start: chat folders move (no copy) out of the project, logs and journals go into the databases. `node scripts/unmigrate.mjs <project>` moves them back for an earlier build.

**Managing chats.** In the Conversations window each chat shows its size and the window shows the total. **Delete…** removes a chat's records and folder (never its painting). **Export…** saves the selected chat, or every chat in the project, as one `.creative-agent-archive` file (a SQLite file with records, logs, images and the journal); **Import…** adds chats from an archive on this or another computer and never changes the archive. Copying a project to another computer without an archive opens it with no chats.

**Maintenance commands** (run with Krita idle; each refuses while a chat is painting):

```sh
node scripts/clean-records.mjs <project> [--dry-run]   # previews and other rebuildable files
node scripts/recode-images.mjs <project> [--dry-run]   # stored PNG chat images as JPEG, then compact
```

**Update state through the runtime.** Do not edit `records.sqlite` or `journal.sqlite` while Krita or the companion runs. For an offline repair, stop the companion first and keep a copy of both files.

Artwork links are project-relative in records and resolved at tool boundaries. Save As follows the bound document. File relocation uses relinking.


### One-file troubleshooting report

In Settings → Connections, choose **Export troubleshooting report**. This creates `diagnostics/latest.json` in the agent data folder and opens it. It collects the selected conversation's messages/tool results, saved plan and records, current target/context, connection/build metadata, and captured Krita Python errors. It makes no model requests, uploads nothing, and does not operate the canvas. Export can run while the model is painting; records are a best-effort snapshot, not an atomic checkpoint.

For troubleshooting without touching the app:

```sh
node krita-creative-agent/scripts/export-diagnostics.mjs "$HOME/Library/Application Support/Creative Agent/data"
```

Optionally append a conversation UUID. Without one, this uses the last active-session marker, which can differ from the chat shown in the panel. The CLI report contains saved records; the panel export additionally includes live runtime state and build metadata.

Artwork and image bytes are excluded; credential fields, common API-key patterns and (for panel export) known runtime secrets are redacted. The report still contains conversation text and local paths and is kept local. Reports have a 16 MiB source-data budget, with explicit omissions for missing/truncated records and incomplete lines. Re-export replaces `latest.json`. Original durable records remain in place so conversation restore continues working.

## License

GPL-3.0-or-later (see [LICENSE](LICENSE)), like Krita and its plugin (`krita-mcp`).

# Painting capability review after the warm colour-field study

Date: 13 September 2026. Scope: the Creative Agent companion and native bridge, compared with the completed direct-MCP painting experiment. This is a source review with targeted tests and a read-only live bridge health check. It does not modify plugin code or run a new model painting session.

Follow-up: the user subsequently authorized the first generator. Candidate 021 now implements and locally loads `paint_recipe`; see [implementation and validation](RECIPE_TOOL_VALIDATION.md). The findings below describe the pre-implementation audit. Single-contribution execution, reference sampling and brush memory remain future work.

## Conclusion

The native painting engine is capable of useful work. Creative Agent does not yet give its model the same working environment used to create `warm_color_fields.kra`. The major gaps are procedural stroke authoring, reference measurements, off-canvas brush calibration, reusable material knowledge, and the cost/semantics of a contribution. More permissions or a larger context window alone do not close those gaps.

An important correction to the initial batching explanation: **Creative Agent already sends an entire paint pass/toolbox contribution in one HTTP request and loops over its commands inside Krita.** The per-command HTTP overhead found during the painting experiment belongs to the external `artist_server.py` MCP wrapper. Fixing that wrapper is worthwhile for external agents, but it is not the main speed fix for the in-Krita plugin.

The result remains a reference-guided study with softer, more uniform pigment than its reference. It is evidence of a workable method, not proof of exact reproduction or independent artistic mastery. See the [experiment and images](../../reference-board/warm-color-fields/EXPERIMENT.md).

## What was verified

- Read the product redesign plan, current README, experiment journal, tool schemas, native contribution handlers, runtime/controller, and relevant tests.
- Live bridge health reported Krita **5.3.3 (git 858d352)**, Creative protocol 2 and build ID `7d1c9b552d5199951266fe183937be3ac937631d8feaef0775cb12e07222c17d`. No creative painting session was active.
- The configured installed companion's `tools.mjs`, `studio.mjs`, `runtime.mjs`, `bridge.mjs` and `prompt.mjs` match workspace source. Installed `creative_tools.py`, `creative_docker.py` and `creative_validation.py` also match.
- Installed `__init__.py` and `precision_tools.py` differ from workspace source: the installed copy adds `fill_selection` and registers it. The build manifest still carries the older ID. A manifest ID alone therefore does not establish byte-for-byte reproducibility. This review did not test that installed-only command.
- `node --test tests/bridge.test.mjs tests/studio.test.mjs`: **48 passed**. `python3 -m unittest discover -s krita-creative-agent/tests -p test_toolbox.py`: **4 passed**. These use simulated providers/native harnesses; they establish controller and contribution behavior, not painting quality or real-provider speed.

## Capability comparison

| Work needed | Direct-MCP experiment | Creative Agent today |
|---|---|---|
| Native painting | Curves, short strokes, layers, opacity and texture settings | Available through `paint_pass` and `painting_toolbox` |
| Hundreds of strokes in one native request | Existing nested `batch` action | Already native-batched, up to 256 curves/commands per contribution |
| Thousands of varied marks | Seeded local scripts generated the commands | Model must emit explicit arrays; no recipe or script-authoring tool |
| Reference palette and local colour | Scripts sampled attached reference pixels with neighbourhood averaging | Exact sampling of the canvas only, up to 16 positions; reference viewing only |
| Brush experiments away from artwork | Existing `brush_probe` temporary two-colour document | Probe is absent from the agent tools and native creative allowlist |
| Texture material | Generated monochrome pattern, UI import, native setter | Setter exposed, but no material generation/registration/catalogue workflow |
| Close material comparison | Existing `compare_region` matched source and canvas crop | Canvas crop observation exists; reference crop and matched comparison are not exposed |
| Learning from failed brushes | Human-readable experiment and retained images | No shared calibration store; runtime does not load repository skills/context files |
| One artistic layer across many chunks | Direct commands kept an active layer | Every `paint_pass` creates a new layer; toolbox creates or duplicates a contribution |

Sources: [agent tools](../src/tools.mjs), [native creative tools](../../krita-mcp/krita-plugin/kritamcp/creative_tools.py), [raw bridge commands](../../krita-mcp/krita-plugin/kritamcp/__init__.py), [external MCP wrapper](../../krita-mcp/artist_server.py), [runtime](../src/runtime.mjs).

## 1. Highest priority: let the model author painting algorithms

`tools.mjs:55` requires every curve, control point, colour and setting in the model's tool call. `painting_toolbox` wraps each command's parameters in another JSON string. Neither tool lets the model express a loop, seeded variation, local reference sampling, coverage, or a reusable brush recipe.

The retained command files from our study total **1,921,732 bytes**. Scripts generated most of that mechanically; the model did not have to generate all of it token by token. Asking another model to spell out those coordinates is materially different from giving it the same task. The count also includes an unsuccessful contour experiment and should not become a target stroke count.

Add an authoring layer above the existing native executor:

- An editable, persisted recipe containing region, reference mapping, palette source, brush recipe, coverage/spacing, directional variation, overlap, strength and seed.
- Local expansion into native commands, with a stored command plan and preview. Support model-authored generators as well as reusable operations such as broad coverage, scumble and edge breakup; do not confine painting to three hard-coded effects.
- One execution job owns the expanded commands, contribution, native chunk receipts and Stop handling. The model can revise the recipe after seeing the result.
- Reference sampling remains explicit: a material-only reference must not silently supply composition or replacement colours. Preserve original dimensions, mappings and excluded scan borders.

Acceptance: the agent can produce a useful 1,000+ mark texture contribution from a compact recipe without writing 1,000 tool arguments, while the result remains native editable paint. Repeating the same seed/settings in a controlled starting state should reproduce the command plan. Interrupted execution must not repeat completed chunks.

## 2. Expose brush calibration and retain its evidence

`__init__.py:1162` already contains `cmd_brush_probe`. The agent cannot call it through `tools.mjs` or `creative_tools.py:491`. Instead `prompt.mjs` tells it to make a small pass when unfamiliar with a brush, which puts exploratory work into the artwork/save/review machinery.

Expose a dedicated calibration operation that restores the target document and brush state. The existing probe is a starting point, not a finished calibration system: it currently uses fixed opacity/flow 1 and pressure 0.9, with a configurable size. Extend it to the actual settings/path mode being proposed, including repeated overlap and relevant grounds. Internal probe document switching must not be mistaken for the artist changing the painting target.

Persist swatches and observations keyed by preset/resource hashes, Krita version, settings, size, flow, opacity and pressure/path mode. Retrieve relevant records automatically across chats and providers. Record failures as well as successes. Our Chalk Grainy probe looked useful, but small dense marks made cellular edges; settings and scale matter.

The creative brush list requests only the first 80 matching names (`creative_tools.py:98`), with no exposed offset or limit. Add complete paging and useful material search rather than treating that truncated list as all available tools.

Acceptance: a fresh conversation can retrieve this study's calibrated settings and failed-brush observations without the user pasting the journal. Recalibration occurs when relevant conditions change, not on every normal pass.

## 3. Separate a contribution from its execution chunks

The plugin already batches native painting. Its additional costs are elsewhere:

- Before a mutation it captures a full observation (`creative_tools.py:147`).
- After each contribution it saves the complete `.kra` and exports another observation (`:207`, `_creative_checkpoint` at `:331`).
- It computes layer fingerprints for reversal, including full-canvas and node-bounds pixel reads (`:437`).
- It writes and renames `.progress.json` for every stroke/command (`:855`), while the companion polls every 200 ms (`runtime.mjs:258`).
- Native `curve_stroke` already refreshes and waits; the toolbox adds another `waitForDone` after each command (`precision_tools.py:127`, `creative_tools.py:592`).

These are code-confirmed costs, not a measured ranking of current latency. Profile them before promising a speedup. Layer fingerprints and operation receipts serve useful recovery/reversal purposes; removing them indiscriminately is not the fix.

Introduce a job containing many bounded native chunks on one owned contribution. Preserve per-chunk execution receipts, make previews/progress available at useful intervals, and finalize the contribution at an artistic boundary. Give saving its own truthful state and recovery policy: a persisted command receipt alone does not mean paint has been durably saved. Save on completion and Stop, and choose an explicit crash-recovery strategy for long jobs. Never replay an uncertain in-flight chunk automatically.

Throttle progress writes and benchmark projection waits before changing their ordering. Keep small chunks where required for responsiveness; increasing the number 256 alone does not solve model output cost, layer proliferation or saving overhead. Independent visual review already happens at stage completion and should stay there.

Acceptance: compare the same prepared commands through direct native batching and the contribution executor on controlled canvases. Record model time separately from execution, projection, hashing, preview, save and review time. Verify Stop, crash recovery, no duplicated marks and reversal after manual edits.

## 4. Give the agent full-resolution reference inspection

`view_reference` returns the whole attachment. `sample_canvas_colors` samples only the destination. `observe_canvas(region)` can return a canvas crop, but `reviewCanvas` only requests it when the plan has a stage region (`studio.mjs:1000`). A full-stage texture task without such a region can therefore be judged from the maximum-1024 overview alone. Pi image auto-resizing also means large crop delivery needs verification rather than assuming the original file resolution reaches the model.

Add reference pixel/neighbourhood sampling, reference crops and matched canvas/reference comparisons. Treat **inspection regions** separately from **painting restrictions**: inspecting one edge must not accidentally prohibit painting elsewhere. Let the painter and reviewer request diagnostic crops even when the whole canvas is authorized.

Acceptance: for this reference, the agent can inspect the red/salmon edge at matching scale and identify the remaining material difference that the whole-canvas view obscures. Sampling reports its reference ID and coordinate mapping.

## 5. Put painting experience into runtime context

Updating README and journals alone does not teach this companion. `runtime.mjs:185` sets `noSkills: true` and `noContextFiles: true`. The preparation workers and reviewer do the same. The runtime supplies its own instructions, brief and recent progress; it has no shared brush-knowledge retrieval tool.

Keep a compact curated painting guide in runtime context and retrieve brush/recipe evidence when relevant. Include successful recipes, rejected trials, their actual settings and images. During execution recovery, bring forward the applicable failed approaches instead of relying only on a generic instruction to try something different and the latest six progress entries (`studio.mjs:293`, `:982`).

This is working memory and evidence retrieval, not training model weights. More context is optional; useful retrieved knowledge should work with smaller windows too.

## 6. Close tool and build inconsistencies

- `set_brush_texture` requires an already registered local pattern and identifies it partly by filename (`__init__.py:1253`). Expose resource discovery/registration with stable IDs and retain generated materials with their recipes. This removes the exact UI detour from our study.
- Resize-existing-canvas is missing from the reviewed tool surface. Add it as an intentional document operation and reconcile dimensions/mapping, rather than requiring creation of another painting.
- The installed-only `fill_selection` addition is absent from source and the creative toolbox. Bring it into a tested, versioned source build before claiming capability parity. This review does not endorse its implementation without validation.
- Generate a capability manifest from actual registered commands. Verify component file hashes, not only equal build-ID strings, so a locally patched installation cannot silently masquerade as the original release.
- README's blanket statement that circular fill is not flood fill is now incomplete: the reviewed toolbox also exposes `flood_fill`. Update documentation from the actual capability surface.

## What is already improved and should not be rebuilt

The current `StudioRuntime.runGoal` continues across ordinary assistant replies and internal scheduling yields, requests independent reviews only at stage/allowance boundaries, advances completed stages and refreshes an idle execution session. Targeted tests cover these behaviors. The old automatic three-pass audit and idle-reply pause are not an accurate description of the current reviewed controller.

Retain Ask/Plan read-only behavior, document identity, operation deduplication, explicit artist Stop and explicit user-defined boundaries. These do not explain the missing procedural painting capability. Existing provider selection and optional parallel preparation can remain; two workers producing large hand-written coordinate arrays are not a substitute for a local stroke generator.

## Recommended implementation order

1. Establish one reproducible source/installed build and capture baseline timings. Keep the new painting untouched.
2. Add command-generating recipes plus reference sampling, and execute them through the document-bound native path.
3. Add off-canvas calibration, resource registration and persistent brush/recipe retrieval.
4. Introduce contribution jobs with chunk-level progress/recovery and measured save/preview costs.
5. Add matched reference crops to painter and reviewer, including material checks independent of painting scope.
6. Run the same ordinary-language painting task through the actual panel on controlled fresh evaluation canvases with the chosen provider. Compare elapsed time, model output volume, pauses, interventions and the resulting artwork. Keep failed trials. Do not substitute passing controller tests for this end-to-end evidence.

The immediate product priority is painting capability and throughput. Another visual restyle or a new goal scheduler would not supply the missing tools demonstrated by this experiment.

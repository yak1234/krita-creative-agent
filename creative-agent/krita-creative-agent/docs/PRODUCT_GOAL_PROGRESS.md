# Creative Agent product goal — execution record

The user authorized all nine outcomes on 11 September 2026. This record distinguishes implemented candidates, local verification, live Krita verification and external release evidence. The goal is not complete until the full requested behavior is demonstrated.

## Scope and current evidence

| Goal | Required evidence | Current state |
|---|---|---|
| 1. Reliable canvas context | Fresh real image in a new Ask conversation; visible receipt; detach/refresh/pin; unsaved/no canvas/tab switch; no Ask/Plan saves | Candidate001 passed a real new Ask conversation: the provider received the exact canvas image shown by the receipt, described it correctly, and made no tool calls or painting passes. Remaining context and Plan scenarios still need live verification. |
| 2. Professional sidebar | All main states, resizing, themes, keyboard, long history in actual Krita | Complete native Qt implementation passes local rendering/interaction checks. Candidate003 loaded with matching UI/companion/bridge identity; live review found Settings and chevron polish issues, fixed in candidate004 with local UI smoke checks. Full live matrix and participant review remain open. |
| 3. Reference and language planning | Useful questions, editable rules/characters/stages, preserved across correction/model/restart/compaction | Candidate implemented. Actual Pi SDK forced-compaction test with a simulated provider preserves durable characters/rules through model change and restart. Live scenario outstanding. |
| 4. Bounded autonomous stages | Stage limit, guidance, interruption at every phase; no replay; concrete review/correction | Native region mask, durable operation journal and companion stage lifecycle are integrated and covered by local tests. Real brush-stage execution, phase interruption and stopping-boundary evidence remain open. |
| 5. Reviewable reversible work | Actual before/after, pass strength/rejection, preserved manual edits | Native pass journal/review implemented; tests preserve unrelated layers and reject reversal of modified agent pixels. Actual Krita evaluation outstanding. |
| 6. Portable files and history | Save As/Finder move/project relocation, migration/relink/paused restore | Project store/history integration, portable paths, non-destructive migration and relink are implemented and tested locally; native save refuses a disappeared destination. Full real Krita move/relink/restore sequence remains open. |
| 7. Useful artistic improvement | Matched test copies, brush calibration, crop and thumbnail evidence, protected pixels unchanged, exact stopping boundary | Outstanding. Two-trial calibration is awaiting the user's specific consent to send the painting snapshot to DeepSeek through OpenRouter and paint a separate working copy. No answer has arrived; the original painting remains unchanged. |
| 8. Dependable Mac release | Self-contained install/update, real model capabilities, migrations, clean Mac, usability evidence | Registry-locked bundle, graphical installer, isolated install/rollback/hash tests and actual DeepSeek image/tool capability probe passed. Exact candidate001 companion passed all 61 Node tests. Clean external Mac, distribution signing/notarization and participant evidence remain open. |
| 9. Elegant streaming panel | Live visual review, stable streamed Markdown, no forced scroll/selection loss, clean composer, no Git controls | Native chat implementation passes local stream/selection/scroll checks; the redesigned panel is loaded in real Krita with a matching candidate003 handshake. Complete live streaming/keyboard/accessibility matrix and artist review remain open. |

## Historical baseline — before implementation and live reload

The following was the starting state, not the current loaded panel or current test count.

- Authoritative objective: the user's `/goal` and saved goal-objective.md attachment (all nine outcomes; ninth heading was pasted adjacent to item eight).
- Native bridge reachable; reports bridge 2.3.0. Existing Creative Agent is the old loaded UI.
- Live Krita inspection: `painting.kra` open, 768 × 1024, 34.5 MiB; sidebar contains the old missing-canvas response. No artwork edited by this implementation pass.
- Native tests: 18 passed after context, read-only resume, save relocation guard, region mask and guarded pass review changes. These are harness tests, not real brush proof.
- No goal has yet met all of its live/release acceptance conditions.

## Ownership and integration

- Root: native bridge, painting validation, live checks, original-art preservation, integration and evidence.
- Runtime agent: Pi companion, context/plan/stage lifecycle, protocol and tests.
- UI agent: complete Qt interface, stream behavior, themes, offscreen visual checks.
- Storage/release agent: portable project store, migration/relink/history utility, self-contained Mac bundle/install.

One version/content-hash handshake must identify the loaded UI, companion and bridge before accepting live results. Copying files into an installation is not evidence that Krita loaded them.

## Local implementation verification

- 44 Python tests pass, including stage rejection, dependency reversal, manual-edit protection, restart quarantine, installation rollback, physical stage grouping, read-only colour sampling and exact protected-pixel comparison.
- All 61 Node tests passed against a temporary physical copy of the exact candidate001 companion and registry-installed dependencies, using its bundled Node 22.23.2 with isolated HOME/PATH. This includes actual-SDK forced compaction against a simulated provider. The original hashed bundle was verified before and after and remained unchanged. Test source hashes and output: `output/live-candidate-001-test-validation.json` and `output/live-candidate-001-tests.log`.
- Qt candidate passed six theme/size cases, larger text, Unicode selection during streaming, scroll preservation, context receipts/detach/pinning, question boundaries and orderly conversation restore. Renders are in `output/ui-review/`; they are **offscreen evidence**, not the loaded panel.
- The native journal quarantines uncertain operations across restart. An explicit inspection and acknowledgment can release the quarantine without painting or saving.
- Native review exposes reversible stage groups, validates all affected layers before rejection, and follows dependent agent adjustments. New stage paint now enters a named Krita group. Existing artwork is never reparented; manually changed containers remain untouched. These native changes are still awaiting live verification.
- Model-delivered canvas revisions are separate from UI preview revisions; refreshing a thumbnail must not authorize paint planned against an older image.
- `scripts/evaluate-stage-one.mjs` prepares a real-provider calibration on an isolated new copy. It has not been run; the current painting's hash remains `c6c2e8de7340c4c8000308d698313936e78184fda4ca8045d4e4246c448a219a`.
- A standalone registry-locked bundle installed/imported in temporary profiles. A compiled AppKit installer installs with bundled Node and no user Python prerequisite; six installer tests and local ad-hoc signature verification pass. Every candidate receives its own manifest and separate installer; the exact artifacts and verification records are listed in `MAC_INSTALLER.md`. This is not a Developer ID signed/notarized public release.

## Live Krita verification — 11 September 2026

The earlier Mac lock is resolved. The redesigned panel has been loaded without using a lock bypass; the old baseline UI is no longer the current state.

Candidate001, build `eef076e480c0e639effb0596357c6394b36b5ae7c6264c772e2968804dee0b21`, passed the actual Ask scenario in **Krita 5.3.3 (git 858d352)** using **OpenRouter / openai/gpt-5.6-luna**. A new conversation received a 768 × 1024 snapshot of `painting.kra`. The serialized user-image SHA-256 exactly matched the visible context receipt's content ID (`96309ec6169742c5b4eeafff894cd436664046cb3d5fc9f8567e0c1c9f624136`). The model correctly described the two red-orange fields on beige. There were zero tool calls, zero paint passes and no native painting binding. The actual panel and exact snapshot preview were visually inspected. The original artwork hash remained `c6c2e8de7340c4c8000308d698313936e78184fda4ca8045d4e4246c448a219a`. Evidence: `output/live-candidate-001-canvas-check.json`.

The root agent subsequently observed candidate003 connected in actual Krita: Settings showed **UI 0.2.0 · 808972854443**, **Companion 0.2.0 · 808972854443**, and **Bridge 0.2.0 · 808972854443**. Native health reported the same full build ID, `80897285444336afd992b11558b230c2ea9752175eded7646ad382be8a3116f5`. This is a recorded live observation from the root agent; no separate handshake evidence file is claimed here. It establishes the loaded component identity, not the remaining painting, accessibility or release gates.

Candidate004 includes the subsequent chevron/icon polish and passed the UI agent's local smoke checks. Its packaging and headless installer verification are separate from the loaded candidate003; do not infer that candidate004 has been installed or loaded from those artifact checks.

## Real model-route check

On 11 September 2026 at 10:14 UTC, **OpenRouter / deepseek/deepseek-v4.1-flash** passed the actual Pi SDK capability probe: it identified randomized quadrant colours from transmitted PNG pixels, called the harmless reporting tool, and returned the nonce supplied only in that tool result. The run took approximately 2.3 seconds and reported 1,611 total tokens including cached input. No artwork was sent and no painting tools were available.

Evidence: `output/model-route-deepseek-001/verification.json`. Probe source SHA-256: `3879c71773e7aaf6e498f5af9910ecba3e716e955ba61d7d4b9b8d29e21f7f7c`. This establishes this route's image/tool compatibility at that time. It does not establish native painting quality, other model routes, or the loaded Krita build. The runtime uses a bounded, cancellable probe and an expiring route/configuration-specific cache before painting.

Seven actual-SDK capability tests using a simulated provider passed, covering wrong-image answers, missing tools, missing result confirmation, cancellation, timeout, safe credential-free failures/cache, expiry/configuration changes and batch/text-only rejection. They are included in the combined suite.

The final planning regression was reproduced and fixed: a second unapproved draft could previously drop a first draft's character details. Requirements and character facts are now protected from the first recorded proposal, including after restore; a requested change uses the explicit revision flow. Direct user edits remain authoritative.

## Pending calibration consent

Automatic approval review rejected the planned real-provider calibration with this reason:

> The evaluation would transmit a copy derived from the user’s private painting to the untrusted OpenRouter destination and perform native painting operations; authorization covers DeepSeek evaluation in substance but does not explicitly authorize this sensitive artwork payload to OpenRouter.

The pending user question is: **“May I send a snapshot of painting.kra to DeepSeek through OpenRouter and run the two calibration brush trials on a separate working copy? Your original painting will remain unchanged.”** The offered choices are to use DeepSeek through OpenRouter or skip the model painting test for now. **No user answer has arrived as of this checkpoint.** No dependent evaluation is authorized by elapsed time or by the completed synthetic route probe. The calibration payload is an artwork-derived snapshot, its external destination is OpenRouter for the DeepSeek route, and the proposed native edits are confined to a separate working copy. Packaging and independent local verification can continue while this question remains pending.

## Remaining completion gates

All unchecked requirements in the redesign plan remain binding. In particular, no simulated provider result can establish artistic quality, a staged install cannot establish a clean external Mac installation, and automated UI checks cannot substitute for the requested artist/non-artist usability review. Record these limits honestly while completing all independently executable work.


## Current Agent handoff defect — 11 September, candidate006

User narrowed work to the live “painting tools are not reaching me” defect. Typed Agent messages were always routed through the planning tool set, and a prose answer left an existing plan in draft with its Start control hidden. Added an explicit `start_painting` planning-to-execution tool for Agent execution requests; Ask/Plan remain read only, discussion retains a paused plan, and Resume remains available for existing drafts. Starting a canvas-derived plan can no longer silently create a blank target.

Added **Use this canvas as painting target** for zero-pass conversations. It captures and pins the attached saved painting, preserves the plan/history, releases old ownership, and stays paused without painting or saving artwork. Conversations with painting changes or uncertain operations cannot be retargeted through this action.

Candidate006 `a9f49d0a83f9857a11dd456ca1b314aa4419102f35d9a5ed257d3af4a0bbaf60` installed and loaded in Krita 5.3.3; bridge health and companion process match. All 67 runtime tests and the Qt smoke suite pass. Actual UI action reconnected conversation `2d852ad8-3fad-4917-8198-827260b3dded` to `painting.kra`, with Resume visible and all six stages retained. Visually reviewed actual panel. No model painting was run for this focused fix; artistic quality and full end-to-end real-provider execution remain separate outstanding checks. Evidence: `output/current-agent-handoff-fix.json`.

The local reload helper also now restores by `study_id`, not the output directory (which changes to the artwork folder after saving). The existing conversation was restored after detecting this helper defect.


## Agent loop repair — 11 September, candidate008

The user requested autonomous painting rather than repeated Resume prompts. Reproduced a false image-test failure on actual `openai-codex/gpt-5.6-sol`: the 128px fixture returned four green quadrants incorrectly. A 512px fixture passed the actual image/tool/confirmation round trip. Evidence: `output/sol-loop-diagnostic-001/verification.json` and `output/sol-loop-diagnostic-002/verification.json`. The capability checker now uses 512px, bounded automatic retries for transient/test failures, and a stable probe-version cache key rather than invalidating on every UI build.

Fixed the bridge discarding structured HTTP 500 results. Krita sends validation failures using HTTP 500; these had been wrongly classified as lost mutation outcomes and latched the entire agent as faulted. Delivered native error codes are now preserved. The native server's serialized ValueError validations remain correctable tool errors; internal runtime failures, timeouts, partial changes and genuinely lost responses retain uncertainty protection. Verified against the actual bridge using a non-owner request, which was rejected before mutation.

Enabled Pi's bounded model retry (two retries), displaying retry progress and clearing recovered errors. Regression proves a transient provider failure after one completed paint pass recovers without replaying that pass. Removed the arbitrary 12-cycle stop while retaining time/pass/stage limits, Stop, required artistic questions and three ineffective-attempt stopping. Strengthened host instructions to correct failed visual criteria and rejected arguments without asking the artist to operate the review loop. The current plan's stop_after fields were cleared through edit_plan per the user's explicit instruction to continue across reviews.

70 Node tests pass; Qt smoke checks pass including a new active-view restore guard. Candidate008 `033c06f0c59176af68bd1924d0fcacb2d546b2a581b0a10fe64f7a0f8fcfcdfb` installed and loaded, verified through bridge health.

**Reload incident / unresolved live acceptance:** Candidate007's live reload crashed Krita. The native crash stack enters `Window_showView` / `KisViewManager::setCurrentView` during automatic conversation focus. Added an early return for an already-active document and disabled automatic focus in the reload helper. Candidate008 reloaded successfully with no painting open. The painting's saved .kra is intact; its newer unsaved upper-field appearance differs and survives in the final captured PNG. Both are preserved in `.creative-agent/recovery/2026-09-11-reload/`. User was informed immediately and asked whether to restore newer appearance or continue from saved art. Conversation restored; painting not resumed pending that choice. Do not claim end-to-end live painting loop acceptance yet.

## 2026-09-11 — Original-canvas Agent troubleshooting (candidate 012)

User authorization: continue testing and painting on `painting.kra`; no further disposable canvases. Existing-layer editing is explicitly authorized. Removed the obsolete agent-only-layer requirement from the current saved brief (backup: `goal-before-authorized-tool-access.json` alongside its record).

Confirmed defects and changes:
- Restored plans compared process-local document IDs after Krita restarted. The same saved painting was falsely rejected as a changed canvas. Compare canonical saved file paths and dimensions, refresh IDs on restore and before execution, and retain rejection for genuinely different documents or dimensions.
- Independent visual review received only flattened pixels, then failed a layer-provenance requirement because layer metadata was unavailable. Supply actual native layer metadata and persisted operation records; distinguish appearance checks from workflow evidence.
- A full-canvas stage region unnecessarily blocked whole-layer toolbox operations. Full-canvas regions now allow those operations; explicit smaller protected regions remain enforced.
- Agent toolbox adds native pressure/curve strokes, solid shapes, selections, selection modification, erasing, move/rotate/scale/shear, blend modes, brush dynamics and reversible copies of existing paint. Existing unlocked layers can be adjusted with a captured baseline. Removed 256px brush ceiling and 200-operation session lifetime cutoff. Command batches still have a responsiveness bound.
- Live Krita revealed that Node.paintPath ignores the View eraser toggle. Preset CompositeOp=erase produces actual erasure; the eraser wrapper now temporarily applies and restores that preset setting.

Evidence so far: candidate 012 build `1ad38e2da6bdaaf1132f9dad978499b3083816350cd7ee9a80986528953d9551` reported by running Krita 5.3.3. 71 runtime tests passed, 52 native tests passed. Candidate 009 live shape/selection/600px brush/rotation and exact-image rejection succeeded; corrected erasure was visibly confirmed through preset configuration. Candidate 011 resumed the original conversation and painted/saved pass 17 in the original artwork. Its reviewer exposed the missing technical evidence defect above. Candidate 012 is undergoing the complete live Agent run; do not infer artistic completion or release readiness from these checks alone.

### Stage review cadence correction — candidate 014

Removed the forced three-paint-call handoff to independent review. A scheduling yield after 24 tool turns now continues construction without treating it as a stage boundary. The model is instructed to finish substantial batches and request review at the end of the whole current stage. Pass and toolbox batches now accept up to 256 strokes/commands, including 100-stroke batches. Explicit user stop/allowance boundaries remain.

Live review uncovered another strictness defect: an extra `technical-layered-document` check caused rejection of an otherwise complete structured assessment, then the reviewer ended and the whole run paused. Extra check IDs are now tolerated; every required check must still be supplied exactly once. Regression test paints six batches without intermediate review and includes an extra observation in the final review. All 72 runtime tests pass; 52 native tests pass. Installed candidate 014 build is `4bc1ba4fc4d8bfc91c43749edd8348538e3ee9497e3e8e414e7d9a44a4eebda4`.

The attempted offline removal of the obsolete plan requirement was overwritten by companion shutdown persistence. It was subsequently removed through the live Plan → Brief editor and saved, which is the authoritative update. Do not claim an offline state edit persisted without rereading the running state.

### Candidate 015 — repeated-review and history cost

The live candidate 014 run still requested repeated reviews without applying a single correction. Added a guard against re-reviewing a failed stage at the same plan revision and painting-pass count: the painter gets an actionable tool response to address the reported issue, not another paid review call. Existing older review entries remain readable. Compaction now starts around 64k context tokens (with 12k recent tokens retained), rather than waiting to approach a model's very large context window. Observed restored history was approximately 365k input/cache tokens per decision. Current brief, requirements and canvas are still supplied independently of conversational compaction.

Candidate 015 build: `8e85f443cc7568ac8aa6bbc06161b7bc1cd584bf6cab6b5fb65ef643ec4c5f68`. All 72 then-existing runtime tests passed; added duplicate-review regression subsequently passed with all 37 studio tests. Artistic completion remains unverified; candidate 014 stopped at Stage 1 after three unchanged-review attempts, with the original painting saved at 17 passes.

### 2026-09-11 — Candidate 016: explicit stage audit boundaries

User correction: substantial painting batches should run directly, with independent audits at stage completion, not after a handful of strokes. Candidate 015 already removed the forced three-operation review and supports 256-stroke batches. Its original-painting run reached 25 passes and stage 2, then the 20-minute allowance; it did not finish the painting. Live session compaction reduced request context from approximately 381k to 28k tokens.

Candidate 016 also removes the implicit audit on every normal assistant reply. Ordinary progress replies and tool scheduling yields continue the painting loop; only an explicit stage-review request or operation allowance triggers review. Three successive cycles with no painting action still stop an unproductive model. Cancellation and explicit user stage boundaries remain enforced.

Reviewer consistency: `continue` with all required checks marked met is rejected for correction within the same reviewer session. Later-stage refinements belong in the summary, not current-stage blocking issues. This does not automatically approve unmet criteria. Painting instructions favor coherent batches (100 where useful, maximum 256) and meaningful progress milestones instead of narration after every batch.

Validation: 75 Node tests passed, including multiple batches across natural-language progress replies with exactly one stage audit, and reviewer correction of contradictory all-checks-met/continue output. Installed candidate build `8c051122082e5ebfb6c6eb25e4144c85733f7db5b57671edb6aed798d565ceee`. No claim of final artistic completion or guaranteed minutes-to-finish. User had switched to the DeepSeek conversation `84bf6415-d220-4c8f-88d3-0dc9cff82b7d`; do not silently resume the earlier Luna conversation.

### 2026-09-11 — Candidate 017: current canvas and unrestricted run allowance

User explicitly requested the original painting, no time limit, no artificial stage/pass caps, full available native painting tools, and review only at stage completion.

- New chats default to Current canvas; New painting and Copy are explicit choices. Native `current` binding operates on the actual saved or unsaved document, saving unsaved artwork to an ordinary project filename. Legacy unbound chats planned from attached artwork no longer fail with the new-blank-target error.
- Zero time/pass allowance means unlimited and is the new default. Plan UI labels zero as No time limit / No pass limit. Explicit nonzero user budgets still work. Prompts prohibit inventing stage operation/region restrictions. Repeated issue wording alone no longer triggers the three-attempt pause; no-action/unchanged-canvas detection remains.
- Native toolbox now exposes foreground colour, circular fill (not flood fill), whole-contribution solid fill, and imported brush textures. Locked source paint layers can be copied and edited on an unlocked contribution while original pixels remain intact. Toolbox and paint_pass each support up to 256 commands/strokes.
- Current user conversations `84bf6415-d220-4c8f-88d3-0dc9cff82b7d` and `b8a7626b-e382-4cd9-b62a-7a18658a0349` were updated to unlimited time/pass allowance and no stage operation/region caps, preserving artistic requirements. Backups retained. IMPORTANT: `record.json` is authoritative; `goal.json` is only a mirror. An initial mirror-only migration was overwritten on restore; corrected the authoritative records while the companion was stopped and verified after reopening.
- Validation: 75 Node tests and 54 native Python tests passed, including current-document binding for saved and unsaved canvases, unlimited elapsed time/pass count, and editing a locked source through an unlocked copy. Python panel syntax passed.
- Installed and running build `24a86316dd938f6a7d1002dc8243e99ce0d296c675acae0e16c9cab29fa601b3`, Krita 5.3.3. Live formerly blocked DeepSeek chat entered Agent execution on original `painting.kra`; persisted state after Resume confirms active, minutes=0, passes=0, all stage caps absent, target_needs_review=false, provider=deepseek. No artistic completion claim yet.

Live continuation after corrected authoritative migration: DeepSeek executed four saved native contributions on the original painting (three paint batches of 14, 14 and 10 curves plus a layer adjustment), with zero independent stage audits and no automatic pause. The model chose those batch sizes; 256 is capacity, not a forced stroke count. Run remained active. Artistic completion remains unverified.

### 2026-09-11 — Candidate 018: stage review could not represent deferred work

Live defect: at 29 contributions the reviewer confirmed Stage 1 interiors complete but marked the Stage 2 edge requirements `met=false`, returning `continue`. The painter correctly refused perimeter work because Stage 1 scope excluded it, producing repeated idle replies. This was a host/review-contract deadlock, not missing artist input.

Review checks now support a structured later-stage deferral (`deferred_to_stage`, 1-based, with `preserved=true`). The host derives nonfinal stage completion from all applicable checks; pending future work remains recorded and cannot block a finished current stage. Current-stage done_when cannot be deferred, final-stage requirements cannot be deferred, and a degraded established property cannot be deferred. Final completion still requires the full brief.

An unchanged legacy review is re-evaluated once under the corrected contract on Resume, without requiring another painting pass. Subsequent reviews retain the unchanged-canvas duplicate guard. Validation: 77 Node tests passed, including actual two-stage SDK transition, legacy deadlock recovery, and refusal to defer current-stage failures/final checks/regressions. Candidate build `8ca9b1adb24d7c7c7db1c859c0169ff756344a336ba3647a8e8898a912a5ba3f`.

Live verification: candidate 018's native health and running companion paths match. On Resume, the fresh review returned complete for Stage 1, with edge/silhouette checks explicitly deferred to Stage 2 and preserved=true. Persisted state automatically advanced current_step from 0 to 1 while retaining 29 passes (no unnecessary repaint); status active, same original painting.kra, DeepSeek official provider, unlimited allowance. Stage 2 execution resumed. During the first shutdown a deleted-QLabel exception interrupted quitting; closing the error allowed a clean restart. That shutdown defect remains separate from the verified stage transition fix.

### Source work after candidate 018 — autonomous recovery and brush documentation

User wants Agent to finish without recurring Resume prompts. Source now replaces the three-idle-reply and three-unchanged-attempt automatic pauses with a fresh execution session retaining the brief, user requirements, recent progress, last review, original artwork and operation journal. This changes the model's conversational context, not the canvas or review criteria. Stop and actual uncertain-operation handling remain. Regression verifies recovery, one original-document binding, preserved requirements and eventual completion without user Resume. 78 Node tests pass. These changes have NOT been installed into the active candidate 018; the current painting run was left uninterrupted.

The model's Dry Bristles diagnosis confused Pixel Mix with canvas pickup and read inactive parameter values as active behavior. The stored preset showed PressureMix=false, PressureScatter=false and PressureMirror=false, despite stored values/sensor curves. Krita's documented Mix blends foreground/background or samples the source gradient; Mirror reflects the tip mask. Source instructions now distinguish these meanings. No claim of a completed reusable brush-memory system: its required identities, fingerprints, measured swatches, provenance and invalidation are documented in README.

README rewritten from observed implementation and failures: current canvas workflow, unlimited defaults, stage deferrals, automatic recovery status, provider identity/auth, the approximately 64k working-context policy versus advertised model capacity, durable records, tool limitations, and actual release/artistic validation status. All local documentation links resolve. No unverified per-model million-token claim was introduced.


## Provider/model selectors and execution settings — 11 September 2026

Implemented separate provider and model dropdowns in the composer. The second dropdown contains only the chosen provider’s Pi models. Model-switch failure restores both controls to the accepted route, and sending waits for acknowledgement. Unconnected providers remain discoverable without silently continuing on another provider.

Settings → Agent execution now offers Single painter or Parallel preparation (two workers), plus Auto/Off/Minimal/Low/Medium/High/Extra high/Maximum reasoning. Preferences persist in project defaults and each conversation; Pi’s effective session level is displayed. Parallel workers share one stage snapshot and can only submit proposals. Native painting stays sequential. Stale suggestions are discarded and Stop cancels both workers. This is optional preparation concurrency, not a demonstrated overall speed improvement.

Validation: 82 Node tests, 54 native Python tests and real Qt interaction/layout checks passed. New tests exercise actual simultaneous local provider requests, single native painting execution, Stop cancellation, stale proposals, fallback after worker failure, provider rollback and reasoning persistence. Live candidate 019 showed only the three official DeepSeek models and changed the active session from Low to High and back to Auto/Low through the settings UI. Candidate 020 adds the Maximum choice reported by the live Pi route. Original painting and existing conversation retained throughout.

Known separate defect: quitting Krita can show a deleted-QLabel script error; dismissing it allows normal shutdown. Artwork was saved and unchanged during these reloads. This remains a release issue, not a claim of clean product shutdown.

Final running build: candidate 020, `7d1c9b552d5199951266fe183937be3ac937631d8feaef0775cb12e07222c17d`, matched across live UI, companion and native bridge on Krita 5.3.3. Maximum appears in the live reasoning menu. Restored conversation `84bf6415-d220-4c8f-88d3-0dc9cff82b7d` retained `{concurrency: 2, reasoning: auto}` and the original `painting.kra`; live effective reasoning is Low. Agent resumed into concurrent preparation with Stop available.

Live parallel verification: the two official DeepSeek preparation sessions began at 23:21:45.630 and 23:21:45.631 UTC and returned `submit_batch_proposal` at 23:22:23.320 and 23:22:54.603 UTC. Both requests completed; the controller handed off to the single painter without user intervention. No end-to-end speedup or artistic completion is claimed by this check.

### 2026-09-13 — Candidate 021: generated painting recipes

Added `paint_recipe` to Agent and parallel preparation proposals. Seeded local generation expands region, palette, brush size/opacity ranges, direction and irregularity into native curves. Existing precise tools remain available. Saved 256-curve contributions retain operation receipts and Stop boundaries; recipes return compact counts plus the last image. No single-layer/across-chunk contribution or reference sampling is claimed. Intersected requested region with stage region so a broad stage cannot remove the recipe's tighter brush clip.

Validation: 88 Node tests passed. A simulated Pi SDK run executes 1,200 recipe strokes through five native calls and one final stage review. Real Krita test: 1,200 strokes in 16.0 seconds including saves/previews, with clipped boundaries; a second test stops at 256 of 600 strokes. Provider latency is excluded and real-provider artistic recipe selection remains unverified. [Detailed evidence](RECIPE_TOOL_VALIDATION.md).

Build `d7eb8663c57b6188b0896bb7d4e711d25b407c125b86ef916162fbb76749e715` installed and loaded in Krita 5.3.3 without restart. New companion process and live bridge identify the build; all six changed/new runtime modules match tested source. Release packaging preserved the installed native payload, including the installed-only fill_selection addition noted in the prior audit. Original warm_color_fields.kra is unchanged, open and attached in the refreshed panel; test artwork is separate.

# How the krita-fork tasks are worked: batches of two agents and a lead

Started 19 October 2026, at the artist's request: "divide and conquer in batches … don't skimp on quality".

## Roles
- **Two agents per batch,** each on tasks that share no files, each in its own git worktree and branch of the fork
  (`forks/krita-master`, branch `agent/<task>`) with its own build directory, so they build in parallel. Helper tasks
  (`krita-native/agent-accel`) and plugin tasks work in this repository, never two at once on the same files.
- **The lead** (the main session) reviews every result, runs every suite, measures live in Krita, merges, ticks
  `tasks.md`, and starts the next agent the moment one finishes: a batch never waits for its slower agent.
- **Wake-ups:** each agent's completion wakes the lead. A recurring check-in is the backstop if one is missed.

## Quality gates, for every task
1. **Test first:** each behaviour has a test that was seen to fail. Fork code adds tests in Krita's own suites
   (`libs/libkis/tests`, `libs/image/tests`, or a new `KisTest`), and the plugin side adds ours.
2. **Green:** the fork builds; Krita's touched test suites pass; ours pass (`uv run … unittest discover`, `npm run
   test:unit`, `npm run typecheck`).
3. **Measured** where the task names a number (task 2.6's targets, 0.4's 8 seeds), live, with the numbers recorded in
   `tasks.md`.
4. **Reviewed:** a fresh reviewer agent reads each batch's diff against the specs before merging into `krita-agent`.
   Critical and important findings are fixed with a failing test first.
5. **Licence of new fork files:** the licence of the Krita library they live in (LGPL-2.0-or-later in `libs/libkis`,
   GPL-2.0-or-later in `libs/image`, `libs/ui`, and so on), copyright the artist, so they can be offered upstream. Our
   own repository stays GPL-3.0-or-later.
6. **Never:** commits with AI attribution; pushes or publishing without the artist; touching the artist's Krita 5.3.3
   settings; restarting Krita while it paints.

## Batches (dependencies first; within a batch, the two agents share no files)
| Batch | Agent 1 | Agent 2 | Lead |
|---|---|---|---|
| 1 *(running)* | 1.1 fork build, own app id and settings; 1.4 upstream policy | 0.4 whole selection in one C++ call, then 0.5 tilt, rotation and speed (same helper files, so after it) | review B's work; measure live |
| 2 | 1.2 plugin and companion running in the fork | 2.1 region refresh and 2.3 scaled region read | 0.2 the 1024×768 comparison |
| 3 | 2.2 and 2.8 revision, changed rect, change events | 2.7 and 2.5 undo history, named steps, agent move steps | 0.4 background save in the helper |
| 4 | 2.4 async stroke jobs with pressure (`paintPolylineStroke`) | 2.9 libkis traps fixed | measure |
| 5 | 5.1 brush tips and presets; 5.2 merge and bake | 5.3 tools as functions | 2.6 verify the speed targets |
| 6 | 6.1 and 6.2 feature list in the core, `.kra` round trip, libkis `Feature` | 6.3 builders (from 0.4's code, magnetic, lazy-brush) | |
| 7 | 6.4 queries and 6.5 protection | 6.6 plugin and companion use features | |
| 8 | 4.1 panel from launch; 4.2 project view | 4.3 and 6.7 canvas overlays | |
| 9 | 6.8, 6.9 and 6.10 feature memory, export, seams as features | 1.3 release pipeline | |
| 10 | 3.1a Revamp: clipping masks, folder groups, brush previews | 3.1b Revamp: scrubby zoom, overview, toolbar, presets | |
| 11 | 3.2 Revamp's plugins on Qt6 | 3.3 new-install defaults | final review of the change |

## Revamp gate (batches 10–11)
Revamp changes the interface, not the agent's ground: libkis (one `Node.setChildNodes` fix), the layer model (its
clipping masks are a view of Krita's alpha inheritance, which `clip_to` uses), the `.kra` format and the brush engine
stay as they are. After each Revamp feature lands, the Agent-mode test chats pass unchanged, plus two checks:
- **Persistent brush tweaks** (`KisPaintOpPresetSessionStorage`, Revamp `b908ad5`) keep changed preset settings until
  Reload: after an agent pass, and after one stopped mid-way, the artist's presets keep their own size, opacity and
  flow. Task 2.9's per-stroke overrides make agent strokes never change the view's preset.
- **separatebrusheraser** swaps presets with eraser mode: the plugin's eraser passes use the intended brush.

## Waiting for the artist (queued, never guessed)
- The fork's name and branding (working name "Krita Agent").
- Judging the Photoshop-like interface and the defaults by eye (batches 10–11).
- Any push, publish or release.

## Ledger
One line per finished task: task, commit(s), tests, measurement.
- 0.3: native helper on 5.3.3 (earlier commits; measured 19 October).
- 0.4 (part): protocol 3, a025c4a; timing 7a75bc8; d35e0cc.
- 0.4 (selection): protocol 4, 1dede58: 8 seeds at 6000×4500 0.67 s for the whole select (from 9.0 s), identical pixels; tests: C++ 36, Python 355, JS 388.
- 1.1 and 1.4: fork `krita-agent` ff7ec1b, 09ef936 (forks/krita-master): Qt6 arm64 build, launched with separate settings; stock files unchanged; `.kra` still opens in 5.3.3.
- 0.5: protocol 5, fbf6edd: tilt 2→9 px, speed 48→28 px live; time unconfirmed; tests Python 371, JS 388.
- Batch 1 review (fresh reviewer): 1 critical (shared autosave folder can delete either app's recovery files), 4 important (exported UTIs, empty identity not upstream, shipped kritarc defaults, kritarunner); task 1.1 reopened until fixed.
- 1.2 (code): a477e3a, Python 389, JS 390, server 21; live re-check pending (the fork app was rewritten mid-run by another build).
- Lesson: worktree builds must never install into the main checkout's `_install`; fixed in the speed agent's build script ($ROOT).
- 1.2 live: clean-install re-check passed (Agent-mode move, 46 actions, no errors). Painter issue seen: the table layer painted above the apple, hiding its lower half (layer order), for a later painter fix.
- Lesson: Krita (stock and fork) stalls while the display sleeps; unattended live checks run under `caffeinate -d -u`.
- 0.4 (save): protocol 6, 2ccd598: checkpoint returns in 6 ms instead of 5.5 s; no window-freeze gain (stock already ≤28 ms); file reopens intact; Python 405, JS 392.
- 1.1 review fixed: agent/identity-fixes merged ad7c422 into krita-agent; identity tests pass; installed Info.plist has no exported types, ranks Alternate; leak gate passes.
- 2.1/2.3 review: merge after fixes (licence headers, an unlocked scaled read could overflow on a colour-space change, refresh not grown for effect halos, missing mask and style tests). Fixes with the author.
- 2.2/2.8 review: merge after fixes (Python could hold deleted Node and Document wrappers, leaks, a global lock on every update, LOD coordinates, source mark timing, event order). Fixes with the author.
- 2.5/2.7 review: rework (a stack-wide macro absorbed artist strokes, disabled Ctrl+Z during a move and ended the artist's stroke; barrier locks could stall the GUI; no guard for a move left open). Redesign with the author: an agent-only collector, one step when the move's strokes finish, split on a shared layer, no barriers, a context manager and auto-close.
- 2.2 and 2.8: agent/events merged into krita-agent after review fixes (10 commits); suites re-run by the lead, 3/3 pass.
- 2.1 and 2.3: agent/speed-region merged 178896a (conflicts in the libkis CMake lists and AGENT-FORK.md, both sides kept); merged build: identity 2, events 2, speed 2 suites pass (DYLD_LIBRARY_PATH and KIS_TEST_PREFIX_PATH set). Note: `build-macos.sh --tests` does not turn BUILD_TESTING on in an existing cache.
- Helper halo fix (protocol 7, 03c7520): region refresh grown by every effect, equal to a whole refresh (29 C++ checks). Live on New Moscow it was no faster than the whole refresh (medians 38-47 ms against 21-25 ms), so stock keeps the whole refresh (b35f14d). The fork's region refresh grows the same way: measure it live on New Moscow before relying on it.
- Ruling (lead): batch 4 (2.4 async jobs, 2.9 traps) waits for agent/undo, since both edit `Node.cpp` and `PaintingResources` where the undo rework puts its collector; 5.1+5.2 (agent/craft) and 6.1+6.2 (agent/features) start first. Cost if wrong: a later rebase of 2.4/2.9.
- 1.5 (most): one repository. Fork-first is the artist's decision; the plan and this ledger now live in the fork at `creative-agent/openspec`.
- 2.5/2.7 rework done (agent/undo, collector design; TestDocumentHistory 22, TestPythonAgentMove 5); under a second review. Baseline check by the lead: `kis_doc2_test` (SegFault) and `FreehandStrokeTest` (SIGSEGV) already fail headless without the undo changes.
- 2.5/2.7 second review: merge after fixes (legacy GUI macros absorbing a step, pixel writes after a queued stroke on the same layer, auto-close on export and long strokes, the context manager ending another move, a 30 s freeze in setUndoIndex with the pen down, image replacement, GUI-thread pushes). Fixes with the author; the two failing upstream suites cannot be caused by the branch (reviewer) and fail on the baseline (lead).
- Priority (the artist): 1.6 fork parity goes first. Audit found the fork less capable than stock + helper: the helper is built for 5.3.3 and not loaded in the fork, so no pressure, tilt or speed, the 9 s Python seed selection, no background save, and 0 Krita actions (the audit is keyed to 5.3.3).
- 5.1/5.2: done on agent/craft (6b12a43..ade57d0; 19 new tests pass), parked unreviewed and unmerged to save usage (86%) for the critical path (1.6 parity, 2.5/2.7 undo, rest of 1.5). Review and merge after the fork is usable; then `merge_agent_work` can switch to mergeGroups and FilterMask.bake.
- Budget rule (the artist, usage 86%): at most two agents, critical path only; builds `nice -n 19`, 6 jobs.
- 6.1/6.2: done on agent/features (47172ac, 77737b2; KisFeatureListTest 16, KisKraFeaturesTest 8, TestDocumentFeatures 9, TestPythonFeatures 3; stock 5.3.3 kritarunner opened a fork .kra with features, pixels identical, no warnings). Parked for the 3:41 pm review. Open: canvas resize, crop, scale and rotate do not transform feature masks yet; stock Krita drops features if it saves the file.
- 2.5/2.7: agent/undo merged 2253af0 after two reviews; lead re-ran TestDocumentHistory and TestPythonAgentMove (pass). Main rebuild deferred until 1.6 parity merges.
- 1.6: agent/parity merged; live parity measured in the fork (above). The audit used to target port 5678 (stock) regardless; fixed. Open: mirrorNodeX in the fork, an Agent-mode chat in the fork, main rebuild running.
- Main fork rebuilt with identity, speed, events, undo and parity merged (BUILD_TESTING on): build exit 0, helper installed in the app, 13/13 merged suites pass together. Next after the 3:41 pm reset: an Agent-mode chat in the fork, then the parked reviews.
- 1.6 live chat in the fork (New Moscow copy, "finish the clouds"): 30 tool calls, 15 actions, 1066 strokes, Luna no regressions in 4 batches, the move stopped at its size limit; buildings, woman and car untouched. Seam candidates reached the painter (18 crops; it painted a "Seam repair" layer). Found: a soft horizontal band in the upper-left sky with straight top and bottom edges, made during the move, that neither Luna nor the seam check named (seams.py looks for tile strips, not a region pass's own edges): queued as a seam-check gap. Fork quit clean, no autosave. Remaining for 1.6: mirrorNodeX.
- Seam-check gap fixed at its cause: a paint pass's region mask now fades in over 48 px on edges inside the painting (stage_mask.py; canvas-border edges stay full, nothing painted outside the region). test_stage_mask 6 + test_native region test RED→GREEN; Python suite 451 OK. Open: live check in the fork (install, one region pass, look at the edge).
- 5.1/5.2 fork side: agent/craft fixed (C1, I1-I5, M2/M4/M6 docs; rulings: locked or hidden-parent refusal returns false/0 with a warning, "name (2)" for others' names, I3 documented not changed) and merged 020af6a; lead ran 14 suites via agent/run-tests.sh, all green (TestDocument without the known testAnnotations). Open: plugin side of 5.1/5.2; mergeGroups does not check locked layers inside a merged group; merge records no touched layers for move splitting.
- Test runs: crash dialogs on the artist's screen came from our setup (no KIS_TEST_PREFIX_PATH, no KRITA_PLUGIN_PATH, Krita's modal load-error box, QTest's aborting watchdog). agent/run-tests.sh is now the only way to run fork tests; agent/known-test-failures.txt lists upstream programs that block here (kis_kra_saver_test, kis_kra_loader_test: cause not found) and TestDocument::testAnnotations.
- 5.2 plugin side: merge_agent_work on the fork merges each run with one Document.mergeGroups call inside one agent move ("Merge agent work", one undo step; a refused run stops with its group names); stock keeps the projection copy. test_native_craft 2 RED→GREEN; Python 457, JS 393, typecheck OK. Live check queued for the next fork session (with the soft region edge, mirrorNodeX and the fork region-refresh timing).
- 6.1/6.2 + 6.1b: agent/features fixed (F1 complete with undo: KisFeatureImageCommand, one-line hooks in kis_image.cc x5 and kis_node_manager.cpp; F2-F4; minors). Lead ran 15 suites via agent/run-tests.sh: all green. F1 is new core code, so a fresh reviewer reads 6505aa3..422e176 before merge. Runner gained EXTRA_RESOURCE_DIRS (the fixer found colour conversions segfault without it); the upstream .kra tests still fail with it, so they stay known.
- Running: 2.4 async stroke jobs (agent/jobs), 5.3 part 1 tools as functions (agent/tools), the features fix review. Three agents (the limit).
- Features fix review (6505aa3..422e176): merge after fixes. I1 the no-features shortcut misses features restored by a queued undo; I2 upstream-touching paths untested (real mirror hook, layer-only rotate/shear, no-extra-job proof). Sent back with minors M1-M5, M8, M11 to fix and M6/M7/M9/M10/M12 to document (ruling: feature names are trimmed in add/rename).
- 6.1/6.1b/6.2: second fix round (I1 by a sticky mayHaveFeatures flag instead of an idle check, which cannot hold after the applicator queued its stroke: ruled sound, since an undo that restores a feature implies the flag was set; I2 tests incl. a real KisNodeManager mirror test) verified by the lead (17 suites green) and merged.
- Main fork rebuilding with craft + features merged (ba66a95). Next in the free slot: 6.3 builders, started after the build (its worktree clones main _install). Running: 2.4, 5.3.
- 2.4: agent/jobs done (d452406): Node.paintStrokes -> StrokeJob (state, progress, changedRect, wait for this job only, cancel as a flag, finished signal), full pen input in both stroke forms, one step or part of an agent move, refused input returns a failed job. TestStrokeJobs 14 + TestPythonStrokeJobs 4 RED via a stub, then GREEN; 21 suites green by the author. Headless 256 strokes on an empty 6000x4500: 123-306 ms (not comparable with the helper live). Fresh review running. Remaining after merge: the plugin switch-over (paint_pass to paintStrokes, Stop as cancel, bridge job registry, companion polls) and a live New Moscow measurement.
- Main fork rebuilt with craft + features (build exit 0); 22 merged suites pass together via agent/run-tests.sh.
- 5.3 part 1: agent/tools done (7a35a05): Node.fill, encloseAndFill, gradient, smartPatch; Node.move undoable (bool). TestNodeAgentTools 15 + TestPythonAgentTools 3 RED via stubs then GREEN; 25 suites green by the author. Its runs of upstream FillProcessingVisitorTest made 3 crash reports before it was listed as known; the review checks whether that failure is really upstream or our runner. Fresh review running. Merge note: 2.4 and 5.3 both edit Node.h/Node.sip and add friend class Node to Selection.h. Rule for briefs from now on: each agent writes scratch files under scratchpad/<its task>/ (two build logs collided).
- 2.4 review: merge after fixes. C1 Wash-mode presets report done before the merge (pixels, agent marking, changedRect wrong); I1 Esc / undo docker / view close cancel agent jobs; I2 unbounded wait() on the GUI thread can deadlock; I3 each job stroke ends the artist's open strokes; I4 unbounded coordinates; I6 test gaps and a gate-semaphore hazard. Ruling (I5): the artist has priority: jobs feed strokes in small windows so artist strokes run between them, and an artist Ctrl+Z mid-job cancels the job (definite prefix) and then performs the undo. Sent back to the author.
- 5.3 review: merge after fixes. Tool defaults differ (useSelectionAsBoundary, includeContourRegions); NaN and huge gradient input reach an x86 out-of-bounds read; every call ends artist strokes and waits for the whole image (ruled: not for the new calls; the older pattern added to 2.9); smart patch unbounded; test gaps. FillProcessingVisitorTest is upstream-broken (krita_add_broken_unit_test), and agent/run-tests.sh now skips every program upstream registers that way. Sent back to the author.
- 5.3 part 1: fix round verified by the lead (16 programs via agent/run-tests.sh, all green; plugin Python 459 OK by the author) and merged. Rulings: a timed-out call cancels its stroke (false means nothing changed); a node not in the document and the root are refused by move; smart patch capped at 512x512 bounding box (measured: 500x500 5 s, 1 MP over 13 s). Remaining of 5.3: part 2 (perspective, warp, liquify), pattern fill, moving a selection's pixels, the live seam scenario, the plugin side.

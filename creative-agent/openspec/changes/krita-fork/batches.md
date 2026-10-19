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

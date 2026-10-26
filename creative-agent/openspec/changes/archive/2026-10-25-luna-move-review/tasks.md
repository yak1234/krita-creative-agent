# Luna Move Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In Agent mode, Luna reviews every painting batch against the canvas before it. A batch that covered a
focal feature or added an artifact is undone, at most twice per move. Its verdict shows on the move and in tests.

**Architecture:** There is a new typed check, `moveCheck`, in `visual-checks.ts`, with two new question kinds:
covered feature and texture over forms. A shipped Pi extension, `extensions/luna-review.ts`, runs it from Pi's
`tool_result` event through a `ReviewHost` port that `studio.mjs` provides. The port covers mode, the batch's passes,
feature names, review, undo through `review_pass`, record and stop. The test driver gains a Luna override, a
`runtime_luna` summary and a test-only "keep protected area" that works only on benchmark copies.

**Tech Stack:** Node companion (Pi SDK `tool_result` handlers, async and chained), strict TypeScript, node:test,
the Krita 5.3.3 Python plugin (unittest via uv), FastMCP (`test_driver_client.py`).

**Spec:** `openspec/changes/luna-move-review/specs/luna-move-review/spec.md`, design in `design.md` beside it.

## Global Constraints

- New modules are strict TypeScript (`tsconfig.extensions.json`). Pi extensions are registered inline
  (`extensionFactories`), never by path.
- Threshold is the existing `QUESTIONS.pass.threshold` (0.7). Automatic undos: at most **2 per move**; a third
  finding is reported, not undone, and the move stops for the artist.
- Luna setting `routing`: `off` does nothing; `evaluate` records only and never delays the painter; `guide` awaits
  the review and undoes.
- Skip calls that only change layer settings (`adjust_layer`, `set_layer`), calls with no painted pass, and errors.
- A Luna fallback (timeout, bad answer) is never a pass: it is recorded as `fallback` and the batch stays.
- Runtime verdicts are labelled `runtime_luna` in test output, never as an offline score.
- `creative_docker.py` is not reloadable. Its card line waits for the artist's next Krita restart. Ask once, at the
  end, and never restart a running Krita without a yes.
- Tests: `npm run test:unit` and `npm run typecheck` in `krita-creative-agent`. Python:
  `uv run -q --with pyqt5 --with pillow --with numpy --with httpx python -m unittest discover -s tests -p 'test_*.py'`.
  Tests delete every file they write. Commits carry no co-author line.
- Live steps: check idle in a step of its own first. Use copies only. Announce documents before and after.

## Review Focus

1. Undo fails (the pass was already rejected, or the revision changed): it is reported as `warned`, does not count
   toward the cap, and the painter's result still carries the finding. Tested in Task 2.
2. A feature named in an area that was absent from BEFORE never counts as lost: the question compares with BEFORE.
   Tested in Task 1 (the wording) and live in Task 6.
3. Evaluate never awaits Luna. The tool result comes back before the review resolves. Tested in Task 2.
4. The Luna setting changes between moves: the host reads `mode()` on every call, never cached. Tested in Task 2.
5. Two checks on one batch: the per-pass `visualPassCheck` must not also run in an Agent move, or it would cost
   twice and add a second note. Tested in Task 3.

---

### Task 1: `moveCheck`: the batch question set

**Files:**
- Modify: `krita-creative-agent/src/visual-check-questions.json` (new `move` section)
- Modify: `krita-creative-agent/src/visual-checks.ts`
- Test: `krita-creative-agent/tests/visual-checks.test.mjs`

**Interfaces:**
- Produces:
  - `type MoveFinding = LocatedFinding & {feature?: string}`.
  - `type MoveCheckResult = CheckFallback | {findings: MoveFinding[]; usage; elapsed_ms; fallback?: undefined}`.
  - `moveCheck({client, before, after, features, signal}: {client: DecisionMaker; before: DecisionPart; after: DecisionPart; features: string[]; signal?: AbortSignal}): Promise<MoveCheckResult>`.
  - `MAX_FEATURES = 4`.

JSON `move` section, exact copy:

- `texture_over_forms`:
  - label "texture over forms";
  - instructions "Does AFTER lay a broad, even texture or wash over forms that BEFORE showed clearly (cloud shapes, edges, lit areas), so they read flatter or vaguer than in BEFORE?";
  - criteria true "AFTER flattens or blurs forms BEFORE showed.", false "Forms BEFORE showed are as clear or clearer.";
  - `blockin_exempt: true`.
- `feature`:
  - instructions "Is the {feature} that BEFORE shows as visible in AFTER as in BEFORE? Answer true only if BEFORE shows it and AFTER covers, removes or hides it. If BEFORE does not show it, answer false.";
  - criteria true "AFTER covered or removed the {feature} BEFORE showed.", false "The {feature} is as visible as before, or BEFORE did not show it.";
  - label "{feature} covered".
- `any_feature`:
  - instructions "Did a distinct object BEFORE shows (a moon, figure, light source, building top) disappear or get covered in AFTER?";
  - criteria true "A distinct object from BEFORE is gone or covered in AFTER.", false "Every distinct object from BEFORE is still visible.";
  - label "an object covered".

- [x] **Step 1: Write the failing tests** (fake `client.decide` that records the questions and returns answers)
  - `moveCheck asks the artifact questions, texture over forms and one question per feature`:
    - features `['Moon','Lit window']`;
    - the first request's question keys include `flat_block`, `established`, `texture_over_forms`, `feature_0`, `feature_1`;
    - they exclude `splice` (reference only) and `any_feature`;
    - `feature_0` instructions contain `Is the Moon that BEFORE shows`.
  - `with no features it asks the generic object question`: the key `any_feature` is present, `feature_0` is absent.
  - `a covered moon is a located finding naming the feature`:
    - answers `feature_0` noul 0.9, everything else 0.1 (established 0.95), then locate answers `feature_0` choice `top_right`;
    - the result is `findings: [{type:'covered_feature', feature:'Moon', label:'Moon covered', probability:0.9, location:'top_right'}]`.
  - `texture over forms on a block-in is exempt`: `texture_over_forms` 0.9, `established` 0.3 → `findings: []`.
  - `features past MAX_FEATURES are dropped`: 6 names → only `feature_0..feature_3` asked.
  - `a fallback is returned, not findings`: decide returns `{fallback:'timeout', elapsed_ms:5}` → `{fallback:'timeout', elapsed_ms:5}`.

- [x] **Step 2: Run them to see them fail**
  Run: `cd krita-creative-agent && node --test tests/visual-checks.test.mjs`
  Expected: FAIL, `moveCheck` is not exported.

- [x] **Step 3: Implement `moveCheck` in `visual-checks.ts`**
  - Make one `detect-move-failures` request:
    - `artifactQuestions()`;
    - `texture_over_forms`;
    - one `feature_<i>` per name, with `{feature}` replaced (names trimmed, de-duplicated, sliced to 60 characters);
    - or `any_feature` when there are none.
  - Artifact findings come from `artifactFindings`, with `texture_over_forms` given the same block-in exemption.
  - Feature findings: type `covered_feature`, with `feature` set to the name, or label "an object covered" for `any_feature`.
  - Locate the flagged ones with the existing location question in a `locate-move-failures` request. Factor the
    locate step out of `passCheck` into a shared helper, so `passCheck` keeps its exact requests (its tests must
    still pass).

- [x] **Step 4: Run them to see them pass**
  Run: `node --test tests/visual-checks.test.mjs && npm run typecheck`
  Expected: PASS, no type errors.

- [x] **Step 5: Commit** `Luna move check: covered features and texture over forms beside the artifact checks`

### Task 2: `extensions/luna-review.ts`

**Files:**
- Create: `krita-creative-agent/extensions/luna-review.ts`
- Modify: `krita-creative-agent/src/extensions.mjs` (export `lunaReviewExtension(host)`)
- Test: `krita-creative-agent/tests/luna-review.test.mjs`

**Interfaces:**
- Consumes: `MoveCheckResult` and `MoveFinding` (Task 1).
- Produces:

```ts
export type LunaMode = 'off' | 'evaluate' | 'guide';
export type BatchPass = { id: string; before_path: string; title?: string; layer_id?: string; area?: number[] | null };
export type Verdict = { move: number; call_id: string; status: 'kept' | 'undone' | 'warned' | 'fallback';
  findings: MoveFinding[]; undone_pass_ids?: string[]; reason?: string };
export type Undone = { pass_ids: string[]; image?: ImageContent; image_path?: string; revision?: string };
export interface ReviewHost {
  mode(): LunaMode;                     // read on every call
  move(): number | null;                // the Agent move in progress; null outside an Agent move
  painting(toolName: string): boolean;  // the paced painting tools
  batch(toolCallId: string, toolName: string, input: Record<string, any>, details: any): BatchPass[]; // painted, not layer settings
  features(): Promise<string[]>;        // kept and proposed protected-area names
  review(input: { before: string; after: string; features: string[] }): Promise<MoveCheckResult>;
  undo(passes: BatchPass[]): Promise<Undone | null>;
  record(verdict: Verdict): void;
  stop(message: string): void;         // end the move after this turn
}
export const UNDO_CAP = 2;
export default function lunaReview(host: ReviewHost): (pi: ExtensionAPI) => void;
```

  - `extensions.mjs`: `lunaReviewExtension = host => ({ name: 'luna-review', factory: lunaReview(host) })`.

Fixed copy of the `luna_review` line appended to the tool result (one JSON text part `{luna_review: {...}}`):
- Undone: `note`:
  > Luna undid this batch: <lost>. The attached image is the canvas now. Reach the same goal another way: keep what already works and refine it. If <feature> is in the way, propose_protection for it first.

  Plus `findings` and `undone_pass_ids`.
  - `<lost>` is the findings' labels with their location, joined by "; ", e.g. `Moon covered (top_right)`.
  - The protection sentence appears only when a finding has a `feature`.
- Warned, cap reached: `note`:
  > Luna found <lost>, but it already undid <UNDO_CAP> batches in this move, so this one stays. Stop here: the artist decides.

  Then `host.stop("Luna undid 2 batches in this move; this one also has <lost>.")`.
- Warned, the undo failed: `note`:
  > Luna found <lost> in this batch; it could not be undone. Repair it in the next batch.

- [x] **Step 1: Write the failing tests** (a fake `pi` collecting `on('tool_result')`, as in `loop-guards.test.mjs`, and
  a fake host whose `review` returns scripted results)
  - `guide: a covered moon is undone and the painter told what was lost`:
    - the result content has no image part from before;
    - it has the undone image;
    - the `luna_review.note` starts with `Luna undid this batch: Moon covered (top_right).`;
    - the note contains `propose_protection`;
    - `undo` was called with the batch's passes;
    - `record` got `{status:'undone', move:1}`.
  - `guide: a clean batch is recorded kept and the result is unchanged`: the handler returns undefined, and `record` got `status:'kept'`.
  - `the third finding in one move is not undone and stops the move`:
    - three findings in move 1: `undo` was called twice;
    - the third `record` has `status:'warned'`;
    - `stop` was called once, with a message containing `Luna undid 2 batches`.
  - `the cap is per move`: two undos in move 1, then move 2's finding is undone.
  - `a failed undo is warned and does not count toward the cap`: `undo` returns null → `warned`, with "could not be undone". The next two findings are still undone.
  - `evaluate records without delaying the result`: `review` never resolves until released; the handler resolves to undefined first, and `record` comes after the release; `undo` is never called.
  - `off, no move, layer settings, errors and empty batches are skipped`:
    - `review` is never called for: mode off; `move()` null; tool `adjust_layer` (`painting` false); `isError: true`; `batch` returning `[]`.
  - `a fallback keeps the batch`: `{fallback:'timeout'}` → `record` gets `status:'fallback'`, and no undo.
  - `mode is read on every call`: the first call in guide, the host is switched to off, the second call is not reviewed.

- [x] **Step 2: Run them to see them fail**
  Run: `node --test tests/luna-review.test.mjs`
  Expected: FAIL, it cannot find `extensions/luna-review.ts`.

- [x] **Step 3: Implement `lunaReview`**
  - Count undos per move number in a Map.
  - BEFORE is `batch[0].before_path`; AFTER is `details.image_path`.
  - On undo, return `{content, details: {...details, image_path, revision}}`, with image parts replaced by `undone.image`.
  - Errors thrown by the host are caught and recorded as `fallback` (reason: the message). A handler that throws
    only reaches Pi's `emitError`.

- [x] **Step 4: Run them to see them pass**
  Run: `node --test tests/luna-review.test.mjs && npm run typecheck`
  Expected: PASS.

- [x] **Step 5: Commit** `Luna review extension: per-batch review in Agent moves, undo capped at two per move`

### Task 3: Studio wiring: the host, the move's verdict, one check per batch

**Files:**
- Modify: `krita-creative-agent/src/runtime.mjs:255-266` (a `extensionFactories?: () => any[]` hook, added after the loop guards)
- Modify: `krita-creative-agent/src/studio.mjs` (`reviewHost()`, `extensionFactories()`, `visualPassCheck` skip, `runMove` activity line)
- Modify: `krita-mcp/krita-plugin/kritamcp/creative_docker.py:1887-1895` (`show_move` adds `move['review_line']` when present)
- Test: `krita-creative-agent/tests/studio.test.mjs`, `krita-creative-agent/tests/ui_smoke.py` (or the panel test that covers `show_move`)

**Interfaces:**
- Consumes: `ReviewHost`, `Verdict`, `lunaReviewExtension` (Task 2); `moveCheck` (Task 1).
- Produces:
  - `move.review = {verdict: 'kept'|'undone'|'warned', findings: MoveFinding[], undone_batches: number, batches: number}`.
    `verdict` is `undone` if any batch was undone, else `warned` if any was warned, else `kept`. Fallback batches
    count in `batches` only.
  - `move.review_line`, a one-line string:
    - "Luna: no regressions in N batches"
    - "Luna undid K of N batches (Moon covered)"
    - "Luna warned: Moon covered"
  - `move.luna_stopped`: the stop message.
  - Diagnostics event `{type:'move_review', ...verdict}`.

- [x] **Step 1: Write the failing tests** in `studio.test.mjs`, with the existing fake bridge and a fake Luna client
  answering `detect-move-failures`:
  - `an Agent batch that covers the moon is undone and the move carries the verdict`:
    - an Agent move, Luna `guide`, one `paint_batch` whose Luna answer flags `feature_0` (protection_list returns `[{name:'Moon', state:'pending'}]`);
    - the bridge received `review_pass` reject for the batch's passes;
    - `move.review.verdict === 'undone'`;
    - `move.review_line` matches `/Luna undid 1 of 1 batch.*Moon covered/`.
  - `an Agent move does not also run the per-pass check`: the same move with a clean answer → zero `detect-pass-failures` requests and one `detect-move-failures` request.
  - `a stopped move tells the artist why`: a third finding → the idle activity text includes `Luna undid 2 batches`.
  - `features are kept and proposed areas, not locked layers`: protection_list returns `Moon/active`, `Rim/pending`, `locked-layers/active`, `Old/removed` → features `['Moon','Rim']`.
  - Panel: `show_move` with `review_line` renders it under the detail line, html-escaped. Without it, the card text is unchanged.

- [x] **Step 2: Run them to see them fail**
  Run: `node --test tests/studio.test.mjs` (and the panel test command)
  Expected: FAIL, no `move.review`.

- [x] **Step 3: Implement**
  - `reviewHost()` returns:
    - `mode: () => this.lunaMode()`;
    - `move: () => this.mode==='agent' && this.executionPhase==='agent' ? this.currentMove?.number ?? null : null`;
    - `painting: name => PACED_TOOLS.includes(name)`;
    - `batch`: `this.callPasses({id, tool, args: input}, {details})` filtered to not `LAYER_SETTINGS` with a `before_path`;
    - `features`: `super.callNative('protection_list')` names with state `active` or `pending`, excluding id `locked-layers`, and `[]` on error;
    - `review`: images through `imageContent` + `moveCheck` with `this.luna()` and `this.lunaSignal()`;
    - `undo`: `rejectDamage`, mapped to `Undone`, and it sets `currentMove.canvas`;
    - `record`: updates `move.review` and `review_line`, diagnostics, emits `{type:'visual_check', mode, findings}` when there are findings, then persists and publishes;
    - `stop`: sets `move.luna_stopped` and `this.yieldRequested = true`.
  - `extensionFactories()` returns `[lunaReviewExtension(this.reviewHost())]`. `runtime.mjs` appends
    `hooks(this).extensionFactories?.() ?? []` after `LOOP_GUARDS`. Luna review is kept even with `loopGuards: false`.
  - `visualPassCheck` returns early when `this.mode==='agent' && this.currentMove`.
  - `runMove`'s finally appends `move.review_line` to the idle activity text. When `move.luna_stopped` is set, it is used instead of "keep it, undo it…".
  - `creative_docker.show_move`: the review line is a third line.

- [x] **Step 4: Run them to see them pass**
  Run: `npm run test:unit && npm run typecheck` and the panel test.
  Expected: PASS, and the full suite stays green.

- [x] **Step 5: Commit** `Agent moves carry Luna's verdict: the studio hosts the review, undoes through review_pass, and shows one line`

### Task 4: The painter proposes protection for focal features

**Files:**
- Modify: `krita-creative-agent/src/prompt.mjs` (`<protection>` section)
- Modify: `krita-creative-agent/skills/repaint-area/SKILL.md`, `skills/fix-region/SKILL.md`, `skills/paint-sky/SKILL.md`
- Test: the existing prompt tests (length cap), plus one assertion in `tests/core.test.mjs` or wherever the prompt sections are asserted

- [x] **Step 1: Write the failing test** `the protection section asks for a named area before a broad pass over a focal feature`:
  `PAINTING_INSTRUCTIONS` matches `/before a broad pass over a focal feature/` and `/propose_protection/`. The prompt's
  length stays at or under its value at the start of this task.
- [x] **Step 2: Run it to see it fail.** Expected: FAIL on the first regex.
- [x] **Step 3: Edit the prompt and the skills**
  - Replace "call propose_protection when the artist asks to protect something" with:
    > call propose_protection when the artist asks to protect something, and before a broad pass over a focal feature (the moon, a figure, a lit window): name it ("Moon") and say so
  - Trim elsewhere in the same section if the cap needs it.
  - In each skill's broad-pass step, add one line: "First propose_protection for any focal feature inside the area (the moon, a figure), named; Luna checks it after the batch."
- [x] **Step 4: Run** `npm run test:unit`. Expected: PASS.
- [x] **Step 5: Commit** `Painter proposes a named protected area before a broad pass over a focal feature`

### Task 5: Test driver: the Luna override, `runtime_luna`, keeping a proposed area on a test copy

**Files:**
- Modify: `krita-mcp/krita-plugin/kritamcp/creative_tools.py` (operation `test_keep_protection`, guarded like `close_benchmark_copy`)
- Modify: `krita-creative-agent/src/test-companion.ts` (`StartOptions.luna`, `protect(name)`)
- Modify: `krita-creative-agent/src/test-driver-server.ts` (`POST /protect`; `/state` adds `runtime_luna`)
- Modify: `krita-creative-agent/test_driver_client.py` (`creative_test_protect(name)`; `creative_test_start(luna=...)`)
- Test: `tests/test_protection.py` (or `test_native_craft.py`, whichever holds the `close_benchmark_copy` guard tests), `tests/test-companion.test.mjs`, `tests/test-driver-server.test.mjs`, `tests/test_test_driver_client.py`

**Interfaces:**
- Produces:
  - Plugin `creative` operation `test_keep_protection` `{name}`:
    - the active document's path must match the benchmark-copy regex (factor the regex out of `close_benchmark_copy` into one constant used by both);
    - it sets every pending area with that name to `active`;
    - it returns `{status:'ok', kept: n}`;
    - it refuses with "Only test copies in benchmark-runs/ can be kept from a test." otherwise;
    - it refuses with "No proposed area named '<name>'." when there is none.
    - It makes no pass and no checkpoint.
  - `TestCompanion.protect(name: string): Promise<{kept: number}>` calls the bridge `creative` operation `test_keep_protection`.
  - `StartOptions.luna?: 'off'|'evaluate'|'guide'` is written into the copied `execution-settings.json` as `routing`.
  - `/state` adds `runtime_luna: [{move, verdict, undone_batches, batches, findings}]`, one per move with a `review`.

- [x] **Step 1: Write the failing tests**
  - Python, `test_keep_protection`:
    - it refuses on a document outside `benchmark-runs/`;
    - it keeps "Moon" on a path like `/x/benchmark-runs/202610181200-tool-choice/moscow-finish-clouds-1/new_moscow_finished.kra`;
    - it refuses an unknown name;
    - `close_benchmark_copy`'s existing tests still pass with the shared constant.
  - TS: `start({luna:'evaluate'})` writes `routing: 'evaluate'` into the test chat's settings and leaves the artist's file untouched; `protect('Moon')` sends `test_keep_protection`; `/state` returns `runtime_luna`; `POST /protect` without a name is a 400.
  - Python MCP client: `creative_test_protect` posts `/protect`.
- [x] **Step 2: Run them to see them fail.** Expected: FAIL (unknown operation, missing route).
- [x] **Step 3: Implement** as in Interfaces.
- [x] **Step 4: Run** the Python suite, `npm run test:unit`, `npm run typecheck`. Expected: PASS.
- [x] **Step 5: Commit** `Test driver: Luna override, runtime_luna per move, and keeping a proposed area on a test copy`

### Task 6: Build, install, reload, and the clouds test

Not TDD: the live check that the change does what the artist asked ("especially the moon").

- [x] **Step 1:**
  - Build and install the companion (`npm run build`, then the install script the repo uses).
  - Check that Krita is idle in its own step, then reload the bridge (`dev_reload`).
  - The new plugin operation is reloadable; `creative_docker` is not, so its card line waits for a restart.
- [x] **Step 2:** Run the clouds test:
  - `creative_test_start` on `new_moscow_finished.kra` (a copy), with `luna:'guide'` and the `moscow-finish-clouds` request;
  - when the painter proposes "Moon", keep it with `creative_test_protect('Moon')`;
  - wait for the move, and read `runtime_luna` and the canvas;
  - export the final canvas for the artist (SendUserFile).
- [x] **Step 3:** Record what happened:
  - the verdicts, the undos, whether the moon survived, the time and cost per batch;
  - write it in `openspec/changes/luna-move-review/design.md` under a new "Live results" heading;
  - commit `Luna move review: live clouds result`.
- [x] **Step 4:** End the test chat (`creative_test_end`), and check that the copy is closed and deleted. List the documents before and after.

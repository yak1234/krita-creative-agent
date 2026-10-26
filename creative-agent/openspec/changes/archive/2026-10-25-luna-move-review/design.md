## Context

Luna is the second model that makes decisions while painting. Its decision code is strict TypeScript
(typed-luna-core). `visual-checks.ts` `passCheck({client, before, after})` asks the pass questions in
`visual-check-questions.json` (six failure types: splice, duplicate, flat_block, stripes, ellipses, hard_graphic;
threshold 0.7). Autopilot uses it after each painting call; Agent mode skips it (`studio.mjs` afterPainting returns
early). Protected areas (`protection.py`): the painter proposes an area, the artist keeps or removes it in the panel
(`PANEL_ONLY`), and every operation's result is erased or masked inside kept areas.

Evidence: five live clouds tests, 2026-10-18 (benchmark-runs/2026101820*-tool-choice). Every one had a good middle
and a worse end; in two the moon disappeared under the last broad pass.

## Goals / Non-Goals

**Goals**
- A regression made by one painting batch is caught before the next batch, and undone in Guide mode.
- Focal features the artist cares about survive a move: hard protection when the artist kept the area, Luna's check
  by name otherwise.
- The artist sees Luna's verdict on the move card; tests read the same verdict.

**Non-Goals**
- Changing Autopilot's pacing review (it already checks each call).
- Judging whether the request was fulfilled ("are the clouds finished?"): that stays with the painter and the artist.
- Protecting areas the artist has not approved.

**Anti-goals** (failure even if it works)
- An undo loop: Luna undoing batch after batch until the move ends empty.
- False alarms on changes that cannot add an artifact (opacity, blend, style: `LAYER_SETTINGS`, as Autopilot skips).
- A runtime Luna graded by itself: test reports label runtime verdicts as runtime, never as an offline score.

## Decisions

### Where it runs: a Pi extension with a host port
`extensions/luna-review.ts` exports `lunaReview(host: ReviewHost): ExtensionFactory`, registered inline beside the
loop guards. Its `tool_result` handler runs for painting calls (the paced tools) that changed the canvas. The host
port, provided by `studio.mjs`, keeps the extension free of studio internals and testable with a fake host:
- `mode(): 'off' | 'evaluate' | 'guide'` (the existing Luna setting) and `agentMove(): boolean`;
- `batch(toolCallId)`: the passes the call made, with their before/after images;
- `features()`: the names of kept and proposed protected areas;
- `review({before, after, request, features})`: the typed check (below);
- `undo(passIds)`: rejects the passes through `review_pass`, as the panel's reject does;
- `record(verdict)`: diagnostics, the move card, the test driver.

### What Luna checks
One vision request per batch: the existing pass questions plus
- `covered_feature`: for each feature name, "is <feature> as visible in AFTER as in BEFORE?" and, with no names, a
  generic "did a distinct object (moon, figure, light source, building top) disappear or get covered?";
- `texture_over_forms`: "did a broad texture flatten forms BEFORE showed (cloud shapes, edges)?".
Threshold: the existing 0.7. Located findings, as `passCheck` returns them.

### What happens (Guide)
- No finding: nothing; the verdict is "kept".
- A finding: `undo` the batch's passes, then append to the tool result one `luna_review` line: what was lost, where,
  and "the batch was undone; reach the same goal another way, protecting <feature> first if it is in the way".
- **Undo cap** *(my call)*: at most two automatic undos per move; a third finding is reported, not undone, and the
  move stops for the artist ("Luna undid two batches; this one also covered the moon").
- Evaluate: record only. Off: nothing. Skipped: layer-settings-only calls, and calls whose result changed nothing.

### Focal features through protection (the artist's choice)
- Prompt and the repaint-area and fix-region skills: before a broad pass over an area with a focal feature (the
  moon, a figure, a lit window), propose a protected area for it with a name ("Moon") and say so in the progress
  line. The artist keeps it in the panel; kept areas are enforced by the plugin as today.
- Luna's `covered_feature` question uses the names of kept and proposed areas, so a feature is checked even before
  the artist keeps it.
- Already kept areas from earlier chats count the same way.

### Move card and tests
- The move gains `review: {verdict: 'kept' | 'undone' | 'warned', findings, undone_batches}`; the card shows one
  line. The panel already renders move fields through the companion; *(builder to confirm whether the line needs a
  `creative_docker.py` change, which would need a Krita restart batched with others)*.
- `creative_test_state` returns each move's `review`, so the clouds test scores: methods (tool choice) and Luna's
  runtime verdict, labelled `runtime_luna`.
- Test-only: `creative_test_protect(name)` keeps a proposed area in the test chat, as the artist's panel click
  would *(my call: tests cannot click the panel)*.

## Risks / Trade-offs

- **Cost and time**: one vision call per batch (a few seconds, a few cents); in Guide the next batch waits for it.
- **False positives undo good work** → threshold 0.7, the undo cap, and the reason shown to the painter and on the
  card so the artist sees why.
- **Feature names Luna cannot find** ("Moon" when the moon is tiny) → the question asks about visibility relative
  to BEFORE, so a feature absent in BEFORE never counts as lost.

## Live results (2026-10-18)

- **Runs 1 and 3, New Moscow at full size (6000×4500, 258 nodes):** both blocked by the painting's weight, not by this change.
  - One `observe` took 909 s while 10 live filter masks recomposited, a wavelet noise reducer among them.
  - Two `fill_region` results were lost while a 500 MB checkpoint saved.
  - Follow-up: the `painting-weight` change.
- **Run 2:** found that `propose_protection` changed the canvas revision, so the painter's next pass was refused. Fixed:
  the revision skips the protection group.
- **Run 4, a flat 2000×1500 copy of the same picture:**
  - the painter proposed "Moon" itself, and the test kept it;
  - protection undid a filter that reached the Moon;
  - Luna reviewed the move: kept, no findings. The card read "Luna: no regressions in 1 batch".
  - Found: a batch that stopped on a failed action was not reviewed. Fixed: the host finds a batch's passes by what it
    added.
  - The moon survived. The visible change was small (a sky block-in), so the clouds themselves are not yet judged.

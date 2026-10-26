## 1. Luna client and routing

- [x] 1.1 Create `src/luna-decisions.mjs` (`LunaClient`) per D1. It covers ordered text/image parts (Pi image content → data URL via `image_url`), the 4 s deadline plus caller abort, and the mapping of refusals, errors and aborts to fallback reasons, with no response bodies in logs. Verify with unit tests in 5.1.
- [x] 1.2 Create `src/routing.mjs`: move the neutral exports from `typesafe-routing.mjs` unchanged and add `LunaRouter` (the existing question texts, plus an optional `image`). Verify `node -e "import('./src/routing.mjs')"` loads without `@typesafe-ai/sdk`.
- [x] 1.3 Delete `src/typesafe-routing.mjs` and `src/typesafe-credentials.mjs`. Verify `grep -rn -i typesafe src/` returns nothing after task 3.4.

## 2. Visual checks

- [x] 2.1 Create `src/visual-check-questions.json` with the six per-pass failure texts (introduced-by-pass wording), the 3×3 location labels and the progress scale. Verify it parses and that both `visual-checks.mjs` and the Python evaluation load it.
- [x] 2.2 Implement `passCheck({client, before, after, signal})` per D2. Request 1 sends six yes/no questions on BEFORE/AFTER. Request 2 asks for locations only when any probability is ≥ 0.7. The result is `{findings, usage}` or a fallback. Verify with unit tests in 5.2.
- [x] 2.3 Implement `progressCheck({client, previous, current, checks, signal})` per D4: one score question per repeated failing check (at most 8), returning `{scores, mean}` or a fallback. Verify with unit tests in 5.2.

## 3. Runtime integration

- [x] 3.1 In `studio.mjs`, add `resolveLunaKey()` (Pi `getAuth('openrouter')`, then `OPENROUTER_API_KEY`) and a cached `LunaClient`. Push the key to `this.secrets`, and clear the cached client in `configureProvider()` when OpenRouter changes. Verify with studio tests for "connected", "env fallback" and "not_connected".
- [x] 3.2 Routing: use `LunaRouter` in the routing method. Load the routed `decisionObservation`'s image (`image_path`, ≤1024 px) and pass it when the canvas is attached or the agent is painting. (Implementation note: this replaces caching the captured content, which would have left stage routing inside the painting loop text-only.) Status text becomes "Luna evaluation/suggestion". Verify with a studio test that the image is sent when attached and omitted when detached.
- [x] 3.3 Per-pass check hook in `callNative` per D3. Evaluate runs in the background (fire and forget) and records `visual_check` diagnostics and a panel event. Guide awaits it and attaches `result.visual_check`. Stale results are discarded. Off makes no call. Verify with studio tests for each mode, plus one asserting that a fallback leaves the pass result unchanged.
- [x] 3.4 Progress check per D4:
  - store the stage-region crop image path on each review record (`:986`);
  - run `progressCheck` when the repeated count is ≥ 2;
  - store `progress` on the review;
  - in Guide mode, make the stall and pause counting use progress (clear ≥ 2 breaks the run; recover only when all three means are < 1; fall back to the current rule when any is missing).

  Verify with studio tests for stalled, progressing and missing-progress sequences.
- [x] 3.5 Remove `configureTypeSafe()` and the `configure_typesafe` case in `main.mjs`, and update the `execution-settings.mjs` error text to "Luna decisions". Verify `grep -rn -i typesafe src/` is empty and `npm run test:unit` passes.

## 4. Panel, packaging and scripts

- [x] 4.1 In `creative_docker.py`:
  - rename the setting to "Luna decisions" (label and accessible name);
  - replace the note with the data-flow text;
  - remove the key field, button and `save_typesafe_connection`;
  - show per-pass findings (type and location) and review progress in the activity or pass history.

  Verify `uv run --python 3.13 --with PyQt5 python tests/ui_smoke.py` passes, with new assertions for the label and the finding display.
- [x] 4.2 Run `npm uninstall @typesafe-ai/sdk`. Update the import check in `scripts/build-release.py`, and drop `typesafe_doppler` carry-over in `scripts/install.py` and `scripts/install-release.mjs`. Verify `npm ls @typesafe-ai/sdk` is empty and `npm run test:packaging` passes.
- [x] 4.3 Replace `scripts/evaluate-typesafe-routing.mjs` with `scripts/evaluate-routing.mjs`, using `LunaRouter` and the D6 key resolution. Verify that running without a key exits with a clear "no credential" message and makes no request.
- [x] 4.4 Create `scripts/evaluate-visual-checks.py` per D7: paired before/after injections for detection, false positives and location; graded corrections for progress ordering; questions loaded from the shared JSON; images and `results.json` saved. Verify a run without a key stops before any request.
- [x] 4.5 Update `scripts/live-acceptance.mjs`: rename the check to `real_luna_routing`, use the Luna key source, and add the image control plus one per-pass check. Verify it reports `blocked` without a key instead of crashing.

## 5. Tests

- [x] 5.1 Port `tests/typesafe-routing.test.mjs` to `tests/routing.test.mjs` with an injected `fetch`. Cover:
  - the URL, model and parts order;
  - the image part only when given;
  - gating;
  - the 502 refusal → `refused`;
  - not_connected, error, cancel and timeout;
  - redaction.

  Verify `node --test tests/routing.test.mjs` passes.
- [x] 5.2 Add `tests/visual-checks.test.mjs`:
  - a clean pass makes one request with no findings;
  - a flagged pass makes two requests and returns findings with locations;
  - answers below 0.7 are ignored;
  - progress scores and their mean;
  - the check cap of 8;
  - fallbacks.

  Verify `node --test tests/visual-checks.test.mjs` passes.
- [x] 5.3 Update the routing tests in `tests/studio.test.mjs` (router field rename) and keep:
  - Ask read-only;
  - inspect advice not stopping;
  - late results being discarded.

  Verify `npm run test:unit` passes in full.

## 6. Evaluation and live verification

- [x] 6.1 Run `doppler run -- node scripts/evaluate-routing.mjs` (OpenRouter only) and record its accuracy in `notes.md`. Verify held-out ≥ 0.9; otherwise stop and report before installing.
- [x] 6.2 Run `doppler run -- uv run scripts/evaluate-visual-checks.py` and record per-type detection, false positives, location and progress ordering in `notes.md`. Verify the results file exists, and report the measured precision before Guide is recommended.
- [ ] 6.3 Build and install the release with backup, then ask the artist to restart Krita. Verify diagnostics show matching UI, companion and bridge build IDs and the panel shows "Luna decisions" without a key field.
- [ ] 6.4 Run live acceptance on a disposable document in Evaluate only:
  - image control;
  - one routed direction;
  - one deliberately striped pass flagged with its location in the panel;
  - an Ask turn with no changes;
  - diagnostics free of keys.

  Verify each check passes and record the evidence paths.
- [x] 6.5 Update the `krita-creative-agent/README.md` current-behavior section (Luna decisions, modes, data flow, key source, evaluation results) and mark the TypeSafe sections as history. Verify the README no longer instructs entering a TypeSafe key.

## 7. Automatic recovery from uncertain actions (added 2026-10-09 at the artist's request)

- [x] 7.1 Fix the luna() credential lookup to read Pi's `{auth:{apiKey}}` shape (the live run showed `not_connected`); verify with a studio test using Pi's real shape and a local check that the Pi key resolves
- [x] 7.2 In `creative_tools.py`, always drop `layer_id` after removing a failed contribution layer, skip pass recording for missing layers, and append (never overwrite) pass-record errors; verify the plugin compiles and with a Python unit test of the error-merging helper
- [x] 7.3 Add `recoverUncertain()` in `studio.mjs` (observe → reconcile at that revision → Luna before/after check → recovery result) and use it from `callNative` and `tools.mjs` in active Agent runs, falling back to the old pause when recovery fails; verify with studio tests: recovered run continues and returns a tool result, failed recovery pauses
- [x] 7.4 Count consecutive uncertain recoveries (reset on a successful mutation): strategy change at 3, pause at 5; verify with a studio test
- [x] 7.5 Run the full unit, UI smoke and packaging suites, rebuild and reinstall the release; verify the installed files match the source
- [x] 7.6 Resume acknowledges a leftover uncertain action on the verified active painting (observe → reconcile) instead of requiring a separate inspection; it keeps the inspection requirement if the document differs or Krita cannot confirm the canvas. Verified by a studio test.

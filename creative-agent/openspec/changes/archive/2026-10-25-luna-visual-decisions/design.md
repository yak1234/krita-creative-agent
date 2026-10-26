## Context

See proposal.md for motivation and specs/luna-visual-decisions/spec.md for required behavior.

Existing code these decisions attach to:

- **Routing:** `src/typesafe-routing.mjs`. Everything except `TypeSafeRouter` and the SDK import is provider-neutral:
  - `OPERATIONS`, `BRUSHES`, `routes`;
  - `safeText`, `routingState`, `contextIdentity`;
  - `answer`, `routingAdvice`.

  TypeSafe's choice-answer format equals OpenRouter's (`{type:'choice', choice, confidence, probabilities}`). The caller is `studio.mjs:185-217`, which uses the lazy router, the stale-identity discard and `diagnostics.record({type:'routing'})`.
- **Pass completion:** `studio.mjs:803` (`callNative`). After a mutating, non-replayed operation the result carries the native `passes` journal. Each entry has `before_path` / `after_path` (written by `creative_tools.py:248`, relative to the study directory). The result object is serialized to the painter by `resultContent` (`tools.mjs:17`), so extra fields reach the painter.
- **Reviews and stalls:**
  - Each review is stored as `goal.reviews[]` with `checks[{id,met,evidence}]`, `image` (canvas path), `content_id`, `revision`, `stage` and `pass_count` (`studio.mjs:986`).
  - `repeatedReviewFailures()` (`:57`) counts consecutive reviews with the same failed-check signature.
  - The loop calls `recoverExecution()` at count 3 and pauses at 5 (`:1011-1019`).
  - The criteria texts come from `reviewCanvas` (`:1105`), and `stage.region` (when set) bounds the stage.
- **Credentials:** Pi stores `openrouter` as `api_key` (`~/.pi/agent/auth.json`). `this.models.getAuth('openrouter')` returns `{apiKey}`. Reconnecting goes through `configureProvider` (`studio.mjs:144`).
- **Luna on OpenRouter** (measured 2026-10-09):
  - Request: `POST https://openrouter.ai/api/alpha/decisions`, with `state` an array of `{type:'text'}` / `{type:'image_url', image_url:{url:dataURL}}` parts. `input_image` shapes are silently ignored.
  - Multiple labelled images work (8 tested). One 2048 px image worked.
  - A refused question returns 502 for the whole request.
  - Latency is about 0.3–0.7 s. Cost is about $0.10 per million input tokens: about 150 tokens per question and about 1,100 per 1024 px image.
  - Yes/no questions can't tell partial improvement from none. Score questions can.

## Goals / Non-Goals

**Goals:**
- One client and one setting for all Luna decisions, so credentials, fallbacks, privacy and diagnostics behave identically.
- Use existing artifacts (pass before/after images, review images and checks) and capture nothing new from Krita.
- Keep Evaluate only free of side effects, so a live comparison can show value before Guide is used.

**Non-Goals:**
- Luna approving stages, skipping reviews, or hiding or rejecting passes.
- Luna choosing the next painting step (it was measured weak at that).
- Reference-vs-canvas difference checks and brush-swatch calibration. These are later changes on the same client.
- Migrating or deleting a saved TypeSafe Keychain key.

## Decisions

### D1. Modules
- `src/luna-decisions.mjs`: `LunaClient({apiKey, fetch, timeout=4000, model})`, with `decide({parts, questions, signal})` returning `{answers, usage, elapsed_ms}` or a `{fallback: reason}`.
  - It builds `state` from ordered text and image parts, converting Pi image content (`{data, mimeType}`) to data URLs.
  - It maps 502 "refused to answer question" to `refused`, other non-200 responses or malformed bodies to `service_or_response_error`, and aborts to `timeout` or `cancelled`.
  - It never logs response bodies, because they can echo upstream key fragments (seen on 2026-10-09).
- `src/routing.mjs`: the moved neutral routing code, plus `LunaRouter`, a thin wrapper that asks the existing two choice questions through `LunaClient`.
- `src/visual-checks.mjs`: `passCheck()` and `progressCheck()`. These are pure functions over images and texts that use `LunaClient`.
- Delete `typesafe-routing.mjs` and `typesafe-credentials.mjs`.

*Alternative:* one module for everything. Rejected, because routing's existing tests should keep a stable boundary.

*Alternative:* the OpenAI SDK. Rejected, because it targets OpenAI's `/v1/decisions` request shape, which differs from OpenRouter's.

### D2. Per-pass check: two-stage request
**Request 1** sends `["BEFORE (canvas before this pass):", before, "AFTER (canvas after this pass):", after]` with six yes/no (`noul`) questions. Each is phrased as introduced by the pass: "Does AFTER show <failure> that is not present in BEFORE?" This gives one model call that handles both "present" and "newly introduced". It replaces asking twice and diffing, which would double the cost and the error.

**Request 2** runs only when at least one answer is ≥ 0.7. It sends the AFTER image with one 3×3 `choice` location question per flagged type.

Clean passes therefore cost one request (about 2,300 input tokens, about $0.00025).

The failure texts reuse the wording validated in `evaluate-luna-defects.py`, plus a "hard graphic look" question from the moonlit-canal test. The threshold is 0.7, not 0.5, because these findings go to the painter, so precision matters more than recall. It can be adjusted with the evaluation in D7.

*Alternative:* call Luna for every native command. Rejected, because a pass is the unit the artist can review and reject.

### D3. Where the per-pass check runs
In `callNative`, after the pass counter update, for mutating, non-replayed results with a latest pass entry that has both paths:
- **Evaluate only:** run the check without awaiting it (fire and forget, bounded by the timeout). Record `diagnostics.record({type:'visual_check', pass_id, findings|fallback})` and emit a panel event. The painter's turn isn't delayed.
- **Guide agent:** await it (at most 4 s) and attach `result.visual_check = {findings:[{type, probability, location}], note:'Possible artifacts introduced by this pass; verify in the returned image before acting.'}` before returning. The painter therefore sees it with that pass's image.

Discard the result if the study, document or pass ID changed.

### D4. Progress check
After a review is pushed (`studio.mjs:986`), when `repeatedReviewFailures(...) >= 2`, the progress check gets:
- the previous and current review images (stage-region crops when `stage.region` exists and the stored review has crops; otherwise whole canvases);
- one `score` question per repeated failing check (capped at 8), using that check's criterion text, on the scale [no improvement, slight, clear, resolved] (0–3).

The mean score is stored on the review as `progress:{scores:{id:score}, mean}`.

In Guide agent mode, `repeatedReviewFailures` takes these scores into account:
- reviews with `progress.mean >= 2` (clear) break the consecutive count;
- the recovery at count 3 looks at the progress scores *within* the repeated run. Each score is measured from the preceding review, so three repeated reviews carry two scores and the first review has none. Recovery runs when both are `< 1`, or when either is missing (falling back to today's rule). Slight progress (1–2) defers it.

(Corrected during implementation: the first wording required scores on all three reviews, which can never be true, so it would always have fallen back.)

The five-review pause keeps its count, with the same break. The recovery reason includes the scores.

A score was chosen over a yes/no because the 2026-10-09 test showed yes/no answers 0 for a partial fix while the score separated none, slight and removed (0 / 0.6–0.9 / 2.1–2.7).

### D5. Routing with the canvas
`LunaRouter.evaluate(state, {signal, identity, image})` uses the existing question texts verbatim, with the image added when the canvas is attached and the captured content belongs to the routed `decisionObservation`. The image is loaded from the routed `decisionObservation.image_path` when the canvas is attached or the agent is painting. This also covers stage routing inside the painting loop, where the observation comes from native `observe` without loaded pixels. `routingState` stays text-only, so its no-base64 test still holds.

The timeout is 4 s, up from 2 s, to cover image requests.

### D6. Credentials and setting
- `resolveLunaKey()` tries `(await this.models.getAuth('openrouter'))?.apiKey`, then `process.env.OPENROUTER_API_KEY`. The key is pushed to `this.secrets` and the client is cached on the runtime. `configureProvider()` clears the cached client when `openrouter` changes.
- Remove the `typesafe_doppler` config key and its Doppler lookup.
- The setting keeps the stored key `routing` and its values, so saved conversations load unchanged.
- The panel label becomes "Luna decisions".
- Remove `configureTypeSafe()`, the `configure_typesafe` case in `main.mjs`, and the panel key field, button and `save_typesafe_connection`.
- New panel display: a pass-history row badge for findings (type and location) and the review's progress mean.

### D7. Evaluations
- **Routing:** `scripts/evaluate-routing.mjs`, replacing `evaluate-typesafe-routing.mjs`. It runs both text fixtures through `LunaRouter`. Bar: held-out ≥ 0.9.
- **Visual checks:** `scripts/evaluate-visual-checks.py`, extending `evaluate-luna-defects.py`, calls the same request shapes as `visual-checks.mjs`. It covers:
  - paired before/after with injected failures, for detection, false positives and location against the injection cell;
  - graded corrections, for progress-score ordering.

  It saves images and `results.json`. A shared JSON file of question texts (`src/visual-check-questions.json`) is read by both the Node module and the Python evaluation, so they can't drift.
- **Live acceptance:** rename the check to `real_luna_routing`, and add the orange/green image control and one per-pass check on a disposable document.

## Risks / Trade-offs

- [The synthetic results (12/12, 9/9) overstate real performance, because real failures are subtler] → Evaluate only is the first mode to use. Guide should only be recommended after the labelled evaluation and a live Evaluate run on a disposable copy show acceptable precision. The thresholds are constants and can be tuned.
- [Luna is weak on duplicated bands (3/12 named correctly; usually called a join)] → It is reported as a finding either way, with its location. The painter gets "possible artifact" wording and the image, not a verdict.
- [A false finding misdirects the painter in Guide mode] → Precision threshold 0.7; the note asks the painter to verify in the image; nothing is hidden or undone automatically.
- [Progress scoring with whole-canvas images dilutes a local change] → Use stage-region crops when available. Otherwise it falls back to today's rule if any score is missing. Location-cropped progress is a later improvement.
- [Added latency in Guide mode] → At most 4 s per pass, typically 0.3–1 s. Evaluate only doesn't wait.
- [More images leave the machine] → Disclosed in the panel. Default Off. Same provider path as the painter.
- [OpenRouter `/api/alpha` changes] → URL and model are constants in one module, and live acceptance catches drift.

## Migration Plan

1. Implement. Pass Node unit tests, the Qt UI smoke test and packaging tests.
2. Run `evaluate-routing.mjs` (stop if held-out accuracy is below 0.9) and `evaluate-visual-checks.py`. Record the results in the change notes.
3. Build a release and install it with backup, then ask the artist to restart Krita.
4. Live acceptance on a disposable document in Evaluate only: image control, routing, a deliberately bad pass flagged with its location, Ask read-only, and no keys in diagnostics.
5. Rollback: reinstall the previous release from the installer backup.

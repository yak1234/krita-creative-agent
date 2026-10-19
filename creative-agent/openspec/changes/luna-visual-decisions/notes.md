# Implementation notes

## 6.1 Routing evaluation — 2026-10-09

`doppler run -- node krita-creative-agent/scripts/evaluate-routing.mjs` (OpenRouter only, text-only state).
Report: `krita-creative-agent/output/routing-eval/`.

| Fixture | Correct | Cost |
|---|---|---|
| routing-heldout-v1 (bar 0.9) | 26/26 | $0.00145 |
| routing-cases | 26/27 | $0.00149 |

The only miss: "Make it better" expected `inspect`, got `mixed_unknown`, which falls back to no advice. Same held-out result as the Jev baseline (26/26, 23 Sep).

## 6.2 Visual-check evaluation — 2026-10-09

`doppler run -- uv run krita-creative-agent/scripts/evaluate-visual-checks.py`, using question file v1 and threshold 0.7. Results: `krita-creative-agent/output/visual-checks/20261009T062351Z/`. There were 108 pass checks and 36 progress checks; the pass checks cost $0.023.

| Failure (injected) | Detected | Located in an accepted cell |
|---|---|---|
| splice | 12/12 | 12/12 |
| duplicate | 7/12 | 7/7 |
| flat_block | 12/12 | 12/12 |
| stripes | 12/12 | 12/12 |
| ellipses | 12/12 | n/a |
| hard_graphic | 12/12 | n/a |

- **False flags: 0/36.** That covers 12 unchanged passes, 12 ordinary-brushwork passes, and 12 passes where stripes already existed in BEFORE.
- **Progress ordering:** 12/12 strictly unchanged < half < fixed. Mean scores were 0.00 / 1.11 / 2.95.
- **Caveat:** the injected failures are more obvious than real ones. Precision on live passes is still unmeasured, so use Evaluate only before Guide.

## 6.3 Release build and install — 2026-10-09

- Built `krita-creative-agent/output/luna-candidate-034`, build ID `ff04b944dc2d5d2254cccb40a6270bee0c2f8e4fc51b88af1d7448ab784ed93e` (staged import check passed, now including the Luna modules). Contains no `@typesafe-ai` files.
- Installed with `install-release.mjs` into the real Krita profile. The previous plugin was backed up to `~/Library/Application Support/krita/.creative-agent-backups/2026-10-09T06-28-54-471Z-44074`. The previous runtime release `1ca04445…` is kept for rollback. `artwork_modified: false`.
- Installed `__init__.py`, `command_queue.py`, `creative_docker.py` and `creative_tools.py` match source (SHA-256). The release includes the `fix-krita-mcp-timeouts-and-batch` bridge changes.
- **Pending:** a Krita restart by the artist, then a diagnostics check that the UI, companion and bridge build IDs match.

## Rollout decision — 2026-10-09

The artist chose to keep the saved setting `routing: "guide"` (`.creative-agent/execution-settings.json`), so Luna decisions start in **Guide agent** after the restart instead of the recommended Evaluate-only period. Live precision on real passes is not yet measured. Watch the panel's "Luna check" and "Luna progress" messages, and switch to Evaluate only if findings mislead the painter. The 6.4 acceptance still runs its own Evaluate-only scenario on a disposable document.

## 7. Automatic recovery — 2026-10-09

- **Live run `ce0f8db9…` (Twilight Mountain Lake Study).** It paused on `partial_change: "Pass record could not be saved: That layer is no longer in this painting."` for two Smart Patch contributions in projection mode. Root cause: when Smart Patch failed, cleanup removed the projection layer but kept `layer_id`, and the pass record then replaced the real Smart Patch error. Fixed in `creative_tools.py`. The real Smart Patch error will now be visible on its next occurrence.
- **Same run, all routing events `not_connected`.** `luna()` read `apiKey` instead of Pi's `{auth:{apiKey}}`. Fixed, and the test now uses Pi's real shape.
- **Uncertain actions now recover automatically,** with a strategy change at 3 consecutive and a runaway pause at 5. Resume acknowledges leftover uncertainty.
- **Installed release `750b3734eb34acb3717acf8f7fe6e972ae2571e61d01ebaa7a833f34eb6be20f`** (candidate 036; 128/128 unit tests, UI smoke test passed). Backup: `.creative-agent-backups/2026-10-09T06-55-30-272Z-49367`. Restart required.

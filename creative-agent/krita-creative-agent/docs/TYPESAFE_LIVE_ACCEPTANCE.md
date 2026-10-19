# TypeSafe live acceptance

## 23 September update

The matched loaded build `0043051c…` passed separate real full-agent Gradient (`live-acceptance-012-final-gradient`) and Smart Patch (`live-acceptance-010`) runs. The Gradient changed 20,800 permitted pixels and none outside its region; Smart Patch repaired 400 defect pixels and changed none outside its mask. Both checked saved KRA pixels. `live-switch-001` verified that switching away before a paint request changed neither document. `live-reject-001` verified a rejected repair restores the defect and can return to the previously accepted canvas. The matched routing-Off Smart Patch run (`live-acceptance-011-off`) used the same tools as Guide, so this task shows no measured tool-choice benefit from TypeSafe. Each individual acceptance runner still marks unrelated scenarios unrun; these results form a composite of separate live checks, not a single green run.

A later real painting surfaced an inspect-advice loop. Source now presents routing advice once per direction/stage and tells the Agent to inspect the supplied canvas and continue painting in the same turn. A Pi controller test reproduces an inspection-only reply followed by a paint call; all 107 Node tests pass. Build `2ab23bdc…` is installed but is not yet loaded in the active Krita painter, so this fix is **not live-verified**. Do not interrupt an in-progress painting merely to reload it.

The acceptance gate uses actual Jev requests, a real Pi painter, the running Krita bridge, and exported pixel comparisons. It never substitutes provider or bridge responses. Unit tests are a separately labelled development aid.

## Run

Use a new output directory on every attempt. Open the user's dedicated 600 × 600 test document. Supply its current bridge document ID and the installed companion directory; process-local document IDs change after reopening. The native adapters must have live acceptance receipts for the current adapter/Krita version. A mismatch or missing receipt blocks the painting run.

```sh
node scripts/live-acceptance.mjs \
  --output docs/typesafe-evidence/live-run-NEW \
  --doppler-project secrets --doppler-config dev \
  --companion '/absolute/path/to/installed/release/companion' \
  --document 'current-bridge-document-id' \
  --provider openrouter --model deepseek/deepseek-v4.1-flash \
  --python '/absolute/path/to/python-with-Pillow'
```

The runner fetches only `TYPESAFE_API_KEY` from Doppler if environment/Keychain lookup fails. It does not print the key or download other secrets. `--routing-only` explicitly leaves overall Krita acceptance blocked.

Exit codes: **0 passed**, **1 failed**, **2 blocked**. Reports include each test's actual result, model/build identity, and evidence. Retain failed and blocked runs. Do not combine their counts with unit-test totals.

## Evidence so far

- `typesafe-evidence/routing-live.json`: initial real Jev run, 26/27 expected labels. Vague “Make it better” fell back rather than guiding execution.
- `typesafe-evidence/live-acceptance-001/acceptance.json`: a separate frozen held-out set, 26/26 real API responses with matching labels; **overall blocked** because the loaded bridge differed from the candidate companion.
- `typesafe-evidence/gradient-live.json` and PNG: native linear-gradient fixture executed in Krita 5.3.3. Correct blue/gold direction and transparent samples outside the mask.
- `typesafe-evidence/patch-live.json` and PNG: native Smart Patch fixture, 400 changed pixels, zero outside the selection, original layer preserved.

The last two tests ran candidate adapters directly through Scripter. They do **not** establish the full Creative Agent route, save/replay behavior, radial gradients, all zoom levels, or document-switch safety.

## Remaining acceptance work

The implemented full-path runner exercises real Ask, a Jev-guided native gradient stage, pixel confinement, saved KRA receipt, Stop during a real request, and restoring without repainting. It currently reports document switching and full-agent Smart Patch as blocked scenarios; those interactive scenarios still need implementation/execution. Passing routing alone must never produce a green overall result.

A generated image or the critic saying “complete” is not the pixel oracle. The independent Pillow checker compares full-resolution before/after images and verifies gradient endpoint colors and unchanged pixels outside the allowed strip. Mock tests remain useful for transport-loss branches, but cannot satisfy any live acceptance requirement.

## Installed candidate — 23 September 2026

Build `4eb40288dea40dfab35e20ee68e05d65c943785770ce54c66a5959c28479c972` is installed and verified loaded after the user's restart. Adapter revision `native-tools-v2` scopes input to the active QMdiSubWindow, instead of looking for one canvas across all open tabs. Its new receipt is pending live execution. No further restart is currently needed.

## Findings from retained runs

- `live-acceptance-002`: the painter produced the gradient with 20,800 changed pixels and zero outside the allowed strip, but TypeSafe was given an earlier discussion message. Fixed stage routing to read the latest actual user direction. A separate receipt lookup bug in the test harness was also corrected.
- `live-acceptance-003`: 26/26 real Jev labels; painting stopped when the test document was closed during the run. This is retained as a failed run, not a completed document-switch test.
- `live-acceptance-004`: 26/26 real Jev labels. Correct Gradient advice reached the painter. With two tabs open the native adapter refused execution because its whole-window canvas lookup was ambiguous. No pixels changed. Ask, Stop during model activity, and resume without repainting passed. The active-subwindow fix is in the installed build above.
- `native-installed-1790133308/result.json`: installed v1 adapter passed linear and radial gradients, two zoom levels, exact mask confinement, Smart Patch's 400-pixel repair, state restoration, source preservation, and changed-layer rejection. These results do not substitute for v2 acceptance.

The full-agent runner now also accepts `--patch-source '<observed paint layer ID>'` to execute a real repair scenario on a visible prepared fixture. It uses an independent exact-pixel repair oracle; fixture setup remains separate from the painter's execution. Full release acceptance remains incomplete until remaining live scenarios are demonstrated.

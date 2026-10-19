# Safety model

An agent with brushes is only useful if it can't ruin your work. These are the guarantees, and where they are enforced.

| Guarantee | How | Where |
|---|---|---|
| Your original file is never overwritten | A study paints into a working copy (`painting.kra` in the study, or a file you chose). Saves refuse to recreate a moved or deleted working file. | `creative_tools.py` `_creative_validate_save_target` |
| Every change is reversible | Passes paint on new layers. Toolbox edits work on a copy of the source layer. Any pass can be faded, hidden or rejected from the pass history. | `creative_tools.py`, panel pass dialog |
| Nothing paints from a stale view | Each action carries the plan revision. A changed canvas, document or plan makes the bridge refuse the action. | `studio.mjs` `callNative`, `cmd_creative` checks |
| No operation runs twice | Operation ids are idempotent: a replay returns the recorded result, and a reused id with different instructions is rejected. | `cmd_creative` |
| Uncertain outcomes are handled | If an action's outcome is unknown or partial, the host observes and acknowledges that exact revision, then tells the painter. If observation fails, the run pauses for inspection. | `studio.mjs` uncertain recovery |
| The artist stays in control | **Stop** pauses immediately. Your own canvas edits during a run are kept, not painted over. Plan approval and changes to locked requirements need your explicit acceptance. | `studio.mjs` |
| Local only | The bridge listens on `127.0.0.1`. Keys are never written to traces, logs or diagnostics. | `__init__.py`, `langfuse-tracing.mjs` `maskSecrets` |

Live tests always use a disposable document.

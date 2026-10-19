---
name: krita-launch
description: Open Krita for the Creative Agent, or check the running one, before any live step (a test chat, an install check, an audit, a tidy). Use when Krita is not running (it crashed, or the artist closed it), when the bridge at 127.0.0.1:5678 does not answer, or to see which build and documents are loaded.
---

# Open or check Krita

Krita is the artist's app: they may be painting in it. Starting it is fine; everything else asks first.

## Steps

1. **Run the launcher** from `krita-creative-agent`:

   ```bash
   node scripts/krita-launch.ts --timeout 180
   ```

   It starts Krita only when it is not running (`open -a krita` on macOS), waits for the Creative Agent plugin's
   bridge, then prints JSON: `status` (`ready` or `no_bridge`), `started`, the loaded `build`, `krita_version`,
   `session_active`, `krita_actions` (vetted Krita actions) and the open `documents`. Exit 0 when ready.
2. **Tell the artist** what happened in one line: "Krita was not running; I started it (build 60f93572, no
   documents open)", or "Krita is running with new_moscow_finished.kra open".
3. **Compare the build** with the installed one (`creative_inspect_state` → `companion_build.build_id`). A different
   build means the install has not been loaded: reload the bridge only when Krita is idle (below).

## Rules

- **Never restart or quit a running Krita** without the artist's yes in this conversation: it may hold unsaved work.
- **Idle before anything live:** `session_active` must be false and no chat may be painting
  (`creative_recent_events`), checked in its own step right before an install, reload, audit, tidy or test chat.
- **Announce document changes:** say before anything opens or closes a document, list `documents` before and after,
  and report the difference.
- **Never open the artist's originals for tests:** tests use copies in `benchmark-runs/<stamp>-tool-choice/`
  (the `creative_test_*` MCP tools do this and clean up after themselves).
- **`no_bridge` after a start:** a large painting may still be loading; run the launcher again with a longer
  `--timeout`. If Krita runs and the bridge never answers, the plugin is not enabled or failed to load: tell the
  artist (Settings → Configure Krita → Python Plugin Manager) instead of retrying in a loop.
- **After a crash:** Krita keeps no open documents and drops any test copy it had open; delete leftover copies
  in `benchmark-runs/` and end any test chat (`creative_test_end`). If Krita crashed, say so and note what it was
  doing; macOS crash reports land in `~/Library/Logs/DiagnosticReports`.

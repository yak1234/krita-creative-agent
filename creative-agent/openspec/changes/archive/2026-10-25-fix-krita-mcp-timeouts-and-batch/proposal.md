## Why

A code review of the external Krita MCP path (`krita-mcp/server.py` → Krita plugin HTTP bridge on :5678) found reliability bugs that can make an agent paint the same marks twice or believe work failed when it succeeded. They are small to fix and should be fixed before the next painting session that uses the newly enabled `krita` MCP server.

## What Changes

- The plugin's queue timeout result carries a machine-readable `error_code: "timeout"`, so the existing cancel path actually removes a timed-out command that has not started. A command that times out is never executed later, and its result is not retained.
- `server.py` stops racing the plugin: every request tells the plugin its queue timeout and waits on HTTP slightly longer than that, so the client always receives the plugin's definite answer instead of abandoning a command that is still running. Per-tool timeouts are aligned with the plugin's long-running set (`open_file`, `get_canvas`, `save`, `save_native`, `new_canvas`).
- A timeout or lost response for a mutating command is reported as an **unknown outcome** ("check the canvas before retrying"), not a plain error that invites a blind retry.
- `krita_batch` sends supported painting commands to the plugin's native `batch` action in bounded chunks (one HTTP round trip per chunk instead of per command) and falls back to individual calls for actions the native batch does not support, preserving order.
- `krita_batch` reports every per-command failure, including `partial` results and nested-batch failures, and no longer truncates diagnostic readback.
- `server.py` sends `Authorization: Bearer <KRITA_MCP_TOKEN>` when that variable is set, so enabling the plugin's optional token no longer breaks every tool. `krita_health` reports the actual failure (unreachable, unauthorized, bad response) instead of a bare `except`.

Out of scope: whether raw pixel writes (`clear`, `paint_pixels`, flood fill, filled shapes) create undo steps. That needs live verification in Krita before any change is proposed.

## Capabilities

### New Capabilities
- `krita-mcp-bridge`: Request/response contract between the external MCP server and the Krita plugin bridge — timeouts, cancellation, unknown outcomes, batching, failure reporting and authentication.

### Modified Capabilities
<!-- None: no existing specs under openspec/specs/. -->

## Impact

- `krita-mcp/server.py`: `send_command`, `krita_batch`, `krita_health`, timeout values of `krita_open_file`, `krita_get_canvas`, `krita_save`, `krita_flood_fill`, `krita_paint_pixels`.
- `krita-mcp/krita-plugin/kritamcp/__init__.py`: `CommandQueue.get_result` / `cancel` and late results, `PaintRequestHandler.do_POST`, `cmd_batch` (per-item results).
- Installed plugin copy at `~/Library/Application Support/krita/pykrita/kritamcp/` must be updated and Krita restarted; this makes the installed `__init__.py` differ from the Creative Agent `build-info.json` identity until the next release build.
- Compatibility: the Creative Agent companion (`krita-creative-agent/src/bridge.mjs`) already maps `error_code: "timeout"` to `outcome_unknown` and matches the "Timeout waiting for command" text; both are preserved. Other HTTP clients (`artist_server.py`, `krita_artist.py`) see only additive response fields.

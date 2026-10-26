## Context

See proposal.md for motivation and specs/krita-mcp-bridge/spec.md for required behavior.

Current state that shapes the approach:

- The plugin runs a single-threaded `HTTPServer` on a `QThread`. `do_POST` pushes onto `CommandQueue`; a 50 ms `QTimer` on Krita's main thread drains up to 16 commands per tick. One request is in flight at a time.
- `do_POST` already accepts a per-request `timeout` field in the body (`__init__.py:183`) and defaults to 120 s, or 300 s for `LONG_RUNNING`.
- `get_result` returns `{"error": "Timeout waiting for command execution after Ns"}` with no `error_code`, so the `cancel()` branch at `:194` is dead code. `set_result` for an abandoned id stores a result nobody pops.
- `server.py` never sends `timeout`, and uses 30 s HTTP timeouts by default, 30 s per `krita_batch` item, and 120 s for `get_canvas`/`save`.
- The Creative Agent companion already uses the correct pattern: body `timeout:120`, HTTP abort at 140 s, and it maps `error_code: "timeout"` on mutations to `outcome_unknown` (`krita-creative-agent/src/bridge.mjs:20-35`).
- Plugin `cmd_batch` supports 23 actions and returns only `{status, count, errors, failures[:20]}`, with no per-item readback. Read-only and long-running actions are not in its handler table (`undo`, `redo`, `get_color_at`, `list_brushes`, `canvas_info`, `list_layers`, `flood_fill`, `new_canvas`, `open_file`, `get_canvas`, `save`, `save_native`, nested `batch`).
- `__init__.py` imports `krita` at module load, so its classes cannot be unit-tested outside Krita. The existing tests load pure helper modules (`stroke_data.py`, `brush_controls.py`) by file path.

## Goals / Non-Goals

**Goals:**
- Make queue cancellation and late-result disposal testable without Krita.
- Keep every response change additive for existing HTTP clients.

**Non-Goals:**
- Making the HTTP server multi-threaded (health checks still wait behind a long save).
- Adding new actions to the native batch, or changing the plugin's command semantics.
- Undo behavior of raw pixel writes.
- Changes to `artist_server.py`, `krita_artist.py` or the Creative Agent companion.

## Decisions

### D1. Client sends its queue timeout and waits a fixed margin longer
`send_command(action, params, timeout)` puts `timeout` in the request body and uses `timeout + 20 s` as the httpx read timeout (the companion uses +20 s too). Defaults: 120 s; 300 s for `open_file`, `new_canvas`, `get_canvas`, `save`, `save_native`, `flood_fill`. The plugin then always answers first with a definite result or a `timeout` code.

*Alternative:* raise client timeouts to a large constant. Rejected. A constant can still drift out of sync with the plugin, and the client could still abandon a running command without knowing it.

### D2. Abandoned-id set in the queue
Under the lock, `get_result` timeout does three things. If the id is still queued, it removes it. If not, the command is in flight, so it adds the id to `abandoned`. Then it returns `{"error": "Timeout waiting for command execution after Ns", "error_code": "timeout"}`. `set_result` drops results for abandoned ids and removes them from the set. `do_POST` no longer calls `cancel` separately, which also removes the dead branch. The existing message text is kept because `bridge.mjs` matches on it.

An in-flight command cannot be interrupted; it runs to completion on the main thread. The spec allows this, and the client reports the outcome as unknown.

### D3. Move `CommandQueue` into a pure module
Move it to `krita-plugin/kritamcp/command_queue.py`, with no `krita`/PyQt imports, and import it from `__init__.py`. Tests load it by path like `stroke_data.py`. This adds no behavior change beyond D2.

### D4. Per-item results from native batch, additive
`cmd_batch` adds `results: [{"index", "action", "ok", "result"}]` alongside the existing fields. `result` is the handler's dict minus the bulky `brushes` key. `failures` stays as is for older callers. Per-item failure means `error` is present or `status` is neither `ok` nor absent.

### D5. `krita_batch` groups runs of natively supported actions
`server.py` holds `NATIVE_BATCH_ACTIONS`, a copy of the plugin's `cmd_batch` handler keys. Contiguous runs of supported actions are sent as `batch` requests of at most 64 commands with the default 120 s timeout. Every other command is sent individually with its per-action timeout. Lines are emitted in input order. If a chunk itself times out or its response is lost, every command in it is reported as an unknown outcome.

*Alternative:* query `/info` for supported batch actions. Rejected for now: `/info` lists top-level commands, not batch handlers, and adding that would be scope creep. A unit test asserts that the copied set matches the plugin source's handler keys, which catches drift.

*Alternative:* send the whole input as one native batch. Rejected because a long batch would exceed any fixed timeout. 64 matches the existing 16-per-tick drain order of magnitude and stays far below the 8 MB body limit.

### D6. Result classification in `server.py`
`send_command` returns a dict; a small helper classifies outcomes:
- `httpx.ConnectError` means not reachable.
- HTTP 401 means unauthorized.
- `httpx.TimeoutException`, `RemoteProtocolError` or `ReadError` after sending, or `error_code == "timeout"`, means unknown outcome for mutating actions and an error for read-only ones.
- Non-JSON bodies are errors.

Read-only actions: `health`, `get_color_at`, `list_brushes`, `canvas_info`, `list_layers`, `brush_settings`, `get_canvas`, `compare_region`, `test_pixel`. Everything else counts as mutating. That is the conservative default.

### D7. Line format for `krita_batch`
Each line is `i: action ok <brief>`, `i: action FAILED <error/failures>`, or `i: action UNKNOWN-OUTCOME <reason>`. Successful paint commands stay brief (first 100 chars). The existing diagnostic actions plus any failed or partial result are printed in full. The output ends with `N commands, F failed, U unknown`.

### D8. Token header
`KRITA_MCP_TOKEN`, read once in `server.py`, adds `Authorization: Bearer …` to every request including `/health`. `krita_health` uses the same classification instead of a bare `except`.

## Risks / Trade-offs

- [Native batch copy drifts from the plugin] → Drift test in D5. An unsupported action inside a chunk still produces a per-item `Unsupported batch action` failure rather than silent loss.
- [Batched commands change timing: one projection refresh per chunk instead of per command] → Handlers already refresh themselves, and `cmd_batch` adds a final refresh. Run the live check in tasks to confirm the canvas output matches the single-command path.
- [Installing the plugin makes `__init__.py` differ from `build-info.json` identity] → Record it in the task notes. Do not claim build-ID parity until the next Creative Agent release build.
- [In-flight timed-out command still paints] → This cannot be prevented without main-thread cooperation. Mitigated by reporting an unknown outcome.
- [Krita restart required] → The queue object is module-global, so `reload_bridge.py` cannot safely swap it. Restart Krita with no unsaved work.

## Migration Plan

1. Back up the installed `kritamcp/__init__.py` to `krita-mcp/backups/pre-timeout-fix/`.
2. Implement and run unit tests. Copy `__init__.py` and the new `command_queue.py` to the installed plugin directory.
3. Restart Krita, then restart or reconnect the `krita` MCP server (`/mcp`).
4. Rollback: restore the backup file, delete the installed `command_queue.py`, restart Krita, and revert `server.py`.

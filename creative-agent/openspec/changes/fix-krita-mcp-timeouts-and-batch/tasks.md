## 1. Plugin queue: cancellation and late results

- [x] 1.1 Back up the installed `~/Library/Application Support/krita/pykrita/kritamcp/__init__.py` to `krita-mcp/backups/pre-timeout-fix/` and verify the copy's SHA-256 matches the installed file
- [x] 1.2 Move `CommandQueue` into a new pure module `krita-plugin/kritamcp/command_queue.py` (no `krita`/PyQt imports) and import it from `__init__.py`; verify `python -c` can load the module by path without Krita
- [x] 1.3 Implement D2: timeout removes queued ids or marks in-flight ids abandoned, returns `error_code: "timeout"` with the existing "Timeout waiting for command" text, and `set_result` drops abandoned results; remove the dead `cancel` branch in `do_POST`
- [x] 1.4 Add `tests/test_command_queue.py` covering: queued command timing out is never popped afterward; in-flight timeout result is discarded and not retained; normal result returns; timeout payload has `error_code` and message text. Verify with `.venv/bin/python -m unittest discover -s tests -v`

## 2. Plugin native batch readback

- [x] 2.1 Extend `cmd_batch` with additive per-item `results` (`index`, `action`, `ok`, `result` without `brushes`), marking `partial`/non-ok statuses as failures, keeping existing fields; verify by a unit test that loads `__init__.py` source and checks the handler table, plus the live check in 5.3

## 3. MCP server request layer

- [x] 3.1 Rewrite `send_command` per D1/D6/D8: body `timeout`, HTTP read timeout = queue timeout + 20 s, per-action long timeouts (`open_file`, `new_canvas`, `get_canvas`, `save`, `save_native`, `flood_fill` → 300 s), bearer token from `KRITA_MCP_TOKEN`, and outcome classification (unreachable / unauthorized / unknown outcome for mutating / error). Verify with unit tests using a patched transport for each classification
- [x] 3.2 Update `krita_open_file`, `krita_get_canvas`, `krita_save`, `krita_flood_fill`, `krita_paint_pixels` to use the shared timeout table and report unknown outcomes; verify unit tests assert the timeout each sends
- [x] 3.3 Replace `krita_health`'s bare `except` with the shared classification and token header; verify unit tests for unreachable, 401 and non-JSON responses

## 4. MCP server batch

- [x] 4.1 Add `NATIVE_BATCH_ACTIONS` and a drift test asserting it equals the handler keys parsed from `cmd_batch` in `__init__.py`; verify the test fails if a key is removed from either side
- [x] 4.2 Rewrite `krita_batch` per D5/D7: group contiguous native-supported commands into ≤64-command `batch` requests, send others individually, emit one line per input command in order plus the summary line; verify unit tests for 150 paint commands → 3 requests, mixed ordering, partial/nested failure reporting, unknown action continuing, and chunk timeout → UNKNOWN-OUTCOME for every command in the chunk
- [x] 4.3 Update the `krita_batch` docstring and `krita-mcp/README.md` (timeouts section, token, batch behavior, native-brush note); verify the README no longer claims 30 s defaults or pixel-only strokes

## 5. Install and live verification

- [x] 5.1 Run the full suite `.venv/bin/python -m unittest discover -s tests -v` and verify all tests pass, including the 11 existing ones
- [ ] 5.2 Copy `__init__.py` and `command_queue.py` into the installed plugin directory, verify hashes match source, ask the user to restart Krita, then reconnect the `krita` MCP server and verify `krita_health` reports bridge 2.3.x
- [ ] 5.3 On a fresh disposable canvas (never an existing artwork), run a `krita_batch` of ~150 set_color/stroke commands plus one `get_color_at`, and verify 3 batch requests, correct line count, and expected sampled colour; export with `krita_get_canvas` and inspect the image
- [ ] 5.4 Verify the timeout path live on the disposable canvas: send a command with a 1 s body timeout behind a slow command, and confirm the tool reports a timeout/unknown outcome and the queued command never paints (pixel sample unchanged)
- [x] 5.5 Record in the change notes that the installed `__init__.py` no longer matches the Creative Agent `build-info.json` identity, and that the companion's timeout handling still works (`error_code: "timeout"` → `outcome_unknown`)

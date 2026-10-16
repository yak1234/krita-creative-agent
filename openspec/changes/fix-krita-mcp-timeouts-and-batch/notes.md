# Implementation notes

## Installed plugin identity (task 5.5)

- Installed 2026-10-09 to `~/Library/Application Support/krita/pykrita/kritamcp/`:
  - `__init__.py` SHA-256 `89bb3bb6de59f509cff9fb74f337aac2f8eca84de13782dc648136087df8b9a4`
  - `command_queue.py` (new) SHA-256 `61c6363b016c298f53ebdeda4fab24c0db9c3942da22f6d7b877363b782fded2`
- Previous installed `__init__.py` (SHA-256 `c2b0f8a0…d70e`) is backed up in `krita-mcp/backups/pre-timeout-fix/`.
- The installed `__init__.py` no longer matches the Creative Agent `build-info.json` build identity. Do not claim build-ID parity until the next Creative Agent release build includes these files.

## Creative Agent companion compatibility

Verified by reading the source, not by a live companion run. `krita-creative-agent/src/bridge.mjs:33-35` takes `error_code` when present and maps `timeout` on mutating requests to `outcome_unknown`; otherwise it falls back to matching the text "Timeout waiting for command". The plugin now sends both, so behavior is unchanged or more precise. Per-item `results` in the native `batch` reply, and the timeout reply's `started` field, are additive.

## Rollback

Restore `backups/pre-timeout-fix/__init__.py` into the installed directory, delete the installed `command_queue.py`, restart Krita, and revert `server.py`.

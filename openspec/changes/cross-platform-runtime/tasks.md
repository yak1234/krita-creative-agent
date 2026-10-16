## 1. Spike (done)

- [x] 1.1 Pi SDK test, the full suite, the Pyodide sandbox, a secret-read probe and single-binary builds under Node, Deno and Bun. Results are in proposal.md.
- [x] 1.2 The sandbox runner refuses to run when its lock is off (`pyodide-runner.mjs`, plus a test). Verified: locked Node runs; unlocked Node and Bun refuse.

## 2. Runtime manager

- [ ] 2.1 `node_runtime.py`: platform keys for win-x64/arm64 and linux-x64/arm64; zip and tar.xz unpacking; a per-OS root (`%LOCALAPPDATA%`, `$XDG_DATA_HOME`); pinned hashes for each archive; tests for each platform key.
- [ ] 2.2 Panel start-up uses the runtime's `node`/`node.exe` path on every OS.

## 3. Releases

- [ ] 3.1 `build-release.py --platform darwin|win32|linux` (validate each on its own OS, or in CI); `install.py` per OS.
- [ ] 3.2 Windows: path quoting and spawning in `python-sandbox.mjs` and the companion launcher.

## 4. Proof

- [ ] 4.1 A clean-machine install and one painted chat on Windows, Linux and macOS; record `clean_verified` per platform and update the README and the AGENTS.md portability gap.

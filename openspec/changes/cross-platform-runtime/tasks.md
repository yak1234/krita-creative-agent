## 1. Spike (done)

- [x] 1.1 Pi SDK test, the full suite, the Pyodide sandbox, a secret-read probe and single-binary builds under Node, Deno and Bun. Results are in proposal.md.
- [x] 1.2 The sandbox runner refuses to run when its lock is off (`pyodide-runner.mjs`, plus a test). Verified: locked Node runs; unlocked Node and Bun refuse.

- [x] 1.3 Public repo with CI on macOS, Windows and Linux (https://github.com/yak1234/krita-creative-agent). Fixed what it found:
  - the decision client's unref'd `AbortSignal.timeout()`, which cancelled requests on Node 22;
  - the records database left open, so Windows could not delete it (`dispose()`, and close-before-delete in tests);
  - stored relative paths written with `\` on Windows (now always `/`);
  - a hard-coded `/tmp` diagnostics socket (a named pipe on Windows);
  - POSIX-mode checks and a native-path `import()` in tests;
  - CRLF checkouts (`.gitattributes`).

  Result: macOS 256/256; Windows and Linux 249/256, where the remaining 7 are the macOS installer tests (sections 2–3).

## 2. Runtime manager

- [x] 2.1 `node_runtime.py`: nodejs.org keys for darwin, linux and win (x64 and arm64); .tar.gz, .tar.xz and .zip (zip paths that leave the folder are refused); per-OS roots (`~/Library/Application Support`, `$XDG_DATA_HOME` or `~/.local/share`, `%LOCALAPPDATA%`); `spec_from_shasums` pins all six archives; System32 `curl.exe` on Windows for the system trust store. Both installers (`install-release.mjs`, `install.py`) use the same keys, node file and per-OS folders, and accept a pinned release with platform `any`. Tests cover each key, each archive format and each OS's folders; the installer tests now run on the OS they run on.
- [x] 2.2 Panel start-up takes node from the runtime manager (`node_runtime.resolve`), so `node.exe` on Windows, rather than trusting the installer's path.

## 3. Releases

- [ ] 3.1 `build-release.py --platform darwin|win32|linux` (validate each on its own OS, or in CI); `install.py` per OS.
- [ ] 3.2 Windows: path quoting and spawning in `python-sandbox.mjs` and the companion launcher.

## 4. Proof

- [ ] 4.1 A clean-machine install and one painted chat on Windows, Linux and macOS; record `clean_verified` per platform and update the README and the AGENTS.md portability gap.

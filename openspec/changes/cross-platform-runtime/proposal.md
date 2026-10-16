## Why

The plugin is distributed, but the agent only starts on macOS:
- `kritamcp/node_runtime.py` refuses any other OS ("The managed Node runtime supports macOS…") and keeps runtimes under `~/Library`;
- `scripts/build-release.py` builds Mac releases only.

On Windows and Linux the plugin loads and the companion never starts. The agent can't move into Krita's own Python, because Pi is a Node/TypeScript SDK and Krita's Python 3.13 ships only PyQt5. So the question was which JavaScript runtime to ship, and how.

## Spike (2026-10-16, this Mac; Bun 1.4.3, Deno 2.9.7, Node 24 locally, Node 22.23.2 in releases)

| Check | Node | Deno | Bun |
|---|---|---|---|
| Pi SDK tool loop (`tests/sdk.test.mjs`) | pass | pass (`--no-check`) | pass |
| Full unit suite (255) | 255 | 252: three `node:sqlite` backup/copy tests | 254: the managed-Node installer test |
| Pyodide numpy + Pillow under the runtime's own lock | pass (`--permission`) | pass (`--allow-read/--allow-write`, plus a network allow-list) | n/a |
| Reading `~/.pi/agent/auth.json` with the lock on | blocked `ERR_ACCESS_DENIED` | blocked `NotCapable` | **read: Bun accepts `--permission` and ignores it** |
| Whole companion as one executable | today's bundle starts in 0.4 s | `deno compile` starts in 2.0 s (212 MB untrimmed); cross-compiles a Windows `.exe` (223 MB) and Linux (246 MB) from this Mac | needs code changes to embed data files |

Conclusions:
1. **Bun is out** for the sandbox: its permission lock silently does nothing. The runner now checks the lock and refuses to run unlocked.
2. **The macOS-only gap is our runtime manager, not Node.** Node publishes official Windows and Linux builds, and the same hash-verified download works for them.
3. **Deno is a viable later step:** it adds a network allow-list Node lacks, and single-file cross-compiled releases. The price is the `node:sqlite` gaps and Pi being verified only through the SDK test and start-up so far.

## What Changes

- **Node stays the runtime.** `node_runtime.py` supports Windows x64 and arm64, Linux x64 and arm64, and macOS. It downloads the pinned official archive (zip on Windows, tar.xz elsewhere), checks its hash, and resolves the runtime folder per OS: macOS Application Support, Windows `%LOCALAPPDATA%`, Linux `$XDG_DATA_HOME`.
- **Releases are built per platform** (`build-release.py --platform`). Pyodide and its wheels are platform-independent and ship unchanged. Windows paths and process spawning are handled.
- **The sandbox runner refuses to run when its lock is off** (done in this change's spike).
- **A clean-machine install on each OS** before a platform counts as supported. The manifest records it per platform (`clean_verified`).
- **Deno stays a documented option:** reconsider it if a network allow-list for scripts becomes a requirement.

## Capabilities

### New Capabilities
- `cross-platform-runtime`: the companion starts on macOS, Windows and Linux from a pinned, verified runtime, with the Python sandbox locked on each.

## Impact

- **Plugin:** `node_runtime.py`, the panel's start-up path.
- **Companion:** `scripts/build-release.py`, `scripts/install.py`, spawning in `python-sandbox.mjs` (Windows).
- **Docs:** the AGENTS.md portability gap closes when every platform passes its clean-machine check.
- **Risk:** Windows path and spawn differences, which the clean-machine check catches.

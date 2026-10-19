# AGENTS.md

<!-- Add your project instructions above or below the Repowise section. Repowise only updates the managed section between markers. -->

## Build for the general case

The Creative Agent is a distributed plugin. Every feature is for every artist, every painting and every
platform, not for the painting in front of us or the one session we are debugging. A fix that makes
New Moscow or the Christmas test pass but would fail on the next painting is not a fix.

The principles, by name:

- **Design for the general case (generalisation).** Solve the class of problem, not the instance.
  "Paint a sky behind a finished subject" is the case; "the sky behind this tree" is one example of it.
- **Separation of mechanism and policy.** Tools are mechanism: small, general and composable, with no
  knowledge of any particular painting (`make_asset`, `paint_from_reference`, `set_layer`). Skills and
  prompts are policy: the workflows that combine them (`paint-sky`, `place-subject`). When a workflow
  needs a capability, add it to the tool (for example a `below_layer_id`), never a special case inside
  the workflow.
- **Open–closed principle.** Extend by adding things (a new skill, a new backend, a new setting) without
  editing the ones that work. Backends sit behind one interface (Codex and OpenRouter behind
  `make_asset`); choices are settings, not hard-coded vendors or models.
- **Don't overfit to the test or the demo.** Never tune thresholds, prompts or coordinates to one image,
  and never hard-code a painting's sizes, colours or layer names. A finding from one run is a hypothesis.
  Before calling a feature general, check it on at least three different cases: an empty canvas, a
  painting in progress, and an existing artwork.
- **Rule of three, balanced by YAGNI.** Generalise what you can already see repeating (the third time a
  workflow appears, it becomes a skill or a tool option), but do not build speculative machinery for
  needs nobody has shown. General is not the same as bigger.
- **Portable by default.** Anything that ships must work on every platform Krita runs on (macOS, Windows,
  Linux) without extra installs. That is why scripts run in Pyodide rather than in a native sandbox or a VM.

Ask before shipping: would this work unchanged for a different artist, a different painting and a
different model? If not, find the general mechanism first.

## Portability (it must run on someone else's machine)

The failure to avoid is "works on my machine". The plugin is open-source and distributed: it has to run
on another person's computer, OS and Krita, with a clean resources folder.

- **No machine-specific assumptions.** Never hard-code a user's home folder, an install path or a
  Krita location. Ask Krita for documents and resources; resolve data and cache folders per OS
  (`krita-creative-agent/src/storage-paths.mjs` covers macOS, Windows and Linux); use `pathlib` and
  `node:path`.
- **Ship everything you depend on, pinned and verified.** Users won't have our pip packages, Node or
  tools. The agent is a deliberate exception to "stay inside Krita's Python": a Node companion with a
  pinned, hash-checked Node runtime, and Python scripts in bundled Pyodide with bundled wheels. Nothing
  may come from the user's own pip, Node or PATH, and nothing may download at run time except a pinned,
  verified runtime.
- **Match Krita's plugin contract.** `kritamcp.desktop` has `X-KDE-Library` equal to the `kritamcp/`
  module folder (with `__init__.py`) and `X-Python-2-Compatible=false`. Any shortcuts go in an `.action`
  file under `actions/`, with unique ids.
- **Fail safely and start small.** Check that a document exists before acting on it. Canvas changes go
  through the journal, never blind repeats. Keep plugin start-up code short and explicit: Krita only
  shows a load error on hover in the Python Plugin Manager.
- **Separate registration from logic.** Docker, extension and signal wiring stay apart from operations,
  so the logic is testable with the mock `krita` module (`tests/test_native.py`).
- **Package it the way users install it,** and document the Krita versions it was tested on, how to
  enable it, and that a restart is needed.
- **Strangers can use the repo.** A licence, a short README and version notes. Never commit `kritarc`,
  caches, keys, `.env` or absolute-path configs.
- **Test on the runtime you ship, not the one you have.** Releases pin Node 22; a local Node 24 hid a
  timer bug (`AbortSignal.timeout` is unref'd, so Node 22 exited with a request pending). Run the suite
  with the pinned runtime; CI runs Node 22 on macOS, Windows and Linux.
- **Prove it on a clean machine.** Install only the release, on another account or OS, with a clean
  Krita resources folder. A build is not "portable" until that passes (`clean_mac_verified` in the build
  manifest records it).

**Current gap:** the managed Node runtime (`kritamcp/node_runtime.py`) and the release build
(`scripts/build-release.py`) are macOS-only, so the companion cannot start on Windows or Linux yet.
New code must not deepen this; closing it is open work.

## Don't tie things to version numbers

An agent does not know which versions are current: its knowledge stops at a training date, and the
"latest" it remembers is usually old. Tying code or text to a version from memory is a hack that goes
stale and misleads the next reader.

- **Don't write version numbers unless the user asks.** No "as of v0.84", "since TypeScript 5.8",
  "Node 22 workaround" or "the latest release is X" in code, comments, docs, prompts or advice.
  Describe the behaviour instead ("Pi's agent no longer reads `shouldStopAfterTurn`").
- **Never pick a version from memory.** When a version does matter, read it from the source of truth at
  the time: `package.json` and the lockfile, the installed package's `.d.ts`, or `npm view`.
- **Pins stay.** The pinned versions in `package.json`, lockfiles and the release build are set by
  tooling and verified, and they are what keeps the plugin portable. Change them deliberately, as their
  own change, never as a side effect.

## Code structure conventions

These follow from the principles above; Shortcut-Composer (a well-structured Krita plugin) applies the
same ones. Some are current practice and some are the direction for new code. Existing code moves toward
them as it is touched, not in big-bang rewrites.

- **Declare once (single source of truth).** A setting, option or policy is declared in one place, and
  validation, defaults, persistence and UI come from that declaration. Execution settings live in
  `krita-creative-agent/src/settings-schema.mjs`; the panel builds its controls from it. A new setting is
  one schema entry. Never hand-write the same list in the companion and the panel.
- **Policies are named choices.** A behaviour switch is an enum whose values have human labels (Luna Off /
  Evaluate / Guide, the image-asset backend, a transfer anchor), so it can be validated, shown in the UI
  and recorded. Avoid bare booleans and magic strings scattered through the code.
- **One interface per kind of part (direction).** Parts of the same kind share one interface, so they are
  interchangeable: image backends behind `make_asset`; Krita operations as small units of validate,
  apply, describe and undo, instead of growing one dispatcher (`cmd_creative` is the counter-example).
- **Cross-cutting steps are hooks, not wrappers (direction).** Journalling, checkpoints, visual checks,
  pacing and tracing run as an explicit, ordered list of hooks around an operation, each testable alone.
  Don't add another layer that wraps `execute`.
- **Wrap the host API.** Talk to Krita (and Pi, and the model providers) through a thin typed layer, so
  version differences and workarounds live in one place, for example the Pyodide `process.binding` shim.
- **Reusable modules stand alone.** A general module (the Python sandbox, the skill loader, the asset
  pipeline) has a clear interface and a header comment or README saying what it does, and does not reach
  into the studio's internals.
- **The artist owns their configuration.** Don't override an artist's choices or bind defaults over their
  setup. Make behaviour a setting, and keep the default safe.
- **New companion modules are TypeScript.** A new standalone module in `krita-creative-agent` (a Pi extension,
  a scorer, a helper with its own tests) is a `.ts` file checked strictly (`tsconfig.extensions.json`, part of
  `npm run typecheck`) against Pi's own types: Node runs it directly in a checkout and esbuild compiles it into
  the release bundle. Use erasable syntax only (`import type`, annotations; no enums or parameter
  properties), import it with its `.ts` extension, and register Pi extensions inline (`extensionFactories`),
  never by path: inside the bundle Pi's path loader cannot resolve its own modules. Existing `.mjs` files move
  to TypeScript through the typed-companion change, not as a side effect of other work.

<!-- REPOWISE_AGENTS:START — Do not edit below this line. Auto-generated by Repowise. -->
## Codebase Intelligence for krita (Repowise)

Indexed by [Repowise](https://repowise.dev). Last indexed: 2026-10-16 (commit 9843464). Confidence: 100%.
### How to work in this repo

- **Trust the index.** `verified: true` and `_meta.complete` mean the bytes were checked against the live tree, so never re-read them. Re-read only what `bounds: "approximate"` or `_meta.stale_warning` names. `confidence` rates the prose, not the evidence: on `low` read the `fallback_targets` or `best_guesses` the reply names, and run `repowise update` and ask again if `_meta.hint` says the index is behind HEAD. `index_behind: true` alone is informational.
- **A zero carries its basis.** An empty `callers`/`callees`/`used_by` comes with a `*_basis` saying how much of that language's calls the graph resolved, so read it before concluding nothing calls a symbol. `_meta.scope_hint` names the areas the answer did not touch.
- **Pre-edit, not instead-of-edit.** These tools decide *which* files to read and edit. Reading a file before you edit it is correct and expected.
- **Noisy commands** (tests, builds, `git log`/`diff`, searches, listings): prefer `repowise distill <cmd>`, the same command with its exit code preserved and errors-first output. A `[repowise#<ref>: N lines omitted]` marker is recoverable via `repowise expand <ref>` (add `-q <regex>` to filter); never re-run the command to see omitted output.
- **Recording a decision** you had to reason out: `repowise decision add --title T --decision D` records it without prompting and prints the id (`--format json` to parse it back). It lands `proposed`, for a person to confirm.

### Tools

| Tool | When and why |
|------|--------------|
| `get_answer(question)` | First call for any how/where/why question. Cite `confidence: "high"` or `grounding: "extracted"` directly; `degraded` means judge by `retrieval_quality`. `symbol_bodies` has live bodies. |
| `get_context(targets=[...])` | Triage card for files/modules/symbols: docs, signatures, hotspot, fix history. No source bytes — `include=["skeleton"]` for the whole file verified, `["callers"|"decisions"]` for depth. Batch targets. |
| `get_symbol(id, depth?)` | **Follow-up, not an entry point** — one verified body for an id a prior response named (`path.py::Name`, `path.py:140-180`, `repowise#<hex>`). Never walk a file symbol by symbol; Read it. |
| `search_codebase(query)` | Hybrid search, auto-routed by query shape; force with `mode=symbol|path|concept|hybrid`. A hit whose `sources` are `[fts]` only has no semantic agreement, so verify it. |
| `get_why(query, targets?)` | Why the code is shaped this way: decision records, git archaeology, rationale comments. Call before a refactor or a pattern divergence. |
| `get_risk(targets, changed_files?, include?)` | File history and structural reach. PR mode leads with `directive`; its 0-10 structural heuristic is uncalibrated, not a probability. Read typed test recommendations and coverage state first. |
| `get_change_risk(revspec?, extensions?, exclude_patterns?)` | Deterministic live-diff review signal for a commit or range. Lead with benchmarked percentile/classification; the 0-10 diff-shape score is supporting, not a probability. `get_risk` scores paths. |
| `get_health(targets?, include?)` | Defect / maintainability / performance scores and findings. Self-check the files you touched before finishing. |
| `get_dead_code(tier?, min_confidence?, safe_only?)` | Confidence-tiered unreachable files / unused exports / zombie packages. For cleanup sweeps, not targeted fixes. |
| `get_overview()` | Architecture map. Call once, first, in an unfamiliar repo; skip it after that. |

### Architecture
Krita Creative Agent is a companion agent for the Krita painting application: it consumes an artist's intent together with live diagnostics read back from the running canvas, routes them through a decision service and a painting runtime, and drives Krita's own tools — over an MCP server and an in-editor plugin — to produce edits on the canvas. The tree is a development checkout of two sibling packages that must stay side by side: the agent that decides what to paint, and the bridge that lets it paint. Release scripts bundle the pair for installation into Krita and curate the public monorepo layout. Two packages, one loop.

### Key modules
- `krita-mcp/krita-plugin/kritamcp` — capabilities.py is the package's source of truth about what the host application offers
- `krita-mcp` — The Python half of the Krita MCP integration turns a running Krita session into a tool surface an MCP client can drive: krita-mcp/server.py…
- `krita-creative-agent/src` — The runtime that turns a user request into Krita actions and a recorded trace of them lives in krita-creative-agent/src, and it is the only…
- `krita-creative-agent` — service.mjs carries the bulk of the group's public surface — fifteen of the thirty-six exported symbols across the six files — and is the…
- `krita-creative-agent/scripts` — Packaging is a two-stage pipeline

### Entry points
- `krita-mcp/server.py`
- `krita-creative-agent/src/main.mjs`

### Files that need care (bug-fix history first, then churn — check `get_risk` before editing)
- `krita-creative-agent/tests/studio.test.mjs` — 11 commits/90d
- `krita-creative-agent/src/studio.mjs` — 16 commits/90d
- `krita-mcp/krita-plugin/kritamcp/creative_tools.py` — 10 commits/90d
- `krita-creative-agent/src/project-store.mjs` — 4 commits/90d
- `krita-mcp/krita-plugin/kritamcp/creative_docker.py` — 7 commits/90d

### Code health
Three co-equal signals: code health 5.73/10 avg (Fair), hotspot health 3.64/10 (stable), worst `krita-mcp/krita-plugin/kritamcp/creative_docker.py` at 1.0/10 · maintainability 6.4/10 · performance risk 178 open static I/O-in-loop / N+1 findings. Detail: `get_health()`.

Critical files:
- `krita-mcp/krita-plugin/kritamcp/creative_docker.py` — untested hotspot — impact −2.0
- `krita-mcp/krita-plugin/kritamcp/__init__.py` — untested hotspot — impact −2.0
- `krita-creative-agent/tests/test_native.py` — low cohesion (Document) — impact −1.0
- `krita-creative-agent/tests/test_layer_craft.py` — low cohesion (Node) — impact −1.0
- `krita-creative-agent/scripts/build-release.py` — complex method (build) — impact −0.9

<!-- REPOWISE_AGENTS:END -->

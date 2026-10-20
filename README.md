# Krita Agent

**Agentic painting inside Krita.** This repository is a fork of [Krita](https://krita.org) (master, Qt6) with an AI painter built
in: you chat with it in a panel, it makes one substantial move at a time on reversible layers, you keep it, undo it or correct it,
and an independent visual reviewer checks the result against your reference. Krita Agent adds the parts of Krita's engine that a
script needs to paint well (pen pressure, tilt and speed, async stroke jobs, one-step agent moves, named regions of the canvas,
undoable tools), and ships the agent with the app.

> Status: pre-alpha, built and run on macOS (Apple silicon). "Krita Agent" is a working name. Krita is a trademark of the
> Krita Foundation; this is an independent fork and is not affiliated with or endorsed by the Krita project.

## What is in this repository

| Path | What it is |
|---|---|
| everything outside `creative-agent/` and `agent/` | Krita itself, with our changes (listed file by file in [AGENT-FORK.md](AGENT-FORK.md)) |
| `creative-agent/krita-mcp` | the agent's Python plugin for Krita, and an MCP server for other clients |
| `creative-agent/krita-creative-agent` | the companion (Node/TypeScript): models, the painter and reviewer, tools, tests |
| `creative-agent/krita-native` | a native helper for stock Krita 5.3.3 (frozen: the fork has these abilities built in) |
| `creative-agent/openspec` | the specs, design and task list for the fork |
| `agent/` | build, test, CI and publishing scripts |
| `README.krita.md` | Krita's own README, unchanged |

The earlier plugin-only repository lives on in the branch `plugin-only` of this repository.

## Build and test (macOS)

```sh
agent/fetch-deps.sh            # once: the dependency tree and tools
agent/build-macos.sh --tests   # configure, build and install into _install (a full build takes hours)
agent/run-tests.sh TestDocument TestStrokeJobs   # C++ tests, safely (see the header of the script)
agent/ci.sh                    # every suite we own: plugin Python, companion JS and typecheck, C++ programs
agent/run.sh                   # start Krita Agent (its own settings folder and bridge port; never stock Krita's)
```

## How changes get here

Work is done on short-lived branches, reviewed by a fresh reviewer, and merged into `krita-agent` locally. **Every merge that
passes `agent/ci.sh` and the pre-publication check (`agent/prepublish-check.sh`: secrets, paintings, personal data) is published
to `main` of this repository by `agent/publish.sh`.** `main` is therefore always the last state that passed its tests.

The public history is a replay of the local main line: its first commit is Krita's tree at the commit this fork started from
(Krita's own history, about 10 GB, stays at [invent.kde.org/graphics/krita](https://invent.kde.org/graphics/krita)), followed by one
commit per merge or change, with its message and author. Krita's master is merged into the fork monthly (see AGENT-FORK.md).

Continuous integration on GitHub is deliberately light (the agent's Python and JS suites, on free hosted runners). Building Krita
takes hours and runs locally.

## Licence

Krita is GPL-3.0-or-later (see `COPYING`); the combined work is distributed under GPL-3.0-or-later. New files in Krita's libraries
carry that library's licence (LGPL-2.0-or-later in `libs/libkis`, GPL-2.0-or-later in `libs/image` and `libs/ui`), copyright
Yakub Rabiutheen, so that they can be offered upstream. The agent's own code (`creative-agent/`, `agent/`) is GPL-3.0-or-later.

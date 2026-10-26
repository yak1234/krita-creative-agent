# Toska

<p align="center"><img src="creative-agent/docs/branding/toska-logo.png" alt="Toska" width="480"></p>

**Agentic painting inside Krita.** Toska is a fork of [Krita](https://krita.org) (master, Qt 6) with an AI painter built in.
You chat with it in a panel. It makes one substantial move at a time on layers you can undo, and you decide whether each move
stays or type a correction. A separate reviewer checks the result against your reference. Underneath, Toska adds the engine
features a script needs to paint well, among them pen pressure and tilt, background stroke jobs, one-step agent moves and named
regions of the canvas. The agent comes with the app.

<p align="center"><img src="creative-agent/docs/gallery/five-minutes.jpg" alt="Pyat' minut (Five Minutes), a painting of Dostoevsky in a white shroud on Semyonovsky Square, snow falling at sunrise" width="800"><br>
<em>Pyat' minut</em> (Five Minutes). Dostoevsky on Semyonovsky Square in 1849, waiting to be shot, not knowing the Tsar had already pardoned him. Painted in Toska.</p>

> Status: pre-alpha, built and run on macOS (Apple silicon). Toska was called "Krita Agent" while it was being made, and the
> repository, the settings folder (`KritaAgent`) and the app's bundle identifier (`local.kritaagent`) keep that name for now (see the
> "Product name" section of AGENT-FORK.md). Toska is based on Krita, the free digital painting program by the Krita developers
> ([krita.org](https://krita.org)), and is distributed under the GNU GPL, as Krita is. Krita is a trademark of the Krita
> Foundation. Toska is an independent fork and is not affiliated with or endorsed by the Krita project.

## What it can do

- **Ask, Plan, Agent and Autopilot.** Ask and Plan only talk. Agent makes one substantial move per message (a whole sky of
  strokes, say), and you keep it or take it back. Autopilot paints an agreed plan through to the end, or until you press Stop.
- **Every move can be undone.** Strokes go on native Krita layers through Krita's own brush engine, and Undo takes back the
  whole move.
- **References with a job.** Each reference image says what it is for: overall direction, a character's likeness, composition,
  palette or material. When the goal picture is much smaller than the canvas, Toska sharpens it on your Mac before painting.
- **It checks its own work.** A vision model looks at each pass as it lands and undoes one that made the painting worse. At the
  end of a step, a reviewer in a fresh session judges the canvas against the plan and gives its evidence.
- **Paint only here.** Type a part ("the sky", "the left buildings") and Toska outlines it. Krita then blocks every stroke
  outside that outline.
- **AI images, only when you allow them.** A move can use a generated image as an asset to repaint, or a canvas edit reference
  that shows a change before anything is painted. Both stay off until you give the chat an allowance.
- **Effects that need a method,** such as falling and settled snow: thousands of soft flakes in depth, with faces kept clear.

## How it works

```mermaid
flowchart TD
    artist(["Artist"])

    subgraph toska["Toska, our fork of Krita"]
        panel["Agent panel<br/>chat, plan, approval cards"]
        bridge["Bridge plugin<br/>checks every paint operation"]
        canvas["Canvas<br/>native layers, full undo"]
    end

    subgraph companion["Companion: agents on Agent Pi"]
        studio["Studio<br/>runs each chat"]
        planner["Planner<br/>vision model"]
        reviewer["Reviewer<br/>fresh eyes on the plan"]
        painter["Painter<br/>tool-calling model"]
        prep["Preparation workers<br/>draft moves in parallel"]
        kit["The painter's kit<br/>brushwork, references with a job,<br/>AI images, snow"]
        checks["Checks<br/>vision model: keep or undo, pace, done"]
    end

    artist <--> panel
    panel <--> studio
    studio --> planner
    studio --> reviewer
    studio --> painter
    prep -.->|drafts| painter
    painter --> kit
    kit -->|paints through| bridge
    bridge --> canvas
    canvas -.->|looks at| checks
    checks -.->|verdicts| studio
```

Toska is Krita with an agent built in. A small plugin inside it is the only part that changes the painting. It checks every
operation before running it and puts each pass on a layer you can undo.

The agents run beside it in a companion app built on Agent Pi. Each chat has a studio that hands out the work. The planner reads
your references and breaks the job into steps. Then the painter makes one move at a time, while preparation workers draft the
next ones in parallel. When a step is done, a reviewer comes in with fresh eyes and judges the result against the plan. Between those, a
fast vision model looks at each pass as it lands and decides whether to keep it, slow down or call the step done.

Anything that needs your say shows up as a card in the panel, so you decide what stays.

For development and testing, an MCP server (`creative-agent/krita-mcp/server.py`) lets a coding agent such as Claude Code drive
Toska the same way. You don't need it to paint.

More detail: [architecture](creative-agent/krita-creative-agent/docs/architecture.md),
[safety](creative-agent/krita-creative-agent/docs/safety.md),
[decision models](creative-agent/krita-creative-agent/docs/decision-models.md) and
[tracing](creative-agent/krita-creative-agent/docs/tracing.md).

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

The earlier plugin-only repository is the branch `plugin-only` of this repository.

## Build and test (macOS)

```sh
agent/fetch-deps.sh            # once: the dependency tree and tools
agent/build-macos.sh --tests   # configure, build and install into _install (a full build takes hours)
agent/run-tests.sh TestDocument TestStrokeJobs   # C++ tests, safely (see the header of the script)
agent/ci.sh                    # every suite we own: plugin Python, companion JS and typecheck, C++ programs
agent/run.sh                   # start Toska (its own settings folder and bridge port, never stock Krita's)
```

## How changes get here

Each change is made on a short-lived branch and checked by a fresh reviewer before it is merged into `krita-agent` locally.
**A merge that passes `agent/ci.sh` and the pre-publication check (`agent/prepublish-check.sh`: secrets, paintings, personal
data) is published to `main` of this repository by `agent/publish.sh`.** So `main` is always the last state that passed its
tests.

The public history replays the local main line. Its first commit is Krita's tree at the commit this fork started from. Krita's
own history (about 10 GB) is at [invent.kde.org/graphics/krita](https://invent.kde.org/graphics/krita). After that comes one
commit per merge or change, with its message and author. Krita's master is merged into the fork monthly (see AGENT-FORK.md).

Continuous integration on GitHub is deliberately light: the agent's Python and JS suites, on free hosted runners. Building Krita
takes hours and runs locally.

## Licence

Krita is GPL-3.0-or-later (see `COPYING`), and the combined work is distributed under GPL-3.0-or-later. New files in Krita's
libraries keep that library's licence (LGPL-2.0-or-later in `libs/libkis`, GPL-2.0-or-later in `libs/image` and `libs/ui`),
copyright Yakub Rabiutheen, so that they can be offered upstream. The agent's own code (`creative-agent/`, `agent/`) is
GPL-3.0-or-later.

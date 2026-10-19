# TypeScript and Pi extensions: what to move first

Date: 2026-10-18. Status: suggestions for the artist to accept, change or reject. Nothing here is built.

This builds on `openspec/changes/typed-companion-and-pi-update/` (the "typed-companion plan"). Where this document
differs from that plan it says so and why. Anything marked **(guess)** is my guess and has not been confirmed by you.

## 1. Intent and why

You want the companion (`krita-creative-agent`) to end up fully TypeScript. You asked which first steps give the
most value, and suggested "Luna decisions as an extension" as an example.

Here is what TypeScript and Pi extensions would fix in this codebase. Each point is something I found in the code
or the history:

- **Silent breakage on Pi updates.** Pi removed `shouldStopAfterTurn`. In plain JavaScript the old assignment
  still succeeds and does nothing, so runs would have continued after Stop (typed-companion proposal). Only the
  compiler catches that kind of break, and `studio.mjs` is still outside the check.
- **Three files are still unchecked:** `src/studio.mjs` (2,094 lines, 28 commits, the most-changed file),
  `src/decisions/client.mjs` and `src/decisions/service.mjs`. The last two are the Luna client itself. Everything
  Luna returns is the loose shape `{answers} | {fallback}`, which no type describes.
- **Tool names are plain strings, repeated in about ten lists:** `runtime.mjs` `onEvent` (twice: the status
  labels and the "Painted:" list), `studio.mjs` `PACED_TOOLS`, `mutates` and `selectTools`, `bridge.mjs`
  `mutating`, `routing.mjs` `routes`, `pacing.mjs` `TRANSFER_TOOLS`/`NOT_AUTHORED`/`REFERENCE_TOOLS`, and
  `loop-guards.ts` `STROKE_TOOLS`/`MARK_TOOLS`. Rename a tool and pacing, routing or the panel's status quietly
  stop working for it. Nothing fails.
- **The same logic is copied in two places.** `actionsOf` exists in both `pacing.mjs` and
  `extensions/loop-guards.ts`. Also, `src/tool-choice.ts` imports painting-call helpers *from the extension*, so
  domain code depends on a Pi plugin when it should be the other way round.
- **The code patches Pi's internals.** `runtime.mjs` replaces `session.agent.transformContext` to run
  `keepRecentImages`. `studio.mjs` `buildTools` wraps the `execute` of every paced tool to run Luna pacing.
  `session-store.mjs` overrides seven private `SessionManager` members (`SDK_INTERNALS`). Pi offers documented
  events (`context`, `tool_call`, `tool_result`) for the first two.
- **Some comments are out of date.** `loop-guards.ts` says it is "loaded by path", but it is registered inline.
  `session-store.mjs` says "The SDK is pinned (0.84.3)", but the installed Pi is 1.3.0.

What extensions add beyond types:

- Each concern gets a small surface you can test. `tests/loop-guards.test.mjs` already shows the pattern: a fake
  `pi` for the rules, plus one real Pi session.
- Handlers compose in registration order.
- You can switch a concern off per session by not registering it. `config.loopGuards === false` already does
  this for benchmarks.

What extensions do **not** do (checked against the installed `core/extensions/types.d.ts`):

- **They cannot end a run.** `turn_end` and `agent_before_settle` can only add entries or ask for *one more*
  request (`continue`). Ending the run cleanly after a turn is `agent.finishTurn`, which belongs to the agent
  core, not the extension API. `ctx.abort()` is a hard abort.
- **They should not own durable painting state.** The goal, the plan and the pace history live in the project
  store (SQLite).

## 2. Goals, non-goals, anti-goals

**Goals**
- Every companion module is eventually a strictly checked `.ts` file.
- The agent loop's concerns (hints, pacing, context trimming) go through Pi's extension events, not patches on
  Pi objects.
- Luna's role is explicit and typed, and can be swapped or switched off per session.
- Each step ships alone and can be tested alone.

**Non-goals**
- Porting the Python Krita plugin to TypeScript.
- Changing what the painter or Luna decide. These are refactors that keep behaviour, except where a step says
  otherwise.
- Supporting user-installed Pi extensions in the painting loop.

**Anti-goals** (bad outcomes even if the code works)
- Two sources of truth for painting state, for example pace history in both `pi.appendEntry` and the project store.
- An "extension" that is really the studio in disguise, holding a reference to the whole `StudioRuntime`. Each
  extension gets a narrow, typed host interface (a "port") instead.
- Removing runtime validation. Every TypeBox `Value.Check` on model input stays, because types cannot check what
  a model sends.
- A migration that needs Krita restarts for each small step, or that touches Krita while it paints.

## 3. Constraints (checked, not from memory)

| Constraint | What I found |
|---|---|
| Node floor | `package.json` `engines.node` is `>=22`. The release ships a managed Node pinned in `scripts/build-release.py` (`NODE_VERSION = '22.23.2'`). I checked that this installed runtime runs a `.mjs` that imports a `.ts` file, with no flags. |
| Syntax | Erasable syntax only (`erasableSyntaxOnly`, `verbatimModuleSyntax` in `tsconfig.extensions.json`). Node does not strip types inside `node_modules`. |
| Bundling | esbuild bundles from `src/release-entry.mjs` with `--target=node22`. It already compiles `loop-guards.ts`. |
| Extensions | Inline only, through `DefaultResourceLoader` `extensionFactories`, with `noExtensions: true`. Path loading fails inside the bundle because Pi's loader cannot find Pi's own modules. |
| Pi pin | `@earendil-works/pi-coding-agent` `1.3.0` and `typebox` `1.3.27`, pinned exactly. Context7 has `/earendil-works/pi/v1.3.0`. Where docs and the installed `.d.ts` disagree, the installed `.d.ts` wins. |
| Checks today | `npm run typecheck` passes: `tsc -p .` (JSDoc, non-strict) plus `tsc -p tsconfig.extensions.json` (strict `.ts`). |
| Working rules | Painter fixes need build, install and reload. Never touch Krita while it paints. Batch the plugin-panel changes into one Krita restart. |

## 4. Loop concerns versus domain code

A concern is a good extension candidate only if it reacts to Pi's loop: a tool call, a tool result, the context
of a request, or the start of a run. Domain logic should be a typed module that an extension may call.

| Behaviour | Where now | What it is | Proposed form |
|---|---|---|---|
| Craft and look hints | `extensions/loop-guards.ts` | Loop: `tool_result` | Already an extension |
| Luna pacing and auto-undo | `studio.mjs` `afterPainting`, `refuseExhaustedMethod`, `rejectDamage`, `paceCloseUp`, `callPasses` (about 160 lines) | Loop: `tool_call` / `tool_result` | **Extension** over a typed core |
| Keep only the newest canvas images | `runtime.mjs:277` patches `transformContext` | Loop: request context | **Extension** (`context`) |
| Stop, turn limits, one move per message | `turn-control.mjs`, five `stopAfterTurn` sites | Agent core (`finishTurn`) | **Typed module**, not an extension |
| Luna client, endpoints, keys, image check | `decisions/*`, `luna-decisions.mjs` | Service | **Typed module** |
| Pace rules (plateau, stall, transfer) | `pacing.mjs`, `visual-checks.mjs` | Pure domain | **Typed module** |
| Per-pass visual check | `studio.mjs` `visualPassCheck`, inside `callNative` | Below the tool level (one per bridge operation) | Stays in the host for now |
| Routing and layer-need advice | `routing.mjs`, `studio.mjs` `routeDirection`/`checkLayerNeed` | Runs before a run and feeds `context(phase)` | Typed module now. Maybe a `before_agent_start` extension later (low gain) |
| Langfuse tracing | `langfuse-tracing.mjs` `watchSession` via `session.subscribe` | Observer | Leave as is (already checked). An extension later is optional |
| Panel activity and diagnostics | `runtime.mjs` `onEvent` | Host UI | Typed host code |
| Chat storage in SQLite | `session-store.mjs` | Pi internals | Typed module, converted last |
| Plan, moves, review, host tools | `studio.mjs` `buildTools` `add(...)` (7 plain-object tools) | Domain | Typed module (`defineTool`) |

## 5. Ranked candidates

Ranked by how much each improves the system. The order to build them in is in section 6.

### 1. Luna pacing as a Pi extension, on a typed decisions core (your example)

**What it is now.** After each paced tool call, `buildTools` wraps the tool's `execute`:
`refuseExhaustedMethod(call)` runs first, then `afterPainting(result, call)`. `afterPainting` mixes three jobs:
- Agent-mode move bookkeeping
- delivering the parallel-preparation suggestions
- Luna pacing: one Luna request, auto-undo of severe artifacts, plateau and stall rules, and the `host_pacing` note

**Is it a good fit as an extension?** Partly. This is where "Luna decisions as an extension" works and where it
does not:

| Luna use | Extension? | Pi events | Why |
|---|---|---|---|
| Pacing note after a painting call | **Yes** | `tool_result` (returns `content`) | Same as today's wrapper, but through Pi's contract. It composes with loop-guards in a known order. |
| Refusing an exhausted method | **Yes** | `tool_call` → `{ block: true, reason }` | Today it throws inside the wrapper. `block` is the documented equivalent. |
| Auto-undo of a severe artifact | Yes, through a port | `tool_result` (replaces content and image) | It needs the bridge (`review_pass`), so the host passes in `rejectPasses()`. |
| Ending the turn for review (`yieldRequested`) | **No** | none | Only `finishTurn` can end a run. The extension asks the host to stop, for example on a `krita:yield` channel on `pi.events`, and `turn-control` decides. |
| The Luna client, endpoints, keys, image check | **No** | none | Shared by routing, layer need, pass checks, review progress and the panel. This is a service. |
| Routing, layer need, review progress, per-pass checks | Not now | none | They run before a run, below the tool level, or in the host's review loop. |

**Proposed form.**
- `src/decisions/*.ts`, `luna-decisions.ts`, `pacing.ts` and `visual-checks.ts` as strict typed modules. A
  `DecisionResult` union makes the code handle `fallback` before it can read `answers`.
- `extensions/luna-pacing.ts` as an inline factory `lunaPacing(port)`. The port is typed and holds the goal
  reader and writer, `luna()`, `peek`, `rejectPasses`, `persist`/`publish`/`emit`, `diagnostics` and `tracing`.
- Move bookkeeping and preparation delivery stay in the host, or become a small `tool_result` handler of their
  own. They are not Luna.

**Improvement.**
- About 160 lines leave the unchecked studio file.
- The `execute` wrapper goes away.
- Pacing gets tests with a fake `pi`, without building a `StudioRuntime`.
- Luna on, off or Evaluate becomes a choice of which extensions to register.

**Cost and risk.** Medium. This behaviour is visible to you as the artist:
- Step changes, undo, and the "change method" notes.
- The order of `tool_result` handlers. Today pacing runs *inside* `execute`, so loop-guards sees the result with
  pacing already applied. To keep that, register `lunaPacing` before `loopGuards`.
- `tool_result` also fires for nested `ctx.executeTool` calls (`parentToolCallId`). Skip those.

**Depends on:** candidate 2 (the shared catalogue and call helpers) and candidate 3 (`Goal` types for the port).

**Verify.**
- Port the pacing cases in `tests/studio.test.mjs` and `tests/pacing.test.mjs` to fake-`pi` tests.
- Run one real-Pi session test, as `loop-guards.test.mjs` does.
- Do one live Autopilot run in Guide mode, after build, install and reload, checking that Krita is idle first.
- Compare the `pacing` and `auto_reject` diagnostics with a run from before the change.

### 2. One typed tool catalogue and painting-call helpers

**What it is now.** About ten string lists (section 1), and `actionsOf` copied twice. `tool-choice.ts` imports
from the extension.

**Proposed form.** `src/painting-calls.ts`:
- An `as const` table: tool name → `{ mutating, paced, label, activity, method }`.
- The `ToolName` type derived from that table.
- `actionsOf`, `plain`, `area`, `countStrokes`, `strokeArea` and `callMethod` moved here.

Every list becomes a filter over the table. `loop-guards.ts`, `tool-choice.ts`, `pacing` and `bridge` all import
from it.

**Improvement.** Renaming or adding a tool becomes a compile error wherever it matters, not a quiet gap. This
also fixes typed-companion task 2.5 for tool names (`.map(Type.Literal)` unions typed `never`).

**Cost and risk.** Low to medium. It is mechanical, and the existing tests cover the behaviour.

**Verify.**
- `npm run typecheck`.
- A unit test that every name in `paintingTools()` and the host tools appears in the table, and the reverse.
- `npm run test:unit`.

### 3. Domain types first (`src/types.ts`), then check `studio.mjs`

**What it is now.** `this.goal` appears 230 times in `studio.mjs` with no type. `main.mjs` holds the runtime as
`any`.

**Proposed form.** A types-only `.ts` module with `Goal`, `Brief`, `Step`, `Study`, `ExecutionSettings`, `Move`
and `PaceEntry`, imported into JSDoc with `import('./types.ts')`. After that, apply typed-companion step 4.1:
`// @ts-check` on `studio.mjs`.

**Improvement.** This closes the last big unchecked file. It also makes the ports of the other candidates
expressible.

**Cost and risk.** Low at runtime, because no code changes. The checking effort is medium.

**Verify.** `tsc` is clean, the unit tests pass, and `main.mjs` no longer needs `any`.

### 4. Context trimming as a `context` extension

**What it is now.** `keepRecentImages` runs by reassigning `agent.transformContext` after Pi has installed its own
chain.

**Proposed form.** `extensions/image-window.ts` with `pi.on('context', e => ({ messages: keepRecentImages(e.messages) }))`.
The function moves to a typed module.

**Improvement.** One less patch on Pi internals. It also proves that two extensions work together, and that
factories can take parameters (`keep: 2`).

**Cost and risk.** Very low. Pi's own `transformContext` calls `runner.emitContext`, and the function only
touches `toolResult` images, so placing it inside Pi's chain or after it gives the same result.

**Verify.**
- Port the existing `keepRecentImages` tests.
- A real-Pi test that a third canvas image reaches the model as the "[Earlier canvas image omitted…]" text.

### 5. Typed panel protocol (`PanelCommand` union)

This is typed-companion task 4.3, unchanged. It adds a TypeBox schema per command and an exhaustive `switch` in
`main.mjs`.

Optional later step **(guess that you would want it)**: export the same schemas as JSON Schema, so the Python
panel (`creative_docker.py`) can check what it sends.

### 6. Host tools through `defineTool` (`src/studio-tools.ts`)

The seven tools that `studio.mjs` `buildTools` makes with `add(...)` are plain objects, so they escape task 2.3's
`ToolDefinition[]` check:
- `finish_move`
- `ask_question`
- `propose_plan`
- `start_painting`
- `revise_requirement`
- `record_progress`
- `request_review`

Move them into a typed module over a `Goal` port. They change durable plan state, so they should stay as tools,
not move into an extension's `registerTool`.

### 7. Turn control as a typed module that collects stop requests

`turn-control.mjs` → `turn-control.ts`. The five stop predicates become one named list of reasons:
- cancelled
- faulted
- yield
- move done
- turn limit
- pass allowance

Extensions request a yield on `pi.events`. This keeps `finishTurn` in one place. It does **not** become an
extension, because Pi gives extensions no way to end a run.

### 8. Later: the bridge schemas shared with Python, `session-store`, tracing

- **Bridge schemas.** The painter's TypeBox schemas are already JSON Schema. Exporting the bridge-operation subset
  would let `creative_validation.py` check the same shapes.
- **Keep Krita's lists live.** Values that come from Krita at run time stay dynamic: blend mode ids from
  `KoCompositeOpRegistry`, filter names, and the `krita_capabilities` lists. Don't freeze them into a schema.
- **Opacity units differ.** The companion sends opacity as 0-1, while Krita's `Node.setOpacity` takes 0-255. A
  shared schema should state that boundary.
- **`session-store` last.** In TypeScript, overriding a `private` member is a compile error, so each of the seven
  overrides would need an explicit `// @ts-expect-error`. That is honest, but it shows how fragile the coupling
  is. Convert it last, or replace it if Pi offers a storage interface.
- **Tracing.** Moving tracing into an extension buys little today.

## 6. Suggested first steps

Each step ships alone and passes `npm run typecheck` and `npm run test:unit`. Steps 4 and 5 also need build,
install and reload.

| # | Step | Size | Typed-companion phase |
|---|---|---|---|
| 1 | **Typed decisions core**: rename `decisions/*.mjs`, `luna-decisions`, `pacing`, `visual-checks` to strict `.ts`. Fix the two stale comments. | S | Phase 6 applied to leaves. Closes 2 of the 3 unchecked files |
| 2 | **`painting-calls.ts` catalogue** (candidate 2). `loop-guards` and `tool-choice` import from it. | S-M | Task 2.5 for tool names |
| 3 | **`image-window` extension** (candidate 4). | S | New. Second inline extension |
| 4 | **`types.ts`, then `@ts-check` on `studio.mjs`, then the `main.mjs` runtime typed**. | M | Tasks 4.1, 4.2 |
| 5 | **`luna-pacing` extension** (candidate 1), with the yield request through `turn-control`. One live Guide run. | M | New |
| 6 | **`PanelCommand` union** (candidate 5), plus `studio-tools.ts` (candidate 6). | M | Task 4.3 |

Steps 1 to 3 can run in any order. Step 5 needs steps 2 and 4.

Where I differ from the typed-companion plan:

- **Phase 6 (".ts files") should not be optional.** You want 100% TypeScript. The release already bundles `.ts`,
  and the managed Node runs it. Renaming a file also moves it into the strict project
  (`tsconfig.extensions.json`). So **renaming a file is how it goes strict**, and phases 5 and 6 merge into one
  per-file step, leaves first. Turning on global `strict` for the JSDoc `.mjs` files would mostly be work on files
  about to be renamed. There is one catch: a strict `.ts` cannot import an unchecked `.mjs` cleanly. That forces
  leaves-first, which the plan already prefers.
- **The plan says the tools are typed through `defineTool`.** That is true for `tools.mjs` and the tool modules,
  but not for the seven host tools in `studio.mjs` (candidate 6).
- **The plan says "Plugin: none".** I agree for that change. The shared schema in candidate 8 would be a separate
  change.
- **I add a domain-types step before task 4.1.** The plan does not have one. It is cheap and makes the check of
  `studio.mjs` useful rather than a wall of `any`.

## 7. Slices I dropped, and what is left to the builder

Dropped:
- **Rename everything to `.ts` at once with `strict` off.** It looks like TypeScript but checks nothing.
- **Make everything an extension, including the studio modes.** This fails the narrow-port anti-goal, and
  extensions cannot end runs.
- **Start with `studio.mjs` because it is the biggest.** It has the most value but also the most risk. It goes
  better after the catalogue and the types exist.
- **Start with tracing.** It is already checked and works, so the gain is small.

Left to the builder: file, port and `pi.events` channel names, whether move bookkeeping becomes its own handler,
and the test layout. Two rules stay fixed: `lunaPacing` registers before `loopGuards`, and nested tool results are
ignored.

## 8. Open questions for you

1. Does "100% TypeScript" include `scripts/*.mjs` and `tests/*.mjs`, or only `src/` and `extensions/`?
   **(guess: only `src/` and `extensions/` first)**
2. Should Luna's **Evaluate** mode (record only) stay, so that the pacing extension has three settings: off,
   evaluate, guide?
3. May the Python plugin read a generated JSON Schema file (candidate 8)? Or should the plugin's validation stay
   hand-written?
4. For step 5, can you set aside time for one live Autopilot run in Guide mode, with Krita idle and one restart at
   most?
5. Should painting extensions always stay internal, or could artists one day add their own? A yes changes
   `noExtensions: true` and the path-loading decision.
6. If you must choose: shrink `studio.mjs` first (candidate 1 sooner), or get the checker over it first
   (candidate 3 sooner)? This document assumes the checker first.

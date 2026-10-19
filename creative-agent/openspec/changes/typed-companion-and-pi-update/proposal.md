## Why

The companion is plain JavaScript checked by TypeScript (`// @ts-check`, `tsc --noEmit` in CI), but its most important
modules are outside that check, and the Pi it pins is far behind Pi's current release.

- **Unchecked core.** `studio.mjs` (the four modes, the largest and most-changed file) and `runtime.mjs` (its base class,
  `PaintingRuntime`) are not checked, and `strict` is off. `main.mjs` holds the runtime as `any` until they are.
- **Pi's types go unused.** Pi ships `.d.ts` files, but tools are plain objects rather than `defineTool()`, so a tool's
  `params` are untyped; Pi events in `runtime.mjs` `onEvent` are matched by string with no checking.
- **Stale Pi.** Docs (Context7, pi.dev) describe the current Pi, not the pinned one, so examples no longer match the
  installed signatures. Pi's current release removes `shouldStopAfterTurn`, which the companion sets in five places to
  end a run (Stop, turn limits, one move per Agent message). In plain JavaScript that assignment still succeeds and is
  ignored: a blind update would let runs continue past Stop.
- **Coupling to Pi internals.** `DbSessionManager` (`session-store.mjs`) overrides `SessionManager`'s private storage
  methods to keep chats in SQLite. The type checker cannot see private members, and Pi has changed the save logic
  around them.

Type checking comes first so the update is found by the compiler, not by an artist.

## What Changes

1. **Check the leaves** (done): `session-store`, `model-capabilities`, `langfuse-tracing`, `reference-generator`.
2. **Check `runtime.mjs`**: declared fields, Pi's `AgentSessionEvent` for `onEvent`, tools through `defineTool()`.
3. **Update Pi** as its own change: pin Pi's current release and the `typebox` it depends on together; replace
   `shouldStopAfterTurn` with Pi's `finishTurn`; re-verify `DbSessionManager` against the new `SessionManager`.
4. **Check `studio.mjs`**, then type `main.mjs`'s runtime and panel commands (a `PanelCommand` union with an exhaustive
   switch).
5. **Turn on `strict`** and fix file by file, leaves first.
6. **Optional: rename to `.ts`**, run directly by the managed Node (type stripping), bundled by esbuild as today.

Runtime validation stays: every TypeBox `Value.Check` on model input remains, because types cannot check what a model
sends.

## Capabilities

### New Capabilities
- `typed-companion`: every companion module is type-checked against its own JSDoc and Pi's `.d.ts`; tools get
  parameter types from their schemas; Pi updates are caught by the checker.

## Impact

- **Companion:** `src/runtime.mjs`, `src/studio.mjs`, `src/main.mjs`, `src/tools.mjs` and the tool modules,
  `src/session-store.mjs`, `tsconfig.json`, `package.json` and `package-lock.json` (Pi, `typebox`).
- **Release:** unchanged unless step 6 is taken (then `scripts/build-release.py`, `scripts/setup-local.mjs`,
  `scripts/run-unit-tests.mjs`, README test command).
- **Plugin:** none. Panel commands are typed on the companion side only.
- **Risk:** the Pi update changes run control and chat storage, both artist-facing. It ships alone, after live runs
  confirm Stop, turn limits and saved chats.

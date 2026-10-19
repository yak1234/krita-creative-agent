## 1. Check the leaves

- [x] 1.1 `// @ts-check` on `session-store`, `model-capabilities`, `langfuse-tracing`, `reference-generator`; annotations
  only, no behaviour change. Verified: `tsc` clean, 259/259 unit tests on the managed Node runtime.
- [x] 1.2 Commit step 1 on its own.

## 2. Check `runtime.mjs`

- [x] 2.1 `// @ts-check`; declare `PaintingRuntime`'s fields.
- [x] 2.2 Type `onEvent(event)` as Pi's `AgentSessionEvent`; narrow by `event.type` instead of reading tool fields from
  every event.
- [x] 2.3 Wrap the painter's tools in `defineTool()` (`tools.mjs` and the tool modules) so `params` come from each schema.
  The tool list is typed as Pi's `ToolDefinition[]`, so a tool that is not wrapped fails the check.
- [x] 2.4 Unit tests on the managed Node runtime; commit. Verified: `tsc` clean, 259/259, release bundle builds.
- [ ] 2.5 Literal unions built with `.map()` (`Type.Union(ASPECTS.map(Type.Literal))` in `assets.mjs`, `paint_batch`'s
  `tool`, the capability palette) are typed `never`: runtime validation is exact, but the checker is blind to these
  fields. Declare the literals as tuples (or with a TypeBox form that keeps them) so their types are the real values.
- [ ] 2.6 One `object()` schema helper: six modules each define the same one (`tools`, `assets`, `contour-tool`, `comic`,
  `reference-generator`, `studio`). Declare it once and import it.

## 3. Update Pi (its own change)

- [x] 3.1 Read Pi's changelog from the pinned release to the current one; list every breaking change the companion
  touches (check with `npm view` and the installed `.d.ts`, not docs or memory).
  Done: what touches the companion is `shouldStopAfterTurn` (removed), and Pi now decodes and resizes every prompt
  image, replacing any it cannot process with an "[Image omitted]" note.
- [x] 3.2 Pin Pi's current release and the `typebox` version it depends on, together.
- [x] 3.3 Replace `shouldStopAfterTurn` with `finishTurn` at all five sites: `runtime.mjs`, `studio.mjs` (three),
  `model-capabilities.mjs`. Find them with grep as well as the checker: `studio.mjs` is not checked yet.
  Done through `stopAfterTurn()` (`src/turn-control.mjs`): `finishTurn` runs before `turn_end`, where the counters
  count, so the helper adds the turn in progress; a real-Pi test checks that a limit of 3 makes exactly 3 requests.
- [x] 3.4 Re-verify `DbSessionManager` against the new `SessionManager`: the overridden private methods and fields
  exist and are still called; a test saves, reopens and appends to a chat in SQLite with no JSONL file written.
  Covered by the existing session-store tests (SDK contract, parity, no JSONL); Pi still calls all four overrides.
- [x] 3.5 Unit, packaging and UI smoke tests; build and install. Verified: 260/260 unit, 8/8 packaging, ui_smoke;
  build `832030a1` installed and live through the bridge `reload`, with no Krita restart.
- [ ] 3.6 Live check in Krita: Stop ends a run, the turn limit ends a run, Agent mode makes one move, a chat reopens.

- [x] 3.7 Regression found after shipping: the release bundle dropped every prompt image. Pi resizes prompt images with
  Photon (a worker beside the module, or in process); the bundle had no worker, no `photon_rs_bg.wasm`, and no
  `__dirname` for Photon's loader, so Pi replaced each image with "[Image omitted: could not be resized ...]". Fixed in
  `build-release.py` (`d99dbfa`, `caa9c23`); found by `scripts/live-painting-run.mjs`, missed by every unit test.
- [ ] 3.8 A release smoke test that sends one prompt image through the bundled companion and fails if the model
  request carries an "[Image omitted" note instead of the image, so a bundling gap cannot ship again.

## 4. Check `studio.mjs` and `main.mjs`

- [ ] 4.1 `// @ts-check` on `studio.mjs`; declared fields.
- [ ] 4.2 Remove the `/** @type {any} */` runtime in `main.mjs`.
- [ ] 4.3 A `PanelCommand` union for the panel's commands, with an exhaustive `switch` in `handle()`, and a TypeBox
  schema checking each command as it arrives from the panel.

## 5. Strict

- [ ] 5.1 `"strict": true`; fix leaves first, one file per commit.

## 6. Optional: `.ts` files

- [ ] 6.1 `tsconfig.json`: `erasableSyntaxOnly`, `verbatimModuleSyntax`, `allowImportingTsExtensions`.
- [ ] 6.2 Rename leaves first; update `build-release.py`, `setup-local.mjs`, `run-unit-tests.mjs` and the README test
  command; build, install and test the release.

## 7. Dev deploy without a Krita restart (development only, not shipped)

- [ ] 7.1 One development command: build the release, install it, check that Krita is idle (no painting session, panel
  not busy) and stop if it is not, call the bridge's `reload`, then confirm the running companion's build id is the new
  one. It reports `restart_required` when `__init__.py`, `creative_docker.py`, `command_queue.py` or
  `creative_document_identity.py` changed, the modules `reload` cannot replace.
- [ ] 7.2 Keep it out of the public repo (`curate-public-repo.py` exclusions) and out of the release bundle.

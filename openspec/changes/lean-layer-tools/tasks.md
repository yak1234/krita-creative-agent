## 1. Remove computer use

- [x] 1.1 Delete `src/computer-use.mjs`, `src/computer-use-service.mjs`, `tests/computer-use.test.mjs` and `tests/computer-use-service.test.mjs`. Remove their uses in `src/studio.mjs` (tool lists, `toolOffered`, `checkComputerUse`, `computerUseFailed`) and `src/main.mjs` (`SERVICE_FLAG`).
- [x] 1.2 `src/execution-settings.mjs` drops `computer_use` from defaults and validation, and ignores a saved key. Update `tests/execution-settings.test.mjs` and `tests/studio.test.mjs`.
- [x] 1.3 Remove the panel checkbox in `creative_docker.py` and its `tests/ui_smoke.py` assertions. Remove `codex-computer-use-mcp` from `package.json`/lockfile, the `.npmrc` it needed (`legacy-peer-deps`), and the README section. The helper app was built at runtime, not by `build-release.py`.
- [x] 1.4 Run `npm run test:unit` and `test:packaging`; the built bundle contains no helper app. Verified: 242/242 unit tests, 7/7 packaging tests and `ui_smoke.py` pass; bundle `output/no-computer-use` has no computer-use references and is installed (reload pending).

## 2. Batched, forgiving layer settings

- [ ] 2.1 Plugin: `set_layer` with `layers` (1–50 entries), whole-call validation, one pass, and reject restoring every entry. Test it in `tests/test_native.py`.
- [ ] 2.2 Plugin: layer references resolve by id, then exact name; shared names are refused; a missing layer on a hide-only entry is reported `already_gone`; other unknowns list nearby names.
- [ ] 2.3 Companion: new `set_layer` schema; remove `adjust_layer` from offered tools, `BATCH_TOOLS`, `LAYER_SETTINGS`, `NOT_AUTHORED` and routing; translate resumed `adjust_layer` calls. Update the `paint_batch` tests.

## 3. Layer previews

- [ ] 3.1 Plugin: a read-only `layer_previews` operation that renders up to 12 layers alone into a labelled contact sheet (≤1568 px), with bounds and `pixel_share`.
- [ ] 3.2 Companion: the `view_layers` tool, defaulting to the 12 newest layers. Test that no pass is recorded.

## 4. Coercion

- [ ] 4.1 Plugin: coerce filter config to Krita's setting types and report coerced keys; clip selection shapes to the image. Test the `horizRadius: 2.5` and out-of-bounds polygon cases.
- [ ] 4.2 Plugin: `apply_filter` on an artist layer runs in copy mode, and reject restores the original. Test that the artist's pixels are unchanged.

## 5. Painter skills and image assets

- [x] 5.1 `src/skills.mjs`: bundled skills only (`additionalSkillPaths`, Pi discovery off); the skill-only `read` tool, so Pi lists the skills; `/skill:name` expansion in the studio before context, with the typed text kept for the transcript and move title.
- [x] 5.2 `src/python-sandbox.mjs` + `src/pyodide-runner.mjs`: Pyodide in a `--permission` child process (no environment; reads only Pyodide, cache, work folder and skill scripts; writes only work and cache; empty `js` module; 120 s limit).
- [x] 5.3 `src/assets.mjs`: `make_asset` (Seedream generate, FLUX 3 Klein draft, Muse edit; cut-out; PNG under 4.5 MB; attached as role `asset`, 12 per chat) and `run_skill_script` (bundled scripts only; outputs become assets).
- [x] 5.4 `skills/image-asset`: `SKILL.md` and scripts `asset_ops.py`, `prepare.py`, `cutout.py`, `match_palette.py`, `fade_edges.py`.
- [x] 5.5 Release: Pyodide, runner, skills and the numpy/Pillow wheels ship beside the bundle; verified offline under Node 22.23.2 with `--permission`. 248/248 unit tests pass.
- [ ] 5.6 Live: `scripts/live-asset-test.mjs` paints a Christmas tree, then the sky, from `/skill:image-asset` messages on a new canvas. Record which skill steps the painter followed, what it skipped, and the cost.
- [ ] 5.7 Slim the descriptions of `set_layer`, `select`, `apply_filter` and `view_layers` and move their workflows into skills once 5.6 shows the painter reads skills.

## 6. Acceptance

- [ ] 6.1 Build, install and reload the bundle in Krita. On a disposable copy of an overpainted painting, run a cleanup brief. Check that:
  - the painter uses `view_layers`;
  - it hides the overpaint in one or two `set_layer` calls;
  - no batch stops on a missing layer;
  - reject restores the hidden layers.
- [ ] 6.2 Run Starry Night in Guide mode and benchmark it against `docs/benchmarks/baseline-starry-night.json`. Painter input tokens per call are lower, review results are no worse, and `read_skill` appears in the trace. Record the result in `docs/benchmarks/`.

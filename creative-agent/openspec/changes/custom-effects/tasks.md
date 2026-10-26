# Custom effects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When painting an effect fails, Toska builds a YAML effect recipe from tested blocks, keeps it on approval, and the painter uses it through one `paint_effect` tool; ships with fog and snow; off by default.

**Architecture:** Plugin: six numpy/OpenCV blocks (`effect_blocks.py`, no Qt) behind two operations, `effect` (paints one layer in the move's group, like `snow`) and `effect_preview` (renders a PNG from the canvas view, no document touched). Companion: strict TypeScript under `src/effects/` — recipe schema and expression reader, library loader, the `paint_effect` tool, the failure policy, and the build loop (worker writes candidates, Luna picks blind, card). Panel: the build card, the setting with Reset, Auto-approve's Keep.

**Tech Stack:** TypeScript (strict), TypeBox 1.3.27, `yaml` (pinned direct dependency), Pi SDK `@earendil-works/pi-coding-agent`, Python numpy + OpenCV (plugin), PyQt5/PyQt6 via `qt_compat` (panel).

**Spec:** `creative-agent/openspec/changes/custom-effects/proposal.md`

## Global Constraints

- Off by default: setting `custom_effects` (boolean, default false). Off: no `paint_effect`, no build, `paint_snow` unchanged; after the second failure of one effect the chat says once "As a last resort, enable Custom effects in Settings."
- No agent-written code ever runs: recipes are YAML only; values are numbers or arithmetic on the recipe's own options (numbers, option names, `+ - * /`, parentheses, `min`, `max`); no `eval`.
- Blocks: `particles`, `wash`, `noise`, `caps`, `rays`, `texture`. Each paints only the effect's own new layer, never inside keep-clear shapes (default `["faces", "hair"]`), sized from the canvas, coloured from the scene light.
- Hard caps the engine enforces whatever a recipe says: particles ≤ 60 000 per call, ≤ 3 depth layers, opacity ≤ 1, block count ≤ 8, render time per call ≤ 30 s on 6000 × 4500 (checked by test at that size).
- `cue` ≤ 160 characters, `lesson` ≤ 300, `evidence` ≤ 300; they reach the painter only quoted ("this effect is for: …").
- Build budget (`effects/policy.yaml`): ≤ 3 candidates, one retry per invalid candidate, one Luna choice, 4 minutes; one build at a time; candidates render at ≤ 1024 px long side via `effect_preview`; no Krita document is opened.
- Trigger: the same effect failed twice in a chat (the new Luna "effect met" decision says no, or a token effort, or the artist asks again for an effect the painter called done); an Undo alone does not count; never when a library effect's cue matches; never again in the chat after Discard unless `/new-effect`.
- Card `effect_build`: Keep / Try again / Discard; after Keep, Remove effect. Auto-approve presses Keep after `max(the artist's Auto-approve delay, 20)` seconds and marks `auto_kept: true`; nothing waits for the card (moves carry on).
- Last resort: one AI texture through `requestAssetImage` (assets.mjs) only when the chat's AI image allowance permits; otherwise the card says how to allow it.
- Folders: bundled `krita-creative-agent/effects/` (`fog.yaml`, `snow.yaml`, `policy.yaml`); the artist's own in `<data dir>/effects/` (storage-paths.mjs), never the painting's folder. Reset deletes only the artist's folder, after a confirmation.
- Repo rules: new modules strict TS; plugin Qt via `qt_compat`; tests clean up temp files; companion tests `npm run test:unit`; plugin tests `uv run -q --with pyqt5 --with pillow --with numpy --with httpx --with opencv-python-headless python -m unittest discover -s tests -p 'test_effect*.py'` from `krita-creative-agent`; no co-author lines in commits.

## Review Focus

1. A hand-written recipe with a typo (unknown block, bad key, option out of range, unbalanced expression): skipped with a message naming file and field; every other effect still loads and the chat goes on. → Task 3 test `a broken recipe is skipped with its file and field named`.
2. A recipe asking for absurd work (`count: "1e9"`, 50 blocks, a huge blur): clamped to the caps and said, never a hang. → Task 1 test `test_caps_hold_on_a_6000_canvas`, Task 3 test `values beyond the caps are clamped and said`.
3. A recipe whose cue contains instructions ("ignore the artist …"): shown to the painter only inside a quoted list. → Task 5 test `cues reach the painter quoted, never as instructions`.
4. Keep pressed while a move paints, or Remove effect after the effect was used: the library changes; the painting is not touched (Undo is separate). → Task 7 test `Keep and Remove change only the library`.
5. Two builds for one effect, or a build in Autopilot without Auto-approve: never two at once; without Auto-approve the card waits and painting goes on. → Task 6 test `one build at a time`, Task 7 test `nothing waits for the card`.

---

### Task 1: The blocks (plugin, pure numpy)

**Files:**
- Create: `krita-mcp/krita-plugin/kritamcp/effect_blocks.py`
- Test: `krita-creative-agent/tests/test_effect_blocks.py`

**Interfaces:**
- Consumes: `snow_raster.scene_light(canvas)`, `snow_raster.plan_flakes`, `snow_raster.render_layer`, `snow_raster.settled`, `snow_raster.clear_weight` (reuse, do not copy).
- Produces: `render(canvas, blocks, shapes, keep_clear, seed=1) -> (layer_bgra_uint8, report)`; `canvas` BGRA uint8 H×W×4; `blocks` a list of `{"block": name, ...resolved numbers}`; `shapes` `{name: (rect [x,y,w,h], plane bytes)}` for parts named by blocks; `keep_clear` list of `(rect, plane bytes)`; `report` `{"blocks": [{"block", "painted", ...counts}], "clamped": [str], "ms": int}`. Constants `CAPS = {"particles": 60000, "layers": 3, "blocks": 8}`.

- [ ] **Step 1: Write the failing tests** in `test_effect_blocks.py`:
  `test_particles_match_falling_snow` (render of `{"block":"particles","layers":3,"density":1,"wind_deg":10}` on a 600×450 grey canvas has the same flakes per depth as `snow_raster.falling` with the same seed, ±0); `test_wash_from_bottom_is_densest_at_the_bottom` (mean alpha of the bottom tenth > 3× the top tenth, `from: bottom, falloff: 0.6, opacity: 0.5`); `test_noise_stays_inside_its_area`; `test_caps_need_a_named_part` (report says which part was missing, layer empty); `test_rays_point_from_their_source`; `test_texture_is_placed_inside_its_area_only`; `test_keep_clear_is_never_painted` (alpha 0 inside a face mask for every block); `test_caps_hold_on_a_6000_canvas` (`count 10**9`, 50 blocks → ≤ 60000 particles, 8 blocks, `clamped` names both, < 30 s at 6000×4500).
- [ ] **Step 2: Run them; expect FAIL** (`ModuleNotFoundError: effect_blocks`).
- [ ] **Step 3: Implement `effect_blocks.py`**: one function per block `(canvas, params, shapes, rng) -> (bgra, report_row)`, composited in order with "over"; keep-clear applied last via `snow_raster.clear_weight`. `particles` delegates to `plan_flakes` + `render_layer` with `streak` and `colour` (`light` | `local`); `caps` delegates to `snow_raster.settled`.
- [ ] **Step 4: Run them; expect PASS**, then the whole plugin suite (command in Global Constraints with `-p 'test_*.py'`).
- [ ] **Step 5: Commit** `Effect blocks: particles, wash, noise, caps, rays and texture in numpy, capped, never inside keep-clear parts`.

### Task 2: The `effect` and `effect_preview` operations (plugin)

**Files:**
- Create: `krita-mcp/krita-plugin/kritamcp/effect_craft.py` (class `EffectCraft`, the shape of `snow_craft.py`)
- Modify: `krita-mcp/krita-plugin/kritamcp/creative_tools.py:38,98,129,620,725,813,932` (import, `NEW_CONTRIBUTIONS`, the class bases, the operation lists, validate/apply branches, title `'Effect'`)
- Test: `krita-creative-agent/tests/test_effect_craft.py`

**Interfaces:**
- Consumes: Task 1 `render`.
- Produces: native operation `effect {name, blocks, keep_clear: [{mask_path, bounds}], parts: {name: {mask_path, bounds}}, seed?}` → one reversible pass, one layer named `Effect: <name>` in the move's group, result `{report}`; native operation `effect_preview {image_path, blocks, keep_clear, parts, out_path}` → writes a PNG of the canvas view with the effect over it, touches no document, result `{report}`.

- [ ] **Step 1: Write the failing tests** (`test_snow_craft.py`'s fakes): `test_effect_paints_one_layer_named_after_it`; `test_effect_rejects_unknown_fields_and_blocks`; `test_preview_writes_a_png_and_opens_no_document` (fake Krita records no `openDocument`/`createDocument`); `test_preview_refuses_a_path_outside_the_chat_folder`.
- [ ] **Step 2: Run; expect FAIL** (no `effect_craft`).
- [ ] **Step 3: Implement `EffectCraft._effect_check/_effect_validate/_effect_apply/_effect_preview`** and register both operations; `effect_preview` reads `image_path` with OpenCV, writes `out_path` only under `session['output']`.
- [ ] **Step 4: Run; expect PASS**; then the plugin suite.
- [ ] **Step 5: Commit** `Effect operations: effect paints a recipe on its own layer; effect_preview renders it on the canvas view without a document`.

### Task 3: Recipe schema, expressions and the library (companion)

**Files:**
- Create: `krita-creative-agent/src/effects/recipe.ts`, `krita-creative-agent/src/effects/library.ts`
- Modify: `krita-creative-agent/package.json` (`"yaml"` pinned to the version now in `node_modules/yaml/package.json`)
- Test: `krita-creative-agent/tests/effect-recipe.test.mjs`, `krita-creative-agent/tests/effect-library.test.mjs`

**Interfaces:**
- Produces:
  - `type Recipe = { name: string; cue: string; lesson?: string; evidence?: string; layer?: string; keep_clear: string[]; options: Record<string, { default: number; min: number; max: number; describe?: string }>; blocks: BlockSpec[]; auto_kept?: boolean }`
  - `parseRecipe(text: string, file: string): { recipe: Recipe } | { error: string }` (error names file and field)
  - `evaluate(expr: number | string, options: Record<string, number>): number` (throws on any other name or token)
  - `resolveBlocks(recipe: Recipe, given: Record<string, unknown>): { blocks: ResolvedBlock[]; notes: string[] }` (clamps options and caps, notes say what was clamped)
  - `loadEffects(dirs: { bundled: string; own: string }): Promise<{ effects: Map<string, Recipe & { source: 'bundled' | 'own'; file: string }>; skipped: string[] }>` (own overrides bundled by name)
  - `saveEffect(own: string, recipe: Recipe): Promise<string>`; `removeEffect(own: string, name: string): Promise<boolean>`; `resetEffects(own: string): Promise<number>`

- [ ] **Step 1: Write the failing tests**: `fog parses and resolves with its defaults`; `expressions allow only numbers, option names, + - * /, parentheses, min and max` (`"0.5 * density"` → 0.5; `"process.exit()"`, `"density.constructor"`, `"1e9 ** 9"` throw); `a broken recipe is skipped with its file and field named` (unknown block `smoke`, `options.density.min > max`, unbalanced `"(0.5"` — `skipped` lists `bad.yaml: blocks[0].block` etc., the other effects load); `values beyond the caps are clamped and said`; `cue, lesson and evidence over their lengths are refused`; `own effects override bundled ones by name`; `reset deletes only the artist's folder`.
- [ ] **Step 2: Run** `npm run test:unit`; expect FAIL (modules missing).
- [ ] **Step 3: Implement** with TypeBox schemas for the recipe and each block (`additionalProperties: false`), the `yaml` parser, and a hand-written expression reader (tokenizer + recursive descent; no `Function`, no `eval`).
- [ ] **Step 4: Run; expect PASS**; `npx tsc --noEmit -p .` clean.
- [ ] **Step 5: Commit** `Effect recipes: YAML checked by schema, arithmetic on its own options only, a library of bundled and own effects`.

### Task 4: Bundled fog, snow and policy

**Files:**
- Create: `krita-creative-agent/effects/fog.yaml`, `krita-creative-agent/effects/snow.yaml`, `krita-creative-agent/effects/policy.yaml`, `krita-creative-agent/src/effects/policy.ts`
- Modify: `agent/package_app.py` only if bundled companion folders are listed explicitly (check `effects/` ships in the app; `package-app.sh --check` must stay 0 problems)
- Test: `krita-creative-agent/tests/effect-bundled.test.mjs`, `krita-creative-agent/tests/test_effect_blocks.py` (one more test)

**Interfaces:**
- Consumes: Task 3 `parseRecipe`, `resolveBlocks`.
- Produces: `type Policy = { failures_before_build: 2; candidates: 3; retries: 1; minutes: 4; preview_side: 1024; auto_keep_min_seconds: 20 }`; `readPolicy(file: string): Policy` (defaults when the file is missing or invalid, never throws).

- [ ] **Step 1: Write the failing tests**: `the bundled effects and policy load with nothing skipped`; `snow.yaml resolves to what paint_snow sends` (falling: same density, wind 10, 3 layers, keep_clear faces and hair as `snow-tool.ts` defaults); Python `test_snow_recipe_paints_what_falling_snow_paints` (same flakes per depth as `snow_raster.falling`).
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Write `fog.yaml`** (wash from bottom, falloff 0.6, lowers contrast 0.3, opacity `0.5 * density`; noise large, opacity `0.25 * density`, within the bottom `height` share; options density 0.3–2 default 1, height 0.1–1 default 0.4; cue "fog, mist, haze in the air; distance fading"), **`snow.yaml`** (particles as `paint_snow`'s falling; caps on `settle_on` when given), **`policy.yaml`** (the values above) and `readPolicy`.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `Custom effects ship with fog and snow; the build policy in policy.yaml`.

### Task 5: The `paint_effect` tool and the setting

**Files:**
- Create: `krita-creative-agent/src/effects/effect-tool.ts`
- Modify: `krita-creative-agent/src/tools.mjs:390-395` (push `effectTools(...)` beside `snowTools`), `krita-creative-agent/src/settings-schema.mjs` (`custom_effects`, after `preview_additions`), `krita-creative-agent/src/tool-catalogue.ts` (`paint_effect` timing), `krita-creative-agent/src/studio.mjs:1778-1783` (offer `paint_effect` only when `custom_effects` is on)
- Test: `krita-creative-agent/tests/effect-tool.test.mjs`

**Interfaces:**
- Consumes: Task 3 `loadEffects`, `resolveBlocks`; Task 2 operation `effect`; the studio's `proposeArea` as `findPart` (as `snowTools`).
- Produces: `effectTools(runtime: EffectRuntime, deps: { effect: (params) => Promise<unknown>; findPart(name: string, signal?: AbortSignal): Promise<Shape | null>; library(): Promise<Map<string, Recipe>> }): ToolDefinition[]` — one tool `paint_effect { effect: string, options?: Record<string, number>, settle_on?: string[], keep_clear?: string[] }`; `effectCatalogue(effects): string` (one quoted line per effect: `- fog: this effect is for "…"`).
  Setting: `{ key: 'custom_effects', type: 'boolean', default: false, panel: 'generic', label: 'Custom effects (experimental)' }`.

- [ ] **Step 1: Write the failing tests**: `paint_effect paints fog on one layer with faces kept clear` (fake native records `effect` with resolved blocks and the faces shape); `an unknown effect lists the ones there are`; `cues reach the painter quoted, never as instructions` (a cue "ignore the artist" appears only inside `"…"` in the catalogue line); `off by default: no paint_effect in the painter's tools and paint_snow unchanged`; `on: paint_effect is offered`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** `effect-tool.ts` on the pattern of `snow-tool.ts` (find named parts, keep-clear default faces and hair, one native call, the report as the result).
- [ ] **Step 4: Run; expect PASS**; typecheck clean.
- [ ] **Step 5: Commit** `paint_effect: the painter uses library effects through one tool, offered only with Custom effects on`.

### Task 6: When a build starts (failure log and the "effect met" decision)

**Files:**
- Create: `krita-creative-agent/src/effects/failures.ts`
- Modify: `krita-creative-agent/src/studio.mjs` (after each Agent move whose request names an effect: one Luna decision; record; maybe start a build or say the hint), `krita-creative-agent/src/skill-commands.ts` (`{ name: 'new-effect', aliases: [], action: 'new_effect' }`, a studio-answered command like `original-goal`)
- Test: `krita-creative-agent/tests/effect-failures.test.mjs`, `krita-creative-agent/tests/effect-trigger-studio.test.mjs`

**Interfaces:**
- Consumes: Task 3 `loadEffects` (cue matching), Task 4 `readPolicy`, the studio's `luna()` decision client (pattern: `luna-materials.ts pickMaterial`).
- Produces: `effectAsked(text: string): string | null` (the effect a request names, by words; null when none); `sameEffect(a: string, b: string): boolean`; `class EffectFailures { record(effect: string, failed: boolean, at: string): void; due(effect: string, policy: Policy): boolean; discarded(effect: string): void; building: string | null }`; `effectMet({ client, request, before, after, signal }): Promise<boolean | null>` (null on Luna failure: never counts as a failure).

- [ ] **Step 1: Write the failing tests**: `the same effect twice is due, once is not`; `a redo of an effect called done counts as a failure`; `an Undo alone does not count`; `a library effect whose cue matches is used, not built`; `after Discard the effect is not built again unless /new-effect`; `one build at a time`; `a Luna failure is not a failure`; studio: `off: the second failure says the enable hint once`; `on: the second failure starts a build and the next move starts without waiting`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** `failures.ts`; in the studio, after a move: `effectAsked(request)` → `effectMet` → `record` → `due` → `startEffectBuild` (Task 7) without `await` on the move's path.
- [ ] **Step 4: Run; expect PASS**; full `npm run test:unit`.
- [ ] **Step 5: Commit** `Custom effects start a build after the same effect fails twice (Luna: was it met?), never on an Undo alone, never twice at once`.

### Task 7: The build, the card and the library changes

**Files:**
- Create: `krita-creative-agent/src/effects/build.ts`, `krita-creative-agent/skills/effect-building/SKILL.md`
- Modify: `krita-creative-agent/src/studio.mjs` (`startEffectBuild`, `answerEffectBuild`, the worker session as `prepareBatchProposal`'s worker at studio.mjs:4455-4462 with one tool `submit_effect_candidates`), `krita-creative-agent/src/test-commands.ts` (`effect_build_answer`, as `canvas_reference_answer`)
- Test: `krita-creative-agent/tests/effect-build.test.mjs`

**Interfaces:**
- Consumes: Tasks 2–6; `requestAssetImage` (assets.mjs) for the last resort; `assertAiImageAllowed`.
- Produces: `effectBuilder(host: EffectBuildHost): { start(effect: string, request: string): Promise<EffectBuildRecord | null>; answer({ id, action }: { id: string; action: 'keep' | 'retry' | 'discard' | 'remove' }): Promise<void> }`; event `{ type: 'effect_build', id, title: 'Custom effect', message, image_path, options, actions, auto_keep_seconds }`; record `{ id, effect, candidates: string[], chosen: 'A'|'B'|'C'|null, state: 'ready'|'kept'|'removed'|'discarded', auto_kept?: boolean }`.

- [ ] **Step 1: Write the failing tests**: `three candidates, an invalid one retried once, Luna chooses blind` (Luna's request shows only A/B/C images and the request text, never recipe text); `the card shows the canvas and the chosen effect`; `Keep and Remove change only the library` (no native call touches the painting); `nothing waits for the card` (a move runs while the card is open); `with no candidate left and AI images allowed, one texture recipe`; `with AI images off, the card says how to allow one`; `over 4 minutes the build ends and says so`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** `build.ts` (worker → `parseRecipe` → `effect_preview` per candidate at ≤ 1024 px → Luna choice → card) and `SKILL.md` (the blocks, their limits, `snow.yaml` as the worked example, "write YAML only").
- [ ] **Step 4: Run; expect PASS**; full suite and typecheck.
- [ ] **Step 5: Commit** `Custom effect builds: candidates from a worker, previewed on the canvas view, chosen blind by Luna, kept by the artist`.

### Task 8: The panel — card, Auto-approve's Keep, setting with Reset

**Files:**
- Modify: `krita-mcp/krita-plugin/kritamcp/creative_docker.py:3376-3385` (a `kind == 'effect_build'` card beside `canvas_reference`, Remove effect after Keep), `krita-mcp/krita-plugin/kritamcp/auto_approve.py` (`effect_build` answerable; delay `max(delay, 20)`; answer `keep`), `krita-creative-agent/src/auto-approve.ts` (same kind), the settings panel (the `custom_effects` checkbox from the schema, plus a **Reset custom effects…** button with a confirmation, sending `{type: 'reset_effects'}`), `krita-creative-agent/src/studio.mjs` (`reset_effects` → `resetEffects`)
- Test: `krita-creative-agent/tests/ui_panel_custom_effects.py` (PyQt5 and PyQt6), `krita-creative-agent/tests/auto-approve.test.mjs`, and add the UI script to `agent/ci.sh`'s panel group

**Interfaces:**
- Consumes: Task 7 event and `answer`.

- [ ] **Step 1: Write the failing tests**: panel — the card shows Keep / Try again / Discard, then Remove effect after Keep; Auto-approve with delay 10 presses Keep at 20 s, with 30 at 30 s; Reset asks first and sends `reset_effects` only on yes. Companion — `effect_build is auto-approvable, canvas_reference still never`.
- [ ] **Step 2: Run** (`uv run -q --with pyqt5 python tests/ui_panel_custom_effects.py`, then pyqt6; `npm run test:unit`); expect FAIL.
- [ ] **Step 3: Implement** with `qt_compat`.
- [ ] **Step 4: Run; expect PASS** under both PyQt versions; then `bash agent/ci.sh` (no file edits while it runs).
- [ ] **Step 5: Commit** `Custom effects in the panel: the build card, Auto-approve keeps after at least 20 s, the setting with Reset`.

### Task 9: Live check (Toska, a copy of the Dostoevsky painting)

- [ ] Build, package, check (0 problems), install with no document open, one restart (agent/build-macos.sh, package-app.sh, install-app.sh).
- [ ] With Custom effects off: ask twice for "low fog over the field"; the chat shows the enable hint once; nothing else changes.
- [ ] On: `paint_effect` fog paints one layer "Effect: fog", faces clear, Undo removes it.
- [ ] `/new-effect light shafts through the clouds`: a card within 4 minutes; Keep; the next move uses it; Remove effect drops it; Reset empties the artist's folder only.
- [ ] Report exactly which of these ran, with the card image sent to the artist.

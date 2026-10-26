# Custom effects: the agent builds its own effect tools when painting fails

Status: design approved by the artist (2026-10-25: "sure"). Nothing is built yet. Experimental: off by default.

## Why

The artist (2026-10-25), after `paint_snow`: "how could the agent do it on its own"; "make it a plugin … so it can build
its own, it can also ask with a detailed customised prompt of one AI image texture generation if needed as a last
resort"; "it should be done if the paint is failing … like a Goldilocks rule: it shouldn't take too long to come to this
choice but it shouldn't do it each time"; "is it safe … I just don't want a sandbox environment but people shouldn't have
to wait … skills shouldn't be breakable"; "could we create a tool module though, and yaml for options … agents and yaml
are good for policy based rules"; "call these custom recipes … recipe or effects whatever" (named Custom effects: `paint_recipe`, a stroke generator, and each chat's `recipes/` folder already exist, recipe-tool.mjs).

`paint_snow` exists because a live test failed: asked for falling and settled snow on the Dostoevsky painting, the
painter typed about 20 dashes of one size and angle (they read as rain) and called it done after 12 strokes. Snow became
a method: thousands of flakes in depth layers, caps on found parts, faces kept clear, counted results. Every effect the
painter cannot type well (fog, rain, haze, sparks, dust in light, frost, light rays) needs the same treatment, and today
each one waits for a person to write it.

Harness² (google-research/harness2, "Recursive Agent Harnessing for an Open World") improves the harness around a fixed
model by proposing several edits, probing each on the same task, choosing blind among anonymized results, and keeping each
adopted result whole in a per-domain experience library with its cue, lesson and evidence. Custom effects are that loop at
the scale of one painting effect.

## The idea in one paragraph

An **effect recipe** (here simply "recipe") is a YAML file: an effect described as a short list of tested **building blocks** with values, the options
the painter may change (with limits), and when to use it. A TypeScript **recipe engine** checks every recipe against a
schema and turns each valid one into a Pi tool (`paint_effect` with `effect: fog`). When the painter fails at the same effect twice, Toska
starts a **recipe build**: the painter writes 2–3 candidate recipes, each is rendered on a small copy of the canvas, Luna
chooses blind, the artist sees the winner beside the canvas and keeps or discards it. Kept recipes go into the library and
are used directly next time. One AI image texture is the last resort. No new code is ever executed: agents and people only
write YAML.

## Goals

1. **Building blocks** (plugin, Python, numpy and OpenCV, no Qt, tested like `snow_raster.py`): a small fixed set, each
   painting onto the move's own layer, sized from the canvas, coloured from the scene's light, and never inside the
   keep-clear parts. Initial set (the builder may merge or split, but not widen beyond these effects):
   - `particles`: a field of soft dabs in 1–3 depth layers (count, size range per depth, blur, streak and wind, peak
     opacity, colour from the light or the local colour) — snow, rain, sparks, embers, dust;
   - `wash`: a soft gradient from a side or from a found part, with falloff, opacity and contrast lowering — fog, haze,
     mist, glow;
   - `noise`: large-to-fine soft noise inside an area, as opacity or tone — fog banks, cloud, grime, grain;
   - `caps`: material on the top edges of found parts, thickness from the part, soft shadow — settled snow, frost, rim
     light;
   - `rays`: soft beams from a point or a side through an area — light shafts;
   - `texture`: an image (the last-resort AI texture, or a bundled one) placed inside an area with a blend mode and
     opacity.
   Every block reports what it painted (counts, coverage per part) so a token result cannot pass as done.
2. **Recipe format** (YAML, TypeBox schema in strict TypeScript, `yaml` added as a pinned direct dependency): `name`,
   `cue` (when to reach for it), `lesson`, `evidence`, `layer` name, `keep_clear` (default faces and hair, as
   `paint_snow`), `options` (each with default, min, max, description), `blocks` (an ordered list of the blocks above).
   Values may be numbers or tiny arithmetic on the recipe's own options (`"0.5 * density"`), read by a small expression
   reader: numbers, option names, `+ - * /`, parentheses, `min`/`max`. No `eval`, no other names. Parts are named in words
   and found by Find it, as `paint_snow`'s `settle_on` and `keep_clear`.
3. **Recipe engine** (new strict TypeScript module): loads recipes from the bundled folder (`effects/` in the companion)
   and the artist's own folder (in Toska's data folder, never the painting's folder); rejects an invalid one with a message
   naming the file and the field. The painter gets **one** tool, `paint_effect { effect, options, area? }`, plus the
   list of effects (name and cue, one line each) in its tool help, the way `painting_tool_help` lists tools. So the
   prompt grows by one line per effect, not one tool, and an effect kept mid-chat is usable at once with no change to
   the session's tool set (the studio replaces the active tool set on each phase change, so Pi's `deferred` /
   `tool_search` / `registerTool` path would drop it; decided below). `options` are checked against the effect's own
   TypeBox schema built from its YAML; out-of-range values are clamped and said. A call runs the blocks in order in the
   plugin, as one reversible pass on one layer in the move's group ("Effect: fog"), so the move's Undo removes it.
4. **When a build starts** (policy in `effects/policy.yaml`, not in the model's judgment):
   - the same effect failed twice in a chat: the per-move Luna verdict says the request was not met, or the result counts
     show a token effort; or the artist asks again for an effect the painter called done (a redo counts as a failure).
     An Undo alone does not count (it is ambiguous). "The same effect" is matched by words between the requests (as
     `paint_snow` matches parts), and a library effect matches a request by the words of its cue;
   - never when a recipe whose cue matches already exists: that recipe is used;
   - never twice for the same effect in a chat after the artist discarded a candidate, unless asked;
   - at most one build at a time, with a time limit and a cost limit;
   - `/new-effect <effect>` starts one at once.
5. **A build** (the Harness² loop, small): an effect-building skill (instructions only) teaches the painter the blocks, the
   rules and `paint_snow` as the worked example. The painter writes 2–3 candidate recipes; each that passes the schema is
   rendered on a small copy of the canvas (never the painting); an invalid one gets one retry, then is dropped. Luna sees
   the candidates as A, B, C with the request and chooses one, and why. The winner's card sits beside the chat: the canvas
   and the canvas with the recipe, **Keep** / **Try again** / **Discard**; Auto-approve presses Keep after 20 seconds (see Decisions). Keep saves the
   recipe in the artist's folder with its cue, the lesson Luna gave, and the evidence (chat, date, the choice), registers
   it, and the move paints with it.
6. **Last resort**: when no candidate survives (all invalid, or Luna rejects all), one AI image texture is made through the
   image asset backend the Image assets setting names, with a detailed prompt built from the request, the scene's light
   and the area (e.g. "a bank of low fog, transparent background, soft falloff upwards, cool dawn light"), counted against
   the chat's AI image allowance; it becomes a recipe using the `texture` block, offered on the same card.
7. The artist can write or edit a recipe by hand (or ask Claude Code, Cursor or any editor to); it is picked up by the
   next chat and checked by the same schema.

## Settings, shipping and safety (the artist, 2026-10-25)

- **Settings › Custom effects (experimental)**: **Enable** (off by default) and **Reset** (deletes every effect in the
  artist's own folder after a confirmation; the bundled ones stay). The artist: "under settings … enable and reset as
  well, where users can remove all their custom recipes as it's experimental".
- **Off**: nothing of this feature runs (no `paint_effect`, no builds). When the same effect fails twice, the chat says
  once: "As a last resort, enable Custom effects in Settings." `paint_snow` stays the painter's snow tool.
- **Ships with fog and snow** ("it can ship with fog and snow"): bundled `fog.yaml` and `snow.yaml`; `snow.yaml`
  reproduces what `paint_snow` paints (falling and settled), which is also the engine's check.
- **What a recipe can do**: choose among the bundled blocks, set numbers inside limits the engine fixes (hard caps on
  counts, sizes, opacity and render time, so no recipe can stall the Mac), and name parts in words for Find it. It paints
  only its own new layer. It cannot read or write files, reach the network, run code, touch other layers or the saved
  painting, change settings or open documents.
- **Text in a recipe is data**: `cue` and `lesson` have length limits and reach the painter only as quoted descriptions
  ("this effect is for: …"), never as instructions, so a recipe copied from elsewhere cannot steer the painter beyond
  calling `paint_effect`.

## Decisions made for the builder (Claude's calls, 2026-10-25; the artist may overrule)

- **While a Keep card waits (the artist, 2026-10-25: "carry on unless you push a button"; "should be automatic after
  like 20 seconds … as long as the model's not waiting")**: nothing waits. The move that failed has ended; the build runs
  in the background while later moves paint; the card appears when the build is done.
  - Auto-approve **on** (any mode, Autopilot included): the card counts down 20 seconds, then Keep is pressed for the
    artist; the effect is marked `auto_kept` in its file. The card then stays with **Remove effect** (drops it from the
    library; Undo still removes its paint, which is a different thing).
  - Auto-approve **off**: the card waits for the artist's click; painting goes on meanwhile.
  - Custom effects **off**: no build; the one hint to enable it.
- **Name**: Custom effects, not recipes (the existing `paint_recipe` tool and per-chat `recipes/` folder would confuse
  the painter and collide on disk). The artist: "recipe or effects whatever".
- **One dispatcher tool** (`paint_effect`) and a host-side catalogue, not one Pi tool per effect (see goal 3).
- **Candidates render in pure numpy**: the blocks are "canvas array and masks in, layer pixels and a report out", run on
  the canvas view downscaled (at most 1024 px on its long side), with no Krita document opened; the same block code then
  paints the kept effect at full size through the layer-pass path `paint_snow` uses. So a build never opens or touches a
  document and can run while the artist looks at the canvas.
- **Budget per build**: at most 3 candidates, one retry each for an invalid one, one Luna choice, 4 minutes; written in
  `policy.yaml`. The candidates are written in a separate worker session (the preparation-worker pattern), so the move's
  own conversation is not filled with YAML.
- **AI images off** (the default allowance is 0): the last resort is not run; the card says no effect was found and that
  turning on AI images in the chat's limits allows one texture try.

## Non-goals

- No agent-written code is ever run: no scripts, no sandbox, no plugins written at run time.
- No new building blocks at run time: a block is plugin code, written and tested like any other.
- `paint_snow` is unchanged and stays the snow tool while Custom effects is off; the bundled `snow.yaml` reproduces it.
- No recipe sharing between artists or a recipe store.
- No change to how normal moves paint when nothing fails.

## Anti-goals (failure even if it technically works)

- A build on the first miss, or on every move: the artist waits for nothing.
- A recipe that paints over faces, or onto the painting outside its layer.
- A recipe or YAML file that can crash Toska or stop a chat: a bad recipe is rejected with a message and skipped.
- The painter's prompt growing with every kept recipe.

## Done when

On the Dostoevsky painting the artist asks twice for "low fog over the field"; the second failure starts a build; within
a few minutes a card shows the canvas and the canvas with fog; Keep saves `fog.yaml` (the artist's effects folder) and the move paints it on its own
layer with the faces clear. In the next chat, "fog over the river" calls `paint_effect` with `effect: fog` directly with no build. A hand-written
recipe with a typo is reported by file and field and skipped, and the chat goes on.

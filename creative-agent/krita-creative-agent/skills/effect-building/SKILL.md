---
name: effect-building
description: How Toska's effect builder writes a custom effect recipe in YAML from the six tested blocks (particles, wash, noise, rays, caps, texture), their parameters and limits. Read by the effect build's worker only; the painter uses effects through paint_effect.
disable-model-invocation: true
---

# Building a custom effect

A custom effect is a **YAML recipe**, never code. It names tested blocks the plugin paints on the effect's own new layer,
sized from the canvas and coloured from the scene's light. Write YAML only: no code fences, no prose, no scripts.

## The recipe

```
name: <the name you are given>             # lowercase letters, digits, hyphens
cue: <when to use it, at most 160 characters>
lesson: <what makes the effect read, at most 300 characters>
layer: "Effect: <name>"                    # optional
keep_clear: [faces, hair]                  # optional; this is the default. Keep faces clear.
options:                                   # optional, at most 16: numbers the painter may change
  density: { default: 1, min: 0.3, max: 2, describe: How thick it is. }
blocks:                                    # 1 to 8, painted in order, each over the last
  - { block: wash, from: bottom, opacity: 0.5 * density }
```

A number may be a number or arithmetic on the recipe's own options: numbers, option names, `+ - * /`, parentheses,
`min(a, b)` and `max(a, b)`. Nothing else (no other names, no functions, no text).

## The blocks

Every block also takes `opacity` (0 to 1) and `within`: a part name in words (`the river`) that confines it; nothing
outside that part is painted. Parts are found on the canvas by Find it, so name them as they look.

- `particles`: soft dabs in depth layers, far small and dim, near few and large — snow, rain, sparks, embers, dust.
  `layers` 2 or 3 (3), `density` above 0 (1), `count` (total, overrides density; at most 60 000), `wind_deg` (0: straight
  down; positive drifts right), `streak` 0 or more (1: elongation along the wind times this; rain wants 4 to 10),
  `colour` `light` (the scene's light) or `local` (the picture's colour there), `opacity` (1).
- `wash`: a soft gradient from a side — fog, haze, mist, glow. `from` top | bottom | left | right (bottom), `falloff`
  0 to 1 (0.6: the share of the canvas it fades over), `lower_contrast` 0 to 1 (0: how far what it covers flattens toward
  the picture's mean tone), `opacity` (0.5).
- `noise`: large-to-fine soft noise — fog banks, cloud, grime, grain. `scale` small | medium | large (medium), `band`
  `{ from: top|bottom|left|right, share: 0 to 1 }` (only inside that strip, its inner edge softened), `opacity` (0.5).
- `rays`: soft beams — light shafts. `from_point` `[x, y]` as 0 to 1 shares of the canvas (default: where the scene's
  light is) or `from` a side, `count` (8, at most 64), `spread_deg` (40), `opacity` (0.5).
- `caps`: material on the top edges of a part — settled snow, frost, rim light. `part` (a part name, required),
  `thickness` (1: multiplies the cap's thickness), `opacity` (1). `part: settle_on` is a placeholder the painter fills
  with the parts it names; without them the block is dropped.
- `texture`: an image laid over a part. Do not use it: the builder supplies a texture itself only as a last resort.

## Limits the engine holds whatever a recipe says

60 000 particles per call, 3 depth layers, opacity 1, 8 blocks, 30 seconds on a 6000 x 4500 canvas. A value beyond is
clamped and said. A recipe that does not check (an unknown block or key, a value that is not a number, unbalanced
arithmetic) is refused with the field named; fix exactly that field.

## Good candidates

- Paint the effect as the request describes it, where it describes it (`within`, `band`, a wash from the right side).
- Keep faces and hair clear (the default `keep_clear`); never cover the figures.
- Make the candidates differ: other blocks, or clearly other amounts, so one can be chosen by looking.
- An effect should be visible over the whole area it covers, not a few marks.
- `snow.yaml` (particles in depth, then caps on named parts) and `fog.yaml` (a wash from the bottom, then noise in a
  band) are the worked examples you are given.

## Why

On 2026-10-18 the clouds test on New Moscow (6000×4500) shows the painter's two ways to add soft volume, and both fall short:
- **Strokes** (`paint_batch`, `paint_pass`): Luna undid 2 of 2 batches for texture over forms. Generic brushes do not carry
  the painting's own texture.
- **Reference transfer** (`paint_from_reference` from a relit asset): it looked right, but planned 156,304 strokes and
  painted for ten minutes, with a checkpoint save every chunk.

Krita can turn an area of the painting into a brush tip ("Stamp" and "Clipboard" in the brush editor's Custom Brush
dialog), but only by hand. Krita 5.3.3's scripting API can list presets, read and edit their XML, and pick one. It
cannot create or import a brush tip, and a tip file written into the resources folder is only seen after a restart.

A throwaway spike stamped tips cut from the painting's own clouds with Qt's `QPainter`, onto the sky only: 523 dabs in
0.6 s. The clouds looked fuller and softer, and the buildings, towers and moon were untouched (scratchpad,
`stamp_spike.py`).

## What Changes

- **Materials:** the painter makes a material from any source:
  - an area of the painting;
  - an agent or artist layer (read only);
  - an attached reference or an asset from `make_asset`.

  A material is a small set of greyscale tips (at most 8), saved with the chat and shown to the painter as one sheet
  image. A tip is never cut from inside a protected area.
- **Stamping:** `stamp_material` stamps a material's tips into an area (a saved selection or selection steps) on one
  new agent layer, as one reversible pass:
  - dab count, size range, opacity range, rotation jitter and a seed;
  - colour taken from the canvas under each dab, shifted toward an optional tint (moonlight on cloud tops).

  Protection, Luna move review and the painting-weight monitor apply as to any pass.
- **A TypeScript Pi extension, `extensions/material-stamp.ts`,** registers both tools and plans the dabs. The plugin
  does the pixel work: it cuts tips, samples colour and stamps with `QPainter`.

## Capabilities

### New Capabilities
- `material-stamp`: making materials from any source, and stamping them into an area as one reversible pass.

## Impact

- Plugin: `material_stamp.py`, with the native operations `make_material` and `stamp`.
- Companion: `extensions/material-stamp.ts` (tools, dab planning, the native port), registered inline. Skill text in
  `paint-sky` and `repaint-area`.
- No Krita resources are written, and no restart is needed. A material lives with its chat, like an asset.

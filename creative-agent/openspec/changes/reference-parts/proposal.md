## Why

The agent works best on one thing at a time, and an artist often wants it to follow only part of a reference: the
sky of New Moscow, not its towers, river and car. Today the only way to say so is in words, and the painter then picks
a **rectangle** of the reference. A sky is not a rectangle: it wraps around the Stalinist tower, the Kremlin spires and
the skyscrapers, so any rectangle that holds the sky also holds the tops of the buildings, and the agent paints them.

The transfer tool already skips transparent pixels. A reference that is see-through everywhere except the sky makes
the agent paint only the sky, in place, around the buildings. What is missing is a way for the artist to cut that part
out, with Krita's own selection tools.

## What Changes

- **Two actions on a reference**, in the preview that already opens when its thumbnail is clicked:
  **Select a part in Krita…** and **Crop in Krita…**.
- **The reference opens in Krita as a temporary document**, so the artist selects with Krita's real tools: similar
  colour select (magic wand), magnetic lasso, freehand lasso, rectangle, and their add/subtract modes. The painting is
  never touched.
- **The panel shows "Use this part" and "Cancel"** while the temporary document is open.
- **Select a part** saves a new reference the size of the original, see-through outside the selection (soft selection
  edges stay soft). **Crop** saves only the selection's bounding rectangle, for a close-up detail.
- **The part becomes its own reference** beside the original, named by the artist (for example "Sky"), and the painter
  is told it is a part of the original and where it sits. The original stays attached.

## Capabilities

- Reference parts: the artist makes a part or a crop of an attached reference with Krita's selection tools; the agent
  paints from it like any reference, and only where it is opaque.

## Impact

- `krita-mcp/krita-plugin/kritamcp/creative_docker.py`: the two actions in `ReferencePreview`, the selecting state with
  Use this part and Cancel, opening and closing the temporary document, saving the part. **Needs a Krita restart.**
- `krita-creative-agent/src/studio.mjs`: references carry `part_of` and `bounds`; the painter's reference context and
  guidance describe a part.
- No change to the transfer tools: transparency is already skipped, and a part has its original's proportions.

## Why

The agent uses Krita like a raw hammer. On the New Moscow sky it measured the skyline by eye with six zoomed looks,
traced a feathered polygon, and laid the base as 560-px airbrush strokes, when Krita can select the sky from one point
and fill a live gradient in one call. Two things are tangled:

1. **Missing tools.** Some Krita features the agent cannot reach at all (clone layers, splitting a painting by colour,
   colour to alpha, Krita's own menu actions).
2. **Wrong choice.** Several features it already has go unused: fill layers (live gradients), non-destructive filter
   masks, the new seed (magic wand) selection. Strokes feel safe, so it reaches for them first.

The artist wants an agent that works inside Krita the way a skilled Krita user does: the right feature for the job,
strokes only for marks.

## What Changes

- **Clone layers**: a live copy of any layer that follows the original, for repeated motifs and reflections.
- **Split by colour**: the painting (or one layer) split into its main colour regions, each saved as a named
  selection, or as its own layer on request.
- **Colour to alpha**: lift a colour out of a layer (paper white under line art, black under a glow).
- **Krita actions by name**: a vetted list of Krita's own menu commands the agent can run on its layers, each checked
  on the installed Krita to need no dialog.
- **Choosing the right tool**: the painter prompt is reorganised into named sections with a tool-choice guide and
  worked examples; the agent names the Krita method before each move; repeated looks without painting get a nudge;
  a scored test set checks which tools the agent picks.

Every new tool runs through the same path as today's: one reversible pass with Keep / Undo, protected areas enforced,
recorded in the move journal.

## Capabilities

### New Capabilities
- `krita-native-tools`: clone layers, split by colour, colour to alpha, vetted Krita actions, and tool choice.

## Impact

- Plugin: new operations in `creative_tools.py` (clone, split, actions) and pixel work beside `region_craft.py`;
  protection covers them.
- Companion: new tool schemas in `tools.mjs`, the prompt in `prompt.mjs` reorganised, a look-without-painting nudge
  in `studio.mjs`, a tool-choice benchmark script.
- Panel: move cards name the new tools. One Krita restart for the batch.

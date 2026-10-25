# Snow: a real snow method (paint_snow)

Status: APPROVED by the artist (2026-10-25): "a real snow method".

## Why

Live test, 2026-10-25, the Dostoevsky mock execution (6000 x 4500, impasto oil style, a warm sunset). Asked to "add
falling snow over the whole scene, and fresh snow settled on the shoulders, hats, the posts and the rooftops", the
painter typed about 20 sparse dashes of one size and one angle with paint_pass. They read as rain or scratches, not
snow. No snow settled on any form (shoulders, hats, posts, roofs all bare), one flake landed by the main figure's nose,
and the painter called the request done after 12 strokes. Evidence (the session's scratchpad, read only):
`dostoevsky/06-final-snow.jpg`, `crop-main-face.jpg`, `crop-posts-ground.jpg`, `crop-soldiers-officer.jpg`.

Snow is a method, not a few typed strokes: a painter's snowfall is thousands of soft dabs at several depths in the
scene's own light, and snow lies on the tops of things. Typed strokes cannot do either at 27 MP, and the painter has no
measure that tells it 20 dashes are a token effort.

## Goals

1. **Falling snow.** Many flakes (thousands at 6000 x 4500) in 2-3 depth layers: far small, dense, soft and dimmer;
   mid; near a few large blurred discs (bokeh-like). Each a soft dab (an ellipse, a smaller brighter dab inside the
   larger ones, blurred), never a pixel dot, with a slight motion streak along a wind angle, each flake's angle
   jittered. Sizes follow the canvas's long side and counts its proportions (the same look at any resolution); density
   multiplies the counts. Alpha low enough that it reads as snowfall, not noise.
2. **The scene's light.** The flakes' white is the scene's light (its brightest pixels) as a warm or cool white (a
   sunset gives warm-white flakes), mixed with the local colour more for the far layer.
3. **Faces stay clear.** keep_clear shapes (faces by default when people are in the scene; any part the painter names)
   get no snow inside and a feathered fall-off around them.
4. **Settled snow.** For each part the painter names (hats, shoulders, posts, roofs), its Find it area; on the mask's
   upward edges (the smoothed outward normal pointing up: a gentle slope holds some, a steep side none, the bottom
   never) a cap rising above the edge and sinking a little into the form, a few px to tens of px thick (from each
   piece's width, capped by the canvas), irregular and soft, patchy along long edges, slightly overhanging, shaded by
   the light, with a soft shadow under it.
5. **One reversible pass per kind.** One layer per call ("Snow: falling", "Snow: settled on <parts>") in the move's
   group, through the creative operation journal like the other crafts: validated before anything changes, protected
   areas kept, the move's Undo removes it, goal likeness never undoes it (weather the goal image does not have).
6. **A result the painter cannot pass off.** paint_snow reports flakes per depth layer and caps per part (and what Find
   it could not find), and its description says one call is the whole snowfall: never typed flakes.
7. **Plannable.** painting_tool_help's catalogue lists paint_snow with a rough time; a plan step "Add: snow" (built
   apart, branch agent/single-plans) can name the tool.

## Non-goals

- Snow on the ground as a texture or a snow-covered field (the underpainting and the architecture texture's snow
  materials do that); drifts, footprints, melting.
- Rain, fog, sleet or other weather (a later change can reuse the depth-layer mechanism).
- Animated snow; physically simulated accumulation; snow on surfaces Find it cannot outline.
- A new brush preset: the flakes are baked pixels on a layer, so the pass is one undo step and does not depend on a
  preset's dab.

## Done when

- The plugin's `snow` operation and paint_snow exist, with tests on synthetic canvases: flake counts and size spread
  across layers, mean alpha bounds, nothing inside keep_clear beyond the feather, caps only on upward edges of a hat
  and a post (none on sides or bottom), thickness scaling with the shape, colour following a warm or cool scene, Undo
  removing the layer, and the time on a 6000 x 4500 canvas reported.
- A preview on a copy of the Dostoevsky final shows snowfall with depth and caps on hats, posts and roofs, faces clear.
- Live in Toska on the Dostoevsky scene: one paint_snow call (settle_on hats, shoulders, posts, rooftops) gives
  snowfall that reads as snow at the preview size and at full size, caps where the parts were found, no flake on a
  face, and the move's Undo removes both layers.

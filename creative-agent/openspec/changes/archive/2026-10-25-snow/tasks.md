## 1. Pixels (plugin)

- [x] 1.1 `snow_raster.py` (numpy and OpenCV, no Qt): `plan_flakes` (2-3 depth layers, counts from the canvas's
      proportions times density, radii from its long side, never below MIN_RADIUS, angles from the wind jittered, a
      gentle clumping field), `render_layer` (soft streaked ellipses with an inner dab, drawn reduced for soft layers,
      blurred), `falling` (the layers composited far to near in bands, the light's white mixed with the local colour,
      keep_clear zeroed inside and feathered around, flakes taken off counted).
- [x] 1.2 `scene_light` (the brightest pixels' colour and where they are), `snow_white` (TINT of the way to it).
- [x] 1.3 `settled`: top edges of the mask whose smoothed outward normal points up, thickness per connected piece from its
      width (CAP_SHARE, at most CAP_MAX_SHARE of the long side, times thickness), lumpy and patchy along long edges, a
      slight overhang, soft edges, shaded over the form and by the light's side, a soft shadow under it on the form.

## 2. The operation (plugin)

- [x] 2.1 `snow_craft.py`: operation `snow` {name, mode falling|settled, density, wind_deg, layers, seed, keep_clear
      [shapes], settle_on [{name, inside_shape}], thickness}; every value and shape file checked before anything
      changes (shapes only from the chat folder's .shapes, shape_mask.read_shape).
- [x] 2.2 One paint layer per call in the move's group, the canvas read once before anything is written, written only in
      the squares that hold snow (parts merged over each other), a reversible pass of the operation journal.
- [x] 2.3 Dispatch in `creative_tools.py` (validate, apply, new contribution, pass title).

## 3. The tool (companion)

- [x] 3.1 `src/snow-tool.ts` (strict TypeScript): paint_snow {mode falling|settled|both, density, wind_deg, depth_layers,
      settle_on [names], keep_clear [names] (default faces), thickness thin|normal|thick}; names found through the
      studio's proposeArea (Find it, quietly); settled first, then falling, each its own pass; a part not found is reported
      and never guessed; settled with nothing found paints nothing.
- [x] 3.2 The result: flakes per depth and total, caps and thickness per part, what was kept clear or not found, and a note
      that one call is the whole snowfall (Undo and call again to change it).
- [x] 3.3 Registered in `tools.mjs`; offered in Agent painting and paced (`studio.mjs`); `snow` journalled and long in
      `craft.mjs`, mutating in `bridge.mjs`; goal likeness exemption `effect`.
- [x] 3.4 painting_tool_help's catalogue: paint_snow with a rough time on this canvas (`MEASURED_TOOLS`).

## 4. Tests

- [x] 4.1 `tests/test_snow_raster.py`: counts and size spread across layers, wind, mean alpha bounds, nothing on a face,
      warm and cool light, caps on a post's top and a hat's crown and brim only, a shoulder slope yes and a steep side
      no, thickness with the shape and `amount`, timing at 6000 x 4500 (falling about 2 s, a 2500 x 1500 roof about
      1.1 s offline).
- [x] 4.2 `tests/test_snow_craft.py`: one layer in the move's group, faces clear, the move's Undo removes it; settled on
      two parts in one layer, nothing down the sides; every wrong call refused before anything changes.
- [x] 4.3 `tests/snow-tool.test.mjs`: faces by default, both modes in order with their own ids, a part not found reported,
      nothing painted when nothing is found, keep_clear [], the catalogue entry, the goal-likeness exemption.
- [x] 4.4 Preview on a copy of the Dostoevsky final with hand-made masks (refined by GrabCut) for hats, posts,
      shoulders and roofs; before and after saved for the artist.

## 5. Live (after build and install, by the artist's leave)

- [ ] 5.1 The Dostoevsky scene in Toska: paint_snow with settle_on hats, shoulders, posts, rooftops; check the snowfall at
      the preview size and at full size, the caps where Find it found the parts, no flake on any face, and the move's Undo.
- [ ] 5.2 Time it on the 6000 x 4500 canvas (the canvas read, the layer writes and Find it per part) and update
      `MEASURED_TOOLS`.

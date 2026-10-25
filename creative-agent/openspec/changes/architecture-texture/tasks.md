## 1. Texture library (companion)

- [x] 1.1 Catalogue `src/texture-catalogue.json`: the 50 CC0 materials (40 ambientCG 1K-JPG zips: the 20 approved, the 20 the artist
      added, 3 Moscow City facades; 7 Poly Haven maps fetched one by one), each with material, tags, the part kinds it suits, metres
      per tile (estimated), download URL, the zip's sha256 and bytes, and each kept map's name, bytes and sha256. No image is
      committed.
- [x] 1.2 `src/texture-library.ts`: the catalogue read and checked; a material's pinned download (the zip, checksum-verified,
      only Color, Displacement and AmbientOcclusion kept) through `shapes/model.ts downloadModel` into the companion's data
      folder (`textures/<id>/1K-JPG`, as goal-sharpen keeps its model under the data folder); a test-only library folder.
- [x] 1.3 Part kinds: an architectural part (buildings, church, towers, domes, bridge, street, railing, walls, roofs, ledges)
      from its name; sky, water, people, vehicles, trees never; snow only on street, railing, roofs and ledges.

## 2. The planner's typed choice (companion)

- [x] 2.1 `src/texture-choice.ts`: the request to the planner model (default Qwen3 VL) with the canvas view, each part's
      bounds and folder note and the materials allowed for it; its reply read as JSON and checked against a TypeBox schema.
- [x] 2.2 The host validates and clamps: materials only from the part's allowed list (at most 2), tile size near/far in
      canvas px, direction, vanishing point, strength 0.10-0.30, blend overlay or soft light; a default from the part's kind
      when the model is missing, fails or answers nothing usable.

## 3. The pixel operation (plugin)

- [x] 3.1 `texture_raster.py` (numpy only): each material's detail (high-pass luminance of colour, displacement and AO, unit
      spread, a mip chain); a one-point perspective map from tile size near/far, direction and vanishing point; texture bombing
      (random offsets per cell, whole courses for regular patterns) so no tile repeats visibly; the part's mask feathered inside its edge; the detail
      applied to the painting's luminance only (Overlay or Soft Light at the strength), so hue and chroma never change.
- [x] 3.2 `texture_craft.py`: operation `texture`, validated before anything changes; one paint layer "Texture: <part>" in the
      move's group, written only in squares that hold detail; a reversible pass (the move's Undo / Redo removes it).
- [x] 3.3 Dispatch in `creative_tools.py`; Python tests under PyQt5 and PyQt6.

## 4. The Pi extension (companion)

- [x] 4.1 `extensions/architecture-texture.ts`: the tool `texture_architecture`, its how-to in the description.
- [x] 4.2 Mandatory: after refine_to_goal in an architectural refine step the host runs the texture pass itself; finish_move is
      blocked while an architectural refine step's move has no texture pass; non-architectural parts are never textured.
- [x] 4.3 Studio wiring: the TextureHost (step parts and their found areas, the planner call, the library, the native call),
      the extension registered, the tool offered in Agent and Autopilot, Met refused for an architectural refine move without
      its texture pass.

## 6. Textured brushes (goal 6)

- [x] 6.1 `texture_patterns.py`: a material's detail as a height map, registered through the fork's Krita.createPattern as
      "Texture: <id>" (once a session), by the texture pass and the `register_patterns` operation.
- [x] 6.2 Finish `grain`: in an architectural refine step the form strokes carry their part's pattern (alpha thinned where the
      pattern is low, strength 0.3, inside the part only); refine_to_goal passes it; one material decision serves both passes.
- [x] 6.3 `set_brush_texture` registers its file itself on our Krita (no manual import); stock still asks for the import.

## 7. Materials in the plan (goal 7)

- [x] 7.1 `plan-materials.ts`: per aspect (walls, roofs, windows, ground, trim) a catalogue id or name, scale and recedes
      hints; unknown ids dropped and reported; kept through propose_plan, the panel edit and PLAN.md.
- [x] 7.2 FOLDER_PLAN asks for them; painting_tool_help name "materials" lists the library.
- [x] 7.3 The plan dialog shows and edits them in plain words (PyQt5 and PyQt6).
- [x] 7.4 The texture pass and the grain use the planned materials; the model is asked only for parts they leave out.

## 8. Goal brushwork patterns (goal 8)

- [ ] 8.1 Next round: patterns cut from the goal per part (high-passed, seamless), "Goal brushwork: <part>".

## 5. Checks

- [x] 5.1 Companion unit suite and typecheck; plugin suite through agent/ci.sh --no-cpp.
- [ ] 5.2 Live in Toska (not done here): a copy of New Moscow, time per part at 6000 x 4500, no visible tiling, no colour shift,
      sky, river, people and car untouched.

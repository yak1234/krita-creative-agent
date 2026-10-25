## 1. Texture library (companion)

- [ ] 1.1 Catalogue `src/texture-catalogue.json`: the 40 CC0 ambientCG 1K-JPG materials (the 20 approved plus the 20 the artist
      added: dome metals, fish-scale roofs, church stone, snow, planks), each with material, tags, the part kinds it suits, metres
      per tile (estimated), download URL, the zip's sha256 and bytes, and each kept map's name, bytes and sha256. No image is
      committed.
- [ ] 1.2 `src/texture-library.ts`: the catalogue read and checked; a material's pinned download (the zip, checksum-verified,
      only Color, Displacement and AmbientOcclusion kept) through `shapes/model.ts downloadModel` into the companion's data
      folder (`textures/<id>/1K-JPG`, as goal-sharpen keeps its model under the data folder); a test-only library folder.
- [ ] 1.3 Part kinds: an architectural part (buildings, church, towers, domes, bridge, street, railing, walls, roofs, ledges)
      from its name; sky, water, people, vehicles, trees never; snow only on street, railing, roofs and ledges.

## 2. The planner's typed choice (companion)

- [ ] 2.1 `src/texture-choice.ts`: the request to the planner model (default Qwen3 VL) with the canvas view, each part's
      bounds and folder note and the materials allowed for it; its reply read as JSON and checked against a TypeBox schema.
- [ ] 2.2 The host validates and clamps: materials only from the part's allowed list (at most 2), tile size near/far in
      canvas px, direction, vanishing point, strength 0.10-0.30, blend overlay or soft light; a default from the part's kind
      when the model is missing, fails or answers nothing usable.

## 3. The pixel operation (plugin)

- [ ] 3.1 `texture_raster.py` (numpy only): each material's detail (high-pass luminance of colour, displacement and AO, unit
      spread, a mip chain); a one-point perspective map from tile size near/far, direction and vanishing point; two shifted
      samplings mixed by low-frequency noise so no tile repeats visibly; the part's mask feathered inside its edge; the detail
      applied to the painting's luminance only (Overlay or Soft Light at the strength), so hue and chroma never change.
- [ ] 3.2 `texture_craft.py`: operation `texture`, validated before anything changes; one paint layer "Texture: <part>" in the
      move's group, written only in squares that hold detail; a reversible pass (the move's Undo / Redo removes it).
- [ ] 3.3 Dispatch in `creative_tools.py`; Python tests under PyQt5 and PyQt6.

## 4. The Pi extension (companion)

- [ ] 4.1 `extensions/architecture-texture.ts`: the tool `texture_architecture`, its how-to in the description.
- [ ] 4.2 Mandatory: after refine_to_goal in an architectural refine step the host runs the texture pass itself; finish_move is
      blocked while an architectural refine step's move has no texture pass; non-architectural parts are never textured.
- [ ] 4.3 Studio wiring: the TextureHost (step parts and their found areas, the planner call, the library, the native call),
      the extension registered, the tool offered in Agent and Autopilot, Met refused for an architectural refine move without
      its texture pass.

## 5. Checks

- [ ] 5.1 Companion unit suite and typecheck; plugin suite through agent/ci.sh --no-cpp.
- [ ] 5.2 Live in Toska (not done here): a copy of New Moscow, time per part at 6000 x 4500, no visible tiling, no colour shift,
      sky, river, people and car untouched.

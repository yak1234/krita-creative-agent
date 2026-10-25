# Architecture texture: subtle photobash detail for stone, cobblestones and weathering

Status: APPROVED by the artist (2026-10-25): subtle photobashing for architectural details; "i don't know how to
create textures"; "make it an agent skill, don't make it optional for architectural structures"; "shouldn't we have
our qwen vl do that"; "pi agent plugin why not". 2026-10-25: "why not make it an agent pi plugin, not an agent skill"; "build the
photobashing, download the materials now".

## Why

After Finish and Refine, painted architecture on New Moscow reads smooth at full size: stone grain, cobblestones and
weathering are hard to paint stroke by stroke. Painters add them as subtle photo texture. The Krita Photobash Images
plugin (veryprofessionaldodo, GPL-3, 2023) only browses a folder and pastes a photo through the clipboard as a plain
layer (no blend, mask, perspective or colour handling); it is not used, only its idea of searching a texture folder.

## Goals

1. **Texture library.** 50 CC0 ambientCG materials (1K-JPG sets; chosen 2026-10-25): paving/cobble PavingStones046,
   138, 150; brick Bricks085, 094, 097, 105; cut stone Tiles130, 143; rough stone Rock051, 063; plaster Plaster001,
   PaintedPlaster006, Concrete034; roofs RoofingTiles006, 013A; rust/streaks Metal021, 053B; wood PaintedWood005;
   street Asphalt031. More at the artist's request ("can we get more textures"): domes Metal047B, 048C, 035,
   PaintedMetal004, Metal027; slate fish-scale RoofingTiles001, 002, old clay 014B; stone Bricks083, 008, Concrete012,
   Tiles144, Granite005A, Rock020; snow on street, railing, roofs and ledges Snow013, 012, 010A, 006; wet asphalt
   Asphalt025C; planks Planks037A. Chosen by reading the goal (2026-10-25): Moscow City night glass and window grids
   Facade001, 009, 013 (ambientCG); from Poly Haven (CC0, per-map 1K files, md5 then sha256 pinned) the Kremlin's old
   red brick castle_brick_02_red, green tower roofs green_metal_rust, the Stalinist high-rise's stone
   large_sandstone_blocks and old_sandstone_02, the embankment and railing posts granite_wall and granite_tile_03,
   snowy slate roofs grey_roof_tiles_02 (50 in all). A committed catalogue holds each one's material, tags, metres per tile, URL and zip sha256; the
   zips are downloaded once on first use, checksum-verified (like the sharpening model) and only the Color,
   Displacement and AmbientOcclusion maps are kept. Nothing is committed but the catalogue. The artist creates nothing.
2. **The decision model chooses, the host applies.** For each architectural part (folder notes help), the planner model
   (default Qwen3 VL) answers in a typed result: material(s) from the catalogue, scale near/far in canvas px, direction
   (courses, rows, perspective vanishing direction), strength. The host validates and clamps it.
3. **Detail only, never colour.** The texture's high-pass detail (luminance) is blended over the painting's own colours
   (Overlay/Soft Light at 10-30%), warped to the part's perspective, confined to the part's found area with a soft edge,
   baked into one layer named "Texture: <part>" in the step's group (layer plan).
4. **Mandatory for architecture.** A refine step whose parts are architecture (buildings, church, towers, bridge, street,
   railing, walls, roofs) runs the texture pass after its refine; sky, water, people, vehicles, trees never do. Redo
   undoes it with the step.
5. **A Pi extension, not a skill.** The decision, the tool and its how-to (in the tool's description) live in a Pi
   extension (like extensions/goal-likeness.ts and luna-review.ts). Its hook makes it mandatory: an architectural refine
   step cannot be met until its texture pass ran. The pixel work is a plugin operation (Krita side).

6. **Textured brushes (Krita patterns).** Approved by the artist 2026-10-25 ("yes please"). On first use the
   extension registers the library's maps as Toska patterns itself (no manual Manage Resources import). When Finish
   or Refine paints form strokes on an architectural part, the brush carries that part's chosen material as its
   Texture/Pattern at low strength, so the grain lives inside the paint strokes (fits the impasto goal). Pattern fill
   layers are not used for structure (they tile flat, no perspective); the warped overlay of goal 3 keeps doing
   windows, courses and scales. Buildings only, like the rest. The old manual `set_brush_texture` becomes a thin
   wrapper over the same registration.

7. **Materials are chosen in the plan.** The artist, 2026-10-25: "make that part of the planning prompt, qwen 3vl
   picks the krita patterns for each aspect". While planning, the planner model (Qwen3 VL by default) already views each
   part's image; for each architectural "Refine: <group>" step it writes `materials`: per aspect (walls, roofs/domes,
   windows, ground, trim) a catalogue id, plus scale and direction hints. The plan card shows them in plain words
   ("walls: old red brick; tower roofs: green painted metal") and the artist can edit them before Start, as the rest
   of the plan. The texture pass and the textured brushes use the planned materials; only a step without them (an
   older plan, a step added later) asks the model at paint time. Ids are validated against the catalogue; unknown ones
   are dropped and reported.

## Non-goals

- No photo pasted as a visible layer; no AI image generation.
- No texture on non-architectural parts.

## Done when

Live in Toska on a copy of New Moscow: the facades, church, towers, bridge, street and railing gain subtle stone,
cobble and weathering detail at full size without colour shifts or visible tiling; the sky, river, people and car are
untouched; layers stay one per part; time per part measured.

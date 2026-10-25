# Architecture texture: subtle photobash detail for stone, cobblestones and weathering

Status: APPROVED by the artist (2026-10-25): subtle photobashing for architectural details; "i don't know how to
create textures"; "make it an agent skill, don't make it optional for architectural structures"; "shouldn't we have
our qwen vl do that"; "pi agent plugin why not". Starts after layer-plan lands.

## Why

After Finish and Refine, painted architecture on New Moscow reads smooth at full size: stone grain, cobblestones and
weathering are hard to paint stroke by stroke. Painters add them as subtle photo texture. The Krita Photobash Images
plugin (veryprofessionaldodo, GPL-3, 2023) only browses a folder and pastes a photo through the clipboard as a plain
layer (no blend, mask, perspective or colour handling); it is not used, only its idea of searching a texture folder.

## Goals

1. **Bundled texture library.** About 20 CC0 textures (ambientCG / Poly Haven: cobblestone, worn paving, brick, cut
   stone blocks, rough stone, plaster, roof tiles, weathering and grime, rain streaks, moss, wood), downloaded once on
   first use, checksum-pinned (like the sharpening model), each with a short catalogue entry (material, tags, metres
   per texture tile). The artist creates nothing.
2. **The decision model chooses, the host applies.** For each architectural part (folder notes help), the planner model
   (default Qwen3 VL) answers in a typed result: material(s) from the catalogue, scale near/far in canvas px, direction
   (courses, rows, perspective vanishing direction), strength. The host validates and clamps it.
3. **Detail only, never colour.** The texture's high-pass detail (luminance) is blended over the painting's own colours
   (Overlay/Soft Light at 10-30%), warped to the part's perspective, confined to the part's found area with a soft edge,
   baked into one layer named "Texture: <part>" in the step's group (layer plan).
4. **Mandatory for architecture.** A refine step whose parts are architecture (buildings, church, towers, bridge, street,
   railing, walls, roofs) runs the texture pass after its refine; sky, water, people, vehicles, trees never do. Redo
   undoes it with the step.
5. **A Pi extension plus a skill.** The decision and the tool live in a Pi extension (like extensions/goal-likeness.ts
   and luna-review.ts) with an agent skill "texture architecture"; the pixel work is a plugin operation (Krita side).

## Non-goals

- No photo pasted as a visible layer; no AI image generation.
- No texture on non-architectural parts.

## Done when

Live in Toska on a copy of New Moscow: the facades, church, towers, bridge, street and railing gain subtle stone,
cobble and weathering detail at full size without colour shifts or visible tiling; the sky, river, people and car are
untouched; layers stay one per part; time per part measured.

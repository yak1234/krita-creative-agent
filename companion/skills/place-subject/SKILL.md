---
name: place-subject
description: Add one subject to a painting (a tree, figure, animal, lamp post, car, building) at the right place, size and lighting, standing on its ground with a contact shadow. Use when the artist asks to add or replace an object or character.
---

# Place a subject

Tool details are in the `image-asset` skill.

1. **Look and decide** (`observe_canvas`): where it stands, the ground line, its height in the scene
   (perspective: smaller further away), and where the light comes from. Write the target [x,y,w,h] so its
   bottom edge sits on the ground line.
2. **Make it:** `make_asset` `mode: generate`, `cutout: true`, `fit_to` = the target, `anchor: bottom`,
   aspect near the target's (tall subjects `3:4` or `2:3`). Prompt: the subject, its pose or angle, the
   painting's style, and the light direction and colour *("lit warm from the left, cool shadow side")*.
3. **Check the preview:** whole subject, nothing extra, clean edge. Regenerate rather than paint a bad one.
4. **Match the scene** when its colours look pasted: `run_skill_script` `image-asset/match_palette.py`,
   `inputs: {input: <asset>}`, `region_inputs: {palette_from: <canvas area around the target>}`,
   `strength: 0.5`.
5. **Paint it:** `paint_from_reference` with the result's arguments. Transparent pixels are skipped, so
   only the subject is painted.
6. **Ground it:** a soft contact shadow under it on its own layer (`create_layer` `blend_mode: multiply`,
   low opacity, then a short soft `paint_pass` along the ground line, darkest where it touches).
7. **Crisp edges:** `paint_reference_edges` on the subject's region. Then `observe_canvas`.

---
name: fix-region
description: Repair one area of a painting by editing a crop of it (a patchy or seamed sky, a wrong building, a smeared face, a hard rectangular patch) and repainting only that area. Use when part of the painting looks wrong and the rest should stay.
---

# Fix a region

Tool details are in the `image-asset` skill.

1. **Find it** (`observe_canvas`, then a region crop): the damaged area [x,y,w,h]. Add about 15% on each side
   that meets good paint, so the repaired patch can fade into it.
2. **Edit it:** `make_asset` `mode: edit`, `edit_region` = that rectangle, `fit_to` = the same rectangle.
   Prompt what to change **and** what to keep: *"remove the dark rectangular patch and the seam; continue
   the clouds naturally; keep every building and the moon exactly where they are"*.
3. **Check:** an `asset_check` that says the edit moved content means a smaller region or a stricter prompt.
4. **Paint it:** `paint_from_reference` with the result's arguments. On an established painting this is a
   patch: it fades over its outer edge and may cover only the region the tool allows.
5. **Blend** smooth areas with `paint_reference_surface` and sharpen key contours with
   `paint_reference_edges`. Then `observe_canvas` and compare with the area before.

---
name: fix-region
description: Repair one area of a painting by editing a crop of it (a patchy or seamed sky, a wrong building, a smeared face, a hard rectangular patch) and repainting only that area. Use when part of the painting looks wrong and the rest should stay.
---

# Fix a region

**Which route:** your instructions say how many AI images this chat allows. With one available, use the
**AI image route**; with AI images off or used up, use the **hand-painted route** and do not call `make_asset`.
Tool details for the AI image route are in the `image-asset` skill.

## Hand-painted route

1. **Find it**, as in step 1 below, and `select` it as a named selection with a feather of about 10% of its
   smaller side, so the repair fades into the good paint around it. A damaged area of one colour selects
   with a seed step inside it, or as a `split_by_color` region of that part.
   **A hard-edged patch or seam** (a flat rectangle in clouds): select it with a seed step inside the patch,
   since its edge *is* the seam, then `grow` the selection 2-4% of its smaller side and feather as much, so the
   repair overlaps the seam on both sides. Never a rectangle selection on organic content (clouds, foliage,
   water): rectangle edges show through every later layer. Repair only the patch and keep the forms around it
   (the moon, the cloud shapes): a repair that repaints its neighbours is a new defect.
2. **Match:** `sample_canvas_colors` just outside the damage, on every side that meets good paint.
3. **Repaint:** First propose_protection for any focal feature inside the area (the moon, a figure), named; Luna checks it after the batch. Then, inside the selection, `fill_region` a gradient between those samples for a smooth area (sky,
   wall), or `paint_recipe` with their palette for a textured one (clouds, foliage), on a new layer.
4. **Blend and redraw:** a blur mask (`apply_filter`, limited to the selection) where the area should be soft,
   then `paint_batch` strokes to redraw any contour the damage crossed. Then `observe_canvas` and compare.

## AI image route

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

---
name: paint-sky
description: Paint or replace a sky (night, dusk, storm, clear) as one convincing painted band that meets the horizon, buildings and trees cleanly. Use for any sky request, a sky that looks flat, patchy or seamed, or a sky behind subjects that are already painted.
---

# Paint a sky

**Which route:** your instructions say how many AI images this chat allows. With one available, use the
**AI image route**; with AI images off or used up, use the **hand-painted route** and do not call `make_asset`.
Tool details for the AI image route (prompts, checking assets, scripts) are in the `image-asset` skill.

## Hand-painted route

1. **Look**, as in step 1 below: the sky band [x,y,w,h] and what overlaps it.
2. **Base gradient:** `create_layer` `type: fill` with a linear gradient over the band (`region` = the band,
   start at the top, end at the horizon): the deep upper sky colour down to the lighter, warmer or hazier
   horizon colour. Where subjects already overlap the band, select the sky itself instead, with a seed step
   in it or the matching `split_by_color` region (the `repaint-area` skill), and `fill_region` the gradient in
   that selection, so the subjects stay untouched.
3. **Cloud masses:** `paint_recipe` on a new layer, `region` = the band, `direction: horizontal`,
   `irregularity` about 0.7, large sizes and low opacity, a palette of three to five values taken from the base
   (`sample_canvas_colors`). Then a second, smaller and lighter recipe for the edges the light catches.
4. **Moon or sun:** a small `fill_region` disc (`area` an ellipse step) for the body, a third in from a side.
   For its glow, `create_layer` `type: fill`, a radial gradient from the glow colour at the centre to black,
   `blend_mode: screen`: black adds nothing in Screen, so the glow fades out with no edge.
5. **Blend:** soften the cloud layers with `apply_filter` (a blur from `krita_capabilities`, `mode: mask`),
   so dabs become continuous cloud. Leave the moon, stars and city lights crisp.
6. **Check**, as in step 6 below.

## AI image route

1. **Look.** `observe_canvas`. Find the sky band [x,y,w,h]: from the top edge down to the horizon or the
   lowest point where sky shows. Note what already overlaps it (towers, a tree, a moon you must keep).
2. **Make the sky asset** (`make_asset`, `fit_to` = the band, `anchor: fill`):
   - **Nothing painted in the band yet:** `mode: generate`, prompt *"night sky only: … clouds, … moon
     position …, in the painting's style …; no buildings, no horizon, no ground"*, aspect near the band's.
   - **Subjects already overlap the band:** `mode: edit` with `edit_region` = the band, prompt *"repaint only
     the sky as …; keep <the tree / every building> exactly as it is"*. Edits keep framing, so the subjects
     stay where they are and are repainted with the sky.
   - Put the moon or sun where the composition wants the light (usually a third in from a side).
3. **Fade the lower edge** of a generated (not edited) sky: `run_skill_script` `image-asset/fade_edges.py`,
   `inputs: {input: <asset>}`, `edges: "bottom"`, `width: 0.15`, so it melts into the horizon haze.
4. **Paint it:** `paint_from_reference` with the result's `paint_from_reference` arguments (add `name`,
   and a soft or bristle preset such as `b) Basic-5 Size` or `f) Bristles-3 Large Smooth`).
5. **Blend:** `paint_reference_surface` over the band with a Color Smudge blender, so dabs become
   continuous clouds. Leave stars, the moon and city lights crisp.
6. **Check** with `observe_canvas`: one moon, no seams or rectangular patches, the horizon line clean,
   subjects in front untouched. Fix a bad area with the `fix-region` skill, not a whole new sky.

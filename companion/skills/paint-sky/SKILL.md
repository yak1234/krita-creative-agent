---
name: paint-sky
description: Paint or replace a sky (night, dusk, storm, clear) as one convincing painted band that meets the horizon, buildings and trees cleanly. Use for any sky request, a sky that looks flat, patchy or seamed, or a sky behind subjects that are already painted.
---

# Paint a sky

Tool details (prompts, checking assets, scripts) are in the `image-asset` skill.

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

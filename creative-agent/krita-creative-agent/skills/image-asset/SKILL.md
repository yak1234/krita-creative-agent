---
name: image-asset
description: Make an image asset with an image model (a subject such as a tree, figure or building, or a background such as a sky) or fix part of the painting by editing a crop of it, then repaint it into the painting with native brush strokes. Use when a subject or area is hard to construct by hand, when the artist asks for one, or when a region (a sky, a background) needs replacing.
---

# Image assets

**Only within the chat's AI image allowance.** Your instructions say how many AI images this chat allows.
With AI images off or used up, do not call `make_asset`, even when the artist invokes this skill: say that
the allowance is 0 (or used up) and that they can raise AI images for this chat in the panel, then stop.

When the artist invokes this skill and an AI image is available, make an asset for what they asked for
(each subject or area they name) and paint it from that asset; do not fall back to hand-painting it. An asset is a reference image you make on purpose. It never goes into the painting as pixels: you
repaint it with `paint_from_reference`, which samples it into native brush dabs, then finish with
edges. Assets come from the artist's ChatGPT plan through their Codex sign-in (or OpenRouter at
about 1–2 cents, if they chose it in settings) and take about 30 seconds: make one, look at it, and only
make another if it is wrong.

## 1. Decide what to make

| Need | mode | cutout | aspect_ratio |
|---|---|---|---|
| A subject to place (tree, figure, lamp, car) | `generate` (or `draft` to try an idea cheaply) | `true` | the subject's shape: `3:4` or `2:3` tall, `4:3` wide |
| A background band (sky, distant city, sea) | `generate` | `false` | the band's shape: `16:9`, `21:9` |
| Fix an area already painted (a patchy sky, a wrong building) | `edit` with `edit_region` [x,y,w,h] | `false` | ignored: edit keeps the crop's framing |
| A background **behind** something already painted (a sky behind a finished tree) | `edit` with `edit_region` covering both, prompt "repaint only the sky…, keep the tree exactly" | `false` | ignored |
| Match the painting's look | add `style_reference_id` (an attached reference or the painting's own crop asset) | | |

## 2. Write the prompt

- Say the subject, then the painting's style and light: *"a tall snow-dusted fir decorated with warm
  gold lights and red baubles, oil painting with visible impasto brushstrokes, lit by a warm window from
  the left, cool blue night shadows"*.
- Use the painting's palette words (look at the canvas first) so the asset belongs.
- A background: say what it is **only**: *"night sky only: no buildings, no horizon, no ground"*.
- An edit: say what to change **and** what to keep exactly: *"repaint only the sky…; keep every building,
  tree and light exactly as it is"*.
- With `cutout: true`, do not describe a background: the tool asks for a transparent (or plain) one and
  removes it.

## 3. Check the asset

Give `fit_to` = the canvas target [x,y,w,h] (step 4) when you know where it goes: the asset comes back
at exactly that aspect ratio, with ready `paint_from_reference` arguments (source, target, steps).

`make_asset` returns a preview (transparent = grey checkerboard). Before painting, check:
- the whole subject is there, not cropped; nothing extra (no ground, frame, text);
- a cut-out has a clean edge and **no pale specks or haze** around the subject: leftover background
  is painted too, as white smoke (if you see any: `run_skill_script` with `cutout.py`, `tolerance` 70);
- the colours fit the painting (if not: `match_palette.py` with `region_inputs` = the canvas area around
  where it goes, `strength` 0.4–0.7).

## 4. Place it on the canvas

1. Choose the target rectangle [x,y,w,h] on the canvas before making the asset, and pass it as
   `fit_to`. Size it to the scene: a tree that stands on the ground has its bottom on the ground line
   (`anchor: bottom`, the default for cut-outs); a background band uses `anchor: fill`.
2. Call `paint_from_reference` with the `paint_from_reference` arguments the result gives (add `name` and
   `preset`). Without `fit_to`, the target must have exactly the asset's aspect ratio, and use the `steps`
   the result gives: the default steps fail on a large asset. Transparent pixels are skipped, so only
   the subject is painted.
3. A transfer paints on a new layer on top. Paint backgrounds before the subjects in front of them; if
   the subject is already painted, use an `edit` asset that contains both (see step 1's table).
   - On a painting that already exists, a transfer may only patch a region (the tool says the limit);
     a patch fades over its outer edge, so make the target about 15% larger than the area to cover
     where it meets existing paint.
   - A sky or background band on its own: fade its lower edge first (`fade_edges.py`, `edges: "bottom"`) so it
     melts into what is below.
4. Finish: `paint_reference_surface` for smooth areas (sky, snow, skin), then `paint_accents` on the
   subject's region, which brightens, deepens and sharpens its own paint where the subject image is crisper. Then look at the canvas.

## 5. Order for a scene

Back to front: sky and background bands first, then large subjects, then small ones, then light
effects. Each subject is its own asset and its own transfer, so each can be rejected alone.

## Scripts (`run_skill_script`, skill `image-asset`)

All run in a sandbox that sees only this conversation's assets. Pass images with `inputs`
(argument → reference_id) or `region_inputs` (argument → canvas [x,y,w,h]). Each writes a new asset.

| script | inputs | args |
|---|---|---|
| `cutout.py` | `input` | `tolerance` (default 40; 60–80 for a textured background), `crop` (default true), `feather` |
| `match_palette.py` | `input`, `palette_from` (usually a `region_inputs` canvas crop) | `strength` 0–1 (default 0.6) |
| `fade_edges.py` | `input` | `edges` ("bottom", "left right", …), `width` (share, default 0.12) |

# Worked example: a harbour town at dusk

The scene is a harbour town at dusk: houses on a hill with lit windows, a lighthouse with its lamp burning, a pier
running out into the water, and moored boats. The canvas is 4800 × 3200. The goal image (`goal`, 1600 × 1067) has the
canvas's proportions, so goal pixels × 3 are canvas pixels. The lighthouse has its own photo (`lighthouse`,
1024 × 1536).

## Measure before drawing

Look at the goal image (`view_reference`) and write each position down as a **fraction of the canvas**: the top, the
bottom and the centre of each big mass. These are the numbers for this goal; with yours, measure them again.

| What | In the goal image | On the canvas |
|---|---|---|
| Eye level (the sea's horizon) | 0.38 of the height | y 1216 |
| Vanishing point of the pier | 0.30 of the width, on the eye level | (1440, 1216) |
| Hill with houses | left 0 to 0.45, top 0.12 to 0.55 | [0, 384, 2160, 1377] |
| Lighthouse | left 0.62 to 0.70, top 0.10 to 0.50 | [2976, 321, 384, 1278] |
| Pier | left 0.10 to 0.75, top 0.45 to 0.80 | [480, 1440, 3120, 1122] |
| Boats | left 0.55 to 0.95, top 0.55 to 0.80 | [2640, 1761, 1920, 798] |

A target is the measured box on the canvas. Its `source` is the same box in the goal image, so the two share their
proportions.

## The moves

1. **The underpainting (the first move, no guides):** this is a fresh canvas, so `paint_from_reference` lays the
   goal's colours and light over the whole canvas, then `finish_move`.
2. **The artist asks for a block-in with guides, so a guides move (nothing painted):**
   - the eye level and the pier's vanishing point;
   - the goal's masses (`masses: true`, the whole goal onto the whole canvas): sky, sea, hill, the lit lamp warm;
   - the silhouettes of the hill and houses (`medium`: rooflines and setbacks), the lighthouse, the pier (`medium`:
     its posts) and the boats;
   - the light shapes: the lighthouse lamp and the lit windows with `lights`, and the sunset's glitter path on the
     water as a hand-drawn `weight: 'light'` line;
   - `finish_move`.
3. **One element per move, here the lighthouse:**
   - tighten its guide (it has one: the artist asked for guides) from its own photo with `replace: true`; the crop of
     the photo (451 × 1500) has the target's proportions (384 × 1278);
   - paint it in your own strokes, following the guide, with the lamp the lightest value;
   - `finish_guide`, then `finish_move`.

The houses, the pier and the boats each get a move like the third.

```json
{
  "canvas": [4800, 3200],
  "references": { "goal": [1600, 1067], "lighthouse": [1024, 1536] },
  "moves": [
    [
      { "tool": "paint_from_reference", "args": { "name": "Harbour colour pass", "reference_id": "goal", "preset": "b) Basic-5 Size Opacity", "source": [0, 0, 1600, 1067], "target": [0, 0, 4800, 3200] } },
      { "tool": "finish_move", "args": { "summary": "Underpainting: the goal's dusk colours and light over the whole canvas" } }
    ],
    [
      { "tool": "draw_guide", "args": { "element": "Perspective", "perspective": { "eye_level_y": 1216, "vanishing_points": [[1440, 1216]], "rays": 8 } } },
      { "tool": "draw_guide", "args": { "element": "Masses", "from_reference": { "reference_id": "goal", "source": [0, 0, 1600, 1067], "target": [0, 0, 4800, 3200], "masses": true } } },
      { "tool": "draw_guide", "args": { "element": "Hill and houses", "from_reference": { "reference_id": "goal", "source": [0, 128, 720, 459], "target": [0, 384, 2160, 1377], "detail": "medium", "lights": true } } },
      { "tool": "draw_guide", "args": { "element": "Lighthouse", "from_reference": { "reference_id": "goal", "source": [992, 107, 128, 426], "target": [2976, 321, 384, 1278], "detail": "simple", "lights": true } } },
      { "tool": "draw_guide", "args": { "element": "Pier", "from_reference": { "reference_id": "goal", "source": [160, 480, 1040, 374], "target": [480, 1440, 3120, 1122], "detail": "medium" },
        "lines": [{ "points": [[480, 2560], [1440, 1216]], "weight": "construction" }] } },
      { "tool": "draw_guide", "args": { "element": "Boats", "from_reference": { "reference_id": "goal", "source": [880, 587, 640, 266], "target": [2640, 1761, 1920, 798], "detail": "simple" } } },
      { "tool": "draw_guide", "args": { "element": "Glitter path", "lines": [{ "points": [[3168, 1230], [3060, 2000], [2900, 3150]], "weight": "light" }] } },
      { "tool": "finish_move", "args": { "summary": "Construction: eye level, pier vanishing point, masses, hill and houses, lighthouse, pier, boats and the light shapes" } }
    ],
    [
      { "tool": "draw_guide", "args": { "element": "Lighthouse", "replace": true, "from_reference": { "reference_id": "lighthouse", "source": [286, 18, 451, 1500], "target": [2976, 321, 384, 1278], "detail": "medium", "lights": true } } },
      { "tool": "paint_pass", "args": { "name": "Lighthouse tower", "preset": "b) Basic-5 Size Opacity", "strokes": [
        { "start": [3060, 1590], "segments": [[3075, 1200, 3090, 800, 3110, 520]], "size": 40, "opacity": 0.9, "flow": 1, "color": "#d9cbb8" },
        { "start": [3280, 1590], "segments": [[3265, 1200, 3250, 800, 3230, 520]], "size": 40, "opacity": 0.9, "flow": 1, "color": "#8c7f74" },
        { "start": [3170, 420], "segments": [[3175, 420, 3180, 420, 3185, 420]], "size": 60, "opacity": 1, "flow": 1, "color": "#fff3c4" }] } },
      { "tool": "finish_guide", "args": { "element": "Lighthouse" } },
      { "tool": "finish_move", "args": { "summary": "Lighthouse: tapered tower, warm lamp, the lightest value in the picture" } }
    ]
  ]
}
```

## Check each stage

- **Perspective:** the pier's posts and edges meet at the vanishing point.
- **Placement:** each mass sits at the fractions in the table. Check its top, bottom and centre.
- **Silhouettes:** the lighthouse reads as a tapering tower with a lamp room, the houses step up the hill, and the
  boats have hulls and masts.
- **Light:** the lamp, the windows and the glitter path are outlined warm, and stay the lightest values once painted.

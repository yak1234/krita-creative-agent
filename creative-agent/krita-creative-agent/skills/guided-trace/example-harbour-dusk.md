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
2. **The artist asks for guides, so a guides move (nothing painted), every line placed by hand:**
   - the eye level and the pier's vanishing point;
   - the hilltop and the houses' rooflines as a few lines measured in the goal (goal pixels, mapped onto the canvas);
   - the lighthouse's centre line, top and base; the pier's two edges to the vanishing point; the boats' waterline;
   - the light shapes: the lighthouse lamp and the sunset's glitter path on the water as `weight: 'light'` lines;
   - `finish_move`.
3. **One element per move, here the lighthouse:**
   - tighten its guide (it has one: the artist asked for guides) from its own photo with `replace: true`: its centre
     line and the lamp room measured there; the crop of the photo (451 × 1500) has the target's proportions (384 × 1278);
   - paint it in your own strokes, following the guide, with the lamp the lightest value;
   - make it crisp with `paint_accents` on its box (the lamp, the window glints, the railing sharpened in its own paint);
   - `finish_guide`, then `finish_move`.

The houses, the pier and the boats each get a move like the third.

```json
{
  "canvas": [4800, 3200],
  "references": {"goal": [1600, 1067], "lighthouse": [1024, 1536]},
  "moves": [
    [
      {"tool": "paint_from_reference", "args": {"name": "Harbour colour pass", "reference_id": "goal", "preset": "b) Basic-5 Size Opacity", "source": [0, 0, 1600, 1067], "target": [0, 0, 4800, 3200]}},
      {"tool": "finish_move", "args": {"summary": "Underpainting: the goal's dusk colours and light over the whole canvas"}}
    ],
    [
      {"tool": "draw_guide", "args": {"element": "Perspective", "perspective": {"eye_level_y": 1216, "vanishing_points": [[1440, 1216]], "rays": 8}}},
      {"tool": "draw_guide", "args": {"element": "Hill and houses", "reference_id": "goal", "source": [0, 0, 1600, 1067], "target": [0, 0, 4800, 3200], "lines": [{"points": [[0, 150], [180, 128], [420, 170], [720, 260]]}, {"points": [[60, 300], [200, 280], [340, 300], [480, 330]], "weight": "construction"}]}},
      {"tool": "draw_guide", "args": {"element": "Lighthouse", "lines": [{"points": [[3168, 321], [3168, 1599]], "weight": "construction"}, {"points": [[3060, 1599], [3110, 500], [3230, 500], [3280, 1599]]}]}},
      {"tool": "draw_guide", "args": {"element": "Pier", "lines": [{"points": [[480, 2560], [1440, 1216]], "weight": "construction"}, {"points": [[3600, 2560], [1440, 1216]], "weight": "construction"}]}},
      {"tool": "draw_guide", "args": {"element": "Boats", "lines": [{"points": [[2640, 2400], [4560, 2380]]}]}},
      {"tool": "draw_guide", "args": {"element": "Light shapes", "lines": [{"points": [[3140, 420], [3200, 420]], "weight": "light"}, {"points": [[3168, 1230], [3060, 2000], [2900, 3150]], "weight": "light"}]}},
      {"tool": "finish_move", "args": {"summary": "Construction by hand: eye level, pier vanishing point, hill and rooflines, lighthouse, pier, boats and the light shapes"}}
    ],
    [
      {"tool": "draw_guide", "args": {"element": "Lighthouse", "replace": true, "reference_id": "lighthouse", "source": [286, 18, 451, 1500], "target": [2976, 321, 384, 1278], "lines": [{"points": [[512, 18], [512, 1518]], "weight": "construction"}, {"points": [[420, 1518], [470, 260], [555, 260], [605, 1518]]}, {"points": [[470, 120], [555, 120]], "weight": "light"}]}},
      {"tool": "paint_pass", "args": {"name": "Lighthouse tower", "preset": "b) Basic-5 Size Opacity", "strokes": [{"start": [3060, 1590], "segments": [[3075, 1200, 3090, 800, 3110, 520]], "size": 40, "opacity": 0.9, "flow": 1, "color": "#d9cbb8"}, {"start": [3280, 1590], "segments": [[3265, 1200, 3250, 800, 3230, 520]], "size": 40, "opacity": 0.9, "flow": 1, "color": "#8c7f74"}, {"start": [3170, 420], "segments": [[3175, 420, 3180, 420, 3185, 420]], "size": 60, "opacity": 1, "flow": 1, "color": "#fff3c4"}]}},
      {"tool": "paint_accents", "args": {"reference_id": "goal", "area": {"box": [2976, 321, 384, 1278]}, "kinds": ["lights", "glints", "lines"], "count": 30}},
      {"tool": "finish_guide", "args": {"element": "Lighthouse"}},
      {"tool": "finish_move", "args": {"summary": "Lighthouse: tapered tower, warm lamp, the lightest value in the picture"}}
    ]
  ]
}
```

## Check each stage

- **Perspective:** the pier's posts and edges meet at the vanishing point.
- **Placement:** each mass sits at the fractions in the table. Check its top, bottom and centre.
- **Proportions:** the lighthouse is a tapering tower about three times as tall as its base is wide, the houses step
  up the hill.
- **Light:** the lamp and the glitter path are marked warm, and stay the lightest values once painted.

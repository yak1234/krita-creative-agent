"""The mask a paint pass's region clips its strokes to.

Strokes may run a brush size past the region so they reach its edge at full width (creative_validation.validate_pass);
a hard 255 rectangle then cuts them along a dead-straight line, which prints into open paint as a band with straight
edges: the fork's first Agent-mode chat (19 October) left one in New Moscow's sky that neither Luna nor seams.py named,
since the band lay in textured paint. The mask fades in over FEATHER px from each edge that lies inside the painting, so
nothing is painted outside the region and no straight cut is left; an edge on the canvas border stays full, so a pass
still reaches the frame.
"""
import numpy as np

FEATHER = 48                # px over which an inner edge fades in
MIN_CORE = 0.5              # a small region keeps at least this share of each side at full strength


def _ramp(length, start_inner, end_inner, feather):
    """1-d weights 0-1 along one side: smoothstep up from each inner end over `feather` px."""
    t = np.ones(length, np.float32)
    i = np.arange(length, dtype=np.float32)
    if start_inner:
        t = np.minimum(t, np.clip((i + 0.5) / feather, 0, 1))
    if end_inner:
        t = np.minimum(t, np.clip((length - i - 0.5) / feather, 0, 1))
    return t * t * (3 - 2 * t)


def mask(region, width, height, feather=FEATHER):
    """uint8 (h, w) mask of `region` [x, y, w, h] on a width x height canvas, for Selection.setPixelData."""
    x, y, w, h = (int(v) for v in region)
    fx = max(1.0, min(feather, w * (1 - MIN_CORE) / 2))
    fy = max(1.0, min(feather, h * (1 - MIN_CORE) / 2))
    across = _ramp(w, x > 0, x + w < width, fx)
    down = _ramp(h, y > 0, y + h < height, fy)
    return np.round(np.outer(down, across) * 255).astype(np.uint8)

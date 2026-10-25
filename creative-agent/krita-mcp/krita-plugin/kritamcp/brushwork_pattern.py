# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Goal brushwork patterns (openspec architecture-texture goal 8; the artist 2026-10-25: "isn't krita patterns from image
exactly what we need"). For each architectural part the goal image is cut at the part's found area (Find it), high-passed
(its light and shading removed, its stroke grain kept), made seamless and registered with the fork's
Krita.createPattern() as "Goal brushwork: <part>", so the part's form strokes can carry the goal's own impasto rhythm as
their brush texture. The library material (goals 1, 6) adds the full-size detail the small goal lacks.

- The crop: the part's found area (a canvas mask in the chat folder's .shapes) mapped into the goal's pixels through where
  the goal sits on the canvas (finish_pass.py check_goal: source and target), the goal read once (its Sharpen-ed copy when
  the chat has one: the companion sends that file). The square window inside the part with the most of the part in it,
  at most MAX_SIDE goal px.
- High-pass: the luminance less its Gaussian blur (HIGH_PASS_SIGMA), the blur normalised by the mask so the paint around
  the part (the sky behind a tower) never leaks in as an edge; then unit spread, clipped at 3.
- Energy: the high-pass spread inside the part, in luminance levels (0-255). Below ENERGY_MIN the part is flat (smooth
  shading, a plain wall) and gets no pattern: the brush uses the library material alone. A window smaller than MIN_SIDE
  is tiny: no pattern either.
- Seamless: offset and blend, one axis at a time. The tile rolled by half its side is continuous across its wrap edge; a
  tent weight keeps the unrolled tile in the middle (hiding the rolled one's seam) and the rolled one at the edges, the
  mix renormalised so its spread stays. Done in x, then in y on the result, so neither axis has a seam.
- Stored as a grey height map, mid grey 128 and CONTRAST levels per unit (a brush texture reads a pattern as height).

Pure numpy/OpenCV in brushwork_tile (tests/test_brushwork_pattern.py, no Krita); BrushworkCraft is the plugin operation
`brushwork_patterns`, dispatched by creative_tools.py. It changes no document (no pass, no checkpoint), like make_material.
What each part got is kept in this process for the brush texture (goal 6): goal_brushwork_pattern(part).

The same crop gives the part's goal dabs (goal 9, goal_dabs.py): a few impasto dabs registered with Krita.createBrushTip as
"Goal dab: <part> <n>" (kept for the Finish's strokes even where Krita cannot make tips); `dabs` lists their names.
"""
import time

import numpy as np

HIGH_PASS_SIGMA = 5.0      # goal px: strokes of the goal (2-10 px at 1448 px wide) stay, light and shading go
ENERGY_MIN = 2.5           # luminance levels; flat paint or a smooth gradient measures about 0, JPEG noise about 1
MIN_SIDE = 24              # goal px: a smaller window holds too few strokes to repeat
MAX_SIDE = 512             # goal px: the largest pattern
MIN_COVER = 0.75           # share of the window inside the part
CONTRAST = 40.0            # grey levels per unit of detail
CLIP = 3.0
MOST_PARTS = 8
PREFIX = 'Goal brushwork: '
PARAM_FIELDS = ('goal', 'parts')
PART_FIELDS = ('name', 'inside_shape')

# What each part got in this Krita session: {part key: {name, energy, size, scale}} (see goal_brushwork_pattern).
_REGISTERED = {}


def _luminance(bgr):
    pixels = bgr.astype(np.float32)
    return 0.114 * pixels[..., 0] + 0.587 * pixels[..., 1] + 0.299 * pixels[..., 2]


def _window(part, side):
    """The (y, x, n) square of side <= `side` with the most of `part` (0/1 float) in it, shrinking until MIN_COVER of it is
    the part; None when no such square of MIN_SIDE fits."""
    h, w = part.shape
    total = np.zeros((h + 1, w + 1), np.float64)
    total[1:, 1:] = part.cumsum(0).cumsum(1)
    n = min(side, h, w)
    while n >= MIN_SIDE:
        step = max(1, n // 4)
        ys = np.unique(np.r_[np.arange(0, h - n + 1, step), h - n])
        xs = np.unique(np.r_[np.arange(0, w - n + 1, step), w - n])
        y0, x0 = ys[:, None], xs[None, :]
        inside = total[y0 + n, x0 + n] - total[y0, x0 + n] - total[y0 + n, x0] + total[y0, x0]
        best = np.unravel_index(int(np.argmax(inside)), inside.shape)
        if inside[best] >= MIN_COVER * n * n:
            return int(ys[best[0]]), int(xs[best[1]]), n
        n = int(n * 0.8)
    return None


def _seamless(detail):
    """`detail` (n, n), zero mean, made to tile: offset and blend in x, then in y (see the header)."""
    n = detail.shape[0]
    tent = 1 - np.abs(2 * np.arange(n, dtype=np.float32) / max(1, n - 1) - 1)
    norm = np.sqrt(tent ** 2 + (1 - tent) ** 2)
    out = detail
    for axis in (1, 0):
        shape = (1, n) if axis == 1 else (n, 1)
        weight, scale = tent.reshape(shape), norm.reshape(shape)
        out = (weight * out + (1 - weight) * np.roll(out, n // 2, axis=axis)) / scale
    return out


def brushwork_tile(bgr, mask=None, max_side=MAX_SIDE):
    """A goal crop (h, w, 3) BGR uint8 and the part's mask over it (h, w, 255 inside; None: all of it) as a seamless grey
    pattern: (tile (n, n) uint8, energy, None), or (None, energy, 'flat' | 'tiny')."""
    import cv2
    part = np.ones(bgr.shape[:2], np.float32) if mask is None else (np.asarray(mask) > 127).astype(np.float32)
    window = _window(part, max_side)
    if window is None:
        return None, 0.0, 'tiny'
    y, x, n = window
    # The blur with a margin around the window, normalised by the mask: only the part's own paint is averaged.
    margin = int(3 * HIGH_PASS_SIGMA) + 1
    y0, x0 = max(0, y - margin), max(0, x - margin)
    y1, x1 = min(bgr.shape[0], y + n + margin), min(bgr.shape[1], x + n + margin)
    lum, inside = _luminance(bgr[y0:y1, x0:x1]), part[y0:y1, x0:x1]
    blur = lambda image: cv2.GaussianBlur(image, (0, 0), HIGH_PASS_SIGMA, borderType=cv2.BORDER_REFLECT)
    low = blur(lum * inside) / np.maximum(blur(inside), 1e-3)
    detail = ((lum - low) * inside)[y - y0:y - y0 + n, x - x0:x - x0 + n]
    kept = inside[y - y0:y - y0 + n, x - x0:x - x0 + n]
    count = float(kept.sum())
    mean = float(detail.sum()) / count
    detail = (detail - mean) * kept
    energy = float(np.sqrt(float((detail ** 2).sum()) / count))
    if energy < ENERGY_MIN:
        return None, energy, 'flat'
    unit = np.clip(detail / energy, -CLIP, CLIP)
    tile = _seamless(unit - float(unit.mean()))
    return np.clip(np.round(128 + CONTRAST * tile), 0, 255).astype(np.uint8), energy, None


def _key(part):
    return ' '.join(str(part).split()).lower()


def goal_brushwork_pattern(part):
    """The goal brushwork pattern registered for `part` in this Krita session: {name, energy, size, scale} (name: the Krita
    pattern resource's name; scale: canvas px per pattern px, for the brush texture's scale), or None (flat, tiny, not
    made yet)."""
    found = _REGISTERED.get(_key(part))
    return dict(found) if found else None


def pattern_name(part):
    return (PREFIX + ' '.join(str(part).split()))[:120]


class BrushworkCraft:
    def _brushwork_patterns(self, doc, session, params):
        """Operation brushwork_patterns: {goal: {path, sha256, size, source, target}, parts: [{name, inside_shape}]} ->
        {status, brushwork: [{part, pattern, energy, size, scale, dabs, reason?}]}. Everything is checked before any pattern is
        made; a part that is flat or tiny, or that Krita refuses, gets pattern None and its reason."""
        from krita import Krita
        from .creative_validation import fields, text
        from . import finish_pass, shape_mask
        fields(params, PARAM_FIELDS, PARAM_FIELDS)
        app = Krita.instance()
        if not hasattr(app, 'createPattern'):
            raise ValueError('Goal brushwork patterns need Toska (Krita.createPattern).')
        width, height = doc.width(), doc.height()
        goal = finish_pass.check_goal(params['goal'], session.get('output'), width, height)
        parts = params['parts']
        if not isinstance(parts, list) or not 1 <= len(parts) <= MOST_PARTS:
            raise ValueError('parts is a list of 1-%d parts.' % MOST_PARTS)
        checked = []
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError('A part is an object.')
            fields(part, PART_FIELDS, PART_FIELDS)
            name = text(part['name'], 'part name', 100)
            rect, mask = shape_mask.read_shape(part['inside_shape'], session.get('output'), width, height)
            checked.append((name, rect, mask))
        picture = finish_pass.read_goal(goal)
        report = [self._brushwork_part(app, picture, goal, name, rect, mask) for name, rect, mask in checked]
        return {'status': 'ok', 'brushwork': report}

    @staticmethod
    def _brushwork_part(app, picture, goal, name, rect, mask):
        from .qt_compat import QImage
        from . import goal_dabs
        started = time.monotonic()
        sx, sy, sw, sh = goal['source']
        tx, ty, tw, th = goal['target']
        kx, ky = sw / tw, sh / th                                     # goal px per canvas px
        x, y, w, h = rect
        gx0, gy0 = sx + (x - tx) * kx, sy + (y - ty) * ky
        gx1, gy1 = gx0 + w * kx, gy0 + h * ky
        px0, py0 = max(0, int(np.floor(gx0))), max(0, int(np.floor(gy0)))
        px1, py1 = min(picture.shape[1], int(np.ceil(gx1))), min(picture.shape[0], int(np.ceil(gy1)))
        entry = {'part': name, 'pattern': None, 'energy': 0.0, 'size': 0, 'scale': round(1 / kx, 3), 'dabs': []}
        _REGISTERED.pop(_key(name), None)
        crop = crop_mask = None
        if px1 > px0 and py1 > py0:
            canvas_mask = np.frombuffer(mask, np.uint8).reshape(h, w)
            # The mask over the crop: the canvas mask resampled to the goal's pixels (nearest: it stays 0/255).
            gxs = np.clip(((np.arange(px0, px1) + 0.5 - gx0) / kx).astype(int), 0, w - 1)
            gys = np.clip(((np.arange(py0, py1) + 0.5 - gy0) / ky).astype(int), 0, h - 1)
            crop_mask = canvas_mask[gys][:, gxs]
            crop = np.ascontiguousarray(picture[py0:py1, px0:px1, :3])
            entry['dabs'] = goal_dabs.register(app, name, crop, crop_mask, 1 / kx)
        if px1 - px0 < MIN_SIDE or py1 - py0 < MIN_SIDE:
            entry['reason'] = 'tiny'
        else:
            tile, energy, reason = brushwork_tile(crop, crop_mask)
            entry['energy'] = round(energy, 2)
            if tile is None:
                entry['reason'] = reason
            else:
                n = tile.shape[0]
                image = QImage(np.ascontiguousarray(tile).tobytes(), n, n, n, QImage.Format.Format_Grayscale8).copy()
                resource = app.createPattern(image, pattern_name(name))
                if resource is None:
                    entry['reason'] = 'refused'
                else:
                    entry.update(pattern=resource.name(), size=n)
                    _REGISTERED[_key(name)] = {'name': resource.name(), 'energy': entry['energy'], 'size': n, 'scale': entry['scale']}
        entry['ms'] = int((time.monotonic() - started) * 1000)
        return entry

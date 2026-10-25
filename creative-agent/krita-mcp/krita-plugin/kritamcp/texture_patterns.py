# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Textured brushes (openspec architecture-texture goal 6, approved by the artist 2026-10-25): the texture library's
materials become Krita patterns ("Texture: <id>") through the fork's Krita.createPattern (libkis: added to the resource
database, listed and usable at once, tagged Agent, the agent's own pattern of that name replaced), so a brush can carry
one as its Texture/Pattern and the artist finds them in the pattern chooser. No manual Manage Resources import.

A pattern is the material's detail (texture_raster.detail_tile: high-passed, seamless) as a height map, mid grey 0.5 and
0.25 a unit of detail. The Finish's form strokes in an architectural part carry it as grain (apply_grain): their alpha
is thinned where the pattern is low, as Krita's brush texture subtracts from a dab, in canvas coordinates at the part's
tile size; their colour stays their own, and nothing changes outside the part.
"""
import hashlib

import numpy as np

PREFIX = 'Texture: '
REGISTERED = {}            # pattern name -> digest of what was registered under it, this Krita session


def height_map(detail):
    """A detail tile (zero mean, unit spread) as heights 0-1."""
    return np.clip(0.5 + 0.25 * detail, 0, 1).astype(np.float32)


def _image(height):
    from .qt_compat import QImage
    h, w = height.shape
    data = np.ascontiguousarray(np.round(height * 255).astype(np.uint8))
    return QImage(data.tobytes(), w, h, w, QImage.Format.Format_Grayscale8).copy()


def register(app, materials):
    """{id: (maps {color|displacement|ao: grey 0-255}, detail_from)} as patterns: {id: the pattern's name}. Empty without
    Krita.createPattern (stock Krita); a material registered this session with the same maps is not made again."""
    from . import texture_raster
    if not hasattr(app, 'createPattern'):
        return {}
    names = {}
    for identifier, (maps, detail_from) in materials.items():
        name = PREFIX + identifier
        height = height_map(texture_raster.detail_tile(maps, detail_from))
        digest = hashlib.sha256(height.tobytes()).hexdigest()
        if REGISTERED.get(name) != digest:
            resource = app.createPattern(_image(height), name)
            if resource is None:
                continue
            name = resource.name()
            REGISTERED[PREFIX + identifier] = digest
        names[identifier] = name
    return names


def pattern_height(app, name):
    """A registered pattern's pixels as heights 0-1 (h, w); ValueError when there is no such pattern."""
    from .qt_compat import QImage, image_bytes
    resource = app.resources('pattern').get(name)
    if resource is None:
        raise ValueError('No pattern "%s": register the materials first.' % name)
    image = resource.image().convertToFormat(QImage.Format.Format_Grayscale8)
    h, w = image.height(), image.width()
    return np.frombuffer(image_bytes(image), np.uint8).reshape(h, w).astype(np.float32) / 255.0


def apply_grain(strokes, rect, grains):
    """The strokes' pixels (h, w, 4 BGRA uint8) over canvas `rect` [x, y, w, h], their alpha thinned by each grain
    (mask uint8, mask rect, height 0-1, tile px, strength 0-1) inside its mask. In place; returned."""
    x0, y0, w, h = rect
    alpha = strokes[..., 3].astype(np.float32)
    for mask, (mx, my, mw, mh), height, tile, strength in grains:
        left, top = max(x0, mx), max(y0, my)
        right, bottom = min(x0 + w, mx + mw), min(y0 + h, my + mh)
        if right <= left or bottom <= top:
            continue
        inside = mask[top - my:bottom - my, left - mx:right - mx] > 127
        if not inside.any():
            continue
        th, tw = height.shape
        ys, xs = np.mgrid[top:bottom, left:right]
        sample = height[((ys / tile) * tw).astype(np.int64) % th, ((xs / tile) * tw).astype(np.int64) % tw]
        keep = 1 - strength * (1 - sample)
        window = alpha[top - y0:bottom - y0, left - x0:right - x0]
        window[inside] *= keep[inside]
    strokes[..., 3] = np.clip(np.round(alpha), 0, 255).astype(np.uint8)
    return strokes


def brush_pattern(app, image, path):
    """The pattern resource a brush texture from the file at `path` uses: the one imported under its file name, else (our
    Krita) the file registered now as "Texture: <file name>"; an error dict when neither."""
    import os
    matches = [r for r in app.resources('pattern').values() if os.path.basename(r.filename()) == os.path.basename(path)]
    if len(matches) == 1:
        return matches[0]
    if not hasattr(app, 'createPattern'):
        return {'error': 'Import this file as Patterns in Settings > Manage Resources first', 'path': path, 'matches': len(matches)}
    made = app.createPattern(image, PREFIX + os.path.splitext(os.path.basename(path))[0])
    return made if made is not None else {'error': 'Krita could not make a pattern of this file', 'path': path}

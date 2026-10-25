# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The architecture texture pass as pixels (openspec architecture-texture goal 3): a photo texture's detail, never its
colour, warped to a part's perspective and laid into the part's found area with a soft edge.

Pure numpy on arrays (Qt only decodes the library's JPEG maps), so it is tested without Krita
(tests/test_texture_raster.py); texture_craft.py reads the painting and writes the layer.

- Detail: the luminance of the material's maps (Color, Displacement, AmbientOcclusion, or the ones a material names: a
  window grid uses its displacement only, never its lit windows), high-passed with a wrap-around blur (the maps tile) so
  only grain, courses and joints are left, zero mean and unit spread, clipped at 3; a mip chain against aliasing.
- Perspective: one-point. The courses run along `direction_deg`; with a vanishing point they converge on it and the tile
  shrinks linearly toward it (image size is proportional to the distance to the vanishing point); without one, a far tile
  smaller than the near one puts a virtual vanishing point beyond the far edge; equal sizes are a flat grid.
- No visible tiling: the plane is cut in cells of 1.5 tiles, each sampling the material at its own random offset, the four
  cells around a pixel blended smoothly with their spread kept (texture bombing), and the strength varied by low-frequency
  noise, so a tile never repeats as it is.
- Colour: the detail is a grey value 0.5 + 0.2 x detail blended over the painting's luminance (Soft Light or Overlay) at the
  strength, and the same change goes to all three channels, so hue and chroma are the painting's own. The layer holds the
  result with the soft mask as alpha: over the painting it adds alpha x the change.
"""
import math

import numpy as np

from .material_raster import decode

WEIGHTS = {'color': 0.5, 'displacement': 0.3, 'ao': 0.2}
HIGH_PASS = 16             # the blur that is taken away: the tile's width over this (64 px of a 1K map)
CONTRAST = 0.2             # the grey value's spread per unit of detail
MIN_LEVEL_SIDE = 16
STRIP = 256                # rows sampled at once
BOMB_CELL = 1.5           # tiles a cell of the random offsets spans
NEAR_LIMIT = 0.05
PERIODIC = 4              # a spacing peak this many times the spectrum's mean is a regular pattern          # a pixel at or past the vanishing point keeps this share of the near tile


def decode_grey(data):
    """A JPEG or PNG map as float32 luminance 0-255 (h, w); ValueError when it cannot be read."""
    decoded = decode(data)
    if decoded is None:
        raise ValueError('A texture map could not be read.')
    bgra, w, h = decoded
    pixels = np.frombuffer(bgra, np.uint8).reshape(h, w, 4).astype(np.float32)
    return 0.114 * pixels[..., 0] + 0.587 * pixels[..., 1] + 0.299 * pixels[..., 2]


def _box_wrap(image, radius):
    """A box blur that wraps around the edges (the maps tile), separable, by cumulative sums."""
    r = max(1, int(radius))
    out = image
    for axis in (0, 1):
        n = out.shape[axis]
        k = min(r, (n - 1) // 2)
        if k < 1:
            continue
        padded = np.concatenate([out.take(range(n - k, n), axis=axis), out, out.take(range(0, k + 1), axis=axis)], axis=axis)
        total = np.cumsum(padded, axis=axis, dtype=np.float64)
        upper = total.take(range(2 * k + 1, 2 * k + 1 + n), axis=axis)
        lower = total.take(range(0, n), axis=axis)
        out = ((upper - lower) / (2 * k + 1)).astype(np.float32)
    return out


def detail_tile(maps, detail_from=None):
    """The material's detail (h, w) float32: zero mean, unit spread, clipped at 3. `maps`: {color|displacement|ao: grey}."""
    keys = [k for k in (detail_from or WEIGHTS) if k in maps and k in WEIGHTS]
    if not keys:
        raise ValueError('A material needs its colour or displacement map.')
    shape = maps[keys[0]].shape
    base = np.zeros(shape, np.float32)
    total = 0.0
    for key in keys:
        grey = maps[key]
        if grey.shape != shape:                         # an odd map: brought to the colour map's size
            ys = (np.arange(shape[0]) * grey.shape[0] // shape[0])
            xs = (np.arange(shape[1]) * grey.shape[1] // shape[1])
            grey = grey[ys][:, xs]
        base += WEIGHTS[key] * grey
        total += WEIGHTS[key]
    base /= total
    radius = max(2, shape[1] // HIGH_PASS)
    high = base - _box_wrap(_box_wrap(base, radius // 2), radius // 2)
    high -= high.mean()
    spread = float(high.std())
    if spread < 1e-6:
        return np.zeros(shape, np.float32)
    return np.clip(high / spread, -3, 3).astype(np.float32)


def pyramid(tile):
    """The tile, then halved (2 x 2 means) while both sides stay at least MIN_LEVEL_SIDE."""
    levels = [tile.astype(np.float32)]
    while min(levels[-1].shape) >= 2 * MIN_LEVEL_SIDE and all(s % 2 == 0 for s in levels[-1].shape):
        t = levels[-1]
        levels.append(0.25 * (t[0::2, 0::2] + t[1::2, 0::2] + t[0::2, 1::2] + t[1::2, 1::2]))
    return levels


def perspective(x, y, near, far, direction_deg, vanishing, bounds):
    """For canvas pixels (x, y): (u, v, scale): u tiles along the courses, v tiles across them, scale the tile's width in px
    there. bounds [x, y, w, h]: the part's, whose near edge is the one away from the vanishing point (or direction)."""
    bx, by, bw, bh = bounds
    corners = np.array([[bx, by], [bx + bw, by], [bx, by + bh], [bx + bw, by + bh]], np.float64)
    if vanishing is not None:
        centre = np.array([bx + bw / 2.0, by + bh / 2.0])
        towards = np.array(vanishing, np.float64) - centre
        length = float(np.hypot(*towards))
        e = towards / length if length > 1e-6 else np.array([1.0, 0.0])
    else:
        angle = math.radians(direction_deg)
        e = np.array([math.cos(angle), math.sin(angle)])
    c = np.array([-e[1], e[0]])
    projections = corners @ e
    anchor = corners[int(np.argmin(projections))]
    extent = float(projections.max() - projections.min())
    a = (x - anchor[0]) * e[0] + (y - anchor[1]) * e[1]
    if vanishing is not None:
        vp = np.array(vanishing, np.float64)
        depth = float((vp - anchor) @ e)
    elif far < near and extent > 0:
        depth = extent * near / (near - far)
        vp = anchor + e * depth
    else:
        scale = np.full(np.shape(x), float(near), np.float32)
        across = (x - anchor[0]) * c[0] + (y - anchor[1]) * c[1]
        return (a / near).astype(np.float32), (across / near).astype(np.float32), scale
    k = np.maximum(NEAR_LIMIT, (depth - a) / depth)
    scale = (near * k).astype(np.float32)
    u = (depth / near) * np.log(1.0 / k)
    v = ((x - vp[0]) * c[0] + (y - vp[1]) * c[1]) / scale
    return u.astype(np.float32), v.astype(np.float32), scale


def _bilinear(level, tx, ty):
    """Wrap-around bilinear samples of `level` at texel coordinates."""
    h, w = level.shape
    x0, y0 = np.floor(tx), np.floor(ty)
    fx, fy = (tx - x0).astype(np.float32), (ty - y0).astype(np.float32)
    x0 = x0.astype(np.int64) % w; y0 = y0.astype(np.int64) % h
    x1, y1 = (x0 + 1) % w, (y0 + 1) % h
    top = level[y0, x0] * (1 - fx) + level[y0, x1] * fx
    bottom = level[y1, x0] * (1 - fx) + level[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def sample(levels, u, v, scale):
    """The material at (u, v) tiles, at the level its tile size in px asks for (blended between two levels)."""
    width = levels[0].shape[1]
    lod = np.clip(np.log2(np.maximum(width / np.maximum(scale, 1e-3), 1.0)), 0, len(levels) - 1)
    low = np.floor(lod).astype(np.int64)
    blend = (lod - low).astype(np.float32)
    out = np.zeros(np.shape(u), np.float32)
    for k in np.unique(low):
        for level, weight in ((k, 1 - blend), (min(k + 1, len(levels) - 1), blend)):
            where = low == k
            tex = levels[level]
            side = tex.shape[1]
            out[where] += weight[where] * _bilinear(tex, u[where] * side, v[where] * side)
    return out


def _hash(ix, iy, seed):
    """A repeatable value 0-1 per integer cell."""
    h = (ix * 374761393 + iy * 668265263 + seed * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF).astype(np.float32) / 65535.0


def periods(tile):
    """The material's course and joint spacing in texels (rows, columns), each None when it has no strong one: a regular
    pattern (bricks, setts, scales) is offset only by whole courses and joints, so blended cells never ghost its lines."""
    found = []
    for axis in (1, 0):
        profile = tile.mean(axis=axis)
        profile = profile - profile.mean()
        spectrum = np.abs(np.fft.rfft(profile))
        n = len(profile)
        spectrum[:3] = 0
        band = spectrum[:max(4, n // 4)]
        k = int(np.argmax(band))
        strong = k > 0 and band[k] > PERIODIC * (float(band[3:].mean()) + 1e-6)
        found.append(n / k if strong else None)
    return tuple(found)


def bombed(levels, u, v, scale, seed, spacing=(None, None)):
    """The material with no visible repeat: the (u, v) plane is cut in cells of BOMB_CELL tiles, each sampling the material
    at its own random offset (whole courses and joints for a regular pattern: `spacing`, periods()), and the four cells
    around a pixel blended smoothly (their spread kept)."""
    height, width = levels[0].shape
    rows, columns = spacing

    def offset(value, period, side):
        if not period:
            return value
        return np.floor(value * side / period) * period / width
    gu, gv = u / BOMB_CELL, v / BOMB_CELL
    iu, iv = np.floor(gu).astype(np.int64), np.floor(gv).astype(np.int64)
    fu, fv = gu - iu, gv - iv
    fu, fv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)
    total = np.zeros(np.shape(u), np.float32)
    energy = np.zeros(np.shape(u), np.float32)
    for du, dv, weight in ((0, 0, (1 - fu) * (1 - fv)), (1, 0, fu * (1 - fv)), (0, 1, (1 - fu) * fv), (1, 1, fu * fv)):
        cu, cv = iu + du, iv + dv
        du_, dv_ = offset(_hash(cu, cv, seed), columns, width), offset(_hash(cu, cv, seed + 7), rows, height)
        total += weight * sample(levels, u + du_, v + dv_, scale)
        energy += weight * weight
    return total / np.sqrt(np.maximum(energy, 1e-6))


def _noise(x, y, cell, seed):
    """Smooth value noise 0-1 at canvas pixels, `cell` px between its random values (the same everywhere for a seed)."""
    gx, gy = x / cell, y / cell
    x0, y0 = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
    fx, fy = gx - x0, gy - y0
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)

    def value(ix, iy):
        return _hash(ix, iy, seed)
    top = value(x0, y0) * (1 - fx) + value(x0 + 1, y0) * fx
    bottom = value(x0, y0 + 1) * (1 - fx) + value(x0 + 1, y0 + 1) * fx
    return (top * (1 - fy) + bottom * fy).astype(np.float32)


def feather(mask, radius):
    """The mask (uint8, 255 inside) as alpha 0-1 that fades in over about `radius` px inside its edge, 0 outside."""
    inside = (mask > 127).astype(np.float32)
    r = max(1, int(radius))
    blurred = inside
    for _ in range(2):
        for axis in (0, 1):
            n = blurred.shape[axis]
            pad = [(0, 0), (0, 0)]; pad[axis] = (r + 1, r)
            total = np.cumsum(np.pad(blurred, pad), axis=axis, dtype=np.float64)
            upper = total.take(range(2 * r + 1, 2 * r + 1 + n), axis=axis)
            lower = total.take(range(0, n), axis=axis)
            blurred = ((upper - lower) / (2 * r + 1)).astype(np.float32)
    t = np.clip((blurred - 0.5) / 0.5, 0, 1)
    return np.where(inside > 0, t * t * (3 - 2 * t), 0).astype(np.float32)


def _blend(lum, grey, mode):
    if mode == 'overlay':
        return np.where(lum < 0.5, 2 * lum * grey, 1 - 2 * (1 - lum) * (1 - grey))
    return (1 - 2 * grey) * lum * lum + 2 * grey * lum            # soft light (the pegtop form: smooth, no seam at 0.5)


def apply_detail(base, detail, alpha, strength, blend):
    """The layer's pixels (h, w, 4 BGRA uint8): the painting `base` with `detail` blended into its luminance at `strength`,
    the same change on every channel, and `alpha` (0-1) as the layer's alpha."""
    pixels = base[..., :3].astype(np.float32) / 255.0
    lum = 0.114 * pixels[..., 0] + 0.587 * pixels[..., 1] + 0.299 * pixels[..., 2]
    grey = np.clip(0.5 + CONTRAST * detail, 0, 1)
    change = np.round(strength * (_blend(lum, grey, blend) - lum) * 255).astype(np.int16)
    channels = base[..., :3].astype(np.int16)
    # Never past black or white on any channel: a clipped channel would shift the hue, so the change stops at the headroom.
    change = np.clip(change, -channels.min(axis=2), 255 - channels.max(axis=2))
    out = np.empty(base.shape, np.uint8)
    out[..., :3] = (channels + change[..., None]).astype(np.uint8)
    out[..., 3] = np.round(np.clip(alpha, 0, 1) * 255).astype(np.uint8)
    return out


def texture_part(base, mask, rect, part, progress=None):
    """One part's layer pixels over canvas `rect` [x, y, w, h] (base and mask cover it). part: materials [(levels, weight)],
    tile_near, tile_far, direction_deg, vanishing ([x, y] or None), strength, blend, seed."""
    x0, y0, w, h = rect
    alpha = feather(mask, min(24, max(2, round(0.006 * max(w, h)))))
    out = np.zeros((h, w, 4), np.uint8)
    near = float(part['tile_near'])
    far = float(part.get('tile_far', near))
    seed = int(part.get('seed', 1))
    weights = np.array([weight for _levels, weight in part['materials']], np.float32)
    norm = float(np.sqrt((weights ** 2).sum())) or 1.0
    spacing = {id(levels): periods(levels[0]) for levels, _weight in part['materials']}
    cell = max(8.0, 1.7 * near)               # the strength's own variation, in canvas px
    for top in range(0, h, STRIP):
        rows = min(STRIP, h - top)
        a = alpha[top:top + rows]
        if not a.any():
            continue
        y, x = np.mgrid[y0 + top:y0 + top + rows, x0:x0 + w].astype(np.float32)
        u, v, scale = perspective(x, y, near, far, part.get('direction_deg', 0), part.get('vanishing'), rect)
        amount = 0.7 + 0.3 * _noise(x, y, 2.3 * cell, seed + 101)
        detail = np.zeros((rows, w), np.float32)
        for (levels, weight) in part['materials']:
            detail += (weight / norm) * bombed(levels, u, v, scale, seed, spacing[id(levels)])
        out[top:top + rows] = apply_detail(base[top:top + rows], detail * amount, a, float(part['strength']), part.get('blend', 'soft_light'))
        if progress:
            progress()
    return out

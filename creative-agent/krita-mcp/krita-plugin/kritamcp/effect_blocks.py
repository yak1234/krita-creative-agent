# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The building blocks of custom effects (openspec custom-effects): an effect is a YAML recipe, never code, made of these
six tested numpy blocks. Numpy and OpenCV only, no Qt and no Krita. snow_raster supplies the scene's light, the flake
plan and renderer, the settled caps and the keep-clear fall-off; this module reuses them.

    render(canvas, blocks, shapes, keep_clear, seed=1) -> (layer BGRA uint8, report)

canvas      BGRA uint8, H x W x 4, the painting as shown.
blocks      a list of {"block": name, ...numbers already resolved}; painted in order, each composited "over" the last.
shapes      {part name: (rect [x, y, w, h], plane bytes, 255 inside)} for the parts the blocks name.
keep_clear  [(rect, plane bytes)]: nothing is painted inside them (a feathered fall-off around), applied to each block.
report      {"blocks": [{"block", "painted" (px with alpha after keep_clear), ...}], "clamped": [str], "ms": int}. A
            block that names a part that is not in `shapes` paints nothing and says so: its row has "missing": <part name>.

Hard caps, whatever a recipe asks (CAPS): 60 000 particles per call (shared by all blocks), 3 depth layers, opacity 1,
8 blocks. Anything beyond is clamped and named in report["clamped"], never a hang. Every block sizes itself from the
canvas and takes its colour from the scene light.

Block API (parameter names; every block also takes opacity 0-1, default as noted, and `within`: a part name that
confines it, nothing outside that part is painted):
  particles  layers 2|3 (3)  density >0 (1)  count (total flakes, overrides density)  wind_deg (0)  streak >=0 (1: the
             flakes' elongation along the wind times this)  colour light|local (light)  opacity (1)
             Row also has "layers": {depth: flakes}.
  wash       from top|bottom|left|right (bottom)  falloff 0-1 (0.6: the share of the canvas it fades over)
             opacity (0.5)  lower_contrast 0-1 (0: the colour moves this far from the light towards the picture's mean
             tone, so what it covers goes flatter)
  noise      scale small|medium|large (medium)  opacity (0.5)  band {"from": top|bottom|left|right, "share": 0-1}: paints
             only inside that strip of the canvas (share of the height for top/bottom, of the width for left/right), its
             inner edge softened (smoothstep over a tenth of the strip) so it does not end in a hard line
  rays       from_point [x, y] as 0-1 shares of the canvas (default: where the scene's light is) or from top|bottom|
             left|right  count (8, at most 64)  spread_deg (40)  opacity (0.5)
  texture    image (BGRA or BGR uint8 array the caller passes in)  area (a part name, required)  blend over|screen|
             multiply (over)  opacity (1)
  caps       part (a part name, required)  thickness (1: multiplies the cap's thickness)  opacity (1)
"""
import math
import time

import numpy as np

from . import snow_raster as snow

CAPS = {"particles": 60000, "layers": 3, "blocks": 8}
RAYS_MAX = 64
SMALL_SIDE = 512                  # noise, rays and washes are made at this long side and enlarged
NOISE_CELL = {'small': 0.01, 'medium': 0.04, 'large': 0.15}     # a blob's size as a share of the long side
SIDES = ('top', 'bottom', 'left', 'right')
LOCAL_WHITE = 0.3                 # particles coloured from the picture: this much of the light's white
BLENDS = ('over', 'screen', 'multiply')


def _num(params, key, default, lo, hi, clamped, block):
    """params[key] as a float within lo..hi; a value beyond is clamped and said."""
    try:
        value = float(params.get(key, default))
    except (TypeError, ValueError):
        value = float(default)
    if not math.isfinite(value):
        value = float(default)
    if value < lo or value > hi:
        clamped.append('%s %s: %g asked, %g used' % (block, key, value, min(hi, max(lo, value))))
        value = min(hi, max(lo, value))
    return value


def _shape_alpha(shape, width, height):
    """The part's mask as a full-canvas float32 0-1 plane."""
    (x, y, w, h), plane = shape
    out = np.zeros((height, width), np.float32)
    x0, y0, x1, y1 = max(0, x), max(0, y), min(width, x + w), min(height, y + h)
    if x1 > x0 and y1 > y0:
        mask = np.frombuffer(plane, np.uint8).reshape(h, w)
        out[y0:y1, x0:x1] = mask[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32) / 255
    return out


def _confine(alpha, shapes, params, row):
    """alpha (float32 H x W) times the part named by `within`; None if that part is missing."""
    name = params.get('within')
    if not name:
        return alpha
    if name not in shapes:
        row['missing'] = str(name)
        return None
    return alpha * _shape_alpha(shapes[name], alpha.shape[1], alpha.shape[0])


def _layer(colour, alpha):
    """BGRA uint8: one colour (BGR) under a float alpha 0-1."""
    out = np.empty(alpha.shape + (4,), np.uint8)
    out[..., :3] = np.clip(np.round(colour), 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(np.round(alpha * 255), 0, 255).astype(np.uint8)
    return out


def _empty(canvas):
    return np.zeros(canvas.shape[:2] + (4,), np.uint8)


def _light_white(canvas, params):
    light = params.get('_light') or snow.scene_light(canvas)
    return snow.snow_white(light[0]), light


def _enlarge(plane, width, height):
    import cv2
    return cv2.resize(plane, (width, height), interpolation=cv2.INTER_CUBIC if plane.shape[1] * 2 < width else cv2.INTER_LINEAR)


def _small_size(width, height):
    k = min(1.0, SMALL_SIDE / float(max(width, height)))
    return max(2, int(round(width * k))), max(2, int(round(height * k)))


def particles(canvas, params, shapes, rng):
    """Flakes, drops or motes in depth layers: snow_raster's plan and renderer, so it matches paint_snow."""
    import cv2
    height, width = canvas.shape[:2]
    clamped, row = params['_clamped'], {}
    layers = int(_num(params, 'layers', 3, 2, CAPS['layers'], clamped, 'particles'))
    density = _num(params, 'density', 1.0, 0.0, 1e6, clamped, 'particles')
    budget = int(params['_budget'])
    base = sum(len(f['x']) for f in snow.plan_flakes(width, height, 1.0, 0.0, layers, 1).values())
    if 'count' in params:
        density = _num(params, 'count', base, 0.0, 1e12, clamped, 'particles') / max(1, base)
    limit = budget / float(max(1, base))
    if density > limit:
        clamped.append('particles: %g asked, %d allowed in this call' % (density * base, budget))
        density = limit
    opacity = _num(params, 'opacity', 1.0, 0.0, 1.0, clamped, 'particles')
    streak = _num(params, 'streak', 1.0, 0.0, 10.0, clamped, 'particles')
    colour_mode = 'local' if params.get('colour') == 'local' else 'light'
    plan = snow.plan_flakes(width, height, density, _num(params, 'wind_deg', 0.0, -80.0, 80.0, clamped, 'particles'), layers,
                            int(params['_seed']))
    left = budget
    for name in reversed(list(plan)):                    # never more than the budget: near (large, visible) flakes are
        flakes = plan[name]                              # kept first, far ones dropped first
        n = min(len(flakes['x']), left)
        left -= n
        for key in flakes:
            flakes[key] = flakes[key][:n]
        if streak != 1.0:
            flakes['streak'] = 1.0 + (flakes['streak'] - 1.0) * streak
    row['layers'] = {name: int(len(f['x'])) for name, f in plan.items()}
    row['flakes'] = sum(row['layers'].values())
    white, _l = _light_white(canvas, params)
    alphas = {name: snow.render_layer(name, f, width, height) for name, f in plan.items() if len(f['x'])}
    confine = None
    if params.get('within'):
        confine = _confine(np.ones((height, width), np.float32), shapes, params, row)
        if confine is None:
            return _empty(canvas), row
    local_small = cv2.GaussianBlur(snow._small(canvas, 192), (0, 0), 2.0)
    out = np.zeros((height, width, 4), np.uint8)
    for top in range(0, height, snow.BAND):
        bottom = min(height, top + snow.BAND)
        local = snow._band_resize(local_small, width, height, top, bottom)
        premult = np.zeros((bottom - top, width, 3), np.float32)
        total = np.zeros((bottom - top, width, 1), np.float32)
        for name, plane in alphas.items():
            a = plane[top:bottom, :, None].astype(np.float32) / 255 * opacity
            if confine is not None:
                a = a * confine[top:bottom, :, None]
            k = snow.LAYERS[name]['white'] * (1.0 if colour_mode == 'light' else LOCAL_WHITE)
            premult = (white * k + local * (1 - k)) * a + premult * (1 - a)
            total = a + total * (1 - a)
        out[top:bottom, :, :3] = np.clip(np.round(premult / np.maximum(total, 1e-6)), 0, 255).astype(np.uint8)
        out[top:bottom, :, 3] = np.clip(np.round(total[..., 0] * 255), 0, 255).astype(np.uint8)
    return out, row


def wash(canvas, params, shapes, rng):
    """A soft veil densest at one side (mist on the ground, haze at the top), fading over `falloff` of the canvas."""
    height, width = canvas.shape[:2]
    clamped, row = params['_clamped'], {}
    side = params.get('from', 'bottom')
    side = side if side in SIDES else 'bottom'
    falloff = _num(params, 'falloff', 0.6, 0.02, 1.0, clamped, 'wash')
    opacity = _num(params, 'opacity', 0.5, 0.0, 1.0, clamped, 'wash')
    contrast = _num(params, 'lower_contrast', 0.0, 0.0, 1.0, clamped, 'wash')
    vertical = side in ('top', 'bottom')
    n = height if vertical else width
    t = (np.arange(n, dtype=np.float32) + 0.5) / n          # 0 at the top / left
    if side in ('bottom', 'right'):
        t = 1 - t
    profile = (1 - snow._smoothstep(0.0, falloff, t)) * opacity
    alpha = np.broadcast_to(profile[:, None] if vertical else profile[None, :], (height, width)).astype(np.float32)
    alpha = _confine(alpha, shapes, params, row)
    if alpha is None:
        return _empty(canvas), row
    white, _l = _light_white(canvas, params)
    mean = snow._small(canvas, 64).reshape(-1, 3).mean(axis=0)
    return _layer(white * (1 - contrast) + mean * contrast, alpha), row


def noise(canvas, params, shapes, rng):
    """Smooth cloudy noise (smoke, haze, grain of mist) in the scene's light; blobs small, medium or large."""
    import cv2
    height, width = canvas.shape[:2]
    clamped, row = params['_clamped'], {}
    scale = params.get('scale', 'medium')
    cell = NOISE_CELL.get(scale, NOISE_CELL['medium'])
    opacity = _num(params, 'opacity', 0.5, 0.0, 1.0, clamped, 'noise')
    sw, sh = _small_size(width, height)
    field = cv2.GaussianBlur(rng.standard_normal((sh, sw)).astype(np.float32), (0, 0), max(1.0, cell * max(sw, sh) / 2.0))
    field = np.clip((field - field.mean()) / max(1e-6, float(field.std())) * 0.3 + 0.5, 0, 1)
    alpha = _enlarge(field, width, height) * opacity
    band = params.get('band')
    if isinstance(band, dict) and band.get('from') in SIDES:
        alpha = alpha * _band_mask(band['from'], _num(band, 'share', 1.0, 0.0, 1.0, clamped, 'noise band'), width, height)
    alpha = _confine(alpha, shapes, params, row)
    if alpha is None:
        return _empty(canvas), row
    white, _l = _light_white(canvas, params)
    return _layer(white, np.clip(alpha, 0, 1)), row


def _band_mask(side, share, width, height):
    """A float32 H x W plane: 1 inside the strip `share` of the canvas deep from `side`, fading to 0 over the strip's inner
    tenth (smoothstep)."""
    vertical = side in ('top', 'bottom')
    length = height if vertical else width
    depth = share * length
    # distance from the strip's inner edge, in pixels, positive inside the strip
    at = (np.arange(length, dtype=np.float32) + 0.5)
    inside = (length - at if side in ('bottom', 'right') else at)
    t = np.clip((depth - inside) / max(1.0, depth * 0.1), 0.0, 1.0)
    ramp = (t * t * (3 - 2 * t)).astype(np.float32)
    return np.broadcast_to(ramp[:, None] if vertical else ramp[None, :], (height, width))


def rays(canvas, params, shapes, rng):
    """Beams (light shafts) fanning out from a source and fading with distance from it."""
    import cv2
    height, width = canvas.shape[:2]
    clamped, row = params['_clamped'], {}
    white, light = _light_white(canvas, params)
    point = params.get('from_point')
    if point is None and params.get('from') in SIDES:
        point = {'top': (0.5, -0.1), 'bottom': (0.5, 1.1), 'left': (-0.1, 0.5), 'right': (1.1, 0.5)}[params['from']]
    if point is None:
        point = light[1]
    px, py = float(point[0]), float(point[1])
    count = int(_num(params, 'count', 8, 1, RAYS_MAX, clamped, 'rays'))
    spread = _num(params, 'spread_deg', 40.0, 1.0, 170.0, clamped, 'rays')
    opacity = _num(params, 'opacity', 0.5, 0.0, 1.0, clamped, 'rays')
    sw, sh = _small_size(width, height)
    # Work in the small plane in pixels, the source at its share of the canvas; beams aim at the canvas's centre.
    sx, sy = px * sw, py * sh
    dx, dy = sw / 2.0 - sx, sh / 2.0 - sy
    base = math.atan2(dy, dx) if math.hypot(dx, dy) > 1 else math.pi / 2
    reach = math.hypot(sw, sh) * 1.5
    plane = np.zeros((sh, sw), np.float32)
    for i in range(count):
        centre = base + math.radians(spread) * ((i + rng.uniform(0.2, 0.8)) / count - 0.5)
        half = math.radians(spread) / count * rng.uniform(0.12, 0.35)
        pts = np.array([[sx, sy], [sx + reach * math.cos(centre - half), sy + reach * math.sin(centre - half)],
                        [sx + reach * math.cos(centre + half), sy + reach * math.sin(centre + half)]], np.float32)
        beam = np.zeros((sh, sw), np.float32)
        cv2.fillConvexPoly(beam, np.round(pts * 16).astype(np.int32), float(rng.uniform(0.45, 1.0)), cv2.LINE_AA, 4)
        plane = np.maximum(plane, beam)
    yy, xx = np.mgrid[0:sh, 0:sw]
    fade = np.clip(1 - np.hypot(xx - sx, yy - sy) / (math.hypot(sw, sh) * 1.1), 0, 1) ** 1.3
    plane = cv2.GaussianBlur(plane * fade.astype(np.float32), (0, 0), max(1.0, 0.012 * max(sw, sh)))
    alpha = _enlarge(plane, width, height) * opacity
    alpha = _confine(alpha, shapes, params, row)
    if alpha is None:
        return _empty(canvas), row
    return _layer(white, np.clip(alpha, 0, 1)), row


def texture(canvas, params, shapes, rng):
    """A caller-supplied image (BGRA/BGR) laid over a named part, covering it, blended over, screen or multiply."""
    import cv2
    height, width = canvas.shape[:2]
    clamped, row = params['_clamped'], {}
    name = params.get('area')
    image = params.get('image')
    if name not in shapes or image is None:
        row['missing'] = str(name if name not in shapes else 'image')
        return _empty(canvas), row
    blend = params.get('blend', 'over')
    blend = blend if blend in BLENDS else 'over'
    opacity = _num(params, 'opacity', 1.0, 0.0, 1.0, clamped, 'texture')
    (x, y, w, h), plane = shapes[name]
    image = np.asarray(image, np.uint8)
    if image.shape[2] == 3:
        image = np.dstack([image, np.full(image.shape[:2], 255, np.uint8)])
    k = max(w / float(image.shape[1]), h / float(image.shape[0]))           # cover the part's box, centred
    fit = cv2.resize(image, (max(w, int(math.ceil(image.shape[1] * k))), max(h, int(math.ceil(image.shape[0] * k)))),
                     interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
    ox, oy = (fit.shape[1] - w) // 2, (fit.shape[0] - h) // 2
    fit = fit[oy:oy + h, ox:ox + w].astype(np.float32)
    x0, y0, x1, y1 = max(0, x), max(0, y), min(width, x + w), min(height, y + h)
    out = _empty(canvas)
    if x1 <= x0 or y1 <= y0:
        return out, row
    fit = fit[y0 - y:y1 - y, x0 - x:x1 - x]
    mask = np.frombuffer(plane, np.uint8).reshape(h, w)[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32) / 255
    under = canvas[y0:y1, x0:x1, :3].astype(np.float32)
    colour = fit[..., :3]
    if blend == 'screen':
        colour = 255 - (255 - under) * (255 - colour) / 255
    elif blend == 'multiply':
        colour = under * colour / 255
    alpha = fit[..., 3] / 255 * mask * opacity
    out[y0:y1, x0:x1] = _layer(colour, alpha)
    return out, row


def caps(canvas, params, shapes, rng):
    """Settled snow, frost or dust on the upward edges of a named part: snow_raster.settled."""
    height, width = canvas.shape[:2]
    clamped, row = params['_clamped'], {}
    name = params.get('part')
    if name not in shapes:
        row['missing'] = str(name)
        return _empty(canvas), row
    thickness = _num(params, 'thickness', 1.0, 0.1, 4.0, clamped, 'caps')
    opacity = _num(params, 'opacity', 1.0, 0.0, 1.0, clamped, 'caps')
    rect, plane = shapes[name]
    pixels, at, report = snow.settled(canvas, rect, plane, seed=int(params['_seed']), amount=thickness, light=params.get('_light'))
    out = _empty(canvas)
    X, Y, W, H = at
    out[Y:Y + H, X:X + W] = pixels
    if opacity < 1.0:
        out[..., 3] = np.round(out[..., 3] * opacity).astype(np.uint8)
    if params.get('within'):
        alpha = _confine(out[..., 3].astype(np.float32) / 255, shapes, params, row)
        if alpha is None:
            return _empty(canvas), row
        out[..., 3] = np.round(alpha * 255).astype(np.uint8)
    row['caps'] = report['caps']
    return out, row


BLOCKS = {'particles': particles, 'wash': wash, 'noise': noise, 'rays': rays, 'texture': texture, 'caps': caps}


def _over(base, top):
    """`top` composited over `base` (both BGRA uint8, same size), in bands; base is changed in place."""
    for y in range(0, base.shape[0], snow.BAND):
        b, t = base[y:y + snow.BAND], top[y:y + snow.BAND]
        ta = t[..., 3:4].astype(np.float32) / 255
        if not ta.any():
            continue
        ba = b[..., 3:4].astype(np.float32) / 255
        total = ta + ba * (1 - ta)
        colour = (t[..., :3] * ta + b[..., :3] * ba * (1 - ta)) / np.maximum(total, 1e-6)
        b[..., :3] = np.clip(np.round(colour), 0, 255).astype(np.uint8)
        b[..., 3] = np.clip(np.round(total[..., 0] * 255), 0, 255).astype(np.uint8)


def _clear_weights(keep_clear, width, height):
    """[(region, weight)] for every keep_clear shape: the weight is 0 inside it, feathered back to 1 around it."""
    fall = snow.feather(width, height)
    out = []
    for (sx, sy, sw, sh), plane in keep_clear:
        region = [max(0, sx - fall), max(0, sy - fall)]
        region += [min(width, sx + sw + fall) - region[0], min(height, sy + sh + fall) - region[1]]
        if region[2] <= 0 or region[3] <= 0:
            continue
        out.append((region, snow.clear_weight(region, [((sx, sy, sw, sh), plane)], width, height, fall)))
    return out


def _clear(layer, weights):
    """Alpha taken to 0 inside every keep_clear shape (weights from _clear_weights), feathered around it."""
    for (x, y, w, h), weight in weights:
        block = layer[y:y + h, x:x + w, 3]
        block[...] = np.round(block * weight).astype(np.uint8)


def render(canvas, blocks, shapes, keep_clear, seed=1):
    """The effect's layer (BGRA uint8, canvas-sized) and its report; see the module docstring."""
    started = time.monotonic()
    clamped = []
    if len(blocks) > CAPS['blocks']:
        clamped.append('blocks: %d asked, %d used' % (len(blocks), CAPS['blocks']))
        blocks = blocks[:CAPS['blocks']]
    light = snow.scene_light(canvas)
    layer = _empty(canvas)
    weights = _clear_weights(keep_clear, canvas.shape[1], canvas.shape[0])
    rows = []
    budget = CAPS['particles']
    for index, spec in enumerate(blocks):
        name = spec.get('block')
        row = {'block': name, 'painted': 0}
        func = BLOCKS.get(name)
        if func is None:
            row['error'] = 'unknown block'
            rows.append(row)
            continue
        params = dict(spec, _clamped=clamped, _seed=int(seed) + index, _budget=budget, _light=light)
        if name == 'particles' and budget <= 0:
            clamped.append('particles: none left in this call (%d at most)' % CAPS['particles'])
            rows.append(row)
            continue
        out, extra = func(canvas, params, shapes, np.random.default_rng(int(seed) + index))
        budget -= int(extra.get('flakes', 0))
        row.update(extra)
        _clear(out, weights)                            # each block cleared before it is counted: painted is what shows
        row['painted'] = int((out[..., 3] > 0).sum())
        _over(layer, out)
        rows.append(row)
    return layer, {'blocks': rows, 'clamped': clamped, 'ms': int(round((time.monotonic() - started) * 1000))}

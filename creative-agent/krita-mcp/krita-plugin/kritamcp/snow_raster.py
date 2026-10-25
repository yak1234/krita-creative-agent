# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""paint_snow's pixels (openspec snow; the artist approved "a real snow method", 2026-10-25). Numpy and OpenCV only, no Qt
and no Krita: snow_craft.py reads the canvas, calls these and writes the layer.

Live test (2026-10-25, the Dostoevsky mock execution, 6000 x 4500, impasto oil): asked for falling snow and fresh snow on
the shoulders, hats, posts and roofs, the painter made about 20 dashes of one size and angle (read as rain or scratches),
no settled snow, a flake by the main figure's nose, and called it done after 12 strokes. A painter's snowfall is many
soft dabs at several depths, and snow lying on the tops of things:

- falling(): 2-3 depth layers. far: many small, dim, soft dabs; mid: fewer, larger, brighter; near: a few large blurred
  discs (bokeh). Each flake is a soft ellipse streaked a little along the wind (its own angle jittered), with a smaller
  brighter dab inside it for a loaded-brush look on the larger layers; positions clump gently (a low-frequency field), so
  it reads as weather, not a grid. Sizes scale with the canvas's long side and counts with its area (SCALE_SIDE), never
  below MIN_RADIUS. The colour is the scene's light (its brightest pixels) as a warm or cool white, mixed with the
  scene's local colour more for the far layer (dimmer, atmospheric). keep_clear shapes (faces) get nothing inside and a
  feathered fall-off around them.
- settled(): a cap on the upward edges of a found area's mask: each column's top edge (outside above, inside below) with
  the smoothed mask's outward normal pointing up (a gentle slope holds snow, a steep side none) gets a cap rising above
  the edge and sinking a little into the form, its thickness from the shape's width (CAP_SHARE, capped by the canvas),
  irregular along the edge (smooth noise), a slight overhang past the ends, soft edges, shaded darker where it lies over
  the form and lighter on the side the light comes from, and a soft shadow just under it on the form.
"""
import math

import numpy as np

SCALE_SIDE = 6000                 # the sizes below are for a canvas whose long side is this; counts for its proportions
                                  # (MEASURED_PIXELS), the same at any resolution
MEASURED_PIXELS = 6000 * 4500
MIN_RADIUS = 1.0                  # a flake is never smaller than this (px): a dab, never a pixel dot
# Per depth layer: flakes at density 1 on the measured canvas, radius range (px at SCALE_SIDE), peak alpha range, how much
# of the light's white (the rest the scene's local colour), streak (long axis / short axis), blur (in radii), the render
# reduction (soft layers are drawn smaller and enlarged), and whether a brighter inner dab is added.
LAYERS = {
    'far': dict(count=4200, radius=(3.0, 6.0), alpha=(0.28, 0.5), white=0.7, streak=(1.1, 1.6), soft=0.45, factor=1, dab=False),
    'mid': dict(count=1100, radius=(6.0, 16.0), alpha=(0.32, 0.62), white=0.8, streak=(1.3, 2.1), soft=0.45, factor=2, dab=True),
    'near': dict(count=55, radius=(30.0, 60.0), alpha=(0.16, 0.3), white=0.88, streak=(1.0, 1.2), soft=0.5, factor=4, dab=True),
}
DEPTHS = {3: ('far', 'mid', 'near'), 2: ('far', 'near')}
ANGLE_JITTER = 4.0                # degrees (standard deviation) each flake's fall differs from the wind's
TINT = 0.4                        # how much of the light's colour the white takes (the rest pure white)
FEATHER_SHARE = 0.01              # keep_clear's fall-off, as a share of the long side (60 px at 6000)
MIN_FEATHER = 6
BAND = 512                        # rows composited at a time (bounded memory at 27 MP)
# Settled snow. Lead review of the Dostoevsky preview (2026-10-25): the far palace roof got a thick bright band floating
# above it, every cap was a continuous rim, and the main figure's thin collar got one. So a cap is as thick as the part
# looks (its width and height on the canvas, thinner higher in the picture: further away), broken along long edges,
# melting into the form below, only on a surface that faces up over some width and has body under it, never where the
# canvas cuts the mask, and in the scene's light: warm where lit, bluish in shadow, dimmer with distance, never brighter
# than the brightest light already in the picture.
MIN_CAP = 3.0                     # a near part's cap is at least this thick (px) before distance and `amount`
MIN_THICK = 1.0                   # no cap is thinner (a hairline on a far roof)
CAP_SHARE = 0.06                  # thickness: this share of the part's size (its width, at most twice its height)
CAP_MAX_SHARE = 0.008             # at most this share of the canvas's long side (48 px at 6000)
CAP_OF_HEIGHT = 0.12              # and at most this share of the part's own height (a short far roofline: a few px)
DISTANCE = (0.35, 0.85)           # a part whose bottom is this high in the picture (share of its height) is far .. near
FAR = 0.35                        # the far end's thickness factor
RISE, SINK = 0.75, 0.3            # a cap rises this many thicknesses above the edge and sinks this many into the form
UP = (0.5, 0.95)                  # the outward normal's upward part: no snow below the first, full snow above the second
                                  # (a slope holds less: a 30-degree shoulder about two thirds)
MIN_RUN = 2.0                     # an upward edge must run at least this many thicknesses (and 5 px) wide
BODY = 0.8                        # and have at least this many thicknesses (and 2 px) of form below it
CAP_ALPHA = 0.92
SHADOW_ALPHA = 0.25
BROKEN_FROM = 20                  # an upward edge running at least this many thicknesses has gaps along its cap (a hat's
                                  # crown or a post's top stays whole, lumpy)
GAPS = 0.3                        # ... where the smooth noise is below this (0-1): about a quarter of the edge bare
COOL = np.array([1.0, 0.9, 0.8], np.float32)   # the shadow side's white, bluish (B, G, R)
AERIAL = 0.35                     # a far cap takes this much of the atmosphere's colour (aerial perspective)
FAR_DIM = 0.2                     # and is this much dimmer


def _smoothstep(lo, hi, v):
    t = np.clip((np.asarray(v, np.float32) - lo) / (hi - lo), 0, 1)
    return t * t * (3 - 2 * t)


def scale(width, height):
    return max(width, height) / float(SCALE_SIDE)


def _small(canvas, side=256):
    """The canvas (BGRA or BGR uint8) reduced to at most `side` on its long side, BGR float32."""
    import cv2
    h, w = canvas.shape[:2]
    k = min(1.0, side / float(max(w, h)))
    small = cv2.resize(np.ascontiguousarray(canvas[..., :3]), (max(1, int(round(w * k))), max(1, int(round(h * k)))), interpolation=cv2.INTER_AREA)
    return small.astype(np.float32)


def scene_light(canvas):
    """The scene's light: (BGR 0-255 of its brightest pixels, normalised so the strongest channel is 255; (x, y) of where
    they are as a share of the canvas). A sunset gives a warm light, a winter noon a cool one."""
    small = _small(canvas)
    lum = small[..., 0] * 0.114 + small[..., 1] * 0.587 + small[..., 2] * 0.299
    cut = np.percentile(lum, 98.5)
    bright = lum >= cut
    colour = small[bright].mean(axis=0)
    colour = colour * (255.0 / max(1.0, float(colour.max())))
    ys, xs = np.nonzero(bright)
    h, w = lum.shape
    return colour, ((float(xs.mean()) + 0.5) / w, (float(ys.mean()) + 0.5) / h)


def snow_white(light):
    """The light as the white of snow: pure white turned TINT of the way to the light's colour (BGR float32)."""
    return np.float32(255) * (1 - TINT) + np.asarray(light, np.float32) * TINT


def _field(rng, width, height, cells=(8, 6), lo=0.45):
    """A smooth random field (lo..1) at canvas coordinates, for clumping the flakes."""
    grid = rng.uniform(lo, 1.0, (cells[1], cells[0])).astype(np.float32)
    def sample(xs, ys):
        gx = np.clip(xs / max(1, width) * (cells[0] - 1), 0, cells[0] - 1)
        gy = np.clip(ys / max(1, height) * (cells[1] - 1), 0, cells[1] - 1)
        x0, y0 = np.floor(gx).astype(int), np.floor(gy).astype(int)
        x1, y1 = np.minimum(x0 + 1, cells[0] - 1), np.minimum(y0 + 1, cells[1] - 1)
        fx, fy = gx - x0, gy - y0
        top = grid[y0, x0] * (1 - fx) + grid[y0, x1] * fx
        bottom = grid[y1, x0] * (1 - fx) + grid[y1, x1] * fx
        return top * (1 - fy) + bottom * fy
    return sample


def plan_flakes(width, height, density=1.0, wind_deg=0.0, layers=3, seed=1):
    """{layer: {x, y, r, streak, angle, alpha}} (numpy arrays, canvas px; angle in degrees, image coordinates, 90 = down)."""
    rng = np.random.default_rng(seed)
    k = scale(width, height)
    # The picture, not its pixels: a smaller copy of the same canvas gets the same flakes, smaller (sizes follow the long
    # side); a squarer or wider picture of the same long side more or fewer, by its area in long sides.
    area = width * height / float(max(width, height) ** 2) / (MEASURED_PIXELS / float(SCALE_SIDE ** 2))
    field = _field(rng, width, height)
    plan = {}
    for name in DEPTHS[int(layers)]:
        spec = LAYERS[name]
        count = int(round(spec['count'] * area * density))
        count = max(count, 3 if name == 'near' else 8)
        xs = rng.uniform(0, width, count * 3)
        ys = rng.uniform(0, height, count * 3)
        keep = rng.uniform(0, 1, count * 3) < field(xs, ys)
        xs, ys = xs[keep][:count], ys[keep][:count]
        n = len(xs)
        lo, hi = spec['radius']
        r = np.maximum(MIN_RADIUS, rng.uniform(lo, hi, n) * k)
        streak = rng.uniform(*spec['streak'], n)
        angle = 90.0 - float(wind_deg) + rng.normal(0, ANGLE_JITTER, n)
        alpha = rng.uniform(*spec['alpha'], n)
        plan[name] = dict(x=xs, y=ys, r=r, streak=streak, angle=angle, alpha=alpha)
    return plan


def render_layer(name, flakes, width, height):
    """One depth layer's alpha (uint8, height x width): soft streaked dabs, drawn reduced for the soft layers."""
    import cv2
    spec = LAYERS[name]
    r_mid = float(np.median(flakes['r'])) if len(flakes['r']) else 1.0
    f = int(max(1, min(spec['factor'], r_mid / 2.0)))
    sw, sh = int(math.ceil(width / f)), int(math.ceil(height / f))
    plane = np.zeros((sh, sw), np.uint8)
    S = 16                                                   # cv2's fixed-point shift 4
    for x, y, r, st, a, alpha in zip(flakes['x'], flakes['y'], flakes['r'], flakes['streak'], flakes['angle'], flakes['alpha']):
        centre = (int(x / f * S), int(y / f * S))
        axes = (max(1, int(r * st / f * S)), max(1, int(r / f * S)))
        cv2.ellipse(plane, centre, axes, float(a), 0, 360, int(round(alpha * 255)), -1, cv2.LINE_AA, 4)
        if spec['dab']:                                      # the loaded brush: a smaller, brighter dab up and to the left
            inner = (int((x - 0.2 * r) / f * S), int((y - 0.2 * r) / f * S))
            cv2.ellipse(plane, inner, (max(1, int(axes[0] * 0.55)), max(1, int(axes[1] * 0.55))), float(a), 0, 360,
                        int(round(min(1.0, alpha * 1.3) * 255)), -1, cv2.LINE_AA, 4)
    sigma = max(0.5, spec['soft'] * r_mid / f)
    plane = cv2.GaussianBlur(plane, (0, 0), sigma)
    if f > 1:
        plane = cv2.resize(plane, (width, height), interpolation=cv2.INTER_LINEAR)
    return plane


def feather(width, height):
    return max(MIN_FEATHER, int(round(FEATHER_SHARE * max(width, height))))


def clear_weight(region, shapes, width, height, fall):
    """The share of snow kept in `region` [x, y, w, h] (float32 0-1): 0 inside every keep_clear shape ((rect, bytes)),
    rising to 1 over `fall` px outside it."""
    import cv2
    x, y, w, h = region
    weight = np.ones((h, w), np.float32)
    for (sx, sy, sw, sh), plane in shapes:
        mask = np.frombuffer(plane, np.uint8).reshape(sh, sw)
        # The shape and its fall-off, cut to the region.
        x0, y0 = max(x, sx - fall), max(y, sy - fall)
        x1, y1 = min(x + w, sx + sw + fall), min(y + h, sy + sh + fall)
        if x1 <= x0 or y1 <= y0:
            continue
        inside = np.zeros((y1 - y0 + 2, x1 - x0 + 2), np.uint8)       # one pixel of margin: distances measured past the cut
        ix0, iy0 = max(sx, x0), max(sy, y0)
        ix1, iy1 = min(sx + sw, x1), min(sy + sh, y1)
        if ix1 > ix0 and iy1 > iy0:
            inside[iy0 - y0 + 1:iy1 - y0 + 1, ix0 - x0 + 1:ix1 - x0 + 1] = mask[iy0 - sy:iy1 - sy, ix0 - sx:ix1 - sx] > 127
        if not inside.any():
            continue
        distance = cv2.distanceTransform((inside == 0).astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
        here = _smoothstep(0, fall, distance)
        here[inside[1:-1, 1:-1] > 0] = 0
        block = weight[y0 - y:y1 - y, x0 - x:x1 - x]
        np.minimum(block, here, out=block)
    return weight


def falling(canvas, density=1.0, wind_deg=0.0, layers=3, keep_clear=(), seed=1):
    """Falling snow over `canvas` (BGRA uint8, the painting as shown): (BGRA uint8 layer pixels, report)."""
    import cv2
    height, width = canvas.shape[:2]
    light, _where = scene_light(canvas)
    white = snow_white(light)
    plan = plan_flakes(width, height, density, wind_deg, layers, seed)
    alphas = {name: render_layer(name, flakes, width, height) for name, flakes in plan.items()}
    fall = feather(width, height)
    kept = 0
    for (sx, sy, sw, sh), plane in keep_clear:
        region = [max(0, sx - fall), max(0, sy - fall)]
        region += [min(width, sx + sw + fall) - region[0], min(height, sy + sh + fall) - region[1]]
        if region[2] <= 0 or region[3] <= 0:
            continue
        weight = clear_weight(region, [((sx, sy, sw, sh), plane)], width, height, fall)
        x, y, w, h = region
        for alpha in alphas.values():
            block = alpha[y:y + h, x:x + w]
            block[...] = np.round(block * weight).astype(np.uint8)
        for flakes in plan.values():
            inside = (flakes['x'] >= x) & (flakes['x'] < x + w) & (flakes['y'] >= y) & (flakes['y'] < y + h)
            px = np.clip(flakes['x'][inside].astype(int) - x, 0, w - 1); py = np.clip(flakes['y'][inside].astype(int) - y, 0, h - 1)
            kept += int((weight[py, px] < 0.5).sum())
    # The scene's local colour, softly: the far flakes take the most of it.
    small = _small(canvas, 192)
    local_small = cv2.GaussianBlur(small, (0, 0), 2.0)
    out = np.zeros((height, width, 4), np.uint8)
    for top in range(0, height, BAND):
        bottom = min(height, top + BAND)
        local = _band_resize(local_small, width, height, top, bottom)
        premult = np.zeros((bottom - top, width, 3), np.float32)
        total = np.zeros((bottom - top, width, 1), np.float32)
        for name in plan:                                   # far first, near on top
            a = alphas[name][top:bottom, :, None].astype(np.float32) / 255
            k = LAYERS[name]['white']
            colour = white * k + local * (1 - k)
            premult = colour * a + premult * (1 - a)
            total = a + total * (1 - a)
        out[top:bottom, :, :3] = np.clip(np.round(premult / np.maximum(total, 1e-6)), 0, 255).astype(np.uint8)
        out[top:bottom, :, 3] = np.clip(np.round(total[..., 0] * 255), 0, 255).astype(np.uint8)
    report = {'layers': {name: {'flakes': int(len(f['x'])), 'radius_px': [round(float(f['r'].min()), 1), round(float(f['r'].max()), 1)],
                                'mean_alpha': round(float(f['alpha'].mean()), 3), 'streak': round(float(np.median(f['streak'])), 2)}
                         for name, f in plan.items()},
              'light': [int(round(v)) for v in light], 'feather_px': fall, 'kept_clear': kept,
              'density': float(density), 'wind_deg': float(wind_deg)}
    return out, report


def _band_resize(small, width, height, top, bottom):
    """Rows top..bottom of `small` (BGR float32) enlarged to width x height, without enlarging the whole canvas."""
    import cv2
    sh, sw = small.shape[:2]
    ky = sh / float(height)
    # The small rows this band needs (and one either side), enlarged, then cut to the band.
    y0 = max(0, int(math.floor(top * ky - 0.5)) - 1)
    y1 = min(sh, int(math.ceil(bottom * ky + 0.5)) + 1)
    rows = small[y0:y1]
    # Map each output row to the small image's coordinate as cv2.resize does (half-pixel centres).
    ys = (np.arange(top, bottom, dtype=np.float32) + 0.5) * ky - 0.5 - y0
    xs = (np.arange(width, dtype=np.float32) + 0.5) * (sw / float(width)) - 0.5
    map_x = np.broadcast_to(xs[None, :], (bottom - top, width)).astype(np.float32)
    map_y = np.broadcast_to(ys[:, None], (bottom - top, width)).astype(np.float32)
    return cv2.remap(np.ascontiguousarray(rows), map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _noise_1d(rng, n, spacing):
    """Smooth noise (-1..1) of length n, varying over about `spacing` samples."""
    knots = rng.uniform(-1, 1, int(n / max(1.0, spacing)) + 3)
    return np.interp(np.arange(n) / max(1.0, spacing), np.arange(len(knots)), knots).astype(np.float32)


def _distance(bottom, height):
    """The thickness factor of a part whose bottom is at `bottom` on a canvas `height` tall: FAR high up, 1 low down."""
    return FAR + (1 - FAR) * float(_smoothstep(DISTANCE[0], DISTANCE[1], bottom / float(max(1, height))))


def settled(canvas, rect, plane, seed=1, amount=1.0, light=None):
    """Snow lying on the top edges of a found area (`rect` [x, y, w, h], `plane` its mask bytes, 255 inside) on `canvas`
    (BGRA uint8, the whole painting as shown). Returns (BGRA uint8 pixels, the rect they cover, report)."""
    import cv2
    height, width = canvas.shape[:2]
    x, y, w, h = (int(v) for v in rect)
    mask = (np.frombuffer(plane, np.uint8).reshape(h, w) > 127).astype(np.uint8)
    rng = np.random.default_rng(seed)
    top_cap = max(2 * MIN_CAP, CAP_MAX_SHARE * max(width, height))
    # Each piece of the shape (a post, a hat) its own thickness: its size on the canvas, its height, its distance.
    count, labels, stats, _c = cv2.connectedComponentsWithStats(mask, connectivity=8)
    thick = np.zeros(count, np.float32)
    far = np.ones(count, np.float32)
    for i in range(1, count):
        pw, ph = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
        base = float(np.clip(CAP_SHARE * min(pw, 2 * ph), MIN_CAP, top_cap))
        far[i] = _distance(y + stats[i, cv2.CC_STAT_TOP] + ph, height)
        thick[i] = max(MIN_THICK, min(base * far[i], CAP_OF_HEIGHT * ph) * float(amount))
    t_max = float(thick.max()) if count > 1 else MIN_THICK
    pad = int(math.ceil(2.2 * t_max)) + 6
    X0, Y0 = max(0, x - pad), max(0, y - pad)
    X1, Y1 = min(width, x + w + pad), min(height, y + h + pad)
    W, H = X1 - X0, Y1 - Y0
    m = np.zeros((H + 2, W), np.float32)                 # a row of margin above
    m[y - Y0 + 1:y - Y0 + 1 + h, x - X0:x - X0 + w] = mask
    lab = np.zeros((H + 2, W), np.int32)
    lab[y - Y0 + 1:y - Y0 + 1 + h, x - X0:x - X0 + w] = labels
    t_typ = float(np.median(thick[1:])) if count > 1 else MIN_THICK
    smooth = cv2.GaussianBlur(m, (0, 0), max(1.5, 0.25 * t_typ))
    gx = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy) + 1e-6
    # Top edges: inside here, outside just above (the outward normal has an upward part); never the canvas's own top row,
    # where the canvas cut the mask, not a surface.
    edge = np.zeros_like(m, bool)
    edge[1:] = (m[1:] > 0.5) & (m[:-1] < 0.5)
    if Y0 == 0:
        edge[1] = False
    weight = np.zeros_like(m)
    weight[edge] = _smoothstep(UP[0], UP[1], np.clip(gy[edge] / mag[edge], 0, 1))
    # A surface that faces up over some width, with body under it: no rim on a thin collar, no cap on a narrow spike.
    facing = (weight > 0.2).astype(np.uint8)
    n, runs, rstats, _rc = cv2.connectedComponentsWithStats(facing, connectivity=8)
    piece_t = np.zeros(n, np.float32)
    if n > 1:
        ry, rx = np.nonzero(runs)
        np.maximum.at(piece_t, runs[ry, rx], thick[lab[ry, rx]])
    wide = rstats[:, cv2.CC_STAT_WIDTH] >= np.maximum(5, MIN_RUN * piece_t)
    broken = rstats[:, cv2.CC_STAT_WIDTH] >= BROKEN_FROM * piece_t
    wide[0] = False
    ey, ex = np.nonzero(edge & (weight > 0))
    keep = wide[runs[ey, ex]]
    tt = thick[lab[ey, ex]]
    depth = np.maximum(2, np.ceil(BODY * tt)).astype(int)
    below = np.clip(ey + depth, 0, H + 1)
    keep &= m[below, ex] > 0.5
    ey, ex = ey[keep], ex[keep]
    run = runs[ey, ex]
    # Lumpy, as snow lies: a slow swell and a quicker ripple; gaps along a long piece's edge.
    wobble = 0.65 + 0.35 * (0.5 + 0.5 * _noise_1d(rng, W, max(3.0, 4.0 * t_typ))) + 0.3 * (0.5 + 0.5 * _noise_1d(rng, W, max(2.0, 1.0 * t_typ)))
    gaps = _smoothstep(GAPS - 0.08, GAPS + 0.12, 0.5 + 0.5 * _noise_1d(rng, W, max(5.0, 5.0 * t_typ)))
    t = thick[lab[ey, ex]] * weight[ey, ex] * wobble[ex] * np.where(broken[run], gaps[ex], 1)
    keep = t > 0.6
    ey, ex, t = ey[keep], ex[keep], t[keep]
    cap = np.zeros_like(m)
    if len(t):
        top_soft = np.maximum(0.7, 0.25 * t)
        bottom_soft = np.maximum(0.9, 0.5 * t)               # the lower edge melts into the form
        for k in range(-int(math.ceil(t_max * RISE * 1.3)) - 3, int(math.ceil(t_max * (SINK + 0.5))) + 4):
            rows = ey + k
            inside = (rows >= 0) & (rows < H + 2)
            value = np.clip((k + t * RISE) / top_soft + 0.5, 0, 1) * np.clip((t * SINK - k) / bottom_soft + 0.5, 0, 1)
            inside &= value > 0
            if inside.any():
                np.maximum.at(cap, (rows[inside], ex[inside]), value[inside])
        over = max(1, int(round(0.2 * t_typ)))
        cap = cv2.dilate(cap, np.ones((1, 2 * over + 1), np.uint8))
        cap = cv2.GaussianBlur(cap, (0, 0), max(0.6, 0.14 * t_typ))
    # The soft shadow just under the cap, on the form only.
    drop = max(1, int(round(0.35 * t_typ)))
    shifted = np.zeros_like(cap); shifted[drop:] = cap[:-drop]
    # A thin (far) cap casts no shadow worth painting: under a hairline it would only read as a dark outline.
    shadow = cv2.GaussianBlur(np.clip(shifted - cap, 0, 1) * m, (0, 0), max(0.7, 0.25 * t_typ)) * SHADOW_ALPHA * float(_smoothstep(3, 8, t_typ))
    # Distance per pixel (the piece under or nearest below it), for the aerial perspective.
    near = cv2.dilate(far[lab].astype(np.float32) * (lab > 0), np.ones((int(2 * t_max) + 3, 3), np.uint8), anchor=(1, 0))
    cap = cap[1:H + 1] * CAP_ALPHA; shadow = shadow[1:H + 1]; m = m[1:H + 1]; near = near[1:H + 1]
    # Colour: the light's white where the cap faces the light, a bluish white on the shadow side, darker where it lies
    # over the form, with the scene's local colour (more of it far away), never brighter than the picture's brightest.
    if light is None:
        light = scene_light(canvas)
    colour, where = light
    white = snow_white(colour)
    region = canvas[Y0:Y1, X0:X1, :3].astype(np.float32)
    local = cv2.GaussianBlur(region, (0, 0), max(2.0, 2.0 * t_typ))
    wide_smooth = cv2.GaussianBlur(m, (0, 0), max(2.0, 0.8 * t_typ))
    nx = -cv2.Sobel(wide_smooth, cv2.CV_32F, 1, 0, ksize=3); ny = -cv2.Sobel(wide_smooth, cv2.CV_32F, 0, 1, ksize=3)
    norm = np.sqrt(nx * nx + ny * ny) + 1e-6
    lx, ly = where[0] * width - (x + w / 2.0), where[1] * height - (y + h / 2.0)
    ll = math.hypot(lx, ly) or 1.0
    lit = np.clip((nx * lx + ny * ly) / (norm * ll), -1, 1)
    lit = np.where(norm > 1e-3, lit, 0)[..., None] * 0.5 + 0.5
    over_form = cv2.GaussianBlur(m, (0, 0), max(1.0, 0.3 * t_typ))
    grain = cv2.GaussianBlur(rng.uniform(-1, 1, (H, W)).astype(np.float32), (0, 0), max(0.8, 0.15 * t_typ))
    grain /= max(1e-6, float(np.abs(grain).max()))
    sunlit = white * lit + white * COOL * 0.88 * (1 - lit)
    shade = (1 - 0.16 * over_form + 0.05 * grain)[..., None]
    small = _small(canvas)
    farness = (1 - np.clip((near - FAR) / (1 - FAR), 0, 1))[..., None]
    # The atmosphere around the part (the haze it sits in, not the picture's mean: a far cap must not turn grey on a sky).
    atmosphere = cv2.GaussianBlur(region, (0, 0), max(6.0, 0.006 * max(width, height)))
    snow = sunlit * shade * (1 - FAR_DIM * farness)
    snow = snow * (1 - AERIAL * farness) + atmosphere * AERIAL * farness
    snow = snow * 0.82 + local * 0.18
    ceiling = float((small[..., 0] * 0.114 + small[..., 1] * 0.587 + small[..., 2] * 0.299).max())
    lum = snow[..., 0] * 0.114 + snow[..., 1] * 0.587 + snow[..., 2] * 0.299
    snow = np.clip(snow * np.minimum(1.0, ceiling / np.maximum(lum, 1e-3))[..., None], 0, 255)
    shade_colour = local * 0.7
    alpha = cap + shadow * (1 - cap)
    rgb = (snow * cap[..., None] + shade_colour * (shadow * (1 - cap))[..., None]) / np.maximum(alpha, 1e-6)[..., None]
    out = np.zeros((H, W, 4), np.uint8)
    out[..., :3] = np.clip(np.floor(rgb), 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(np.round(alpha * 255), 0, 255).astype(np.uint8)
    caps = cv2.connectedComponents((cap > 0.5).astype(np.uint8), connectivity=8)[0] - 1
    report = {'caps': int(caps), 'cap_px': int((cap > 0.5).sum()), 'edge_px': int(len(t)),
              'thickness_px': round(t_max, 1)}
    return out, [X0, Y0, W, H], report

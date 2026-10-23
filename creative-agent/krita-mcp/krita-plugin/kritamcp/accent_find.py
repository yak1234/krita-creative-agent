# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The accents a reference shows (paint_accents; openspec crisp-accents goals 1-4), in its own pixels (the decode
creative_reference.find_accents makes, at most TRACE_PIXELS). The companion maps them onto the canvas and paints them;
nothing here touches Krita or Qt.

- lights: small spots that shine: lightness plus chroma (a saturated sun on a sky of its own value still shines) over
  the local background (a white top-hat, its reach a share of the crop), one a peak, its core where it is at least
  half-way from the background to the peak (a big lamp's glow: three quarters, or nine tenths, its hot centre). A core
  that runs out of the reach at every level is a mass, never a light.
- glints: the same spots when the core is elongated (a streak on a wet road, a highlight on chrome), with a direction.
- darks: the same, darker than their surroundings (a gap, a deep shadow under an object): round ones are dots, long
  ones short strokes.
- lines: thin bright or dark lines (posts, masts, a spire, window frames, wires): Hessian ridges thinned to their centre,
  joined into chains and filtered as edge_trace's structure is (coherent, long or straight; texture dropped). A ridge
  beside a step between two masses has sides of different values: that is a boundary, never a line, so no shape's or
  mass's outline is ever a line and no shapes model is needed.

Colour by role: lights and glints from the brightest quarter of the core (an averaged neighbourhood dulls them), darks
from the darkest, lines from their own colour along their length (the more extreme half of the samples). Strength (0-1):
how far the accent stands out and how bright (or dark) it is against the crop's own brightest (darkest), with a little
for size or length, so a picture's lamps outrank its snow. The strength levels are relative to the strongest of a kind
in the crop (with a floor), so a quiet picture keeps its accents and a busy one only its standouts.

With a canvas view (`canvas`, at `target`: where the crop sits in it) each accent says how much the canvas there still
looks like the reference at a coarse scale (likeness 0-1), so the companion skips the ones painted over or moved.
"""
import math
import cv2
import numpy as np

try:
    from . import edge_trace
except ImportError:                       # loaded on its own (tests)
    import importlib.util
    import pathlib
    _spec = importlib.util.spec_from_file_location('edge_trace', pathlib.Path(__file__).with_name('edge_trace.py'))
    edge_trace = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(edge_trace)

KINDS = ('lights', 'glints', 'darks', 'lines')
MAX_POINTS = edge_trace.MAX_POINTS
STRENGTHS = {'bold': 0.7, 'medium': 0.45, 'subtle': 0.2}     # a share of the strongest of the kind in the crop
FLOOR = 0.12                                                 # never weaker than this, whatever the picture
CANDIDATES = 4000                                            # spot peaks examined a kind, strongest top-hat first
LINE_CANDIDATES = 400                                        # lines kept to be joined (the most contrasted length first)
REACH = 0.02                                                 # the top-hat's reach, a share of the crop's long side
NEAR = 0.003                                                 # two peaks closer than this are one spot
UNIT = 0.006                                                 # a spot this large (radius) counts as full size
CORE_LEVELS = (0.5, 0.75, 0.9)                               # a core: this far from the background to the peak
HAT = 40                                                     # top-hat of a spot (0-255) at least
ELONGATED = 2.2                                              # major over minor axis: a stroke, not a dot (darks)
GLINT_ELONGATION = 3.0                                       # a glint's direction is reliable from here; less long: a light
LENGTH = math.sqrt(12)                                       # a streak's length over the deviation of its pixels along it
GLINT_LONGEST = 0.02                                         # a longer highlight (share of the crop) is a lit ledge: dropped
GLINT_GRID, GLINTS_PER_CELL = 8, 3                           # at most this many glints in each cell of a grid on the crop
TURN, TURN_TOTAL, ZIGZAG = 25.0, 60.0, 2                    # a line turns at most this much at a corner, in all, and back
EDGE = 2                                                     # a spot this near the crop's edge is cut off: dropped
RIDGE = 20                                                   # ridge strength at least (scale-normalised curvature)
LINE_CONTRAST = 12                                           # a line differs from both sides by at least this
JOIN = 0.01                                                  # line ends this close (share of the crop) and in line join
DETAIL = 0.008                                               # fine detail: a plane minus its blur at this share of the crop
RESIDUAL_MIN = 30.0                                          # the canvas lacks an accent by at least this (0-255 units)
LINE_RESIDUAL = 0.5                                          # a thin line's gap is spread over its width: this share of it
RESIDUAL_FULL = 110.0                                        # a residual this large is full strength
REPAINTED = 25.0                                             # Lab distance, coarse: the canvas there is other paint, no gap


def _check(rgba, source, kinds, strength, max_accents):
    x, y, w, h = (int(v) for v in source)
    if not (w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= rgba.shape[1] and y + h <= rgba.shape[0]):
        raise ValueError('Source crop must fit the reference.')
    if not kinds or any(k not in KINDS for k in kinds):
        raise ValueError('kinds are some of: ' + ', '.join(KINDS))
    if strength not in STRENGTHS:
        raise ValueError('strength is one of: ' + ', '.join(STRENGTHS))
    if isinstance(max_accents, bool) or not isinstance(max_accents, int) or not 1 <= max_accents <= 1000:
        raise ValueError('max_accents must be 1-1000')
    return x, y, w, h


def _shine(rgb):
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    light = lab[..., 0]
    return light, np.clip(light + np.hypot(lab[..., 1] - 128, lab[..., 2] - 128), 0, 255)


def _spots(value, rgb, reach, near, bright):
    """Small spots standing out of `value` (0-255, larger is brighter; darker for bright=False): one a top-hat peak."""
    v = value if bright else 255 - value
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * reach + 1, 2 * reach + 1))
    base = cv2.morphologyEx(v, cv2.MORPH_OPEN, kernel)
    hat = v - base
    m = 2 * near + 1
    peaks = (hat >= HAT) & (hat >= cv2.dilate(hat, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (m, m))))
    ys, xs = np.nonzero(peaks)
    order = np.argsort(-hat[ys, xs], kind='stable')[:CANDIDATES]
    h, w = v.shape
    taken = np.zeros((h, w), bool)
    out = []
    for i in order:
        x, y = int(xs[i]), int(ys[i])
        if taken[y, x] or x < EDGE or y < EDGE or x >= w - EDGE or y >= h - EDGE:
            continue
        b, p = float(base[y, x]), float(v[y, x])
        x0, y0, x1, y1 = max(0, x - reach), max(0, y - reach), min(w, x + reach + 1), min(h, y + reach + 1)
        window = v[y0:y1, x0:x1]
        core = glow = None
        for level in (CORE_LEVELS if bright else CORE_LEVELS[:1]):   # a big lamp's glow outruns the reach, its hot centre not
            _, cc = cv2.connectedComponents((window >= b + level * (p - b)).astype(np.uint8), connectivity=8)
            found = cc == cc[y - y0, x - x0]
            glow = found if glow is None else glow
            if not ((found[0].any() and y0 > 0) or (found[-1].any() and y1 < h) or (found[:, 0].any() and x0 > 0) or (found[:, -1].any() and x1 < w)):
                core = found
                break
        if core is None:
            continue                                       # runs out of the reach at every level: a mass, not a spot
        gys, gxs = np.nonzero(glow)
        taken[gys + y0, gxs + x0] = True                   # no second spot inside the same glow
        cys, cxs = np.nonzero(core)
        taken[cys + y0, cxs + x0] = True
        weights = np.maximum(window[cys, cxs] - b, 1e-3)
        cx = float((cxs * weights).sum() / weights.sum()) + x0; cy = float((cys * weights).sum() / weights.sum()) + y0
        area = len(cys)
        if area >= 3:
            values, vectors = np.linalg.eigh(np.cov(np.vstack([cxs, cys]).astype(np.float64), aweights=weights))
            major, minor = math.sqrt(max(values[1], 0.08)), math.sqrt(max(values[0], 0.08))
            direction = vectors[:, 1]
        else:
            major = minor = 0.4; direction = np.array([1.0, 0.0])
        r = math.sqrt(area / math.pi)
        # The glow: how far the ring round the core is lifted over the background.
        inner, outer = int(math.ceil(r + 1)), int(math.ceil(3 * r + 3))
        gx0, gy0, gx1, gy1 = max(0, x - outer), max(0, y - outer), min(w, x + outer + 1), min(h, y + outer + 1)
        gy, gx = np.mgrid[gy0:gy1, gx0:gx1]
        d = np.hypot(gx - cx, gy - cy)
        ring = (d >= inner) & (d <= outer)
        far = v[max(0, y - 2 * reach):min(h, y + 2 * reach + 1):3, max(0, x - 2 * reach):min(w, x + 2 * reach + 1):3]
        ground = float(np.median(far))                     # the background well beyond the reach
        glow = float((v[gy0:gy1, gx0:gx1][ring].mean() - ground) / max(p - ground, 1)) if ring.any() else 0.0
        order = np.argsort(-window[cys, cxs], kind='stable')
        top, half = order[:max(1, area // 4)], order[:max(1, area // 2)]   # the brightest (darkest) quarter and half of the core
        colour = rgb[cys[top] + y0, cxs[top] + x0].astype(np.float64).mean(axis=0)
        broad = rgb[cys[half] + y0, cxs[half] + x0].astype(np.float64).mean(axis=0)
        out.append({'x': cx + 0.5, 'y': cy + 0.5, 'contrast': p - b, 'level': p, 'r': r, 'major': major, 'minor': minor,
                    'direction': [float(direction[0]), float(direction[1])], 'colour': colour, 'broad': broad, 'glow': max(0.0, glow)})
    return out


def _ridges(light, sigma):
    """Thin bright and dark lines at one scale: Hessian ridges thinned to their centre (non-maximum across the line)."""
    g = cv2.GaussianBlur(light, (0, 0), sigma)
    xx = cv2.Sobel(g, cv2.CV_32F, 2, 0, ksize=3); yy = cv2.Sobel(g, cv2.CV_32F, 0, 2, ksize=3); xy = cv2.Sobel(g, cv2.CV_32F, 1, 1, ksize=3)
    del g
    half = (xx + yy) / 2; root = np.sqrt(((xx - yy) / 2) ** 2 + xy ** 2)
    l1, l2 = half + root, half - root
    del half, root
    first = np.abs(l1) > np.abs(l2)
    across = np.where(first, l1, l2); along = np.where(first, l2, l1)
    del l1, l2, first
    strength = np.abs(across) * sigma * sigma
    # The normal (across the line) is the eigenvector of `across`: (xy, across - xx) or (across - yy, xy), whichever is
    # longer (the other vanishes for a line along an axis).
    ax, ay, bx, by = xy, across - xx, across - yy, xy
    second = np.hypot(bx, by) > np.hypot(ax, ay)
    nx = np.where(second, bx, ax); ny = np.where(second, by, ay)
    del ax, ay, bx, by, second
    flat = (np.abs(nx) + np.abs(ny)) < 1e-6
    nx = np.where(flat, 1.0, nx).astype(np.float32); ny = np.where(flat, 0.0, ny).astype(np.float32)
    norm = np.hypot(nx, ny); nx /= norm; ny /= norm
    h, w = light.shape
    yi, xi = np.mgrid[0:h, 0:w].astype(np.float32)
    keep = (np.abs(across) > 2.0 * np.abs(along)) & (strength >= RIDGE)
    keep &= strength >= cv2.remap(strength, xi + nx, yi + ny, cv2.INTER_LINEAR)
    keep &= strength >= cv2.remap(strength, xi - nx, yi - ny, cv2.INTER_LINEAR)
    return keep, across, nx, ny


def _sample(plane, points):
    return cv2.remap(plane, points[:, 0].astype(np.float32).reshape(1, -1), points[:, 1].astype(np.float32).reshape(1, -1),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[0]


def _direction(a, b):
    d = np.asarray(b, float) - np.asarray(a, float)
    n = float(np.hypot(*d))
    return d / n if n else d


def _join(lines, gap):
    """Pieces of one line broken by a crossing speck or a soft stretch, joined: an end of one within `gap` of an end of
    another of the same kind (bright or dark), running on in the same direction (within about 20 degrees)."""
    lines = list(lines)
    joined = True
    while joined:
        joined = False
        for i, a in enumerate(lines):
            for j in range(i + 1, len(lines)):
                b = lines[j]
                if a['bright'] != b['bright']:
                    continue
                for pa in (a['points'], a['points'][::-1]):
                    for pb in (b['points'], b['points'][::-1]):
                        # pa ends where pb starts
                        if np.hypot(*(pb[0] - pa[-1])) > gap or len(pa) < 2 or len(pb) < 2:
                            continue
                        da, db = _direction(pa[-2], pa[-1]), _direction(pb[0], pb[1])
                        bridge = _direction(pa[-1], pb[0])
                        if da @ db < 0.94 or (np.hypot(*(pb[0] - pa[-1])) > 1 and bridge @ da < 0.9):
                            continue
                        points = np.vstack([pa, pb])
                        if len(points) > MAX_POINTS:
                            points = points[np.linspace(0, len(points) - 1, MAX_POINTS).round().astype(int)]
                        total = a['length'] + b['length']
                        merged = {'points': points, 'length': total + float(np.hypot(*(pb[0] - pa[-1]))), 'bright': a['bright'],
                                  'width': max(a['width'], b['width']), 'contrast': (a['contrast'] * a['length'] + b['contrast'] * b['length']) / total,
                                  'colour': (a['colour'] * a['length'] + b['colour'] * b['length']) / total}
                        lines[i] = merged; del lines[j]; joined = True
                        break
                    if joined:
                        break
                if joined:
                    break
            if joined:
                break
    return lines


def _smooth_enough(points):
    """Nearly straight or gently curved: no corner sharper than TURN degrees, at most TURN_TOTAL in all, and no more than
    ZIGZAG changes of the turning side (a zig-zag along the line is wobble)."""
    if len(points) < 3:
        return True
    d = np.diff(points, axis=0)
    d = d[np.hypot(d[:, 0], d[:, 1]) > 1e-6]
    angles = np.degrees(np.arctan2(d[:, 1], d[:, 0]))
    turns = (np.diff(angles) + 180) % 360 - 180
    if not len(turns):
        return True
    clear = turns[np.abs(turns) >= 10]
    flips = int(np.sum(np.sign(clear[1:]) != np.sign(clear[:-1]))) if len(clear) > 1 else 0
    return float(np.abs(turns).max()) <= TURN and float(np.abs(turns).sum()) <= TURN_TOTAL and flips <= ZIGZAG


def _lines(light, rgb):
    """Thin lines (see the module note), the coarser scale first (a line a few pixels wide has one centre there, two
    flanks at the finer one); a finer line keeps away from the lines kept already."""
    h, w = light.shape
    size = max(w, h)
    shortest = max(12.0, 0.04 * size)
    kept, out = edge_trace._Band((h, w), 3), []
    for sigma in (2.0, 1.0):
        keep, across, nx, ny = _ridges(light, sigma)
        # Bright and dark ridges apart: a dark post's bright flanks would otherwise join it into one loop.
        chains = [points for ridge in (keep & (across < 0), keep & (across > 0))
                  for points in edge_trace._chains(ridge.astype(np.uint8) * 255, {'run': 6.0}, 1.0, shortest, edge_trace._Band((h, w), 2 * sigma + 1))]
        chains.sort(key=lambda points: -edge_trace._length(points))
        reach = 2 * sigma + 1.5
        for points in chains:
            centre = points - 0.5
            xs = np.clip(np.round(centre[:, 0]).astype(int), 0, w - 1); ys = np.clip(np.round(centre[:, 1]).astype(int), 0, h - 1)
            bright = float(np.median(across[ys, xs])) < 0
            normal = np.stack([nx[ys, xs], ny[ys, xs]], axis=1) * reach
            middle, one, other = _sample(light, centre), _sample(light, centre + normal), _sample(light, centre - normal)
            sign = 1 if bright else -1
            contrast = np.minimum(sign * (middle - one), sign * (middle - other))
            ok = (contrast >= LINE_CONTRAST) & (np.abs(one - other) <= np.maximum(contrast, 8))
            if ok.mean() < 0.6 or kept.free(points - 0.5).mean() < 0.5:
                continue                                   # its sides differ (a boundary between masses), or kept already
            kept.add(points - 0.5)
            if not _smooth_enough(edge_trace._simplify(points, 1.5)):
                continue                                   # zig-zags or turns sharply: wobble, never a post or a bar
            values = light[ys, xs]
            extreme = np.argsort(-values if bright else values, kind='stable')[:max(2, len(values) // 2)]
            simple = edge_trace._simplify(points, 1.0)
            if len(simple) > MAX_POINTS:
                simple = simple[np.linspace(0, len(simple) - 1, MAX_POINTS).round().astype(int)]
            out.append({'points': simple, 'contrast': float(np.median(contrast[ok])), 'length': edge_trace._length(points),
                        'width': 2.0 * sigma, 'bright': bright, 'colour': rgb[ys[extreme], xs[extreme]].astype(np.float64).mean(axis=0)})
    out.sort(key=lambda line: -line['contrast'] * line['length'])
    return _join(out[:LINE_CANDIDATES], max(6.0, JOIN * size))


def _hex(colour):
    return '#' + ''.join('%02x' % int(round(min(255, max(0, v)))) for v in colour)


def _canvas_crop(canvas, target, w, h):
    """The canvas view's `target` [x, y, w, h], resampled to the crop's w x h."""
    if canvas is None or target is None:
        raise ValueError('Finding accents needs the canvas view (canvas and target): accents go only where the canvas lacks a sharp '
                         'light or dark the reference has. Look at the canvas first.')
    tx, ty, tw, th = (int(v) for v in target)
    ch, cw = canvas.shape[:2]
    if not (tw > 0 and th > 0 and tx >= 0 and ty >= 0 and tx + tw <= cw and ty + th <= ch):
        raise ValueError('The canvas target must fit the canvas view.')
    view = np.ascontiguousarray(canvas[ty:ty + th, tx:tx + tw, :3])
    return cv2.resize(view, (w, h), interpolation=cv2.INTER_AREA if tw > w else cv2.INTER_LINEAR)


def _detail(plane, sigma):
    """The fine detail of a plane: itself minus its blur at the accent scale."""
    return plane - cv2.GaussianBlur(plane, (0, 0), sigma)


def _peak(plane, x, y, radius):
    h, w = plane.shape
    r = int(math.ceil(radius))
    x0, y0, x1, y1 = max(0, int(x) - r), max(0, int(y) - r), min(w, int(x) + r + 1), min(h, int(y) + r + 1)
    return float(plane[y0:y1, x0:x1].max()) if x1 > x0 and y1 > y0 else 0.0


def find(rgba, source, kinds=KINDS, strength='medium', max_accents=200, canvas=None, target=None):
    """Accents of the crop `source` [x, y, w, h] of `rgba` (H x W x 4 uint8), positions and sizes in rgba's pixels.

    canvas: an RGB(A) view of the canvas (required), `target` [x, y, w, h] where the crop sits in it. An accent is kept
    only where the canvas lacks it: the residual (the reference's fine detail minus the canvas's, at the accent scale)
    is at least RESIDUAL_MIN there, and it is the accent's strength. Returns {accents: [{kind, x, y, size, colour,
    strength, residual, shape (dot | stroke), direction, length, glow, points (lines), bright (lines)}], found: {kind:
    count kept}}: at most max_accents of each kind, strongest first."""
    x0, y0, w, h = _check(rgba, source, kinds, strength, max_accents)
    rgb = np.ascontiguousarray(rgba[y0:y0 + h, x0:x0 + w, :3])
    seen = _canvas_crop(canvas, target, w, h)
    if min(w, h) < 8:
        return {'accents': [], 'found': {k: 0 for k in kinds}}
    soft = cv2.GaussianBlur(rgb, (0, 0), 0.8)
    light, shine = _shine(soft)
    seen_light, seen_shine = _shine(cv2.GaussianBlur(seen, (0, 0), 0.8))
    del soft
    size = max(w, h)
    sigma = max(2.0, DETAIL * size)
    # Positive: the reference shines (or is lighter) there in fine detail and the canvas does not; darks the other way.
    shine_gap = _detail(shine, sigma) - _detail(seen_shine, sigma)
    light_gap = _detail(light, sigma) - _detail(seen_light, sigma)
    # Where the canvas is other paint (repainted, moved), there is nothing of the reference to sharpen: no gap there.
    lab = lambda image: cv2.cvtColor(cv2.GaussianBlur(image, (0, 0), 3 * sigma), cv2.COLOR_RGB2LAB).astype(np.float32) * np.array([100 / 255, 1, 1], np.float32)
    other = np.linalg.norm(lab(rgb) - lab(seen), axis=2) > REPAINTED
    shine_gap[other] = 0; light_gap[other] = 0
    del seen_light, seen_shine, seen, other
    reach, near, unit = max(4, int(round(REACH * size))), max(2, int(round(NEAR * size))), max(1.0, UNIT * size)
    found = []
    if 'lights' in kinds or 'glints' in kinds:
        for s in _spots(shine, rgb, reach, near, True):
            stroke = s['major'] / max(s['minor'], 0.4) >= GLINT_ELONGATION
            if stroke and LENGTH * s['major'] > GLINT_LONGEST * size:
                continue                                   # a long highlight is a lit ledge or rim: paint, not a glint
            kind = 'glints' if stroke else 'lights'
            if stroke:
                s = dict(s, colour=s['broad'])             # a streak's colour from the half of its core: never whiter
            if kind in kinds:
                found.append(dict(s, kind=kind, stroke=stroke, residual=_peak(shine_gap, s['x'] - 0.5, s['y'] - 0.5, max(1.5, s['r']))))
    if 'darks' in kinds:
        for s in _spots(light, rgb, reach, near, False):
            stroke = s['major'] / max(s['minor'], 0.4) >= ELONGATED
            found.append(dict(s, kind='darks', stroke=stroke, residual=_peak(-light_gap, s['x'] - 0.5, s['y'] - 0.5, max(1.5, s['r']))))
    if 'lines' in kinds:
        for line in _lines(light, rgb):
            middle = line['points'][len(line['points']) // 2]
            pts = np.asarray(line['points'], np.float64) - 0.5
            dense = np.vstack([np.linspace(a, b, max(2, int(np.hypot(*(b - a))) + 1)) for a, b in zip(pts[:-1], pts[1:])])
            gap = _sample(light_gap if line['bright'] else -light_gap, dense)
            found.append(dict(line, kind='lines', x=float(middle[0]), y=float(middle[1]), residual=float(np.median(gap))))
    accents, counts = [], {}
    for a in found:
        a['score'] = min(1.0, a['residual'] / RESIDUAL_FULL)
    for a in found:                                    # a line's residual counts as its share: the gap is spread over its width
        if a['kind'] == 'lines':
            a['residual'] /= LINE_RESIDUAL
            a['score'] = min(1.0, a['residual'] / RESIDUAL_FULL)
    found = [a for a in found if a['residual'] >= RESIDUAL_MIN]       # the canvas has it already (or was repainted)
    for kind in kinds:
        mine = sorted((a for a in found if a['kind'] == kind), key=lambda a: -a['score'])
        floor = max(FLOOR, STRENGTHS[strength] * mine[0]['score']) if mine else 1
        mine = [a for a in mine if a['score'] >= floor]
        if kind == 'glints':                               # never a sprinkle: a few glints in each part of the picture
            cells = {}
            def room(a):
                key = (int(a['x'] * GLINT_GRID / w), int(a['y'] * GLINT_GRID / h))
                cells[key] = cells.get(key, 0) + 1
                return cells[key] <= GLINTS_PER_CELL
            mine = [a for a in mine if room(a)]
        counts[kind] = len(mine)
        for a in mine[:max_accents]:
            out = {'kind': kind, 'x': round(a['x'] + x0, 2), 'y': round(a['y'] + y0, 2), 'colour': _hex(a['colour']), 'strength': round(a['score'], 3),
                   'residual': round(a['residual'], 1)}
            if kind == 'lines':
                out.update(points=[[round(float(px) + x0, 2), round(float(py) + y0, 2)] for px, py in a['points']], size=a['width'],
                           length=round(a['length'], 2), bright=a['bright'], shape='stroke')
            else:
                out.update(shape='stroke' if a['stroke'] else 'dot', direction=[round(v, 4) for v in a['direction']],
                           size=round(max(1.5, 2 * a['r']) if not a['stroke'] else max(1.2, 2.5 * a['minor']), 2),
                           length=round(max(3.0, LENGTH * a['major']), 2), glow=round(min(1.0, a['glow']), 3))
            accents.append(out)
    accents.sort(key=lambda a: -a['strength'])
    return {'accents': accents, 'found': counts}

# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Goal dabs (openspec architecture-texture goal 9; the artist 2026-10-25: "krita patterns when it can grab brushes from
images"). For each architectural part a few real impasto dabs are cut from the goal at the part's found area and the
Finish's form strokes in that part (finish_pass.strokes_for, Toska's own baked strokes) are stamped with them along their
path instead of a plain line, so stroke edges break up like the goal's paint.

- Cutting (cut_dabs): the goal crop's luminance high-passed by a mask-normalised Gaussian (patch / 3: light and shading
  go), its local spread over a patch (PATCH goal px, patch_for: about DAB_CANVAS_PX canvas px, MIN_PATCH-MAX_PATCH goal px)
  is the edge energy typical of impasto. Up to MOST_DABS patches with the most of it (ENERGY_MIN at least, at least a patch
  apart, wholly inside the part with the blur's reach around them) each become an alpha shape: the high-pass of the
  patch's dominant sign, normalised and softly thresholded, the blob nearest its centre kept, centred and scaled into a
  TIP_SIDE square, feathered and faded to nothing at the tip's edge. A speck or a fill is no dab. A flat part gives none.
- Registering (register): each one with the fork's Krita.createBrushTip(image, "Goal dab: <part> <n>", 'alpha') (libkis
  KritaAgentResources.cpp: added to the resource database, tagged Agent), so the artist sees and can use the same tip.
  Without it (stock Krita) or when it refuses, the dab is still kept here for the strokes.
- Stamping (strips, dab_mask): per dab set, strips are pre-rendered once (cached): for each unit width in UNITS, each
  stroke length of 0-LONGEST widths and VARIANTS random variants, the dabs stamped every SPACING of the width from start to
  end (rotation and size jittered, combined by max), scaled so the strip covers about what a plain line of that width
  does. A stroke then is one affine warp of the strip of its length onto its chord (two for a bent stroke): rotated to
  its direction, scaled to its width, about as fast as drawing the plain line. The dab reaches at most DAB_REACH of the
  width from the stroke's line (finish_pass.sizes(dabbed=True) pads tiles by it).

Pure numpy/OpenCV but for register and dab_alpha (Qt images); tests/test_goal_dabs.py.
"""
import hashlib
import math

import numpy as np

PREFIX = 'Goal dab: '
DAB_CANVAS_PX = 40         # a dab's patch in canvas px (an impasto dab of the 6000 px painting)
MIN_PATCH, MAX_PATCH = 9, 25
PATCH = 15                 # goal px, when the goal's enlargement is not known
ENERGY_MIN = 6.0           # luminance levels: the high-pass spread over a patch; flat paint and JPEG noise stay under 2
MOST_DABS = 3
TIP_SIDE = 64              # px of a dab's alpha square
SPACING = 0.3              # stamps a width apart along a stroke
UNITS = (4, 8, 16, 32)     # strip widths: a stroke uses the smallest at least its width
LONGEST = 10               # strips up to this many widths long; longer strokes stretch the longest
VARIANTS = 2
RADIUS = 0.75              # a dab's reach from its centre, in widths
SIZE_JITTER = (0.85, 1.15)
ANGLE_JITTER = 25.0        # degrees
DAB_REACH = 0.9            # RADIUS times the largest size jitter, and a little: how far a stamped stroke reaches
BENT = 0.35                # a stroke whose line leaves its chord by more than this of its width is stamped in two

_MADE = {}                 # tip name -> alpha (TIP_SIDE, TIP_SIDE) float32, this Krita session
_STRIPS = {}               # digest of a dab set -> its strips


def _luminance(bgr):
    pixels = bgr.astype(np.float32)
    return 0.114 * pixels[..., 0] + 0.587 * pixels[..., 1] + 0.299 * pixels[..., 2]


def patch_for(scale):
    """The patch side in goal px for a goal drawn `scale` canvas px a goal px."""
    return int(min(MAX_PATCH, max(MIN_PATCH, round(DAB_CANVAS_PX / max(scale, 1e-6)))))


def _smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def _shape(detail):
    """One patch's high-pass (P x P) as a dab: alpha (TIP_SIDE, TIP_SIDE) float32 0-1, or None (a speck, a fill)."""
    import cv2
    p = detail.shape[0]
    ys, xs = np.mgrid[:p, :p].astype(np.float32)
    c = (p - 1) / 2
    near = np.exp(-((xs - c) ** 2 + (ys - c) ** 2) / (2 * (p / 4) ** 2))
    peak = np.unravel_index(int(np.argmax(np.abs(detail) * near)), detail.shape)
    value = detail * (1 if detail[peak] >= 0 else -1)
    positive = value[value > 0]
    if positive.size < 4:
        return None
    top = float(np.percentile(positive, 90))
    if top <= 0:
        return None
    alpha = _smoothstep(0.25, 0.65, np.clip(value / top, 0, 1)).astype(np.float32)
    count, labels = cv2.connectedComponents((alpha > 0.3).astype(np.uint8), connectivity=8)
    if count <= 1:
        return None
    weights = np.bincount(labels.ravel(), weights=(near * alpha).ravel(), minlength=count)
    weights[0] = 0
    best = int(np.argmax(weights))
    blob = labels == best
    if blob.sum() < 4:
        return None
    keep = cv2.dilate(blob.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)
    alpha = alpha * keep
    total = float(alpha.sum())
    cx, cy = float((alpha * xs).sum() / total), float((alpha * ys).sum() / total)
    seen = alpha > 0.05
    extent = float(np.sqrt(((xs[seen] - cx) ** 2 + (ys[seen] - cy) ** 2).max())) + 0.5
    # Centred and scaled so its farthest reach is 0.42 of the tip, feathered, faded to nothing at the tip's edge.
    f = 0.42 * TIP_SIDE / extent
    t = (TIP_SIDE - 1) / 2
    matrix = np.array([[f, 0, t - f * cx], [0, f, t - f * cy]], np.float32)
    tip = cv2.warpAffine(alpha, matrix, (TIP_SIDE, TIP_SIDE), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    tip = cv2.GaussianBlur(tip, (0, 0), TIP_SIDE / 40)
    ty, tx = np.mgrid[:TIP_SIDE, :TIP_SIDE].astype(np.float32)
    r = np.hypot(tx - t, ty - t)
    tip *= np.clip((0.49 * TIP_SIDE - r) / (0.07 * TIP_SIDE), 0, 1)
    if tip.max() < 0.5:
        return None
    tip = np.clip(tip / tip.max(), 0, 1).astype(np.float32)
    cover = float((tip > 0.5).mean())
    return tip if 0.05 < cover < 0.75 else None


def cut_dabs(bgr, mask=None, patch=PATCH, most=MOST_DABS):
    """Up to `most` dabs from a goal crop (h, w, 3 BGR uint8) inside the part's mask over it (h, w, 255 inside; None: all
    of it): [(alpha (TIP_SIDE, TIP_SIDE) float32 0-1, energy)], strongest first; [] for a flat or small part."""
    import cv2
    lum = _luminance(bgr)
    h, w = lum.shape
    inside = np.ones((h, w), np.float32) if mask is None else (np.asarray(mask) > 127).astype(np.float32)
    sigma = patch / 3.0
    reach = int(math.ceil(2 * sigma))
    window = patch + 2 * reach                          # the patch and its blur's reach: all inside the part
    if min(h, w) < window:
        return []
    blur = lambda image: cv2.GaussianBlur(image, (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
    low = blur(lum * inside) / np.maximum(blur(inside), 1e-3)
    detail = (lum - low) * inside
    energy = np.sqrt(np.maximum(cv2.boxFilter(detail * detail, -1, (patch, patch), borderType=cv2.BORDER_CONSTANT), 0))
    cover = cv2.boxFilter(inside, -1, (window, window), borderType=cv2.BORDER_CONSTANT)
    score = np.where(cover >= 0.98, energy, 0).astype(np.float32)
    edge = window // 2
    score[:edge] = 0; score[h - edge:] = 0; score[:, :edge] = 0; score[:, w - edge:] = 0
    half = patch // 2
    found = []
    for _ in range(4 * most):
        if len(found) >= most:
            break
        y, x = np.unravel_index(int(np.argmax(score)), score.shape)
        strength = float(score[y, x])
        if strength < ENERGY_MIN:
            break
        score[max(0, y - patch):y + patch + 1, max(0, x - patch):x + patch + 1] = 0
        alpha = _shape(detail[y - half:y - half + patch, x - half:x - half + patch])
        if alpha is not None:
            found.append((alpha, strength))
    return found


def tip_name(part, n):
    return (PREFIX + ' '.join(str(part).split()))[:110] + ' %d' % n


def tip_image(alpha):
    """The dab as the image Krita makes an 'alpha' brush tip from: black, its coverage in the alpha channel."""
    from .qt_compat import QImage
    side = alpha.shape[0]
    pixels = np.zeros((side, side, 4), np.uint8)
    pixels[..., 3] = np.round(np.clip(alpha, 0, 1) * 255)
    return QImage(pixels.tobytes(), side, side, side * 4, QImage.Format.Format_ARGB32).copy()


def register(app, part, crop, mask, scale):
    """The part's dabs cut from its goal crop, registered as brush tips where Krita can make them, kept for the strokes
    either way: their names (the name Krita gave each), [] when the part gave none."""
    names = []
    for n, (alpha, _energy) in enumerate(cut_dabs(crop, mask, patch_for(scale)), 1):
        name = tip_name(part, n)
        if hasattr(app, 'createBrushTip'):
            resource = app.createBrushTip(tip_image(alpha), name, 'alpha')
            if resource is not None:
                name = resource.name()
        _MADE[name] = alpha
        names.append(name)
    return names


def dab_alpha(app, name):
    """A dab's alpha by its tip name: the one cut in this session, else the brush tip resource's image (after a plugin
    reload), else None."""
    if name in _MADE:
        return _MADE[name]
    try:
        resource = app.resources('brush').get(name)
    except Exception:
        return None
    if resource is None:
        return None
    import cv2
    from .qt_compat import QImage, image_bytes
    image = resource.image()
    if image is None or image.isNull():
        return None
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    data = np.frombuffer(image_bytes(image), np.uint8).reshape(image.height(), image.width(), 4)
    alpha = data[..., 3].astype(np.float32)
    if alpha.min() >= 255:                              # a grey tip: dark is paint
        alpha = 255 - _luminance(data[..., :3])
    alpha = cv2.resize(alpha / 255, (TIP_SIDE, TIP_SIDE), interpolation=cv2.INTER_AREA)
    return np.clip(alpha, 0, 1).astype(np.float32) if alpha.max() > 0 else None


def _stamped(alphas, unit, n, variant, factors):
    """One strip: the dabs stamped from x = R to R + n * unit along y = R (max), and R."""
    import cv2
    reach = int(math.ceil(RADIUS * SIZE_JITTER[1] * unit)) + 2
    strip = np.zeros((2 * reach + 1, n * unit + 2 * reach + 1), np.float32)
    count = max(1, int(math.ceil(n / SPACING))) if n else 0
    rng = np.random.default_rng(1009 * variant + 31 * n + unit)
    t = (TIP_SIDE - 1) / 2
    side = 2 * reach + 1
    for i in range(count + 1):
        k = (variant + i) % len(alphas)
        x = reach + (n * unit * i / count if count else 0)
        y = reach + rng.uniform(-0.05, 0.05) * unit
        matrix = cv2.getRotationMatrix2D((t, t), float(rng.uniform(-ANGLE_JITTER, ANGLE_JITTER)), factors[k] * unit * float(rng.uniform(*SIZE_JITTER)))
        left = int(math.floor(x)) - reach
        matrix[0, 2] += x - left - t
        matrix[1, 2] += y - t
        stamp = cv2.warpAffine(alphas[k], matrix, (side, side), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        lo, hi = max(0, left), min(strip.shape[1], left + side)
        view = strip[:, lo:hi]
        np.maximum(view, stamp[:, lo - left:hi - left], out=view)
    return strip, reach


def strips(alphas):
    """The pre-rendered strips of a dab set (see the header): {(unit, widths long, variant): (strip, R)}, cached."""
    digest = hashlib.sha256(b''.join(np.ascontiguousarray(a, np.float32).tobytes() for a in alphas)).hexdigest()
    if digest in _STRIPS:
        return _STRIPS[digest]
    t = (TIP_SIDE - 1) / 2
    ys, xs = np.mgrid[:TIP_SIDE, :TIP_SIDE].astype(np.float32)
    factors = []
    for alpha in alphas:
        # Tip px to widths: the dab's area that of a disc a width across, its reach at most RADIUS of a width.
        diameter = 2 * math.sqrt(float(alpha.sum()) / math.pi)
        far = float(np.hypot(xs - t, ys - t)[alpha > 0.02].max())
        factors.append(min(1 / diameter, RADIUS / far))
    # Calibrated once on the longest strip: covering what a plain line of the width covers.
    unit = UNITS[-1]
    strip, _r = _stamped(alphas, unit, LONGEST, 0, factors)
    plain = LONGEST * unit * unit + math.pi * unit * unit / 4
    k = float(strip.sum()) / plain
    factors = [min(f / k, RADIUS / float(np.hypot(xs - t, ys - t)[a > 0.02].max())) for f, a in zip(factors, alphas)]
    out = {(unit, n, v): _stamped(alphas, unit, n, v, factors) for unit in UNITS for n in range(LONGEST + 1) for v in range(VARIANTS)}
    if len(_STRIPS) > 32:
        _STRIPS.clear()
    _STRIPS[digest] = out
    return out


def _segment(start, end, width, rect, table, variant):
    import cv2
    unit = next((u for u in UNITS if u >= width), UNITS[-1])
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    n = min(LONGEST, int(length / width + 0.5))
    if n == 0:
        start = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    strip, reach = table[(unit, n, variant)]
    ux, uy = (dx / length, dy / length) if length > 1e-6 else (1.0, 0.0)
    along = n * unit / length if n else unit / width
    across = unit / width
    left, top, w, h = rect
    qx, qy = left - start[0], top - start[1]
    matrix = np.array([[along * ux, along * uy, reach + along * (qx * ux + qy * uy)],
                       [-across * uy, across * ux, reach + across * (-qx * uy + qy * ux)]], np.float64)
    return cv2.warpAffine(strip, matrix, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def bent(points, first, last, widths):
    """Which strokes (points (n, k, 2), their first and last valid index) leave their chord by more than BENT of their
    width: those are stamped in two halves."""
    n = len(points)
    if not n:
        return np.zeros(0, bool)
    rows = np.arange(n)
    p0, p1 = points[rows, first], points[rows, last]
    d = p1 - p0
    length = np.hypot(d[:, 0], d[:, 1])
    rel = points - p0[:, None]
    off = np.abs(rel[..., 0] * d[:, None, 1] - rel[..., 1] * d[:, None, 0]) / np.maximum(length, 1e-6)[:, None]
    k = np.arange(points.shape[1])[None, :]
    off[(k < first[:, None]) | (k > last[:, None])] = 0
    return (off.max(1) > BENT * widths) & (length > 1e-6) & (last - first >= 2)


def dab_mask(poly, width, rect, table, variant, bends=None):
    """A stroke's alpha (float32 0-1) over canvas `rect` [x, y, w, h]: its line `poly` (n, 2, canvas px) stamped with the
    dabs of `table` (strips) at `width`. Its chord, or its two halves when it bends (`bends`: known already, see bent)."""
    width = float(width)
    if bends is None:
        bends = bool(bent(poly[None], np.array([0]), np.array([len(poly) - 1]), np.array([width]))[0])
    first, last = poly[0].tolist(), poly[-1].tolist()
    if bends:
        middle = poly[len(poly) // 2].tolist()
        a = _segment(first, middle, width, rect, table, variant)
        return np.maximum(a, _segment(middle, last, width, rect, table, variant), out=a)
    return _segment(first, last, width, rect, table, variant)

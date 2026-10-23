# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Guide lines from a reference at full resolution (draw_guide from_reference; openspec sharper-guides goals 2 and 3).

The companion maps the lines onto the canvas and draws them; this module only finds them, in the reference's own pixels
(the decode creative_reference.trace_edges makes, at most TRACE_PIXELS). Nothing here touches Krita or Qt.

- outlines: the boundary of each shape the companion found with the shapes model (`labels`, one id a shape, 0 for
  none); without shapes, a part's alpha; without either, a brightness split (Otsu) when the crop is clearly two-toned.
  A border two shapes share is drawn once; the crop's own edge is never an outline.
- structure: Canny edges of an edge-preserving (bilateral) smoothing, on the colour difference (Lab), so a blue tower on
  a blue sky has edges where a brightness split sees none. Edge pixels become chains; a chain that wanders (texture) is
  dropped, a long or straight one is kept: thin tall parts (spires, masts, poles) are straight, so they stay even
  short. With `inside`, only the structure inside the one shape.
- lights: the outlines of the brightest shapes (light sources, lit faces), as before.
Simplification (Douglas-Peucker), the shortest chain kept and the band two lines must keep apart are measured on the
canvas (`scale`: canvas pixels a reference pixel), so an element drawn large keeps more of its shape. Every line has
at most MAX_POINTS points (draw_guide's own limit), and at most `max_lines` lines are kept: outlines first, then the
longest structure.
"""
import math
import cv2
import numpy as np

MAX_POINTS = 64                 # guide-tool.ts GUIDE_POINTS
LIGHT_LIMIT = 8
TWO_TONE = 0.72                 # Otsu separability a crop needs before its brightness split is a silhouette
SPLIT_SIDE = 360                # the block-mean copy that decides it (texture noise there is about 0.64)
# On the canvas (pixels of the traced area drawn there): simplification, the shortest chain kept (share of the area's
# size), a chain's run between corners (multiples of the simplification; shorter runs are texture), the smallest
# shape kept (share of the crop's area), Canny's thresholds (Lab Sobel magnitude: the high one at least this, and at
# least this percentile of the crop's gradients).
DETAIL = {
    'simple': {'epsilon': 2.0, 'epsilon_share': 0.003, 'chain': 0.08, 'run': 8.0, 'area': 0.004, 'light_area': 0.002,
               'high': 90.0, 'percentile': 92.0},
    'medium': {'epsilon': 1.2, 'epsilon_share': 0.0015, 'chain': 0.04, 'run': 8.0, 'area': 0.0012, 'light_area': 0.0005,
               'high': 60.0, 'percentile': 85.0},
}
LOW = 0.4                       # Canny's low threshold, a share of the high one: contours run on through soft stretches
COARSE = 0.0015                 # the coarse scale's blur, a share of the crop's long side
OUTLINE_REACH = 2               # an edge this many bands from an outline is the same contour again: not structure
COHERENT = 0.8                  # a chain's mean local chord over arc (_coherence): below it, texture
STRAIGHT = 0.95                 # end-to-end over length: a chain this straight is kept at half the shortest length


def _luma(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def _otsu(values):
    """Otsu's threshold of values 0-255 (float) and its separability (between-class over total variance)."""
    if values.size < 4 or float(values.var()) < 1:
        return 255.0, 0.0
    hist = np.bincount(np.clip(values, 0, 255).astype(np.int64), minlength=256).astype(np.float64)
    p = hist / hist.sum(); levels = np.arange(256, dtype=np.float64)
    w = np.cumsum(p); mu = np.cumsum(p * levels); total = mu[-1]
    with np.errstate(divide='ignore', invalid='ignore'):
        between = (total * w - mu) ** 2 / (w * (1 - w))
    between[~np.isfinite(between)] = 0
    t = int(np.argmax(between))
    return t + 0.5, float(between[t] / (values.var() * 1.0))


def _drop_small(mask, area):
    """mask (bool) without components (8-connected) smaller than area, and without holes smaller than area."""
    for value in (True, False):
        target = (mask == value).astype(np.uint8)
        n, cc, stats, _ = cv2.connectedComponentsWithStats(target, connectivity=8 if value else 4)
        small = np.zeros(n, bool); small[1:] = stats[1:, cv2.CC_STAT_AREA] < area
        if small.any():
            mask = np.where(small[cc], not value, mask)
    return mask


def _length(points):
    d = np.diff(points, axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum()) if len(points) > 1 else 0.0


def _simplify(points, epsilon, closed=False):
    """Douglas-Peucker (OpenCV) of an (N, 2) float polyline; a closed one keeps its closing point."""
    if len(points) < 3:
        return points
    out = cv2.approxPolyDP(points.astype(np.float32).reshape(-1, 1, 2), float(epsilon), closed)[:, 0, :].astype(np.float64)
    if closed and len(out) > 1:
        out = np.vstack([out, out[:1]])
    return out


def _runs(points, keep, closed):
    """The pieces of a polyline where `keep` holds (consecutive points), a closed one joined across its start."""
    if keep.all():
        return [np.vstack([points, points[:1]]) if closed else points]
    pieces, start = [], None
    for i, k in enumerate(keep):
        if k and start is None:
            start = i
        if (not k or i == len(keep) - 1) and start is not None:
            pieces.append([start, i + 1 if k else i])
            start = None
    if closed and len(pieces) > 1 and pieces[0][0] == 0 and pieces[-1][1] == len(points):
        last = pieces.pop()
        return [np.vstack([points[last[0]:], points[:pieces[0][1]]])] + [points[a:b] for a, b in pieces[1:]]
    return [points[a:b] for a, b in pieces]


class _Band:
    """Where lines are drawn already: a later line keeps `width` pixels away from them (a shared border once)."""
    def __init__(self, shape, width):
        self.mask = np.zeros(shape, np.uint8); self.width = max(1, int(round(width)))

    def free(self, points):
        h, w = self.mask.shape
        xs = np.clip(points[:, 0].astype(np.int64), 0, w - 1); ys = np.clip(points[:, 1].astype(np.int64), 0, h - 1)
        return self.mask[ys, xs] == 0

    def add(self, points, reach=1):
        cv2.polylines(self.mask, [np.round(points).astype(np.int32).reshape(-1, 1, 2)], False, 1, 2 * self.width * reach + 1)


def _outlines(regions, ids, crop, settings, band, shortest):
    """Boundaries of each region id (smallest first, so a figure keeps its own outline against the mass behind it), in
    crop pixels: not along the crop's edge, not where a line is drawn already, chains at least half `shortest`."""
    h, w = regions.shape
    area = max(16.0, settings['area'] * h * w)
    order = sorted(ids, key=lambda i: int((regions == i).sum()))
    out = []
    for i in order:
        mask = _drop_small(regions == i, area)
        if not mask.any() or mask.all():
            continue
        contours, hierarchy = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        for contour in contours:
            points = contour[:, 0, :].astype(np.float64)
            if len(points) < 3:
                continue
            edge = max(2, band.width)
            inner = (points[:, 0] > edge) & (points[:, 1] > edge) & (points[:, 0] < w - 1 - edge) & (points[:, 1] < h - 1 - edge)
            for piece in _runs(points, inner & band.free(points), closed=True):
                if len(piece) >= 2 and _length(piece) >= shortest / 2:
                    band.add(piece, OUTLINE_REACH)
                    out.append(piece + 0.5)
    return out


def _smooth(rgb):
    """Edge-preserving smoothing: texture (brushwork, windows, noise) goes, edges stay. Its reach follows the crop's
    size."""
    h, w = rgb.shape[:2]
    sigma = max(2.0, 0.0025 * max(w, h))
    smooth = cv2.bilateralFilter(rgb, int(2 * round(1.5 * sigma) + 1), 40, sigma)
    return cv2.bilateralFilter(smooth, int(2 * round(1.5 * sigma) + 1), 40, sigma)


def _canny_at(lab, settings, allowed):
    """Canny on the colour difference: per pixel the Lab channel with the strongest Sobel gradient. The high threshold
    is at least settings.high and at least a percentile of the crop's gradients (a busy picture keeps its strongest)."""
    best_dx = best_dy = best = None
    for c in range(3):
        channel = np.ascontiguousarray(lab[..., c])
        dx = cv2.Sobel(channel, cv2.CV_16S, 1, 0, ksize=3); dy = cv2.Sobel(channel, cv2.CV_16S, 0, 1, ksize=3)
        magnitude = np.abs(dx.astype(np.int32)) + np.abs(dy.astype(np.int32))
        if best is None:
            best_dx, best_dy, best = dx, dy, magnitude
        else:
            stronger = magnitude > best
            best_dx = np.where(stronger, dx, best_dx); best_dy = np.where(stronger, dy, best_dy); best = np.maximum(best, magnitude)
        del dx, dy, magnitude
    moving = best[allowed] if allowed is not None else best.ravel()
    moving = moving[moving > 0]
    high = max(settings['high'], float(np.percentile(moving, settings['percentile'])) if moving.size else 0.0)
    return cv2.Canny(best_dx, best_dy, high * LOW, high, L2gradient=False)


def _canny(smooth, settings, allowed):
    """Edges at two scales, joined: the smoothed crop as it is (thin parts: a spire, a mast) and blurred by COARSE of
    its size (the big contours, unbroken by brushwork). The band in _chains keeps their near-copies apart."""
    lab = cv2.cvtColor(smooth, cv2.COLOR_RGB2LAB)
    edges = _canny_at(lab, settings, allowed)
    coarse = cv2.GaussianBlur(lab, (0, 0), max(1.0, COARSE * max(lab.shape[:2])))
    edges |= _canny_at(coarse, settings, allowed)
    if allowed is not None:
        edges[~allowed] = 0
    return edges


def _chains(edges, settings, epsilon, shortest, band):
    """Edge pixels as polylines (crop pixels): each component's outer contour, each pixel once; long chains, or
    straight ones a third as long, that run between corners at least settings.run x epsilon on average; not where a
    line is drawn already. Longest first."""
    n, cc, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    extent = np.maximum(stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT])
    keep = np.zeros(n, bool); keep[1:] = extent[1:] >= shortest / 2 * STRAIGHT
    if not keep.any():
        return []
    kept = keep[cc].astype(np.uint8)
    contours, hierarchy = cv2.findContours(kept, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    candidates = []
    seen = np.zeros(edges.shape, bool)
    for contour, (_, _, _, parent) in zip(contours, hierarchy[0]):
        if parent != -1:
            continue
        points = contour[:, 0, :]
        xs, ys = points[:, 0], points[:, 1]
        fresh = ~seen[ys, xs]
        # The contour of a thin curve runs out and back: only the first visit of a pixel counts.
        linear = ys.astype(np.int64) * edges.shape[1] + xs
        _, first = np.unique(linear, return_index=True)
        once = np.zeros(len(points), bool); once[first] = True
        seen[ys, xs] = True
        closed = bool(once.all()) and len(points) > 8 and abs(int(xs[0]) - int(xs[-1])) <= 1 and abs(int(ys[0]) - int(ys[-1])) <= 1
        for piece in _runs(points.astype(np.float64), fresh & once, closed=closed):
            if len(piece) < 2:
                continue
            steps = np.abs(np.diff(piece, axis=0)).max(axis=1)
            for part in np.split(piece, np.where(steps > 1.5)[0] + 1):     # a jump is two chains
                length = _length(part)
                if length < shortest / 2:
                    continue
                straight = float(np.hypot(*(part[-1] - part[0]))) / length if length else 0
                if length < shortest and straight < STRAIGHT:
                    continue
                if _coherence(part, settings['run'] * epsilon) < COHERENT:
                    continue                                                   # wanders: texture
                candidates.append((length * (1.3 if straight >= STRAIGHT else 1.0), part))
    candidates.sort(key=lambda c: -c[0])
    out = []
    for _, part in candidates:
        for piece in _runs(part, band.free(part), closed=False):
            if _length(piece) >= shortest / 2 and (_length(piece) >= shortest or _straightness(piece) >= STRAIGHT):
                band.add(piece)
                out.append(piece + 0.5)
    return out


def _coherence(points, window):
    """How steadily a chain runs: the mean, over windows of about `window` pixels along it, of chord over arc. A
    contour, straight or curved, is near 1; a texture's random walk much lower."""
    n = max(2, int(round(window)))
    if len(points) <= n:
        return _straightness(points)
    steps = np.hypot(*np.diff(points, axis=0).T)
    arc = np.concatenate([[0.0], np.cumsum(steps)])
    chord = np.hypot(*(points[n:] - points[:-n]).T)
    return float(np.mean(chord / np.maximum(arc[n:] - arc[:-n], 1e-6)))


def _straightness(points):
    length = _length(points)
    return float(np.hypot(*(points[-1] - points[0]))) / length if length else 0.0


def _finish(lines, epsilon, limit, x0, y0):
    """(kind, weight, points) to at most `limit` simplified polylines of at most MAX_POINTS, highest weight first, in
    image pixels; a line that needs more points is simplified harder (up to 4x), then cut into pieces."""
    ranked = sorted(lines, key=lambda line: -line[1])
    out = []
    for kind, _, points in ranked:
        closed = len(points) > 3 and bool(np.allclose(points[0], points[-1]))
        shape = points[:-1] if closed else points
        e, simple = epsilon, _simplify(shape, epsilon, closed)
        while len(simple) > MAX_POINTS and e < 4 * epsilon:
            e *= 1.5; simple = _simplify(shape, e, closed)
        if len(simple) < 2:
            continue
        pieces = [simple] if len(simple) <= MAX_POINTS else [simple[i:i + MAX_POINTS] for i in range(0, len(simple) - 1, MAX_POINTS - 1)]
        for piece in pieces:
            if len(piece) < 2 or len(out) >= limit:
                continue
            out.append({'kind': kind, 'points': [[round(float(x) + x0, 2), round(float(y) + y0, 2)] for x, y in piece]})
        if len(out) >= limit:
            break
    return out


def _lights(gray, opaque, settings, band, shortest, limit_area):
    """Outlines of the brightest shapes over the opaque pixels: well above the darker class (Otsu's low mean), and in
    the top few percent unless the light fills most of the crop (a moon cropped to its box)."""
    values = gray[opaque]
    if values.size < 16:
        return []
    split, _ = _otsu(values)
    low = values[values <= split]
    dark = float(low.mean()) if low.size else float(values.min())
    top = float(values.max()); high = float(np.percentile(values, 95))
    if top - dark < 64:
        return []
    threshold = max((top + dark) / 2, min(high, top - 0.25 * (top - dark)))
    mask = _drop_small((gray >= threshold) & opaque, limit_area)
    # The largest lights first: a moon before the specks of a lit street.
    n, cc, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    largest = 1 + np.argsort(-stats[1:, cv2.CC_STAT_AREA])[:LIGHT_LIMIT]
    return _outlines(np.isin(cc, largest).astype(np.uint8), [1], None, {'area': 0}, band, shortest)


def trace(rgba, source, scale, detail='simple', max_lines=8, labels=None, inside=False, lights=False):
    """Guide lines of the crop `source` [x, y, w, h] of `rgba` (H x W x 4 uint8, RGBA), in rgba's pixels.

    scale: canvas pixels a reference pixel (the size the lines are drawn at); labels: an H x W uint8 of shapes (0 none),
    aligned with rgba; inside: only the shape (labels > 0) is outlined and only its structure kept; lights: also the
    brightest shapes. Returns {lines: [{kind: outline | structure | light, points}], silhouette: shapes | alpha |
    brightness | none}."""
    settings = DETAIL[detail]
    x0, y0, w, h = (int(v) for v in source)
    if not (w > 0 and h > 0 and x0 >= 0 and y0 >= 0 and x0 + w <= rgba.shape[1] and y0 + h <= rgba.shape[0]):
        raise ValueError('Source crop must fit the reference.')
    crop = rgba[y0:y0 + h, x0:x0 + w]
    if min(w, h) < 8:
        return {'lines': [], 'silhouette': 'none'}
    span = math.sqrt(w * h) * scale                           # the traced area's size on the canvas
    epsilon = max(settings['epsilon'], settings['epsilon_share'] * span) / scale
    shortest = settings['chain'] * span / scale
    band = _Band((h, w), max(2.0, 2.5 * epsilon))
    alpha = crop[..., 3] >= 128
    rgb = np.ascontiguousarray(crop[..., :3])
    smooth = _smooth(rgb)
    gray = _luma(smooth.astype(np.float32))
    gray[~alpha] = 0                                           # transparent counts as dark, as in the edge tools
    regions, ids, silhouette, allowed, lines = None, [], 'none', None, []
    if labels is not None:
        regions = np.ascontiguousarray(labels[y0:y0 + h, x0:x0 + w])
        if inside:
            regions = (regions > 0).astype(np.uint8)
            # The shape's structure lies inside it, off its outline.
            allowed = cv2.erode(regions, np.ones((3, 3), np.uint8), iterations=max(1, int(round(band.width)))) > 0
        ids = [int(i) for i in np.unique(regions) if i > 0]
        found = _outlines(regions, ids, crop, settings, band, shortest) if ids else []
        if found or inside:
            silhouette = 'shapes'
            lines = [('outline', 1.5 * _length(p) + 1e6 * inside, p) for p in found]
        else:
            regions = None                                   # no border inside the crop: alpha or brightness instead
    if silhouette == 'none':
        if 0.02 * w * h < int((~alpha).sum()) < 0.98 * w * h:
            regions, silhouette = alpha.astype(np.uint8), 'alpha'
        else:
            # Decided on block means (about SPLIT_SIDE on the long side), where texture noise averages out and a clearly
            # two-toned crop stays two-toned; the split itself is drawn at full resolution.
            k = min(1.0, SPLIT_SIDE / max(w, h))
            means = cv2.resize(gray, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
            threshold, separability = _otsu(cv2.blur(means, (3, 3)).ravel())
            if separability >= TWO_TONE:
                soft = cv2.GaussianBlur(gray, (0, 0), max(1.0, 0.5 / k))
                regions, silhouette = (soft > threshold).astype(np.uint8), 'brightness'
        if regions is not None:
            lines = [('outline', 1.5 * _length(p), p) for p in _outlines(regions, [1], crop, settings, band, shortest)]
    if allowed is None and silhouette == 'alpha':
        allowed = cv2.erode(alpha.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2) > 0
    edges = _canny(smooth, settings, allowed)
    for points in _chains(edges, settings, epsilon, shortest, band):
        lines.append(('structure', _length(points) * (1.3 if _straightness(points) >= STRAIGHT else 1.0), points))
    out = _finish(lines, epsilon, max_lines, x0, y0)
    if lights:
        light_band = _Band((h, w), band.width)
        opaque = alpha if allowed is None or silhouette != 'shapes' else (regions > 0)
        found = _lights(gray, opaque, settings, light_band, shortest, max(16.0, settings['light_area'] * w * h))
        out += _finish([('light', _length(p), p) for p in found], epsilon, LIGHT_LIMIT, x0, y0)
    return {'lines': out, 'silhouette': silhouette}

# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Accents by Krita's own features (paint_accents; the artist, 2026-10-23): stage two adjusts the painting's own paint
where the reference is sharper, brighter or darker than the canvas, instead of adding marks.

The companion sends the accents the finder kept (accent_find.py: positions, sizes and strengths on the canvas, from
the residual between the reference and the canvas view). Here they become soft (feathered) masks, cut by the area the
painter named (a saved selection's or an element shape's own coverage), and each kind one layer made from the canvas's
OWN pixels:

- lights: Krita's Dodge (highlights; exposure from the strength) on a copy of the canvas's pixels, and a bloom: the
  canvas's pixels blurred and Screened over themselves at BLOOM_OPACITY, in a grown mask;
- darks: Krita's Burn (shadows; exposure from the strength) on a copy;
- detail (the thin lines and edges the canvas lost): the canvas's pixels Overlaid with their Gaussian high pass.

Every layer is written at normal blending with its blend already baked in (Overlay or Screen inside an isolated group
would blend with nothing below it: a grey high-pass haze, a soft copy for a bloom). Every kind reads the same clean
source: the composite below the Accents group, without the agent's guides or anything above it, read once before any
accents layer is written. The work is done per TILE square the masks touch (never a whole-canvas read for a few
accents), and an active selection never limits a filter. The layers are plain paint layers in one "Accents" group
(inside the move's stage group, so the move's Undo removes it): no live filter mask recomputes on refresh. Krita keeps
every write out of the protected areas. Nothing of the reference's pixels reaches the canvas.
"""
import math
import numpy as np
from krita import Krita
from . import capabilities, canvas_projection

KINDS = ('lights', 'darks', 'detail')
FIELDS = ('name', 'accents', 'selection', 'inside_shape', 'stage_id', 'region', 'expected_revision', 'panel')
ACCENT_FIELDS = ('kind', 'x', 'y', 'size', 'strength', 'points')
MOST = 400                                    # accents in one call (paint_accents' own cap; it asks the artist past 150)
MAX_SIZE = 96                                 # an accent's size on the canvas at most (pixels): accents, never areas
TILE = 256                                    # work square: only the squares the masks touch are read and written
REACH = 1.0                                   # a light's or dark's mask is this many sizes across
FEATHER = 0.5                                 # and fades over this share of its radius
LINE_REACH = 1.5                              # a detail line's mask is this many line widths wide
BLOOM_GROW = 2.5                              # the bloom's mask reaches this many times the light's
BLOOM_OPACITY = 0.35
BLOOM_BLUR = 1.5                              # the bloom's blur, in light sizes (a Gaussian sigma of half of it)
# Rehearsal in Toska (2026-10-24, New Moscow): (0.15, 0.6) with the mask at the strength itself and an unamplified high
# pass changed almost nothing at preview scale; measured offline on that canvas view these values are noticeable with the
# ring just outside the masks unchanged (no halo). MASK_FLOOR: a mask's value is at least this, the strength adds the rest.
EXPOSURE = (0.3, 0.9)                         # Dodge/Burn exposure for the weakest and the strongest accent
MASK_FLOOR = 0.5
HIGH_PASS = 1.5                               # the high pass's sigma, in detail line widths
DETAIL_GAIN = 2.5                             # the high pass's gain before it is Overlaid
DODGE, BURN = 'dodge', 'burn'                 # Krita's Dodge and Burn filters (plugins/filters/dodgeburn)
SHADOWS, HIGHLIGHTS = 0, 2                    # their "type" (KisFilterDodgeBurn::Type)


def check(params, width, height):
    """The accents, checked: a list of {kind, x, y, size, strength, points?} in canvas pixels, centred on the canvas."""
    accents = params.get('accents')
    if not isinstance(accents, list) or not 1 <= len(accents) <= MOST:
        raise ValueError('accents is a list of 1-%d accents.' % MOST)
    out = []
    for accent in accents:
        if not isinstance(accent, dict) or set(accent) - set(ACCENT_FIELDS) or not {'kind', 'x', 'y', 'size', 'strength'} <= set(accent):
            raise ValueError('An accent is {kind, x, y, size, strength, points?}.')
        if accent['kind'] not in KINDS:
            raise ValueError('An accent kind is one of: ' + ', '.join(KINDS))
        for key, low, high in (('size', 0.5, MAX_SIZE), ('strength', 0, 1), ('x', -MAX_SIZE, width + MAX_SIZE), ('y', -MAX_SIZE, height + MAX_SIZE)):
            value = accent[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise ValueError('accent %s must be %s-%s' % (key, low, high))
        points = accent.get('points')
        if points is not None:
            if (not isinstance(points, list) or not 2 <= len(points) <= 64 or any(
                    not isinstance(p, list) or len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in p)
                    or not (0 <= p[0] <= width and 0 <= p[1] <= height) for p in points)):
                raise ValueError('accent points are 2-64 [x, y] pairs on the canvas.')
            span = max(max(p[0] for p in points) - min(p[0] for p in points), max(p[1] for p in points) - min(p[1] for p in points))
            if span > 4 * TILE:
                raise ValueError('An accent line spans at most %d pixels: points that far apart are no accent.' % (4 * TILE))
        out.append(accent)
    return out


def _extent(accent, grow=1.0):
    reach = accent['size'] * (LINE_REACH if accent['kind'] == 'detail' else REACH) * grow / 2 + 2
    xs = [p[0] for p in accent.get('points') or [[accent['x'], accent['y']]]]
    ys = [p[1] for p in accent.get('points') or [[accent['x'], accent['y']]]]
    return min(xs) - reach, min(ys) - reach, max(xs) + reach, max(ys) + reach


def rect_of(accents, width, height, grow=1.0):
    """The canvas rectangle [x, y, w, h] the accents' masks cover (with `grow`), or None off the canvas."""
    if not accents:
        return None
    boxes = [_extent(a, grow) for a in accents]
    left, top = max(0, int(math.floor(min(b[0] for b in boxes)))), max(0, int(math.floor(min(b[1] for b in boxes))))
    right, bottom = min(width, int(math.ceil(max(b[2] for b in boxes)))), min(height, int(math.ceil(max(b[3] for b in boxes))))
    return [left, top, right - left, bottom - top] if right > left and bottom > top else None


def tiles(accents, width, height, grow=1.0):
    """The TILE squares [x, y, w, h] (clipped to the canvas) the accents' masks touch, top to bottom."""
    out = set()
    for accent in accents:
        left, top, right, bottom = _extent(accent, grow)
        if right <= 0 or bottom <= 0 or left >= width or top >= height:
            continue
        for ty in range(max(0, int(top // TILE)), min((height - 1) // TILE, int(bottom // TILE)) + 1):
            for tx in range(max(0, int(left // TILE)), min((width - 1) // TILE, int(right // TILE)) + 1):
                out.add((tx, ty))
    return [[tx * TILE, ty * TILE, min(TILE, width - tx * TILE), min(TILE, height - ty * TILE)] for tx, ty in sorted(out, key=lambda t: (t[1], t[0]))]


def mask(accents, rect, grow=1.0):
    """A soft mask (rect's h x w, float32 0-1) of the accents: each a disc (lights, darks) or a band along its line
    (detail), reaching `grow` times its usual reach, at full value inside and fading to nothing
    over its outer FEATHER share (inside: MASK_FLOOR plus the strength's share of the rest); the strongest wins where they overlap."""
    import cv2
    x0, y0, w, h = rect
    out = np.zeros((h, w), np.float32)
    for accent in accents:
        line = accent['kind'] == 'detail' and accent.get('points')
        reach = max(1.0, accent['size'] * (LINE_REACH if line else REACH) * grow / 2)
        left, top, right, bottom = (int(math.floor(v)) for v in _extent(accent, grow))
        left, top = max(left, x0), max(top, y0)
        right, bottom = min(right + 2, x0 + w), min(bottom + 2, y0 + h)
        if right <= left or bottom <= top:
            continue
        ys, xs = np.mgrid[top:bottom, left:right].astype(np.float32) + 0.5
        if line:
            # Distance to the line: a thin drawn centreline, then the distance transform of the rest.
            centre = np.full((bottom - top, right - left), 255, np.uint8)
            pts = np.round((np.asarray(accent['points'], np.float64) - [left, top]) * 4).astype(np.int32)
            cv2.polylines(centre, [pts.reshape(-1, 1, 2)], False, 0, 1, cv2.LINE_8, 2)
            d = cv2.distanceTransform(centre, cv2.DIST_L2, 3)
        else:
            d = np.hypot(xs - accent['x'], ys - accent['y'])
        level = MASK_FLOOR + (1 - MASK_FLOOR) * float(accent['strength'])
        soft = np.clip((reach - d) / max(0.5, FEATHER * reach), 0, 1) * level
        view = out[top - y0:bottom - y0, left - x0:right - x0]
        np.maximum(view, soft.astype(np.float32), out=view)
    return out


def exposure(accents):
    """Dodge or Burn exposure from the accents' strength (their mean, so a few strong ones do not blow out the rest)."""
    mean = float(np.mean([a['strength'] for a in accents])) if accents else 0.0
    return round(EXPOSURE[0] + (EXPOSURE[1] - EXPOSURE[0]) * mean, 3)


def cut(bgra, coverage):
    """BGRA bytes with their alpha multiplied by `coverage` (0-1, same size): the pixels only where the mask is."""
    pixels = np.frombuffer(bgra, np.uint8).reshape(coverage.shape + (4,)).copy()
    pixels[..., 3] = np.round(pixels[..., 3].astype(np.float32) * coverage).astype(np.uint8)
    return pixels.tobytes()


def overlay(base, blend):
    """Overlay of `blend` on `base` (0-1 floats): darker under a dark blend, lighter under a light one, unchanged at 0.5."""
    return np.where(base < 0.5, 2 * base * blend, 1 - 2 * (1 - base) * (1 - blend))


def screen(base, blend):
    return 1 - (1 - base) * (1 - blend)


def plan(accents):
    """The layers a call makes, in order (each above the last): (kind, label, how, setting, opacity, grow). `how` is a
    Krita filter (dodge, burn; its configuration in `setting`) or a blend baked here (overlay with the high pass of sigma
    `setting`; screen with the blur of sigma `setting`, at `opacity`)."""
    by = {kind: [a for a in accents if a['kind'] == kind] for kind in KINDS}
    layers = []
    if by['darks']:
        layers.append(('darks', 'darks (burn)', BURN, {'type': SHADOWS, 'exposure': exposure(by['darks'])}, 1.0, 1.0))
    if by['detail']:
        width = float(np.median([a['size'] for a in by['detail']]))
        layers.append(('detail', 'detail (high pass, overlay)', 'overlay', round(max(1.0, HIGH_PASS * width), 2), 1.0, 1.0))
    if by['lights']:
        size = float(np.median([a['size'] for a in by['lights']]))
        layers.append(('lights', 'lights (dodge)', DODGE, {'type': HIGHLIGHTS, 'exposure': exposure(by['lights'])}, 1.0, 1.0))
        layers.append(('lights', 'bloom (screen)', 'screen', round(max(1.0, BLOOM_BLUR * size / 2), 2), BLOOM_OPACITY, BLOOM_GROW))
    return layers


def margin(how, setting):
    """How far past a tile a baked blend reads (its blur's reach), so tiles join without seams."""
    return int(math.ceil(3 * setting)) if how in ('overlay', 'screen') else 0


def bake(how, setting, source, inner, opacity):
    """A baked layer's pixels (BGRA bytes of the `inner` slice) from `source` (BGRA uint8, the tile grown by its
    margin): the source Overlaid with its high pass, or Screened with its blur at `opacity`."""
    import cv2
    own = source[..., :3].astype(np.float32) / 255
    blur = cv2.GaussianBlur(own, (0, 0), max(0.5, setting))
    if how == 'overlay':
        out = overlay(own, np.clip((own - blur) * DETAIL_GAIN + 0.5, 0, 1))
    else:
        out = own + (screen(own, blur) - own) * opacity
    pixels = source.copy()
    pixels[..., :3] = np.clip(np.round(out * 255), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(pixels[inner]).tobytes()


def layer_plan(accents, width, height):
    """Each planned layer with its accents and its work: (tile, the rect read for it) for each square it touches."""
    layers = []
    for kind, label, how, setting, opacity, grow in plan(accents):
        mine = [a for a in accents if a['kind'] == kind]
        spread = margin(how, setting)
        work = []
        for tile in tiles(mine, width, height, grow):
            x, y, w, h = tile
            left, top = max(0, x - spread), max(0, y - spread)
            work.append((tile, [left, top, min(width, x + w + spread) - left, min(height, y + h + spread) - top]))
        if work:
            layers.append((kind, label, how, setting, opacity, grow, mine, work))
    return layers


class AccentCraft:
    """The plugin side of paint_accents' adjustments: one reversible pass, one group of baked layers."""

    def _accents_limit(self, doc, session, params):
        """The area's own coverage as a Selection (a saved selection or features, or an element's shape), or None."""
        if params.get('selection'):
            return self._region_load(session, params['selection'], doc)
        if params.get('inside_shape'):
            return self._region_shape_selection(doc, session, params['inside_shape'])
        return None

    def _accents_validate(self, doc, session, params):
        from .creative_validation import fields, text
        fields(params, FIELDS, ('name', 'accents'))
        text(params['name'], 'name', 120)
        accents = check(params, doc.width(), doc.height())
        if params.get('selection') and params.get('inside_shape'):
            raise ValueError('Limit the accents with selection or inside_shape, not both.')
        if params.get('selection'):
            self._region_check_named(doc, session, text(params['selection'], 'selection', 2000))
        if params.get('inside_shape'):
            self._region_shape_selection(doc, session, params['inside_shape'])
        if not layer_plan(accents, doc.width(), doc.height()):
            raise ValueError('No accent lies on the canvas: nothing to adjust.')
        self._craft_check_rgba(doc, 'Accents')
        self._craft_validate_create(doc, session, {'name': params['name'], 'type': 'group', **{k: params[k] for k in ('stage_id', 'panel') if k in params}})

    def _accents_clean_reads(self, doc, session, group, rects):
        """The composite below `group` (the still empty Accents group) in each rect, as BGRA uint8 arrays: everything
        above it on its way to the top (later layers, lettering, the agent's guides) hidden while it is read, then shown."""
        hidden = []
        node = group
        while node is not None and node.parentNode() is not None:
            parent = node.parentNode()
            siblings = parent.childNodes()
            identifier = node.uniqueId().toString()
            index = next(i for i, child in enumerate(siblings) if child.uniqueId().toString() == identifier)
            for above in siblings[index + 1:]:
                if above.visible():
                    above.setVisible(False); hidden.append(above)
            node = parent
        guides = self._guide_group(doc, session=session)
        if guides is not None and guides.visible():
            guides.setVisible(False); hidden.append(guides)
        # Lettering (comic balloons and captions) is the page's, not paint to brighten: never read into the accents.
        for identifier in {p.get('layer_id') for p in session.get('passes', []) if p.get('kind') == 'letter' and not p.get('rejected')}:
            try:
                lettering = self._creative_node(doc, identifier)
            except Exception:
                continue
            if lettering is not None and lettering.visible():
                lettering.setVisible(False); hidden.append(lettering)
        try:
            out = {}
            for rect in rects:
                canvas_projection.refresh(doc, list(rect)); doc.waitForDone()
                out[tuple(rect)] = np.frombuffer(bytes(doc.rootNode().projectionPixelData(*rect)), np.uint8).reshape(rect[3], rect[2], 4).copy()
            return out
        finally:
            for node in hidden:
                node.setVisible(True)
            if hidden:
                for rect in rects:
                    canvas_projection.refresh(doc, list(rect))

    def _accents_apply(self, doc, session, params, result):
        from .filters import _no_selection
        accents = check(params, doc.width(), doc.height())
        layers = layer_plan(accents, doc.width(), doc.height())
        group = self._craft_create(doc, session, {'name': params['name'], 'type': 'group', **{k: params[k] for k in ('stage_id', 'panel') if k in params}})
        node = self._creative_node(doc, group['layer_id'])
        # One clean read of every square any kind needs, before any accents layer exists: every kind adjusts the same paint.
        sources = self._accents_clean_reads(doc, session, node, sorted({tuple(read) for *_rest, work in layers for _tile, read in work}))
        limit = self._accents_limit(doc, session, params)
        made = []
        for kind, label, how, setting, opacity, grow, mine, work in layers:
            layer = doc.createNode('%s · %s' % (params['name'], label), 'paintlayer')
            children = node.childNodes()
            if layer is None or not node.addChildNode(layer, children[-1] if children else None):
                raise RuntimeError('Krita could not add the accents layer.')
            session['layers'].add(layer.uniqueId().toString())
            layer.setBlendingMode('normal')                       # every blend is baked: nothing blends inside the group
            krita_filter = None
            if how in (DODGE, BURN):
                krita_filter = Krita.instance().filter(how)
                if krita_filter is None:
                    raise RuntimeError('Krita has no filter "%s".' % how)
                krita_filter.setConfiguration(capabilities.configured(krita_filter.configuration(), setting))
            painted = 0
            for tile, read in work:
                x, y, w, h = tile
                source = sources[tuple(read)]
                inner = (slice(y - read[1], y - read[1] + h), slice(x - read[0], x - read[0] + w))
                coverage = mask(mine, tile, grow)
                if limit is not None:
                    coverage = coverage * np.frombuffer(bytes(limit.pixelData(x, y, w, h)), np.uint8).reshape(h, w).astype(np.float32) / 255
                if not coverage.any():
                    continue
                if krita_filter is not None:
                    if layer.setPixelData(np.ascontiguousarray(source[inner]).tobytes(), x, y, w, h) is False:
                        raise RuntimeError('Krita rejected the accents layer pixels.')
                    with _no_selection(doc):                       # an active selection never limits the filter
                        if krita_filter.apply(layer, x, y, w, h) is False:
                            raise RuntimeError('Krita could not apply %s.' % how)
                        doc.waitForDone()
                    pixels = bytes(layer.pixelData(x, y, w, h))
                else:
                    pixels = bake(how, setting, source, inner, opacity)
                if layer.setPixelData(cut(pixels, coverage), x, y, w, h) is False:
                    raise RuntimeError('Krita rejected the accents layer pixels.')
                canvas_projection.pixels_written(doc, tile)
                painted += 1
            made.append({'kind': kind, 'label': label, 'how': how, 'setting': setting, 'opacity': opacity, 'tiles': painted,
                         'layer_id': layer.uniqueId().toString()})
        counts = {kind: sum(1 for a in accents if a['kind'] == kind) for kind in KINDS}
        return dict(group, accents=counts, adjustments=made)

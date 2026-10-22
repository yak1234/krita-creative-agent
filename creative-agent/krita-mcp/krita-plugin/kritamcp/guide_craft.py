# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Guide layers (guided trace): construction lines the agent draws from a reference before it paints an element.

Runs inside the creative operation journal (creative_tools.py), on our Krita only (one Node.paintStrokes job).

- draw_guide paints lines with a forced guide brush on a layer "Guide · <element>" inside one group, "Guides ·
  Creative Agent", at the top of the painting and outside every stage group. Each move draws on a layer of its own
  (a second guide for the element in the same move extends it), so rejecting a move hides only that move's lines.
  The guides group is known by its node id (a document annotation and the guide passes), its name only as a fallback,
  so renaming or moving it changes nothing. merge_passes takes only stroke passes, merge_agent_work never merges a
  group holding the guides group, and tidy never removes a guide. Guides are never locked: a locked layer would refuse
  the agent's own strokes and settings; instead the agent never targets one (refuse_target).
- Each line has a weight: construction (thin: eye level, vanishing rays), contour (stronger: silhouettes, the default) or
  light (a contour in a second, warm guide colour: the outlines of the brightest areas). Widths follow the canvas's long
  side (guide_widths), so a guide reads at fit-to-screen on a 4800 px canvas as on an 800 px one. replace: true tightens
  an element's guide: its earlier guide layers are hidden in the same move, and rejecting the move shows them again.
- finish_guide hides the element's guides when the element is done; hide_guides hides every guide (a finished run,
  the end of a chat), in one undo step. A guide layer the artist painted on is never hidden: it says so instead.
- Looks that judge the painting (Luna, the review), colour samples and seams want it without guides. Hiding the group
  for the read would be undo steps on the fork (Node.setVisible is one), so the painting under the lines is rebuilt
  from the 8-bit sRGB view: only inside the tiles each guide stroke touched (recorded when it was drawn; the layer's
  bounds when that record may be stale), only on the covered pixels, the normal blend undone with the guide colour
  and the coverage the group's own projection gives. When that cannot be done honestly (another colour model, other
  layers over the guides, the artist's paint on a guide layer) the view keeps the guides and says so (a note).
"""
import json
import math
from krita import Krita
from .creative_validation import fields, guide_element, validate_guide
from .script_steps import one_step

GUIDES_GROUP = 'Guides · Creative Agent'
GUIDE_LAYER = 'Guide · '
ANNOTATION = 'creative-agent-guides'   # {"group": <the guides group's node id>}
GUIDE_COLOR = '#4fb3ff'                # a light blue no painting mistakes for its own paint
GUIDE_BGR = (0xff, 0xb3, 0x4f)         # the same in the view's byte order
LIGHT_COLOR = '#ffb347'                # a warm orange for light shapes: the outlines of the brightest areas
LIGHT_BGR = (0x47, 0xb3, 0xff)
GUIDE_COLOURS = {GUIDE_COLOR: GUIDE_BGR, LIGHT_COLOR: LIGHT_BGR}
GUIDE_OPACITY = 0.7                    # of the guide layer: the paint under a line still shows (and can be rebuilt)
# Ruling (line weights): width = share of the canvas's long side, rounded, within [minimum, maximum] pixels. 4800 px:
# construction 4, contour 8; 800 px: 2 and 3. Light lines are contours in the warm colour.
GUIDE_WEIGHTS = {'construction': (0.0008, 2, 8), 'contour': (0.0016, 3, 16), 'light': (0.0016, 3, 16)}
DEFAULT_WEIGHT = 'contour'
GUIDE_PRESET = 'b) Basic-1'            # a plain round brush with no pressure or speed shaping
INVERTIBLE_ALPHA = 0.9                 # past this coverage a guide pixel is filled from around it, not unblended
PROTECTION_GROUP = 'Protected areas · Creative Agent'   # never renders (protection.py)
TILE = 64                              # the grid guide strokes are recorded on
MARGIN = 6                             # pixels past a line's half width: its anti-aliased edge
PAD = 4                                # pixels read around a tile, for the fill to draw from
COLOUR_TOLERANCE = 0.03                # a covered pixel further than this from the guide colour is someone's paint
BLEND_REACH = 10                       # a blend of both guide colours is a crossing only this close to both: half the widest line, and a margin
DEPTHS = {'U8': ('uint8', 255.0), 'U16': ('uint16', 65535.0), 'F16': ('float16', 1.0), 'F32': ('float32', 1.0)}
NOTE_MODEL = ('The guide lines are still in this view: a %s painting\'s colours cannot be read back without them. '
              'Judge the painting knowing the light-blue and warm orange lines are construction guides.')
NOTE_UNDER = ('The guide lines are still in this view: other layers lie over the guides group, so taking the lines out '
              'would change that paint. Judge the painting knowing the light-blue and warm orange lines are construction guides.')
NOTE_ARTIST = ('The guide lines are still in this view: the artist painted on a guide layer, and that paint is never '
               'taken out. Judge the painting knowing the light-blue and warm orange lines are construction guides.')


def guide_widths(width, height):
    """Each weight's line width in pixels on a canvas of this size (GUIDE_WEIGHTS)."""
    side = max(width, height)
    return {weight: int(min(high, max(low, round(side * share)))) for weight, (share, low, high) in GUIDE_WEIGHTS.items()}


def guide_stroke(stroke, widths):
    """A guide line in the forced guide brush: the line's own path, its weight's width (a size asked is ignored), the
    guide colour, or the warm light colour for a light line."""
    weight = stroke.get('weight', DEFAULT_WEIGHT)
    return {'start': stroke['start'], 'segments': stroke['segments'], 'size': widths[weight],
            'opacity': 1, 'flow': 1, 'color': LIGHT_COLOR if weight == 'light' else GUIDE_COLOR}


def element_key(element):
    """Guides compare element names ignoring case and spacing: "Towers" and " towers " share their guides."""
    return ' '.join(str(element or '').split()).casefold()


def _tile_range(low, high, limit):
    return range(max(0, int(math.floor(low / TILE))), min(int(math.ceil(limit / TILE)), int(math.floor(high / TILE)) + 1))


def stroke_tiles(strokes, width, height):
    """The TILE-grid tiles [tx, ty] a set of strokes can have touched: each cubic segment sampled at most 16 px apart,
    widened by the line's half width and MARGIN. Sorted, without repeats."""
    tiles = set()
    for stroke in strokes:
        radius = float(stroke.get('size', GUIDE_WEIGHTS[DEFAULT_WEIGHT][2])) / 2 + MARGIN
        x0, y0 = stroke['start']
        for segment in stroke['segments']:
            c1x, c1y, c2x, c2y, x1, y1 = segment
            length = math.hypot(c1x - x0, c1y - y0) + math.hypot(c2x - c1x, c2y - c1y) + math.hypot(x1 - c2x, y1 - c2y)
            steps = max(1, int(math.ceil(length / 16)))
            for index in range(steps + 1):
                t = index / steps
                u = 1 - t
                x = u * u * u * x0 + 3 * u * u * t * c1x + 3 * u * t * t * c2x + t * t * t * x1
                y = u * u * u * y0 + 3 * u * u * t * c1y + 3 * u * t * t * c2y + t * t * t * y1
                for tx in _tile_range(x - radius, x + radius, width):
                    for ty in _tile_range(y - radius, y + radius, height):
                        tiles.add((tx, ty))
            x0, y0 = x1, y1
    return [list(tile) for tile in sorted(tiles)]


def rect_tiles(rect, width, height):
    """The tiles a rectangle [x, y, w, h] (widened by MARGIN) covers."""
    x, y, w, h = rect
    return {(tx, ty) for tx in _tile_range(x - MARGIN, x + w + MARGIN, width) for ty in _tile_range(y - MARGIN, y + h + MARGIN, height)}


def tile_runs(tiles, width, height, region=None):
    """Rectangles [x, y, w, h] covering `tiles`: neighbouring tiles of a row joined, clipped to the canvas and region."""
    rows = {}
    for tx, ty in tiles:
        rows.setdefault(ty, []).append(tx)
    runs = []
    for ty in sorted(rows):
        columns = sorted(rows[ty])
        start = previous = columns[0]
        for tx in columns[1:] + [None]:
            if tx is not None and tx == previous + 1:
                previous = tx
                continue
            x, y = start * TILE, ty * TILE
            right, bottom = min(width, (previous + 1) * TILE), min(height, (ty + 1) * TILE)
            if region:
                x, y = max(x, region[0]), max(y, region[1])
                right, bottom = min(right, region[0] + region[2]), min(bottom, region[1] + region[3])
            if right > x and bottom > y:
                runs.append([x, y, right - x, bottom - y])
            if tx is not None:
                start = previous = tx
    return runs


def _srgb_to_linear(values):
    import numpy as np
    v = values / 255.0
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4).astype(np.float32)


def _linear_to_srgb(values):
    import numpy as np
    v = np.clip(values, 0.0, 1.0)
    return (np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055) * 255.0).astype(np.float32)


def strip(painting, cover, linear=False, guide=None):
    """The painting without its guide lines, in one rectangle: painting, the view's BGRA pixels (uint8, h x w x 4);
    cover, each pixel's guide coverage 0-1 (the group's alpha times its opacity, float32, h x w); guide, each pixel's
    guide colour as 8-bit sRGB BGR (float32, h x w x 3), the blue guide colour everywhere when None. Only covered pixels
    are worked on (float32): up to INVERTIBLE_ALPHA Krita's normal blend with the guide colour is undone (in linear light
    for a linear painting), above it the pixel is filled from the uncovered paint around it. Returns (pixels, how many
    were worked on); uncovered pixels come back exactly as they were."""
    import numpy as np
    covered = cover > 0
    count = int(np.count_nonzero(covered))
    if not count:
        return painting, 0
    out = painting.copy()
    holes = covered & (cover > INVERTIBLE_ALPHA)
    exact = np.nonzero(covered & ~holes)
    if exact[0].size:
        p = painting[exact].astype(np.float32)
        a = cover[exact].astype(np.float32)
        keep = 1.0 - a
        pa = p[:, 3] / 255.0
        guide = np.array(GUIDE_BGR, np.float32)[None, :] if guide is None else np.asarray(guide, np.float32)[exact]
        colour = _srgb_to_linear(p[:, :3]) if linear else p[:, :3] / 255.0
        guide = _srgb_to_linear(guide) if linear else guide / 255.0
        alpha = np.clip((pa - a) / keep, 0.0, 1.0)
        premultiplied = (colour * pa[:, None] - guide * a[:, None]) / keep[:, None]
        under = np.where(alpha[:, None] > 1e-6, premultiplied / np.maximum(alpha[:, None], 1e-6), 0.0)
        under = _linear_to_srgb(under) if linear else np.clip(under, 0.0, 1.0) * 255.0
        out[exact] = np.concatenate([np.rint(under), np.rint(alpha * 255.0)[:, None]], axis=1).clip(0, 255).astype(np.uint8)
    if holes.any():
        out = _fill(out, holes)
    return out, count


def guide_mix(colours, stored, shown):
    """For pixels of the guides group (colours: n x 3, as stored, 0-1) and the guide colours (stored: k x 3, as stored;
    shown: k x 3, as the view shows them): each pixel's distance from the nearest blend of two guide colours (the guide
    colours themselves included: an anti-aliased crossing of a blue and a warm line is such a blend) and that blend in
    the view's colours. Returns (distances n, view colours n x 3)."""
    import numpy as np
    best = np.full(colours.shape[0], np.inf, np.float32)
    out = np.zeros((colours.shape[0], 3), np.float32)
    for i in range(len(stored)):
        for j in range(i, len(stored)):
            span = stored[j] - stored[i]
            length = float(np.dot(span, span))
            t = np.clip((colours - stored[i]) @ span / length, 0.0, 1.0) if length > 0 else np.zeros(colours.shape[0], np.float32)
            distance = np.abs(colours - (stored[i] + t[:, None] * span)).max(axis=1)
            closer = distance < best
            best[closer] = distance[closer]
            out[closer] = shown[i] + t[closer, None] * (shown[j] - shown[i])
    return best, out


def _grow(mask, radius):
    """A boolean mask grown by `radius` pixels (a square)."""
    import numpy as np
    out = mask.copy()
    for axis in (0, 1):
        grown = out.copy()
        for shift in range(1, radius + 1):
            if shift >= out.shape[axis]:
                break
            ahead = [slice(None)] * 2; behind = [slice(None)] * 2
            ahead[axis], behind[axis] = slice(shift, None), slice(None, -shift)
            grown[tuple(behind)] |= out[tuple(ahead)]
            grown[tuple(ahead)] |= out[tuple(behind)]
        out = grown
    return out


def guide_colours(colours, stored, shown, names, allowed, strong):
    """Which guide colour each pixel of the guides group shows, keeping the artist's paint apart.

    colours: h x w x 3 as stored (0-1); stored, shown: k x 3 (as stored; as the view shows them, linear for a linear
    painting); names: the k colours' names; allowed: {name: h x w bool, where lines of that colour were drawn};
    strong: h x w bool, the pixels opaque enough to judge. A pixel is a guide colour drawn there, or a blend of two
    guide colours (an anti-aliased crossing) where both were drawn and both show unblended within BLEND_REACH pixels.
    Returns (h x w bool: a strong pixel that is neither, h x w x 3 the view colour under each pixel)."""
    import numpy as np
    h, w = colours.shape[:2]
    flat = colours.reshape(-1, 3)
    pure = np.full((len(stored), h * w), np.inf, np.float32)
    for index, name in enumerate(names):
        distance = np.abs(flat - stored[index]).max(axis=1)
        pure[index] = np.where(allowed[name].reshape(-1), distance, np.inf)
    best_pure = pure.min(axis=0)
    out = shown[pure.argmin(axis=0)].astype(np.float32)
    near = {}
    for index, name in enumerate(names):
        found = (pure[index] <= COLOUR_TOLERANCE).reshape(h, w) & strong
        near[name] = near.get(name, np.zeros((h, w), bool)) | found
    near = {name: _grow(mask, BLEND_REACH).reshape(-1) for name, mask in near.items()}
    best_mix = np.full(h * w, np.inf, np.float32)
    for i in range(len(stored)):
        for j in range(i + 1, len(stored)):
            if names[i] == names[j]:
                continue
            span = stored[j] - stored[i]
            length = float(np.dot(span, span))
            if length <= 0:
                continue
            t = np.clip((flat - stored[i]) @ span / length, 0.0, 1.0)
            distance = np.abs(flat - (stored[i] + t[:, None] * span)).max(axis=1)
            where = (allowed[names[i]].reshape(-1) & allowed[names[j]].reshape(-1) & near[names[i]] & near[names[j]])
            distance = np.where(where, distance, np.inf)
            closer = distance < best_mix
            best_mix[closer] = distance[closer]
            blend = shown[i] + t[:, None] * (shown[j] - shown[i])
            use = closer & (distance < best_pure)
            out[use] = blend[use]
    # A covered pixel no rule explains (a faint edge outside every recorded tile) takes the nearest guide colour or blend.
    unexplained = ~np.isfinite(np.minimum(best_pure, best_mix))
    if unexplained.any():
        _distance, nearest = guide_mix(flat[unexplained], stored, shown)
        out[unexplained] = nearest
    paint = strong.reshape(-1) & (np.minimum(best_pure, best_mix) > COLOUR_TOLERANCE)
    return paint.reshape(h, w), out.reshape(h, w, 3)


def _fill(image, holes, rounds=16):
    """Each hole pixel takes the mean of its known neighbours, growing inwards ring by ring (thin lines close in a few)."""
    import numpy as np
    known = ~holes
    work = image.astype(np.float32)
    height, width = holes.shape
    for _ in range(rounds):
        if known.all():
            break
        total = np.zeros_like(work)
        count = np.zeros(holes.shape, np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not dy and not dx:
                    continue
                # Neighbour (y + dy, x + dx) of each pixel, where it exists.
                ys, yd = slice(max(0, dy), height + min(0, dy)), slice(max(0, -dy), height + min(0, -dy))
                xs, xd = slice(max(0, dx), width + min(0, dx)), slice(max(0, -dx), width + min(0, -dx))
                weight = known[ys, xs]
                total[yd, xd] += work[ys, xs] * weight[..., None]
                count[yd, xd] += weight
        grow = ~known & (count > 0)
        if not grow.any():
            break
        work[grow] = total[grow] / count[grow][:, None]
        known = known | grow
    return np.rint(work).clip(0, 255).astype(np.uint8)


class GuideCraft:
    GUIDES_GROUP = GUIDES_GROUP

    # ----- where guides live --------------------------------------------------------------------------------------------
    def _guide_known_ids(self, doc=None, session=None):
        """Node ids the guides group has had: the guide passes' group, and the document's own record of it."""
        session = session if session is not None else (getattr(self, '_creative_session', None) or {})
        ids = {entry.get('group_id') for entry in session.get('passes', []) if entry.get('kind') == 'guide'}
        if doc is not None and hasattr(doc, 'annotation'):
            try:
                ids.add(json.loads(bytes(doc.annotation(ANNOTATION)) or b'{}').get('group'))
            except (ValueError, TypeError, AttributeError):
                pass
        ids.discard(None)
        return ids

    def _guide_is_group(self, node, doc=None):
        if node is None or node.type() != 'grouplayer':
            return False
        return node.uniqueId().toString() in self._guide_known_ids(doc) or node.name() == GUIDES_GROUP

    def _guide_group(self, doc, create=False, session=None):
        """The painting's guides group: by its id wherever it is, else by its name; made at the top of the painting when
        asked, and recorded in the document."""
        ids = self._guide_known_ids(doc, session)
        nodes = [node for node, _depth in self._creative_nodes(doc) if node.type() == 'grouplayer']
        found = next((n for n in nodes if n.uniqueId().toString() in ids), None) or next((n for n in nodes if n.name() == GUIDES_GROUP), None)
        if found is not None or not create:
            return found
        root = doc.rootNode()
        children = root.childNodes()
        group = doc.createNode(GUIDES_GROUP, 'grouplayer')
        if group is None or not root.addChildNode(group, children[-1] if children else None):
            raise RuntimeError('Could not create the guides group.')
        if hasattr(doc, 'setAnnotation'):
            doc.setAnnotation(ANNOTATION, 'Creative Agent guides', json.dumps({'group': group.uniqueId().toString()}).encode('utf-8'))
        return group

    def _guide_in_group(self, node, doc=None):
        """True for a node inside the guides group (at any depth)."""
        parent = node.parentNode() if hasattr(node, 'parentNode') else None
        while parent is not None:
            if self._guide_is_group(parent, doc):
                return True
            parent = parent.parentNode() if hasattr(parent, 'parentNode') else None
        return False

    @staticmethod
    def _guide_holds(node, group):
        """True when `node` is the guides group or one of its ancestors (a stage group it was moved into)."""
        if group is None:
            return False
        identifier, current = node.uniqueId().toString(), group
        while current is not None:
            if current.uniqueId().toString() == identifier:
                return True
            current = current.parentNode() if hasattr(current, 'parentNode') else None
        return False

    @staticmethod
    def _guide_entries(session, element=None):
        """The guide passes not rejected, oldest first (of one element when given)."""
        key = element_key(element) if element is not None else None
        return [entry for entry in session.get('passes', []) if entry.get('kind') == 'guide' and not entry.get('rejected')
                and (key is None or element_key(entry.get('element')) == key)]

    @staticmethod
    def _guide_latest(session, layer_id):
        return next((entry for entry in reversed(session.get('passes', [])) if entry.get('layer_id') == layer_id), None)

    def _guide_layers(self, doc, session, element=None):
        """[(node, newest pass)] of the guide layers still in the painting, oldest first, one per layer."""
        seen, layers = set(), []
        for entry in self._guide_entries(session, element):
            identifier = entry.get('layer_id')
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            try:
                layers.append((self._creative_node(doc, identifier), self._guide_latest(session, identifier)))
            except ValueError:
                continue                                 # the artist removed it
        return layers

    def _guide_artist_painted(self, doc, latest, node):
        """True when the layer is not as the agent's last pass on it left it: the artist painted on it."""
        after = (latest or {}).get('after') or {}
        return self._creative_layer_state(node, doc).get('pixels') != after.get('pixels')

    def _guide_layer_ids(self, doc, session):
        ids = {entry.get('layer_id') for entry in session.get('passes', []) if entry.get('kind') == 'guide'}
        group = self._guide_group(doc, session=session)
        if group is not None:
            ids |= {child.uniqueId().toString() for child in group.childNodes()}
        ids.discard(None)
        return ids

    def _guide_refuse_target(self, doc, session, operation, params):
        """A guide layer is never adjusted, transformed, filtered or clipped to: it is construction, not paint."""
        keys = ['clip_to'] + (['layer_id'] if operation in ('adjust_layer', 'transform_layer') else []) + (['target'] if operation == 'apply_filter' else [])
        named = {params.get(key) for key in keys if isinstance(params.get(key), str)}
        if named and named & self._guide_layer_ids(doc, session):
            raise ValueError('That is a guide layer: guides are construction lines, never adjusted, transformed, filtered or '
                             'clipped to. Paint the element on its own layers; finish_guide hides the guide when it is done.')

    # ----- draw_guide, finish_guide, hide_guides -------------------------------------------------------------------------
    def _guide_validate(self, doc, session, params):
        validate_guide(params, doc.width(), doc.height())
        if GUIDE_PRESET not in Krita.instance().resources('preset'):
            raise ValueError('The guide brush "%s" is not installed in this Krita.' % GUIDE_PRESET)

    def _guide_draw(self, doc, session, params, result):
        """Paint the guide lines on the element's guide layer of this move (a new one unless this move's shows). Fills
        `result` with the layer and group as a pass does, and `_guide` with what the pass records: the tiles the lines
        touched, the layer's bounds after them, the guide colours as the document stores them and, for replace, the
        earlier guide layers it hid. replace: true draws on a new layer and, once its job has painted every line, hides
        the element's guides that showed before (in this operation's undo step): a tightened guide replaces the rough
        one instead of stacking on it, and a refused or stopped job leaves the rough one showing."""
        element = validate_guide(params, doc.width(), doc.height())
        self._creative_passes(session)
        stage = params.get('stage_id')
        node = None
        layers = self._guide_layers(doc, session, element)
        showing = [(n, latest) for n, latest in layers if n.visible()] if params.get('replace') else []
        if params.get('replace'):
            layers = []
        if layers:
            candidate, _latest = layers[-1]
            identifier = candidate.uniqueId().toString()
            first = next(e for e in self._guide_entries(session, element) if e.get('layer_id') == identifier)
            if first.get('stage_id') == stage and candidate.visible() and self._guide_in_group(candidate, doc):
                node = candidate                         # this move's guide for the element: extend it
        extend = node is not None
        if not extend:
            group = self._guide_group(doc, create=True, session=session)
            node = doc.createNode(GUIDE_LAYER + element, 'paintlayer')
            if node is None:
                raise RuntimeError('Could not create the guide layer.')
            node.setOpacity(round(GUIDE_OPACITY * 255))
            children = group.childNodes()
            if not group.addChildNode(node, children[-1] if children else None):
                raise RuntimeError('Could not add the guide layer to the guides group.')
        identifier = node.uniqueId().toString()
        session['layers'].add(identifier)
        result['layer_id'] = identifier
        result['group_id'] = node.parentNode().uniqueId().toString()
        widths = guide_widths(doc.width(), doc.height())
        strokes = [guide_stroke(stroke, widths) for stroke in params['strokes']]
        out = self._creative_stroke_job(doc, session, {'name': node.name(), 'preset': GUIDE_PRESET, 'strokes': strokes},
                                        node, result, not extend)
        if result.get('error_code') != 'validation_rejected':
            session['projection_fresh'] = True           # the job recomposited what it changed
        width, height = doc.width(), doc.height()
        result['_guide'] = {'guide_tiles': stroke_tiles(strokes, width, height),
                            'guide_colour_tiles': {colour: stroke_tiles([s for s in strokes if s['color'] == colour], width, height)
                                                   for colour in sorted({s['color'] for s in strokes})},
                            'guide_bounds': self._guide_bounds(node), 'guide_raws': self._guide_raws(doc, node, strokes)}
        extra = {}
        if params.get('replace'):
            replaced, kept = [], []
            if not result.get('error_code') and (out.get('stroke_job') or {}).get('state', 'done') == 'done':
                replaced, kept = self._guide_hide(doc, session, showing, 'Tighten guide · ' + element, count=False)
            result['_guide']['replaced_layer_ids'] = [n.uniqueId().toString() for n, _latest in showing if not n.visible()]
            extra['replaced'] = replaced
            if kept:
                extra.update(kept_showing=kept, note=self._guide_kept_note(kept))
        return dict(out, element=element, guide_extended=extend, **extra)

    @staticmethod
    def _guide_bounds(node):
        if not hasattr(node, 'bounds'):
            return None
        rect = node.bounds()
        return [rect.x(), rect.y(), rect.width(), rect.height()]

    @classmethod
    def _guide_raws(cls, doc, node, strokes):
        """{guide colour: its channels as the document stores them (hex, alpha left out)} for each colour the lines were
        drawn in. It tells a guide pixel from the artist's paint in any colour depth. Each comes from the colour itself:
        the known bytes of an 8-bit sRGB painting, else Krita's conversion into the document's colour space; only when
        neither works is it read back from the layer (_guide_raw), never where a later line of another colour lies."""
        raws = {}
        for colour in sorted({stroke['color'] for stroke in strokes}):
            raw = cls._guide_known_raw(doc, colour) or cls._guide_converted_raw(doc, colour) or cls._guide_raw(doc, node, strokes, colour)
            if raw:
                raws[colour] = raw
        return raws

    @staticmethod
    def _guide_known_raw(doc, colour):
        """An 8-bit RGBA sRGB painting stores a colour as its own bytes, blue first."""
        model = doc.colorModel() if hasattr(doc, 'colorModel') else 'RGBA'
        depth = doc.colorDepth() if hasattr(doc, 'colorDepth') else 'U8'
        profile = doc.colorProfile().lower() if hasattr(doc, 'colorProfile') else 'srgb'
        if model != 'RGBA' or depth != 'U8' or 'srgb' not in profile:
            return None
        return bytes(GUIDE_COLOURS.get(colour) or bytes.fromhex(colour[1:])[::-1]).hex()

    @staticmethod
    def _guide_converted_raw(doc, colour):
        """The colour converted into the document's RGBA colour space by Krita (ManagedColor), or None."""
        try:
            import numpy as np
            from krita import ManagedColor
            from .qt_compat import QColor
            managed = ManagedColor.fromQColor(QColor(colour))
            if doc.colorModel() != 'RGBA' or not managed.setColorSpace(doc.colorModel(), doc.colorDepth(), doc.colorProfile()):
                return None
            values = list(managed.components())[:3]      # pixel order (blue first for integer depths), alpha last
            dtype, scale = DEPTHS[doc.colorDepth()]
            if dtype.startswith('float'):
                return np.array(values, dtype).tobytes().hex()
            return np.rint(np.clip(np.array(values, np.float64), 0, 1) * scale).astype(dtype).tobytes().hex()
        except Exception:
            return None

    @staticmethod
    def _guide_raw(doc, node, strokes, colour):
        """The colour's channels read back where one of its lines was drawn and no later line of another colour lies
        over it (within that line's half width and a pixel), or None."""
        dtype, _scale = DEPTHS.get(doc.colorDepth() if hasattr(doc, 'colorDepth') else 'U8', DEPTHS['U8'])
        size = {'uint8': 1, 'uint16': 2, 'float16': 2, 'float32': 4}[dtype]
        best = None

        def covered(x, y, later):
            for other in later:
                if other['color'] == colour:
                    continue
                reach = float(other.get('size', 1)) / 2 + 1
                x0, y0 = other['start']
                for segment in other['segments']:
                    x1, y1 = segment[4], segment[5]
                    dx, dy = x1 - x0, y1 - y0
                    span = dx * dx + dy * dy
                    t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / span)) if span else 0.0
                    if math.hypot(x - x0 - t * dx, y - y0 - t * dy) <= reach:
                        return True
                    x0, y0 = x1, y1
            return False
        drawn = [(index, stroke) for index, stroke in enumerate(strokes) if stroke['color'] == colour]
        for index, stroke in drawn[:16]:
            later = strokes[index + 1:]
            for x, y in [stroke['start']] + [segment[4:6] for segment in stroke['segments'][:8]]:
                if not (0 <= x < doc.width() and 0 <= y < doc.height()) or covered(x, y, later):
                    continue
                data = bytes(node.pixelData(int(x), int(y), 1, 1))
                if len(data) <= size:
                    continue
                import numpy as np
                alpha = float(np.frombuffer(data[-size:], dtype)[0])
                if alpha > 0 and (best is None or alpha > best[0]):
                    best = (alpha, data[:-size].hex())
        return best[1] if best else None

    def _guide_hide(self, doc, session, layers, step, count=True):
        """Hide the given (node, newest pass) guide layers in one undo step, leaving any the artist painted on. Returns
        (names hidden, names kept showing). count=False: inside an operation that counts itself as unsaved."""
        hide, kept = [], []
        for node, latest in layers:
            if not node.visible():
                continue
            (kept if self._guide_artist_painted(doc, latest, node) else hide).append(node)
        if hide:
            with one_step(doc, step):
                for node in hide:
                    node.setVisible(False)
            for node in hide:
                self._creative_settle(doc, session, node)
            self._creative_store_passes(session)
            if count:
                session['unsaved_operations'] = session.get('unsaved_operations', 0) + 1
        return [n.name() for n in hide], [n.name() for n in kept]

    def _guide_restore_replaced(self, doc, session, entry):
        """Rejecting a guide pass that replaced earlier guides (replace: true) shows them again, as they were before it:
        only while its element is still being worked on (not finished nor every guide hidden since: finish_guide and
        hide_guides mark the passes they ended) and only a layer whose newest pass was not rejected itself."""
        if entry.get('finished'):
            return
        for identifier in entry.get('replaced_layer_ids') or ():
            latest = self._guide_latest(session, identifier)
            if latest is None or latest.get('rejected'):
                continue
            try:
                node = self._creative_node(doc, identifier)
            except ValueError:
                continue                                 # the artist removed it
            node.setVisible(True)
            self._creative_settle(doc, session, node)

    @staticmethod
    def _guide_kept_note(kept):
        return ('The artist painted on %s, so it was left showing: their paint is never hidden. Mention it to them.'
                % ', '.join("'%s'" % name for name in kept)) if kept else None

    def _guide_finish(self, doc, session, params):
        """Hide the element's guides: it is done. Not a pass; the guide passes keep up with the hidden state, so rejecting
        their move later still works. Again, or with the layers gone, it changes nothing."""
        fields(params, ('element',), ('element',))
        element = guide_element(params['element'])
        self._creative_passes(session)
        entries = self._guide_entries(session, element)
        if not entries:
            raise ValueError("There is no guide for '%s' to finish. Finish only an element you drew a guide for." % element)
        layers = self._guide_layers(doc, session, element)
        newest = layers[-1][0].uniqueId().toString() if layers else entries[-1]['layer_id']
        for entry in entries:
            entry['finished'] = True                     # undoing a tightening move no longer shows the rough guide
        hidden, kept = self._guide_hide(doc, session, layers, 'Finish guide · ' + element)
        extra = {'kept_showing': kept, 'note': self._guide_kept_note(kept)} if kept else {}
        if not hidden:
            return dict({'status': 'ok', 'element': element, 'layer_id': newest, 'visible': bool(kept), 'unchanged': True}, **extra)
        return dict(self._creative_observe(doc, session), status='ok', element=element, layer_id=newest, visible=bool(kept), **extra)

    def _guide_hide_all(self, doc, session, params):
        """Every guide hidden in one undo step (a finished run, the end of a chat), except any the artist painted on."""
        fields(params, ())
        self._creative_passes(session)
        for entry in self._guide_entries(session):
            entry['finished'] = True
        hidden, kept = self._guide_hide(doc, session, self._guide_layers(doc, session), 'Hide guides')
        result = {'status': 'ok', 'hidden': len(hidden), 'kept_showing': kept}
        if kept:
            result['note'] = self._guide_kept_note(kept)
        return result

    @staticmethod
    def _guide_view_options(session, params):
        """unguided_views: also save the view without guides with every look (for Luna's checks), while it is true."""
        fields(params, ('unguided_views',), ('unguided_views',))
        if not isinstance(params['unguided_views'], bool):
            raise ValueError('unguided_views must be true or false')
        session['unguided_views'] = params['unguided_views']
        return {'status': 'ok', 'unguided_views': session['unguided_views']}

    # ----- the painting without its guides ------------------------------------------------------------------------------
    def _guide_on_top(self, doc, group):
        """True when the guides group is a top-level group with nothing that renders over it and it blends normally."""
        children = doc.rootNode().childNodes()
        ids = [child.uniqueId().toString() for child in children]
        identifier = group.uniqueId().toString()
        if identifier not in ids:
            return False
        above = children[ids.index(identifier) + 1:]
        return group.blendingMode() == 'normal' and all(not n.visible() or n.name() == PROTECTION_GROUP for n in above)

    @staticmethod
    def _guide_painting_tile(projection, x, y, w, h):
        """The view's BGRA bytes of one rectangle."""
        from .qt_compat import QImage, image_bytes
        return image_bytes(projection.copy(x, y, w, h).convertToFormat(QImage.Format.Format_ARGB32))

    @staticmethod
    def _guide_patched(projection, patches):
        """A copy of the view with the rebuilt rectangles (x, y, w, h, BGRA bytes) drawn in."""
        from .qt_compat import QImage, QPainter
        out = projection.convertToFormat(QImage.Format.Format_ARGB32)
        painter = QPainter(out)
        try:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            for x, y, w, h, data in patches:
                painter.drawImage(x, y, QImage(data, w, h, w * 4, QImage.Format.Format_ARGB32).copy())
        finally:
            painter.end()
        return out

    def _guide_unguided(self, doc, projection, region=None, session=None):
        """(the view without guides, None), (None, a note) when the guides must stay in it, or (None, None) when no guide
        shows. projection: the 8-bit sRGB view of the whole canvas (a QImage); region [x, y, w, h] limits the work.
        self._guide_work counts what was read and worked on."""
        import numpy as np
        self._guide_work = {'reads': 0, 'read_area': 0, 'pixels': 0}
        session = session if session is not None else (getattr(self, '_creative_session', None) or {})
        group = self._guide_group(doc, session=session)
        layers = [child for child in group.childNodes() if child.visible()] if group is not None and group.visible() else []
        if not layers:
            return None, None
        model, depth = doc.colorModel(), doc.colorDepth()
        if model != 'RGBA' or depth not in DEPTHS:
            return None, NOTE_MODEL % model
        if not self._guide_on_top(doc, group):
            return None, NOTE_UNDER
        width, height = doc.width(), doc.height()
        dtype, scale = DEPTHS[depth]
        tiles, references = set(), set()           # references: (raw, the guide colour it stores)
        drawn = {}                                 # tile: the guide colours drawn in it
        for layer in layers:
            identifier = layer.uniqueId().toString()
            records = [e for e in session.get('passes', []) if e.get('kind') == 'guide' and e.get('layer_id') == identifier]
            bounds = self._guide_bounds(layer)
            recorded = records[-1].get('guide_bounds') if records else None
            names = {c for e in records for c in (e.get('guide_raws') or {})} | {GUIDE_COLOR for e in records if e.get('guide_raw')}
            names = names or set(GUIDE_COLOURS)
            if records and all(e.get('guide_tiles') is not None for e in records) and (recorded is None or bounds is None or recorded == bounds):
                for entry in records:
                    tiles |= {tuple(tile) for tile in entry['guide_tiles']}
                    by_colour = entry.get('guide_colour_tiles')
                    if by_colour is None:                # recorded before light lines (blue), or without its colours (any)
                        known = set(entry.get('guide_raws') or ()) | ({GUIDE_COLOR} if entry.get('guide_raw') else set())
                        by_colour = {colour: entry['guide_tiles'] for colour in (known or GUIDE_COLOURS)}
                    for colour, colour_tiles in by_colour.items():
                        for tile in colour_tiles:
                            drawn.setdefault(tuple(tile), set()).add(colour)
            elif bounds is not None and bounds[2] > 0 and bounds[3] > 0:
                moved = rect_tiles(bounds, width, height)  # moved, transformed or unrecorded: where the layer is now
                tiles |= moved
                for tile in moved:
                    drawn.setdefault(tile, set()).update(names)
            references |= {(e['guide_raw'], GUIDE_COLOR) for e in records if e.get('guide_raw')}   # recorded before light lines
            references |= {(raw, colour) for e in records for colour, raw in (e.get('guide_raws') or {}).items() if raw}
        if not references and depth == 'U8':
            references |= {(bytes(bgr).hex(), colour) for colour, bgr in GUIDE_COLOURS.items()}
        itemsize = np.dtype(dtype).itemsize
        pairs = [(np.frombuffer(bytes.fromhex(raw), dtype).astype(np.float32) / scale, GUIDE_COLOURS[colour], colour)
                 for raw, colour in sorted(references) if len(bytes.fromhex(raw)) == 3 * itemsize and colour in GUIDE_COLOURS]
        if not pairs:
            return None, NOTE_MODEL % (model + ' ' + depth)
        profile = doc.colorProfile().lower() if hasattr(doc, 'colorProfile') else ''
        linear = any(word in profile for word in ('g10', 'linear', 'scrgb'))
        stored = np.array([p[0] for p in pairs], np.float32)
        shown = np.array([p[1] for p in pairs], np.float32)
        if linear:
            shown = _srgb_to_linear(shown)
        names = [p[2] for p in pairs]
        columns, rows = int(math.ceil(width / TILE)), int(math.ceil(height / TILE))
        grids = {name: np.zeros((rows, columns), bool) for name in set(names)}
        for (tx, ty), colours_drawn in drawn.items():
            for name in colours_drawn & set(grids):
                if 0 <= ty < rows and 0 <= tx < columns:
                    grids[name][ty, tx] = True
        opacity = group.opacity() / 255.0
        patches = []
        for x, y, w, h in tile_runs(tiles, width, height, region):
            px, py = max(0, x - PAD), max(0, y - PAD)
            pw, ph = min(width, x + w + PAD) - px, min(height, y + h + PAD) - py
            raw = bytes(group.projectionPixelData(px, py, pw, ph))
            self._guide_work['reads'] += 1
            self._guide_work['read_area'] += pw * ph
            if len(raw) != pw * ph * 4 * itemsize:
                return None, NOTE_MODEL % (model + ' ' + depth)
            values = np.frombuffer(raw, dtype).reshape(ph, pw, 4)
            alpha = values[..., 3].astype(np.float32) / scale
            covered = alpha > 0
            if not covered.any():
                continue
            ty, tx = (np.arange(py, py + ph) // TILE)[:, None], (np.arange(px, px + pw) // TILE)[None, :]
            allowed = {name: grid[np.clip(ty, 0, rows - 1), np.clip(tx, 0, columns - 1)] for name, grid in grids.items()}
            paint, view = guide_colours(values[..., :3].astype(np.float32) / scale, stored, shown, names, allowed,
                                        covered & (alpha >= 8 / 255.0))
            if paint.any():
                return None, NOTE_ARTIST
            colours = _linear_to_srgb(view) if linear else view
            painting = np.frombuffer(self._guide_painting_tile(projection, px, py, pw, ph), np.uint8).reshape(ph, pw, 4)
            out, _worked = strip(painting, alpha * opacity, linear, colours)
            inner = (slice(y - py, y - py + h), slice(x - px, x - px + w))
            self._guide_work['pixels'] += int(np.count_nonzero(covered[inner]))
            patches.append((x, y, w, h, np.ascontiguousarray(out[inner]).tobytes()))
        if not patches:
            return None, None
        return self._guide_patched(projection, patches), None

# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Guide layers (guided trace): construction lines the agent draws from a reference before it paints an element.

Runs inside the creative operation journal (creative_tools.py), on our Krita only (one Node.paintStrokes job).

- draw_guide paints thin lines with a forced guide brush on a layer "Guide · <element>" inside one group, "Guides ·
  Creative Agent", at the top of the painting and outside every stage group. Each move draws on a layer of its own
  (a second guide for the element in the same move extends it), so rejecting a move hides only that move's lines.
  The guides group is known by its node id (a document annotation and the guide passes), its name only as a fallback,
  so renaming or moving it changes nothing. merge_passes takes only stroke passes, merge_agent_work never merges a
  group holding the guides group, and tidy never removes a guide. Guides are never locked: a locked layer would refuse
  the agent's own strokes and settings; instead the agent never targets one (refuse_target).
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
GUIDE_OPACITY = 0.7                    # of the guide layer: the paint under a line still shows (and can be rebuilt)
GUIDE_SIZE = (2, 4, 3)                 # smallest, largest and default line width in pixels
GUIDE_PRESET = 'b) Basic-1'            # a plain round brush with no pressure or speed shaping
INVERTIBLE_ALPHA = 0.9                 # past this coverage a guide pixel is filled from around it, not unblended
PROTECTION_GROUP = 'Protected areas · Creative Agent'   # never renders (protection.py)
TILE = 64                              # the grid guide strokes are recorded on
MARGIN = 6                             # pixels past a line's half width: its anti-aliased edge
PAD = 4                                # pixels read around a tile, for the fill to draw from
COLOUR_TOLERANCE = 0.03                # a covered pixel further than this from the guide colour is someone's paint
DEPTHS = {'U8': ('uint8', 255.0), 'U16': ('uint16', 65535.0), 'F16': ('float16', 1.0), 'F32': ('float32', 1.0)}
NOTE_MODEL = ('The guide lines are still in this view: a %s painting\'s colours cannot be read back without them. '
              'Judge the painting knowing the thin light-blue lines are construction guides.')
NOTE_UNDER = ('The guide lines are still in this view: other layers lie over the guides group, so taking the lines out '
              'would change that paint. Judge the painting knowing the thin light-blue lines are construction guides.')
NOTE_ARTIST = ('The guide lines are still in this view: the artist painted on a guide layer, and that paint is never '
               'taken out. Judge the painting knowing the thin light-blue lines are construction guides.')


def guide_stroke(stroke):
    """A guide line in the forced guide brush: the line's own path, a thin width, the guide colour."""
    low, high, default = GUIDE_SIZE
    return {'start': stroke['start'], 'segments': stroke['segments'], 'size': min(high, max(low, stroke.get('size', default))),
            'opacity': 1, 'flow': 1, 'color': GUIDE_COLOR}


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
        radius = float(stroke.get('size', GUIDE_SIZE[1])) / 2 + MARGIN
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


def strip(painting, cover, linear=False):
    """The painting without its guide lines, in one rectangle: painting, the view's BGRA pixels (uint8, h x w x 4);
    cover, each pixel's guide coverage 0-1 (the group's alpha times its opacity, float32, h x w). Only covered pixels
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
        guide = np.array(GUIDE_BGR, np.float32)
        colour = _srgb_to_linear(p[:, :3]) if linear else p[:, :3] / 255.0
        guide = _srgb_to_linear(guide) if linear else guide / 255.0
        alpha = np.clip((pa - a) / keep, 0.0, 1.0)
        premultiplied = (colour * pa[:, None] - guide[None, :] * a[:, None]) / keep[:, None]
        under = np.where(alpha[:, None] > 1e-6, premultiplied / np.maximum(alpha[:, None], 1e-6), 0.0)
        under = _linear_to_srgb(under) if linear else np.clip(under, 0.0, 1.0) * 255.0
        out[exact] = np.concatenate([np.rint(under), np.rint(alpha * 255.0)[:, None]], axis=1).clip(0, 255).astype(np.uint8)
    if holes.any():
        out = _fill(out, holes)
    return out, count


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
        touched, the layer's bounds after them and the guide colour as the document stores it."""
        element = validate_guide(params, doc.width(), doc.height())
        self._creative_passes(session)
        stage = params.get('stage_id')
        node = None
        layers = self._guide_layers(doc, session, element)
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
        strokes = [guide_stroke(stroke) for stroke in params['strokes']]
        out = self._creative_stroke_job(doc, session, {'name': node.name(), 'preset': GUIDE_PRESET, 'strokes': strokes},
                                        node, result, not extend)
        if result.get('error_code') != 'validation_rejected':
            session['projection_fresh'] = True           # the job recomposited what it changed
        result['_guide'] = {'guide_tiles': stroke_tiles(strokes, doc.width(), doc.height()),
                            'guide_bounds': self._guide_bounds(node), 'guide_raw': self._guide_raw(doc, node, strokes)}
        return dict(out, element=element, guide_extended=extend)

    @staticmethod
    def _guide_bounds(node):
        if not hasattr(node, 'bounds'):
            return None
        rect = node.bounds()
        return [rect.x(), rect.y(), rect.width(), rect.height()]

    @staticmethod
    def _guide_raw(doc, node, strokes):
        """The guide colour's channels as the document stores them (hex, alpha left out), read where a line was drawn,
        or None. It tells a guide pixel from the artist's paint in any colour depth."""
        dtype, _scale = DEPTHS.get(doc.colorDepth() if hasattr(doc, 'colorDepth') else 'U8', DEPTHS['U8'])
        size = {'uint8': 1, 'uint16': 2, 'float16': 2, 'float32': 4}[dtype]
        best = None
        for stroke in strokes[:16]:
            for x, y in [stroke['start']] + [segment[4:6] for segment in stroke['segments'][:8]]:
                if not (0 <= x < doc.width() and 0 <= y < doc.height()):
                    continue
                data = bytes(node.pixelData(int(x), int(y), 1, 1))
                if len(data) <= size:
                    continue
                import numpy as np
                alpha = float(np.frombuffer(data[-size:], dtype)[0])
                if alpha > 0 and (best is None or alpha > best[0]):
                    best = (alpha, data[:-size].hex())
        return best[1] if best else None

    def _guide_hide(self, doc, session, layers, step):
        """Hide the given (node, newest pass) guide layers in one undo step, leaving any the artist painted on. Returns
        (names hidden, names kept showing)."""
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
            session['unsaved_operations'] = session.get('unsaved_operations', 0) + 1
        return [n.name() for n in hide], [n.name() for n in kept]

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
        hidden, kept = self._guide_hide(doc, session, layers, 'Finish guide · ' + element)
        extra = {'kept_showing': kept, 'note': self._guide_kept_note(kept)} if kept else {}
        if not hidden:
            return dict({'status': 'ok', 'element': element, 'layer_id': newest, 'visible': bool(kept), 'unchanged': True}, **extra)
        return dict(self._creative_observe(doc, session), status='ok', element=element, layer_id=newest, visible=bool(kept), **extra)

    def _guide_hide_all(self, doc, session, params):
        """Every guide hidden in one undo step (a finished run, the end of a chat), except any the artist painted on."""
        fields(params, ())
        self._creative_passes(session)
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
        tiles, references = set(), set()
        for layer in layers:
            identifier = layer.uniqueId().toString()
            records = [e for e in session.get('passes', []) if e.get('kind') == 'guide' and e.get('layer_id') == identifier]
            bounds = self._guide_bounds(layer)
            recorded = records[-1].get('guide_bounds') if records else None
            if records and all(e.get('guide_tiles') is not None for e in records) and (recorded is None or bounds is None or recorded == bounds):
                for entry in records:
                    tiles |= {tuple(tile) for tile in entry['guide_tiles']}
            elif bounds is not None and bounds[2] > 0 and bounds[3] > 0:
                tiles |= rect_tiles(bounds, width, height)  # moved, transformed or unrecorded: where the layer is now
            references |= {e['guide_raw'] for e in records if e.get('guide_raw')}
        if not references and depth == 'U8':
            references.add(bytes(GUIDE_BGR).hex())
        itemsize = np.dtype(dtype).itemsize
        guide = [np.frombuffer(bytes.fromhex(raw), dtype).astype(np.float32) / scale for raw in references
                 if len(bytes.fromhex(raw)) == 3 * itemsize]
        if not guide:
            return None, NOTE_MODEL % (model + ' ' + depth)
        guide = np.array(guide)
        profile = doc.colorProfile().lower() if hasattr(doc, 'colorProfile') else ''
        linear = any(word in profile for word in ('g10', 'linear', 'scrgb'))
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
            strong = np.nonzero(alpha >= 8 / 255.0)
            if strong[0].size:
                colours = values[..., :3][strong].astype(np.float32) / scale
                distance = np.abs(colours[:, None, :] - guide[None, :, :]).max(axis=2).min(axis=1)
                if (distance > COLOUR_TOLERANCE).any():
                    return None, NOTE_ARTIST
            painting = np.frombuffer(self._guide_painting_tile(projection, px, py, pw, ph), np.uint8).reshape(ph, pw, 4)
            out, _worked = strip(painting, alpha * opacity, linear)
            inner = (slice(y - py, y - py + h), slice(x - px, x - px + w))
            self._guide_work['pixels'] += int(np.count_nonzero(covered[inner]))
            patches.append((x, y, w, h, np.ascontiguousarray(out[inner]).tobytes()))
        if not patches:
            return None, None
        return self._guide_patched(projection, patches), None

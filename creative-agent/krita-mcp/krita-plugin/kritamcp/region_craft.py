"""Selections and region fills: flats and gradients in one call instead of strokes.

A selection is built from steps (a shape, a layer's alpha, a colour range on the
visible image, or a saved selection), combined and refined in order. `select`
saves it under a name in the study folder, so later turns reuse it; `fill_region`
takes that name or the same steps inline. Neither touches the artist's selection.

`select` is not a canvas change: no pass, no checkpoint. `fill_region` runs inside
the creative operation journal (creative_tools.py) and fills a new layer, or a copy
of an agent layer with the original hidden, so reject restores the original.
"""
import bisect
import hashlib
import json
import os
import re
import time
import zlib
from krita import Krita, Selection
from .creative_validation import color as hex_colour, fields, numeric, text
from .geometry_data import bounds as checked_bounds, polygon
from . import canvas_projection

STEP_FIELDS = ('feature', 'shape', 'bounds', 'points', 'layer_id', 'color', 'seed', 'tolerance', 'saved', 'mode',
               'grow', 'shrink', 'border', 'feather', 'smooth', 'invert')
SOURCES = ('shape', 'layer_id', 'color', 'seed', 'saved', 'feature')
RUN = re.compile(rb'[^\x00]+')
MODES = ('replace', 'add', 'subtract', 'intersect')
REFINEMENTS = ('grow', 'shrink', 'border', 'feather')     # applied in this order, then smooth, then invert
SELECT_FIELDS = ('name', 'steps')
FILL_FIELDS = ('name', 'layer_id', 'selection', 'area', 'color', 'gradient', 'pattern', 'blend_mode', 'opacity',
               'clip_to', 'clip_base', 'stage_id', 'region', 'expected_revision', 'panel')
NEW_LAYER_ONLY = ('blend_mode', 'opacity', 'clip_to', 'clip_base')
STEP_LIMIT = 16
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _-]{0,39}$')
STRIP = 256


def colour_mask(bgra, rgb, tolerance):
    """255 where every channel is within `tolerance` of `rgb` and the pixel is not transparent."""
    count = len(bgra) // 4
    tables = [(2, rgb[0]), (1, rgb[1]), (0, rgb[2])]
    result = int.from_bytes(bgra[3::4].translate(bytes(255 if v else 0 for v in range(256))), 'big')
    for offset, wanted in tables:
        table = bytes(255 if abs(v - wanted) <= tolerance else 0 for v in range(256))
        result &= int.from_bytes(bgra[offset::4].translate(table), 'big')
    return result.to_bytes(count, 'big')


def connected_mask(mask, width, height, x, y):
    """The set pixels of `mask` joined to (x, y) through edge neighbours, as a magic wand selects. Works on runs of set
    pixels per row (found by a regex in C), so its cost follows the number of runs, not of pixels."""
    starts, ends = [], []
    for row in range(height):
        spans = [match.span() for match in RUN.finditer(mask, row * width, (row + 1) * width)]
        starts.append([a - row * width for a, _ in spans]); ends.append([b - row * width for _, b in spans])
    out = bytearray(width * height)
    first = bisect.bisect_right(ends[y], x)
    if first == len(ends[y]) or starts[y][first] > x:
        return bytes(out)
    seen, todo = {(y, first)}, [(y, first)]
    while todo:
        row, index = todo.pop()
        a, b = starts[row][index], ends[row][index]
        out[row * width + a:row * width + b] = b'\xff' * (b - a)
        for near in (row - 1, row + 1):
            if 0 <= near < height:
                # The runs in the next row that overlap [a, b): they end after a and start before b.
                other = bisect.bisect_right(ends[near], a)
                while other < len(starts[near]) and starts[near][other] < b:
                    if (near, other) not in seen:
                        seen.add((near, other)); todo.append((near, other))
                    other += 1
    return bytes(out)


class RegionCraft:
    # ----- steps ---------------------------------------------------------------
    def _region_validate_steps(self, doc, session, steps):
        if not isinstance(steps, list) or not 1 <= len(steps) <= STEP_LIMIT:
            raise ValueError('Give 1-%d selection steps.' % STEP_LIMIT)
        for index, step in enumerate(steps):
            label = 'Step %d: ' % (index + 1)
            try:
                fields(step, STEP_FIELDS)
                sources = [key for key in SOURCES if key in step]
                if len(sources) > 1:
                    raise ValueError('choose one source: shape, layer_id, color, seed, saved or feature')
                if index == 0 and not sources:
                    raise ValueError('the first step needs a source: shape, layer_id, color, seed, saved or feature')
                if 'mode' in step:
                    if step['mode'] not in MODES:
                        raise ValueError('mode must be one of ' + ', '.join(MODES))
                    if not sources:
                        raise ValueError('mode combines a source with the selection so far; give a source')
                    if index == 0 and step['mode'] in ('subtract', 'intersect'):
                        raise ValueError('the first step cannot %s; there is no selection yet' % step['mode'])
                for key in REFINEMENTS:
                    if key in step and (isinstance(step[key], bool) or not isinstance(step[key], int) or not 1 <= step[key] <= 128):
                        raise ValueError(key + ' must be an integer from 1 to 128')
                for key in ('smooth', 'invert'):
                    if key in step and not isinstance(step[key], bool):
                        raise ValueError(key + ' must be true or false')
                self._region_validate_source(doc, session, step, sources[0] if sources else None)
            except ValueError as error:
                raise ValueError(label + str(error)) from None

    def _region_validate_source(self, doc, session, step, source):
        if source != 'shape' and ('points' in step or ('bounds' in step and source not in ('color', 'seed'))):
            raise ValueError('bounds and points belong to a shape (bounds also limits a colour range or a seed)')
        if source not in ('color', 'seed') and 'tolerance' in step:
            raise ValueError('tolerance belongs to a colour range or a seed')
        if source == 'shape':
            shape = step['shape']
            if shape not in ('rectangle', 'ellipse', 'polygon'):
                raise ValueError('shape must be rectangle, ellipse or polygon')
            if shape == 'polygon':
                self._region_polygon(doc, step.get('points'))
                if 'bounds' in step:
                    raise ValueError('a polygon takes points, not bounds')
            else:
                checked_bounds(step.get('bounds'), doc.width(), doc.height())
                if 'points' in step:
                    raise ValueError('a %s takes bounds, not points' % shape)
        elif source == 'layer_id':
            self._craft_check_rgba(doc, 'A selection from layer alpha')
            self._creative_node(doc, text(step['layer_id'], 'layer_id', 200))
        elif source in ('color', 'seed'):
            self._craft_check_rgba(doc, 'A colour-range selection' if source == 'color' else 'A seed selection')
            if source == 'color':
                hex_colour(step['color'])
            else:
                self._region_seed(doc, step)
            if 'tolerance' in step and (isinstance(step['tolerance'], bool) or not isinstance(step['tolerance'], int)
                                        or not 0 <= step['tolerance'] <= 255):
                raise ValueError('tolerance must be an integer from 0 to 255')
            if 'bounds' in step:
                checked_bounds(step['bounds'], doc.width(), doc.height())
        elif source == 'saved':
            self._region_saved_path(session, step['saved'], must_exist=True)
        elif source == 'feature':
            self._feature_selection(doc, step['feature'])          # resolved and discarded: a typo is refused now

    def _region_polygon(self, doc, points):
        return polygon(points, doc.width(), doc.height())

    def _region_build(self, doc, session, steps, whole=True):
        """The selection the validated steps describe: in one native call when `whole` and the steps allow it
        (_region_build_whole), else a selection per source step, combined and refined in order."""
        selection = self._region_build_whole(doc, steps) if whole else None
        self._region_built_with = 'whole' if selection is not None else 'steps'      # select_probe reports it
        if selection is not None:
            return selection
        for index, step in enumerate(steps):
            source = next((key for key in SOURCES if key in step), None)
            if source:
                built = self._region_source(doc, session, step, source)
                mode = step.get('mode', 'replace' if index == 0 else 'add')
                if selection is None or mode == 'replace':
                    selection = built
                else:
                    getattr(selection, mode)(built)
            self._region_refine(selection, step)
        return selection

    def _region_refine(self, selection, step):
        """The step's refinements on the selection so far, in their fixed order."""
        for key in REFINEMENTS:
            if key in step:
                amount = step[key]
                if key == 'grow':
                    selection.grow(amount, amount)
                elif key == 'shrink':
                    selection.shrink(amount, amount, False)
                elif key == 'border':
                    selection.border(amount, amount)
                else:
                    selection.feather(amount)
        if step.get('smooth'):
            selection.smooth()
        if step.get('invert'):
            selection.invert()

    def _region_build_whole(self, doc, steps):
        """Every step in one native call (agent_accel.build_selection: the visible image read once, the masks combined
        in Krita), or None to build step by step. Only when every source is a seed or a colour range, and no step before
        the last source refines: a refinement there changes what later sources combine with. Refinements on the last
        source and after it then apply to the combined selection in their order, as they would step by step."""
        sources = [index for index, step in enumerate(steps) if any(key in step for key in SOURCES)]
        if not sources or any('seed' not in steps[index] and 'color' not in steps[index] for index in sources):
            return None
        last = sources[-1]
        if any(key in step for step in steps[:last] for key in REFINEMENTS + ('smooth', 'invert')):
            return None
        from . import agent_accel
        sent = [dict({key: steps[index][key] for key in ('seed', 'color', 'tolerance', 'bounds') if key in steps[index]},
                     mode=steps[index].get('mode', 'replace' if index == 0 else 'add')) for index in sources]
        found = agent_accel.build_selection(doc.fileName() or '', sent)
        if found is None:
            return None
        (x, y, w, h), mask = found
        selection = Selection()
        if w and h:
            selection.setPixelData(mask, x, y, w, h)
        for step in steps[last:]:
            self._region_refine(selection, step)
        return selection

    def _region_source(self, doc, session, step, source):
        selection = Selection()
        if source == 'shape':
            if step['shape'] == 'rectangle':
                selection.select(*checked_bounds(step['bounds'], doc.width(), doc.height()), 255)
                return selection
            from . import region_raster
            if step['shape'] == 'polygon':
                points, rect = self._region_polygon(doc, step['points'])
            else:
                points, rect = None, checked_bounds(step['bounds'], doc.width(), doc.height())
            selection.setPixelData(region_raster.shape_mask(step['shape'], rect, points), *rect)
            return selection
        if source == 'layer_id':
            return self._craft_alpha_selection(doc, self._creative_node(doc, step['layer_id']))[0]
        if source == 'saved':
            return self._region_load(session, step['saved'])
        if source == 'feature':
            return self._feature_selection(doc, step['feature'])
        return self._region_colour(doc, step, source)

    def _region_colour(self, doc, step, source, native=True):
        """A colour range on the visible image (`color`), or the part of it joined to the seed (`seed`): through the
        native helper when Krita loaded it and `native`, else read in strips here. Both select the same pixels."""
        x, y, w, h = checked_bounds(step['bounds'], doc.width(), doc.height()) if 'bounds' in step else \
            (0, 0, doc.width(), doc.height())
        root = doc.rootNode()
        doc.waitForDone()
        if native:
            selection = self._region_native_colour(doc, step, source, (x, y, w, h))
            if selection is not None:
                return selection
        selection = Selection()
        if source == 'seed':
            seed_x, seed_y = self._region_seed(doc, step)
            pixel = bytes(root.projectionPixelData(seed_x, seed_y, 1, 1))
            wanted = bytes((pixel[2], pixel[1], pixel[0]))
        else:
            wanted = bytes.fromhex(step['color'][1:])
        strips = []
        for top in range(y, y + h, STRIP):
            rows = min(STRIP, y + h - top)
            strips.append(colour_mask(bytes(root.projectionPixelData(x, top, w, rows)), wanted, step.get('tolerance', 24)))
        if source == 'seed':
            strips = [connected_mask(b''.join(strips), w, h, seed_x - x, seed_y - y)]
        selection.setPixelData(b''.join(strips), x, y, w, h)
        return selection

    def _region_native_colour(self, doc, step, source, rect):
        """The colour or seed step from the native helper (agent_accel.select_similar / select_contiguous: the same
        test per channel, the same edge neighbours, on Krita's projection), or None without it. Its mask covers only
        the selected pixels' bounding rect; nothing selected is an empty selection."""
        from . import agent_accel
        tolerance = step.get('tolerance', 24)
        if source == 'seed':
            found = agent_accel.select_contiguous(doc.fileName() or '', self._region_seed(doc, step), tolerance, rect)
        else:
            found = agent_accel.select_similar(doc.fileName() or '', step['color'], tolerance, rect)
        if found is None:
            return None
        (x, y, w, h), mask = found
        selection = Selection()
        if w and h:
            selection.setPixelData(mask, x, y, w, h)
        return selection

    def _region_seed(self, doc, step):
        """The seed's (x, y), checked to lie on the canvas and inside the step's bounds."""
        seed = step['seed']
        if not isinstance(seed, list) or len(seed) != 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in seed):
            raise ValueError('seed must be [x, y] in whole canvas pixels')
        x, y = seed
        if not (0 <= x < doc.width() and 0 <= y < doc.height()):
            raise ValueError('seed must lie on the canvas (%d x %d)' % (doc.width(), doc.height()))
        if 'bounds' in step:
            left, top, w, h = checked_bounds(step['bounds'], doc.width(), doc.height())
            if not (left <= x < left + w and top <= y < top + h):
                raise ValueError('the seed must lie inside its bounds')
        return x, y

    def _region_bounds(self, doc, selection):
        """The selection's extent inside the canvas, or None when nothing is selected there."""
        left, top = max(0, selection.x()), max(0, selection.y())
        right = min(doc.width(), selection.x() + selection.width())
        bottom = min(doc.height(), selection.y() + selection.height())
        if right <= left or bottom <= top:
            return None
        rect = (left, top, right - left, bottom - top)
        covered = sum(bytes(selection.pixelData(*rect)))
        return (rect, covered // 255) if covered else None

    OPEN_EDGE_NOTE = ('This selection ends in a straight line through open paint (open_edges: where, in canvas pixels): '
                      'anything painted inside it shows that line as a hard edge, which Luna undoes as a flat block. '
                      'Extend the selection across it (another seed step, or bounds that reach past it), or feather it widely.')

    def _region_open_edges(self, doc, selection, rect):
        """selection_edges.open_edges on `rect` grown by a pixel inside the canvas, against the visible painting."""
        from . import selection_edges
        x, y, w, h = rect
        left, top = max(0, x - 1), max(0, y - 1)
        grown = (left, top, min(doc.width(), x + w + 1) - left, min(doc.height(), y + h + 1) - top)
        return selection_edges.open_edges(bytes(selection.pixelData(*grown)), bytes(doc.rootNode().projectionPixelData(*grown)),
                                          grown, (doc.width(), doc.height()))

    def _region_warn_edges(self, doc, selection, rect, result):
        found = self._region_open_edges(doc, selection, rect)
        if found:
            result.update(open_edges=found, note=self.OPEN_EDGE_NOTE)
        return result

    # ----- saved selections ----------------------------------------------------
    def _region_saved_path(self, session, name, must_exist=False):
        if not isinstance(name, str) or not NAME.match(name):
            raise ValueError('A selection name is 1-40 letters, digits, spaces, - or _.')
        if not session.get('output'):
            raise ValueError('Saved selections need a study folder.')
        slug = hashlib.sha256(name.strip().lower().encode()).hexdigest()[:24]
        path = os.path.join(session['output'], '.selections', slug + '.sel')
        if must_exist and not os.path.exists(path):
            known = sorted(self._region_saved_names(session))
            raise ValueError('No saved selection "%s". Saved: %s' % (name, ', '.join(known) or 'none'))
        return path

    def _region_saved_names(self, session):
        folder = os.path.join(session.get('output') or '', '.selections')
        names = []
        if os.path.isdir(folder):
            for entry in os.listdir(folder):
                try:
                    with open(os.path.join(folder, entry), 'rb') as stream:
                        names.append(json.loads(stream.readline())['name'])
                except (OSError, ValueError, KeyError):
                    continue
        return names

    def _region_write(self, path, header, data):
        """A JSON header line, then the 8-bit mask bytes compressed. Written atomically."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + '.tmp', 'wb') as stream:
            stream.write(json.dumps(header).encode() + b'\n' + zlib.compress(bytes(data), 6))
        os.replace(path + '.tmp', path)

    def _region_read(self, path):
        with open(path, 'rb') as stream:
            header = json.loads(stream.readline())
            return header, zlib.decompress(stream.read())

    def _region_save(self, doc, session, name, selection, rect):
        self._region_write(self._region_saved_path(session, name),
                           {'name': name.strip(), 'rect': list(rect), 'canvas': [doc.width(), doc.height()]},
                           selection.pixelData(*rect))

    def _region_has_saved(self, session, name):
        return (isinstance(name, str) and bool(NAME.match(name)) and bool(session.get('output'))
                and os.path.exists(self._region_saved_path(session, name)))

    def _region_check_named(self, doc, session, name):
        """Validation of a selection given by name: a saved selection, or (our Krita) a feature name or expression such as
        "Sky - Moon". A saved selection wins when both exist."""
        if self._region_has_saved(session, name):
            return
        if self._feature_ready(doc):
            try:
                self._feature_selection(doc, name)       # resolved and discarded: a typo is refused now, before any layer exists
            except ValueError:
                known = sorted(self._region_saved_names(session))
                raise ValueError('No saved selection or feature "%s". Saved: %s. Features: %s.' % (
                    name, ', '.join(known) or 'none', ', '.join(self._feature_names(doc)) or 'none')) from None
            return
        self._region_saved_path(session, name, must_exist=True)

    def _region_load(self, session, name, doc=None):
        """A saved selection, else (given the document, in our Krita) the features `name` is or combines."""
        if doc is not None and self._feature_ready(doc) and not self._region_has_saved(session, name):
            return self._feature_selection(doc, name)
        header, data = self._region_read(self._region_saved_path(session, name, must_exist=True))
        selection = Selection()
        selection.setPixelData(data, *header['rect'])
        return selection

    # ----- select --------------------------------------------------------------
    def _region_select(self, doc, session, params, whole=True):
        """`whole`: try the one-call build (select_probe turns it off to time the per-step build)."""
        fields(params, SELECT_FIELDS, SELECT_FIELDS)
        self._region_saved_path(session, params['name'])
        self._region_validate_steps(doc, session, params['steps'])
        ms, clock = {}, [time.monotonic()]
        def lap(part):
            now = time.monotonic(); ms[part] = int((now - clock[0]) * 1000); clock[0] = now
        selection = self._region_build(doc, session, params['steps'], whole); lap('build')
        extent = self._region_bounds(doc, selection); lap('bounds')
        if extent is None:
            raise ValueError('The selection is empty inside the canvas. Nothing was saved.')
        rect, pixels = extent
        self._region_save(doc, session, params['name'], selection, rect); lap('save')
        result = self._region_warn_edges(doc, selection, rect, {'status': 'ok', 'name': params['name'].strip(), 'bounds': list(rect), 'selected_pixels': pixels})
        lap('edges')
        result['timings_ms'] = ms                        # where a select's time goes (host-only, like a pass's timings)
        return result

    # ----- fill_region ---------------------------------------------------------
    def _region_validate_fill(self, doc, session, params):
        fields(params, FILL_FIELDS)
        self._craft_check_rgba(doc, 'A region fill')
        paints = [key for key in ('color', 'gradient', 'pattern') if key in params]
        if len(paints) != 1:
            raise ValueError('Fill with exactly one of: color, gradient or pattern.')
        self._region_paint(doc, params)
        areas = [key for key in ('selection', 'area') if key in params]
        if len(areas) != 1:
            raise ValueError('Give the area to fill: selection (a saved name) or area (selection steps).')
        if 'selection' in params:
            self._region_check_named(doc, session, params['selection'])
        else:
            self._region_validate_steps(doc, session, params['area'])
        if params.get('layer_id'):
            given = [key for key in NEW_LAYER_ONLY if key in params]
            if given:
                raise ValueError('%s set up a new layer. To fill an existing layer, leave them out and use set_layer.' % ', '.join(given))
            node = self._creative_node(doc, text(params['layer_id'], 'layer_id', 200))
            if not self._craft_owned(session, params['layer_id']):
                raise ValueError('Only layers the agent created can be filled. Fill a new layer above this one instead.')
            if node.type() != 'paintlayer' or node.locked():
                raise ValueError('Fill an unlocked paint layer, or a new layer.')
            if 'name' in params:
                text(params['name'], 'name', 120)
        else:
            if 'name' not in params:
                raise ValueError('Name the new layer, or give layer_id to fill an agent layer.')
            self._craft_validate_create(doc, session, self._region_layer_params(params))

    def _region_layer_params(self, params):
        layer = {key: params[key] for key in ('name', 'stage_id', 'panel') + NEW_LAYER_ONLY if key in params}
        layer['type'] = 'paint'
        return layer

    def _region_paint(self, doc, params):
        """The validated paint, as region_raster takes it."""
        if 'color' in params:
            return {'kind': 'color', 'color': hex_colour(params['color'])}
        if 'pattern' in params:
            name = text(params['pattern'], 'pattern', 200)
            if name not in self._craft_manifest(doc).get('patterns', []):
                raise ValueError('Unknown pattern "%s". krita_capabilities lists installed patterns.' % name)
            return {'kind': 'pattern', 'name': name}
        gradient = params['gradient']
        fields(gradient, ('type', 'start', 'end', 'stops'), ('start', 'end', 'stops'))
        if gradient.get('type', 'linear') not in ('linear', 'radial'):
            raise ValueError('gradient type must be linear or radial')
        for key in ('start', 'end'):
            point = gradient[key]
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError('gradient %s must be [x,y]' % key)
            for value in point:
                numeric(value, 'gradient ' + key, -100000, 100000)
        if gradient['start'] == gradient['end']:
            raise ValueError('gradient start and end must differ')
        stops = gradient['stops']
        if not isinstance(stops, list) or not 2 <= len(stops) <= 16:
            raise ValueError('a gradient needs 2-16 stops {offset, color}')
        last = -1
        for stop in stops:
            fields(stop, ('offset', 'color'), ('offset', 'color'))
            numeric(stop['offset'], 'stop offset', 0, 1)
            hex_colour(stop['color'])
            if stop['offset'] < last:
                raise ValueError('gradient stops must be in increasing offset order')
            last = stop['offset']
        return {'kind': 'gradient', 'gradient': dict(gradient, type=gradient.get('type', 'linear'))}

    def _region_pattern_image(self, name):
        resource = Krita.instance().resources('pattern').get(name)
        image = resource.image() if resource is not None else None
        if image is None or image.isNull():
            raise RuntimeError('Krita could not load the pattern "%s".' % name)
        return image

    def _region_fill(self, doc, session, params):
        from . import region_raster
        selection = (self._region_load(session, params['selection'], doc) if 'selection' in params
                     else self._region_build(doc, session, params['area']))
        extent = self._region_bounds(doc, selection)
        if extent is None:
            # Nothing changed yet: the journal records this as a refused call.
            return {'status': 'rejected', 'error': 'The area is empty inside the canvas. Nothing was filled.',
                    'error_code': 'validation_rejected'}
        rect, pixels = extent
        x, y, w, h = rect
        spec = self._region_paint(doc, params)
        if spec['kind'] == 'pattern':
            spec['image'] = self._region_pattern_image(spec['name'])
        source = self._creative_node(doc, params['layer_id']) if params.get('layer_id') else None
        if source is not None:
            target, result = self._craft_edit_copy(doc, session, source, params.get('name'))
            base, alpha_lock = bytes(target.pixelData(x, y, w, h)), bool(target.alphaLocked())
        else:
            result = self._craft_create(doc, session, self._region_layer_params(params))
            target = self._creative_node(doc, result['layer_id'])
            base, alpha_lock = None, False
        filled = region_raster.paint(base, w, h, bytes(selection.pixelData(x, y, w, h)), spec, (x, y), alpha_lock)
        if target.setPixelData(filled, x, y, w, h) is False:
            raise RuntimeError('Krita rejected the filled pixels.')
        if source is not None:
            self._craft_finish_copy(doc, session, source, result)
        doc.setActiveNode(target)
        if source is not None:
            doc.refreshProjection()                       # the original is hidden: its whole layer changes
        else:
            canvas_projection.pixels_written(doc, rect)    # a new layer, its settings composited when made: only the fill
        result.update(filled_bounds=list(rect), filled_pixels=pixels)
        return self._region_warn_edges(doc, selection, rect, result)

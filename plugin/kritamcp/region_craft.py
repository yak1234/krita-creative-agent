"""Selections and region fills: flats and gradients in one call instead of strokes.

A selection is built from steps (a shape, a layer's alpha, a colour range on the
visible image, or a saved selection), combined and refined in order. `select`
saves it under a name in the study folder, so later turns reuse it; `fill_region`
takes that name or the same steps inline. Neither touches the artist's selection.

`select` is not a canvas change: no pass, no checkpoint. `fill_region` runs inside
the creative operation journal (creative_tools.py) and fills a new layer, or a copy
of an agent layer with the original hidden, so reject restores the original.
"""
import hashlib
import json
import os
import re
import zlib
from krita import Krita, Selection
from .creative_validation import color as hex_colour, fields, numeric, text
from .geometry_data import bounds as checked_bounds, polygon

STEP_FIELDS = ('shape', 'bounds', 'points', 'layer_id', 'color', 'tolerance', 'saved', 'mode',
               'grow', 'shrink', 'border', 'feather', 'smooth', 'invert')
SOURCES = ('shape', 'layer_id', 'color', 'saved')
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
                    raise ValueError('choose one source: shape, layer_id, color or saved')
                if index == 0 and not sources:
                    raise ValueError('the first step needs a source: shape, layer_id, color or saved')
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
        if source != 'shape' and ('points' in step or ('bounds' in step and source != 'color')):
            raise ValueError('bounds and points belong to a shape (bounds also limits a colour range)')
        if source != 'color' and 'tolerance' in step:
            raise ValueError('tolerance belongs to a colour range')
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
        elif source == 'color':
            self._craft_check_rgba(doc, 'A colour-range selection')
            hex_colour(step['color'])
            if 'tolerance' in step and (isinstance(step['tolerance'], bool) or not isinstance(step['tolerance'], int)
                                        or not 0 <= step['tolerance'] <= 255):
                raise ValueError('tolerance must be an integer from 0 to 255')
            if 'bounds' in step:
                checked_bounds(step['bounds'], doc.width(), doc.height())
        elif source == 'saved':
            self._region_saved_path(session, step['saved'], must_exist=True)

    def _region_polygon(self, doc, points):
        return polygon(points, doc.width(), doc.height())

    def _region_build(self, doc, session, steps):
        """The selection the validated steps describe."""
        selection = None
        for index, step in enumerate(steps):
            source = next((key for key in SOURCES if key in step), None)
            if source:
                built = self._region_source(doc, session, step, source)
                mode = step.get('mode', 'replace' if index == 0 else 'add')
                if selection is None or mode == 'replace':
                    selection = built
                else:
                    getattr(selection, mode)(built)
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
        # A colour range on the visible image, read in strips.
        x, y, w, h = checked_bounds(step['bounds'], doc.width(), doc.height()) if 'bounds' in step else \
            (0, 0, doc.width(), doc.height())
        wanted = bytes.fromhex(step['color'][1:])
        root = doc.rootNode()
        doc.waitForDone()
        for top in range(y, y + h, STRIP):
            rows = min(STRIP, y + h - top)
            selection.setPixelData(colour_mask(bytes(root.projectionPixelData(x, top, w, rows)), wanted,
                                               step.get('tolerance', 24)), x, top, w, rows)
        return selection

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

    def _region_load(self, session, name):
        header, data = self._region_read(self._region_saved_path(session, name, must_exist=True))
        selection = Selection()
        selection.setPixelData(data, *header['rect'])
        return selection

    # ----- select --------------------------------------------------------------
    def _region_select(self, doc, session, params):
        fields(params, SELECT_FIELDS, SELECT_FIELDS)
        self._region_saved_path(session, params['name'])
        self._region_validate_steps(doc, session, params['steps'])
        selection = self._region_build(doc, session, params['steps'])
        extent = self._region_bounds(doc, selection)
        if extent is None:
            raise ValueError('The selection is empty inside the canvas. Nothing was saved.')
        rect, pixels = extent
        self._region_save(doc, session, params['name'], selection, rect)
        return {'status': 'ok', 'name': params['name'].strip(), 'bounds': list(rect), 'selected_pixels': pixels}

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
            self._region_saved_path(session, params['selection'], must_exist=True)
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
        selection = (self._region_load(session, params['selection']) if 'selection' in params
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
        doc.refreshProjection()
        result.update(filled_bounds=list(rect), filled_pixels=pixels)
        return result

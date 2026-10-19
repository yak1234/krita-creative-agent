"""Materials and stamps: brush tips cut from the painting (or a layer, or an image), stamped into an area.

Krita makes a brush tip from an area only in its brush editor (Custom Brush: Stamp, Clipboard); 5.3.3's scripting API
cannot create or import one, and a tip file in the resources folder is only seen after a restart. So a material is the
plugin's own: greyscale tips saved with the chat (`<study>/.materials/<slug>/`), and `stamp` paints dabs of them with
one QPainter onto one new agent layer, a reversible pass like `fill_region`. No Krita resource is written.

`make_material` is not a canvas change: no pass, no checkpoint, like `select`. The pixel work is material_raster.py,
imported where it is used so this module loads without Qt in the companion's tests.
"""
import base64
import binascii
import hashlib
import json
import os

from .creative_validation import color as hex_colour, fields, numeric, text
from . import canvas_projection

MATERIAL_FIELDS = ('name', 'source', 'kind', 'count', 'size')
SOURCE_FIELDS = ('area', 'selection', 'layer_id', 'image_base64')
STAMP_FIELDS = ('name', 'material', 'selection', 'area', 'dabs', 'tint', 'stage_id', 'region', 'expected_revision', 'panel')
DAB_FIELDS = ('x', 'y', 'scale', 'stretch', 'rotation', 'opacity', 'tip')
KINDS = ('light', 'shape')
MAX_DABS = 2000
# Ink per selected pixel (material_raster.coverage) above which a stamp is thinned. On New Moscow's sky (run 10, Luna
# offline on rebuilt batches): 0.44 kept, 2.3 a pale veil Luna undid; 0.6 with the area's edge faded passed.
MAX_COVERAGE = 0.6
MAX_IMAGE = 12 * 1024 * 1024


class MaterialCraft:
    # ----- storage ---------------------------------------------------------------
    def _material_folder(self, session, name, must_exist=False):
        # Any readable name: the folder is a hash of it, so dashes and accents are fine (run 7: "Cloud tips — cut ...").
        if not isinstance(name, str) or not name.strip() or len(name) > 40 or any(ord(c) < 32 for c in name):
            raise ValueError('A material name is 1-40 readable characters.')
        if not session.get('output'):
            raise ValueError('Materials need a study folder.')
        folder = os.path.join(session['output'], '.materials', hashlib.sha256(name.strip().lower().encode()).hexdigest()[:24])
        if must_exist and not os.path.isfile(os.path.join(folder, 'material.json')):
            known = sorted(self._material_names(session))
            raise ValueError('No material "%s". Made in this chat: %s' % (name, ', '.join(known) or 'none'))
        return folder

    def _material_names(self, session):
        root = os.path.join(session.get('output') or '', '.materials')
        names = []
        for entry in (os.listdir(root) if os.path.isdir(root) else []):
            try:
                with open(os.path.join(root, entry, 'material.json')) as handle:
                    names.append(json.load(handle)['name'])
            except (OSError, ValueError, KeyError):
                continue
        return names

    def _material_load(self, session, name):
        from . import material_raster
        folder = self._material_folder(session, name, must_exist=True)
        with open(os.path.join(folder, 'material.json')) as handle:
            record = json.load(handle)
        return record, [material_raster.load_tip(os.path.join(folder, 'tip-%d.png' % i), record['size']) for i in range(record['tips'])]

    # ----- make_material -----------------------------------------------------------
    def _material_source(self, doc, session, source):
        """(BGRA, width, height, origin on the canvas or None, selection mask or None)."""
        from . import material_raster
        if not isinstance(source, dict):
            raise ValueError('source is {area}, {selection}, {layer_id} or {image_base64}.')
        fields(source, SOURCE_FIELDS)
        given = [key for key in SOURCE_FIELDS if key in source]
        if len(given) != 1:
            raise ValueError('Give exactly one source: area (selection steps), selection (a saved name), layer_id, or image_base64.')
        key = given[0]
        if key in ('area', 'selection'):
            if key == 'area':
                self._region_validate_steps(doc, session, source['area'])
            selection = (self._region_load(session, source['selection']) if key == 'selection'
                         else self._region_build(doc, session, source['area']))
            extent = self._region_bounds(doc, selection)
            if extent is None:
                raise ValueError('The source area is empty inside the canvas.')
            rect = extent[0]
            return bytes(doc.pixelData(*rect)), rect[2], rect[3], rect[:2], bytes(selection.pixelData(*rect))
        if key == 'layer_id':
            node = self._creative_node(doc, text(source['layer_id'], 'layer_id', 200))
            box = node.bounds()
            left, top = max(0, box.x()), max(0, box.y())
            right, bottom = min(doc.width(), box.x() + box.width()), min(doc.height(), box.y() + box.height())
            if right <= left or bottom <= top:
                raise ValueError('That layer has no pixels on the canvas.')
            rect = (left, top, right - left, bottom - top)
            return bytes(node.pixelData(*rect)), rect[2], rect[3], rect[:2], None
        try:
            data = base64.b64decode(text(source['image_base64'], 'image_base64', MAX_IMAGE * 2), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError('image_base64 is not base64.')
        decoded = material_raster.decode(data)
        if decoded is None:
            raise ValueError('The image could not be read.')
        return decoded + (None, None)

    def _material_make(self, doc, session, params):
        from . import material_raster
        fields(params, MATERIAL_FIELDS, ('name', 'source'))
        name = params['name'].strip() if isinstance(params['name'], str) else params['name']
        folder = self._material_folder(session, name)
        kind = params.get('kind', 'light')
        if kind not in KINDS:
            raise ValueError('kind is light (light over its surroundings: clouds, highlights) or shape (the source alpha).')
        count = int(numeric(params.get('count', 6), 'count', 1, 8))
        size = int(numeric(params.get('size', 220), 'size', 32, 512))
        bgra, w, h, origin, mask = self._material_source(doc, session, params['source'])
        if kind == 'shape':
            tips = [(material_raster.shape_tip(bgra, w, h, size), (0, 0, w, h))]
        else:
            # Never cut from a protected area: its bounds, moved into the source's coordinates.
            avoid = [] if origin is None else [
                (a['bounds'][0] - origin[0], a['bounds'][1] - origin[1], a['bounds'][2], a['bounds'][3]) for a in self._protect_active(doc)]
            tips = material_raster.light_tips(bgra, w, h, count=count, size=size, mask=mask, avoid=avoid)
            if not tips:
                raise ValueError('No light detail in that source to cut tips from. Choose an area with clouds, foam or '
                                 'highlights, or kind shape for a cut-out.')
            size = int(round(len(tips[0][0]) ** 0.5))                  # light_tips fits the size to the source
        os.makedirs(folder, exist_ok=True)
        for index, (data, _rect) in enumerate(tips):
            material_raster.save_tip(data, size, os.path.join(folder, 'tip-%d.png' % index))
        sheet = os.path.join(folder, 'sheet.png')
        material_raster.contact_sheet([data for data, _rect in tips], size).save(sheet, 'PNG')
        rects = [list(rect) if origin is None else [rect[0] + origin[0], rect[1] + origin[1], rect[2], rect[3]] for _data, rect in tips]
        record = {'name': name, 'kind': kind, 'size': size, 'tips': len(tips), 'source_rects': rects,
                  'source': next(key for key in SOURCE_FIELDS if key in params['source'])}
        with open(os.path.join(folder, 'material.json'), 'w') as handle:
            json.dump(record, handle)
        return {'status': 'ok', 'material': name, 'kind': kind, 'tips': len(tips), 'size': size,
                'source_rects': rects, 'sheet_path': sheet}

    # ----- stamp ---------------------------------------------------------------------
    def _stamp_validate(self, doc, session, params):
        fields(params, STAMP_FIELDS, ('name', 'material', 'dabs'))
        self._craft_check_rgba(doc, 'A stamp')
        record, _tips = self._material_load(session, params['material'])
        areas = [key for key in ('selection', 'area') if key in params]
        if len(areas) != 1:
            raise ValueError('Give the area to stamp into: selection (a saved name) or area (selection steps).')
        if 'selection' in params:
            self._region_saved_path(session, params['selection'], must_exist=True)
        else:
            self._region_validate_steps(doc, session, params['area'])
        dabs = params['dabs']
        if not isinstance(dabs, list) or not dabs:
            raise ValueError('dabs is a list of 1-%d dabs.' % MAX_DABS)
        if len(dabs) > MAX_DABS:
            raise ValueError('At most %d dabs in one stamp.' % MAX_DABS)
        for dab in dabs:
            fields(dab, DAB_FIELDS, DAB_FIELDS)
            numeric(dab['x'], 'dab x', -100000, 100000); numeric(dab['y'], 'dab y', -100000, 100000)
            numeric(dab['scale'], 'dab scale', 0.02, 20); numeric(dab['stretch'], 'dab stretch', 0.2, 5)
            numeric(dab['rotation'], 'dab rotation', -360, 360); numeric(dab['opacity'], 'dab opacity', 0, 1)
            if not isinstance(dab['tip'], int) or not 0 <= dab['tip'] < record['tips']:
                raise ValueError('dab tip is 0-%d: the material has %d tips.' % (record['tips'] - 1, record['tips']))
        if 'tint' in params:
            tint = params['tint']
            fields(tint, ('color', 'amount', 'toward'), ('color', 'amount'))
            hex_colour(tint['color']); numeric(tint['amount'], 'tint amount', 0, 1)
            if tint.get('toward', 'all') not in ('top', 'all'):
                raise ValueError('tint toward is top or all.')
        self._craft_validate_create(doc, session, self._stamp_layer_params(params))

    def _stamp_layer_params(self, params):
        layer = {key: params[key] for key in ('name', 'stage_id', 'panel') if key in params}
        layer['type'] = 'paint'
        return layer

    def _stamp_apply(self, doc, session, params):
        from . import material_raster
        record, tips = self._material_load(session, params['material'])
        selection = (self._region_load(session, params['selection']) if 'selection' in params
                     else self._region_build(doc, session, params['area']))
        extent = self._region_bounds(doc, selection)
        if extent is None:
            return {'status': 'rejected', 'error': 'The area is empty inside the canvas. Nothing was stamped.',
                    'error_code': 'validation_rejected'}
        (x, y, w, h), _pixels = extent
        dabs = [dict(dab, x=dab['x'] - x, y=dab['y'] - y) for dab in params['dabs']]
        tint = dict(params['tint'], color=hex_colour(params['tint']['color'])) if 'tint' in params else None
        mask = bytes(selection.pixelData(x, y, w, h))
        ink = material_raster.coverage(dabs, tips, record['size'], mask)
        thinned = MAX_COVERAGE / ink if ink > MAX_COVERAGE else None
        if thinned:                                       # too much ink veils the area: every dab lighter, same layout
            dabs = [dict(dab, opacity=dab['opacity'] * thinned) for dab in dabs]
        out, placed = material_raster.stamp(bytes(doc.pixelData(x, y, w, h)), w, h, mask, tips, record['size'], dabs, tint)
        if not placed:
            # Nothing changed yet: the journal records this as a refused call.
            return {'status': 'rejected', 'error': 'No dab is centred inside the area. Nothing was stamped.',
                    'error_code': 'validation_rejected'}
        result = self._craft_create(doc, session, self._stamp_layer_params(params))
        target = self._creative_node(doc, result['layer_id'])
        if target.setPixelData(out, x, y, w, h) is False:
            raise RuntimeError('Krita rejected the stamped pixels.')
        doc.setActiveNode(target)
        canvas_projection.pixels_written(doc, (x, y, w, h))   # a new layer, its settings composited when made: only the stamp
        result.update(stamped_bounds=[x, y, w, h], dabs_placed=placed, material=record['name'], coverage=round(min(ink, MAX_COVERAGE), 3))
        if thinned:
            result['opacity_scaled'] = round(thinned, 3)
        return self._region_warn_edges(doc, selection, (x, y, w, h), result)

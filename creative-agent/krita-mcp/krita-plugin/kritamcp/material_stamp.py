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
import contextlib
import hashlib
import json
import os
import re

import krita as krita_module
from krita import Krita, Selection
from .creative_validation import color as hex_colour, fields, numeric, text
from .script_steps import one_step
from .stamp_names import PREFIX
from . import canvas_projection

MATERIAL_FIELDS = ('name', 'source', 'kind', 'count', 'size')
SOURCE_FIELDS = ('area', 'selection', 'layer_id', 'image_base64')
STAMP_FIELDS = ('name', 'material', 'selection', 'area', 'dabs', 'tint', 'brush', 'stage_id', 'region', 'expected_revision', 'panel')
DAB_FIELDS = ('x', 'y', 'scale', 'stretch', 'rotation', 'opacity', 'tip')
KINDS = ('light', 'shape')
MAX_DABS = 2000
# Ink per selected pixel (material_raster.coverage) above which a stamp is thinned. On New Moscow's sky (run 10, Luna
# offline on rebuilt batches): 0.44 kept, 2.3 a pale veil Luna undid; 0.6 with the area's edge faded passed.
MAX_COVERAGE = 0.6
MAX_IMAGE = 12 * 1024 * 1024
# The Krita-brush stamp: the base presets tried in order when the painter names none, and the most tip variants (a tip and a
# preset each, one job each) one stamp makes before its variants get coarser.
BASE_PRESETS = ('b) Basic-1', 'b) Basic-3 Flow', 'b) Basic-5 Size')
MAX_VARIANTS = 48
RESOURCE_PREFIX = PREFIX


REGISTRY = ('creative-agent', 'stamp-resources')      # Krita's settings: {resource name: {digest, preset}} for what the agent made
DESTRUCTIVE = ('erase', 'clear', 'copy', 'multiply', 'destination_in', 'destination_atop', 'alphadarken')


def krita_brush_stamps():
    """True in our Krita: the application can make brush tips and presets (Krita.createBrushTip, createPreset)."""
    app = Krita.instance()
    return hasattr(app, 'createBrushTip') and hasattr(app, 'createPreset')


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
        if krita_brush_stamps():
            self._stamp_base_name(params)
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

    def _stamp_base_name(self, params):
        """The base preset a Krita-brush stamp makes its presets from: `brush`, else the first installed of BASE_PRESETS."""
        installed = Krita.instance().resources('preset')
        if 'brush' in params:
            name = text(params['brush'], 'brush', 200)
            if name not in installed:
                raise ValueError('Use an exact installed preset name from list_brushes as the brush.')
            self._stamp_check_base(name, installed[name])
            return name
        for name in BASE_PRESETS:
            if name in installed:
                return name
        raise ValueError('None of the usual base brushes (%s) is installed: name one with brush (see list_brushes).' % ', '.join(BASE_PRESETS))

    @staticmethod
    def _stamp_check_base(name, resource):
        """A stamp paints soft dabs of light: an eraser, or a brush whose blending mode destroys or darkens, would not. Known
        from the name, and from the preset's CompositeOp when this Krita can give the preset's XML."""
        mode = ''
        preset = getattr(krita_module, 'Preset', None)
        if preset is not None:
            try:
                found = re.search(r'name="CompositeOp"[^>]*>\s*([A-Za-z_]+)\s*<', preset(resource).toXML())
                mode = found.group(1).lower() if found else ''
            except Exception:
                mode = ''
        if re.search(r'eras', name, re.IGNORECASE) or mode in DESTRUCTIVE:
            raise ValueError('The brush "%s" %s: a stamp needs a base brush that paints normally. Choose another with brush.' % (
                name, 'erases' if 'eras' in name.lower() or mode == 'erase' else 'blends in "%s" mode' % mode))

    def _stamp_plan(self, doc, session, params):
        """What both stamps share: the area, the dabs in its coordinates, thinned to the coverage cap. (plan, None), or
        (None, a rejected result) when the area is empty inside the canvas."""
        from . import material_raster
        record, tips = self._material_load(session, params['material'])
        selection = (self._region_load(session, params['selection']) if 'selection' in params
                     else self._region_build(doc, session, params['area']))
        extent = self._region_bounds(doc, selection)
        if extent is None:
            return None, {'status': 'rejected', 'error': 'The area is empty inside the canvas. Nothing was stamped.',
                          'error_code': 'validation_rejected'}
        (x, y, w, h), _pixels = extent
        dabs = [dict(dab, x=dab['x'] - x, y=dab['y'] - y) for dab in params['dabs']]
        tint = dict(params['tint'], color=hex_colour(params['tint']['color'])) if 'tint' in params else None
        mask = bytes(selection.pixelData(x, y, w, h))
        ink = material_raster.coverage(dabs, tips, record['size'], mask)
        thinned = MAX_COVERAGE / ink if ink > MAX_COVERAGE else None
        if thinned:                                       # too much ink veils the area: every dab lighter, same layout
            dabs = [dict(dab, opacity=dab['opacity'] * thinned) for dab in dabs]
        return dict(record=record, tips=tips, selection=selection, rect=(x, y, w, h), dabs=dabs, tint=tint, mask=mask,
                    ink=ink, thinned=thinned), None

    def _stamp_apply(self, doc, session, params, result=None):
        plan, rejected = self._stamp_plan(doc, session, params)
        if rejected:
            return rejected                               # nothing changed yet: the journal records a refused call
        if krita_brush_stamps():
            return self._stamp_brush(doc, session, params, plan, {} if result is None else result)
        painted = self._stamp_painter(doc, session, params, plan)
        if 'brush' in params and painted.get('status', 'ok') == 'ok':
            painted['brush_note'] = 'brush applies only in our Krita (the fork); this stamp was painted without it.'
        return painted

    # ----- the Krita-brush stamp (the fork) ------------------------------------------------------------------------------
    @staticmethod
    def _stamp_slug(name):
        return re.sub(r'[^A-Za-z0-9]+', ' ', name).strip()[:24] or 'material'

    def _stamp_resources(self, session, record, tips, variants, base_name):
        """The preset for each variant (tip index, key), made once and reused: {variant: (preset name, side)}, with the
        counts and any names Krita changed because they belong to another resource."""
        from . import material_raster
        app = Krita.instance()
        installed = app.resources('preset')
        base = installed[base_name]
        try:
            registry = json.loads(app.readSetting(REGISTRY[0], REGISTRY[1], '') or '{}')
        except (ValueError, AttributeError):
            registry = {}
        if not isinstance(registry, dict):
            registry = {}
        label = '%s %s' % (self._stamp_slug(record['name']), hashlib.sha256(record['name'].strip().lower().encode()).hexdigest()[:6])
        made, reused, renamed, got = 0, 0, [], {}
        for tip, key in variants:
            rotation, stretch = key
            side, alpha = material_raster.tip_variant(tips[tip], record['size'], rotation, stretch)
            name = '%s %s t%d r%d s%g' % (RESOURCE_PREFIX, label, tip, rotation, stretch)
            digest = hashlib.sha256(alpha + base_name.encode() + bytes([side % 256, side // 256])).hexdigest()
            entry = registry.get(name)
            if isinstance(entry, dict) and entry.get('digest') == digest and entry.get('preset') in installed:
                reused += 1                                  # the same tip on the same base, made by this agent earlier (any chat)
                got[(tip, key)] = (entry['preset'], side)
                continue
            resource = app.createBrushTip(material_raster.tip_image(alpha, side), name, 'alpha')
            preset = app.createPreset(base, resource, name) if resource else None
            if not preset:
                raise ValueError('Krita could not make a brush from the material "%s" with the base brush "%s": %s.' % (
                    record['name'], base_name, 'it refused the tip' if not resource else 'the base brush has no brush tip engine; choose another with brush'))
            if preset.name() != name:
                renamed.append(preset.name())
            registry[name] = {'digest': digest, 'preset': preset.name()}
            made += 1
            got[(tip, key)] = (preset.name(), side)
        if made:
            try:
                app.writeSetting(REGISTRY[0], REGISTRY[1], json.dumps(registry))
            except AttributeError:
                pass
        return got, made, reused, renamed

    def _stamp_clip(self, doc, params, plan):
        """The job's selection: the area's mask faded at its edge, times the stage region's mask, in the area's rectangle."""
        from . import material_raster
        x, y, w, h = plan['rect']
        clip = material_raster.clip_mask(plan['mask'], w, h, plan['dabs'], plan['record']['size'])
        if params.get('region'):
            import numpy
            from .stage_mask import mask as stage_mask
            rx, ry, rw, rh = params['region']
            stage = stage_mask(params['region'], doc.width(), doc.height())
            left, top, right, bottom = max(x, rx), max(y, ry), min(x + w, rx + rw), min(y + h, ry + rh)
            out = numpy.zeros((h, w), numpy.uint8)
            if right > left and bottom > top:
                area = numpy.frombuffer(clip, numpy.uint8).reshape(h, w)[top - y:bottom - y, left - x:right - x].astype(numpy.uint16)
                out[top - y:bottom - y, left - x:right - x] = (area * stage[top - ry:bottom - ry, left - rx:right - rx] // 255).astype(numpy.uint8)
            clip = out.tobytes()
        selection = Selection()
        selection.setPixelData(clip, x, y, w, h)
        return selection

    def _stamp_brush(self, doc, session, params, plan, result):
        from . import material_raster
        record, tips, dabs = plan['record'], plan['tips'], plan['dabs']
        x, y, w, h = plan['rect']
        mask = plan['mask']
        placed = [dab for dab in dabs if 0 <= dab['x'] < w and 0 <= dab['y'] < h and mask[int(dab['y']) * w + int(dab['x'])] >= 128]
        if not placed:
            return {'status': 'rejected', 'error': 'No dab is centred inside the area. Nothing was stamped.',
                    'error_code': 'validation_rejected'}
        keys, level = material_raster.bucket_variants(placed, MAX_VARIANTS)
        variants = list(dict.fromkeys((dab['tip'], key) for dab, key in zip(placed, keys)))
        colours = material_raster.dab_colours(bytes(doc.pixelData(x, y, w, h)), w, h, placed, plan['tint'])
        base_name = self._stamp_base_name(params)
        try:
            presets, made, reused, renamed = self._stamp_resources(session, record, tips, variants, base_name)
        except ValueError as refused:
            return {'status': 'rejected', 'error': str(refused), 'error_code': 'validation_rejected'}
        batches = {}
        for dab, key, colour in zip(placed, keys, colours):
            preset, side = presets[(dab['tip'], key)]
            batches.setdefault(preset, []).append({
                'points': [[dab['x'] + x, dab['y'] + y]], 'color': colour, 'flow': 1.0,
                'size': min(10000.0, max(1.0, side * dab['scale'] * max(1.0, key[1]))),
                'opacity': min(1.0, max(0.01, dab['opacity']))})
        selection = self._stamp_clip(doc, params, plan)
        with (one_step(doc, 'Stamp: ' + params['name']) if len(batches) > 1 else contextlib.nullcontext()):
            result.update(self._craft_create(doc, session, self._stamp_layer_params(params)))
            node = self._creative_node(doc, result['layer_id'])
            result['stroke_job'] = job = {'state': 'done', 'strokes': 0, 'total': len(placed), 'ms': 0, 'jobs': len(batches)}
            for preset, strokes in batches.items():
                out = self._creative_stroke_job(doc, session, {'name': params['name'], 'preset': preset, 'strokes': strokes}, node,
                                                result, True, None, selection)
                if result.get('status') == 'rejected':
                    return {}                              # Krita refused: the layer is gone, nothing was painted
                done = out.get('stroke_job', {})
                job.update(strokes=job['strokes'] + done.get('strokes', 0), ms=job['ms'] + done.get('ms', 0), state=done.get('state', job['state']))
                if out.get('stopped'):
                    result.update(stopped=out['stopped'], stopped_after_strokes=job['strokes'], strokes_total=len(placed))
                    break
        result.update(stamped_bounds=[x, y, w, h], dabs_placed=len(placed), material=record['name'], engine='krita_brush',
                      coverage=round(min(plan['ink'], MAX_COVERAGE), 3),
                      brush={'base': base_name, 'application': 'alpha', 'presets': len(variants), 'created': made, 'reused': reused,
                             'variants': level})
        if level == 'plain' and any(d['rotation'] or d['stretch'] != 1 for d in placed):
            result['brush']['dropped'] = 'rotation and stretch: more than %d tip variants were needed' % MAX_VARIANTS
        if renamed:
            result['brush']['renamed'] = renamed
        if plan['thinned']:
            result['opacity_scaled'] = round(plan['thinned'], 3)
        return self._region_warn_edges(doc, plan['selection'], plan['rect'], result)

    # ----- the QPainter stamp (stock Krita, frozen) ---------------------------------------------------------------------
    def _stamp_painter(self, doc, session, params, plan):
        from . import material_raster
        record, tips, dabs, tint, mask = plan['record'], plan['tips'], plan['dabs'], plan['tint'], plan['mask']
        x, y, w, h = plan['rect']
        ink, thinned, selection = plan['ink'], plan['thinned'], plan['selection']
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

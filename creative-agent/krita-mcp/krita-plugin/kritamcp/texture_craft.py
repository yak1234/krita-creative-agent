# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""texture: the architecture texture pass (openspec architecture-texture goals 3-4), subtle photobash detail on a refine
step's architectural parts. The companion (extensions/architecture-texture.ts) decides the materials, tile sizes, direction
and strength per part with the planner model and sends the library's maps; this bakes them.

Each part's found area (a mask in the chat folder's .shapes, as Find it writes it) is read 1:1, the painting under it read
once, and texture_raster.py gives the part's pixels: the painting with the material's detail in its luminance only, the
mask's soft edge as alpha. Every part goes into ONE paint layer named by the call ("Texture: <part>"), a normal-blend layer
so the move's Met can merge its group whole, written only in the 64-px squares that hold detail. It is one pass of the move
(the creative operation journal, creative_tools.py), so the move's Undo (Redo of the step) hides it, protected areas are
kept as for any pass, and a call that is wrong in any way is refused before anything changes.
"""
import base64
import binascii
import time

import numpy as np

from .creative_validation import fields, numeric, text

TEXTURE_FIELDS = ('name', 'stage_id', 'materials', 'parts', 'panel', 'expected_revision')
PART_FIELDS = ('name', 'inside_shape', 'materials', 'tile_px', 'direction_deg', 'vanishing', 'strength', 'blend', 'seed')
MAP_FIELDS = ('color', 'displacement', 'ao', 'detail_from')
MAPS = ('color', 'displacement', 'ao')
BLENDS = ('soft_light', 'overlay')
STRENGTH = (0.05, 0.3)           # the companion keeps to 0.10-0.30; a little lower is allowed for a window grid
TILE = (16, 4000)
MOST_PARTS = 8
MOST_MATERIALS = 8
MAP_BYTES = 8 * 1024 * 1024
WRITE = 64


class TextureCraft:
    def _texture_maps(self, params):
        """{id: {color, displacement, ao}} decoded to greyscale arrays, and each material's detail_from."""
        from . import texture_raster
        materials = params['materials']
        if not isinstance(materials, dict) or not 1 <= len(materials) <= MOST_MATERIALS:
            raise ValueError('materials is {id: {color, displacement, ao}} for 1-%d materials.' % MOST_MATERIALS)
        decoded = {}
        for identifier, maps in materials.items():
            text(identifier, 'material id', 60)
            if not isinstance(maps, dict):
                raise ValueError('Material %s: its maps are {color, displacement, ao}.' % identifier)
            fields(maps, MAP_FIELDS, ('color', 'displacement'))
            grey = {}
            for key in MAPS:
                if key not in maps:
                    continue
                try:
                    data = base64.b64decode(text(maps[key], key + ' map', MAP_BYTES * 2), validate=True)
                except (binascii.Error, ValueError):
                    raise ValueError('Material %s: the %s map is not base64.' % (identifier, key)) from None
                grey[key] = texture_raster.decode_grey(data)
            detail_from = maps.get('detail_from')
            if detail_from is not None and (not isinstance(detail_from, list) or not detail_from or any(k not in MAPS for k in detail_from)):
                raise ValueError('Material %s: detail_from lists maps (color, displacement, ao).' % identifier)
            decoded[identifier] = (grey, detail_from)
        return decoded

    def _texture_parts(self, doc, session, params, known):
        """The parts checked, each with its found area read: [(part, rect, mask bytes)]."""
        from . import shape_mask
        parts = params['parts']
        if not isinstance(parts, list) or not 1 <= len(parts) <= MOST_PARTS:
            raise ValueError('parts is a list of 1-%d parts.' % MOST_PARTS)
        checked = []
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError('A part is an object.')
            fields(part, PART_FIELDS, ('name', 'inside_shape', 'materials', 'tile_px', 'strength'))
            text(part['name'], 'part name', 120)
            chosen = part['materials']
            if not isinstance(chosen, list) or not 1 <= len(chosen) <= 2:
                raise ValueError('Part %s: materials is a list of 1-2 {id, weight}.' % part['name'])
            for material in chosen:
                if not isinstance(material, dict) or material.get('id') not in known:
                    raise ValueError('Part %s: a material that was not sent with the call.' % part['name'])
                numeric(material.get('weight', 1), 'material weight', 0.01, 1)
            tile = part['tile_px']
            if not isinstance(tile, dict) or 'near' not in tile:
                raise ValueError('Part %s: tile_px is {near, far} in canvas px.' % part['name'])
            near = numeric(tile['near'], 'tile near', *TILE)
            numeric(tile.get('far', near), 'tile far', TILE[0], near)
            numeric(part.get('direction_deg', 0), 'direction_deg', -360, 360)
            vanishing = part.get('vanishing')
            if vanishing is not None and (not isinstance(vanishing, list) or len(vanishing) != 2):
                raise ValueError('Part %s: vanishing is [x, y] or null.' % part['name'])
            for value in vanishing or []:
                numeric(value, 'vanishing', -1000000, 1000000)
            numeric(part['strength'], 'strength', *STRENGTH)
            if part.get('blend', 'soft_light') not in BLENDS:
                raise ValueError('Part %s: blend is soft_light or overlay.' % part['name'])
            if 'seed' in part and (not isinstance(part['seed'], int) or not 0 <= part['seed'] < 2 ** 31):
                raise ValueError('Part %s: seed is a whole number.' % part['name'])
            rect, mask = shape_mask.read_shape(part['inside_shape'], session.get('output'), doc.width(), doc.height())
            checked.append((part, rect, mask))
        return checked

    def _texture_validate(self, doc, session, params):
        fields(params, TEXTURE_FIELDS, ('name', 'materials', 'parts'))
        text(params['name'], 'name', 120)
        self._craft_check_rgba(doc, 'A texture pass')
        known = self._texture_maps(params)
        self._texture_parts(doc, session, params, known)
        self._craft_validate_create(doc, session, self._texture_layer_params(params))

    def _texture_layer_params(self, params):
        layer = {key: params[key] for key in ('name', 'stage_id', 'panel') if key in params}
        layer['type'] = 'paint'
        return layer

    def _texture_apply(self, doc, session, params, result=None):
        from . import texture_raster
        from . import canvas_projection
        from .qt_compat import QCoreApplication
        maps = self._texture_maps(params)
        parts = self._texture_parts(doc, session, params, maps)
        levels = {}
        for identifier, (grey, detail_from) in maps.items():
            levels[identifier] = texture_raster.pyramid(texture_raster.detail_tile(grey, detail_from))
        created = self._craft_create(doc, session, self._texture_layer_params(params))
        layer = self._creative_node(doc, created['layer_id'])
        doc.waitForDone()
        report, written = [], 0
        for index, (part, rect, mask) in enumerate(parts):
            started = time.monotonic()
            x, y, w, h = rect
            base = np.frombuffer(bytes(doc.rootNode().projectionPixelData(x, y, w, h)), np.uint8).reshape(h, w, 4)
            area = np.frombuffer(mask, np.uint8).reshape(h, w)
            tile = part['tile_px']
            spec = dict(materials=[(levels[m['id']], float(m.get('weight', 1))) for m in part['materials']],
                        tile_near=float(tile['near']), tile_far=float(tile.get('far', tile['near'])),
                        direction_deg=float(part.get('direction_deg', 0)), vanishing=part.get('vanishing'),
                        strength=float(part['strength']), blend=part.get('blend', 'soft_light'), seed=int(part.get('seed', index + 1)))
            pixels = texture_raster.texture_part(base, area, rect, spec, progress=QCoreApplication.processEvents)
            squares = 0
            for sy in range(0, h, WRITE):
                for sx in range(0, w, WRITE):
                    square = pixels[sy:sy + WRITE, sx:sx + WRITE]
                    if not square[..., 3].any():
                        continue
                    sh, sw = square.shape[:2]
                    if index:                                # an earlier part may hold this square: this one over it
                        below = np.frombuffer(bytes(layer.pixelData(x + sx, y + sy, sw, sh)), np.uint8).reshape(sh, sw, 4)
                        if below[..., 3].any():
                            square = self._texture_over(below, square)
                    if layer.setPixelData(np.ascontiguousarray(square).tobytes(), x + sx, y + sy, sw, sh) is False:
                        raise RuntimeError('Krita rejected the texture pixels.')
                    squares += 1
            written += squares
            QCoreApplication.processEvents()
            report.append({'name': part['name'], 'bounds': list(rect), 'squares': squares, 'ms': int((time.monotonic() - started) * 1000),
                           'materials': [m['id'] for m in part['materials']]})
        x0, y0 = min(r[0] for _p, r, _m in parts), min(r[1] for _p, r, _m in parts)
        x1, y1 = max(r[0] + r[2] for _p, r, _m in parts), max(r[1] + r[3] for _p, r, _m in parts)
        canvas_projection.pixels_written(doc, (x0, y0, x1 - x0, y1 - y0))
        created.update(layer_type='texture', written_squares=written, texture={'parts': report})
        try:                                                # the same materials as brush patterns (goal 6); never fails the pass
            from krita import Krita
            from . import texture_patterns
            created['patterns'] = texture_patterns.register(Krita.instance(), maps)
        except Exception as error:
            created['patterns_error'] = str(error)
        return created

    def _texture_register(self, params):
        """register_patterns: {materials} as Krita patterns "Texture: <id>" (goal 6), or why not."""
        from krita import Krita
        from . import texture_patterns
        fields(params, ('materials',), ('materials',))
        app = Krita.instance()
        if not hasattr(app, 'createPattern'):
            return {'status': 'unavailable', 'patterns': {}, 'error': 'Patterns need our Krita (Krita.createPattern).'}
        return {'status': 'ok', 'patterns': texture_patterns.register(app, self._texture_maps(params))}

    @staticmethod
    def _texture_over(below, above):
        """`above` over `below`, both BGRA uint8 with straight alpha."""
        a = above[..., 3:4].astype(np.float32) / 255
        b = below[..., 3:4].astype(np.float32) / 255
        alpha = a + b * (1 - a)
        colour = (above[..., :3] * a + below[..., :3] * b * (1 - a)) / np.maximum(alpha, 1e-6)
        out = np.empty(above.shape, np.uint8)
        out[..., :3] = np.clip(np.round(colour), 0, 255)
        out[..., 3:4] = np.clip(np.round(alpha * 255), 0, 255)
        return out

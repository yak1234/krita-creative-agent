# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""snow: paint_snow's plugin operation (openspec snow; the artist approved "a real snow method", 2026-10-25).

One call paints one kind of snow into ONE new paint layer in the move's group, named by the companion:
  mode falling   "Snow: falling": thousands of soft flakes in 2-3 depth layers over the whole picture (snow_raster.falling),
                 slanted by wind_deg, density times the default count, nothing inside the keep_clear shapes (faces) and a
                 feathered fall-off around them;
  mode settled   "Snow: settled on <parts>": a cap of snow on the upward edges of each found area in settle_on (the masks
                 Find it wrote in the chat folder's .shapes; shape_mask.read_shape), thickness times the default.
The painting is read once as shown, before anything is written (the new layer is still empty), for the scene's light and
local colour. The layer is written only in the WRITE squares that hold snow, at normal blend, so the move's Met can merge
its group whole. It is one pass of the move (the creative operation journal, creative_tools.py): the move's Undo (the
step's Redo) removes it, protected areas are kept as for any pass, and a call that is wrong in any way is refused before
anything changes.
"""
import time

import numpy as np

from .creative_validation import fields, numeric, text

SNOW_FIELDS = ('name', 'mode', 'stage_id', 'panel', 'expected_revision', 'density', 'wind_deg', 'layers', 'seed',
               'keep_clear', 'settle_on', 'thickness')
PART_FIELDS = ('name', 'inside_shape')
MODES = ('falling', 'settled')
DENSITY = (0.2, 3.0)
WIND = (-60, 60)
THICKNESS = (0.3, 2.0)
MOST_PARTS = 8
MOST_CLEAR = 16
WRITE = 256


class SnowCraft:
    def _snow_check(self, doc, session, params):
        """(mode, keep_clear [(rect, bytes)], parts [(name, rect, bytes)]), every value checked and every shape read."""
        from . import shape_mask
        fields(params, SNOW_FIELDS, ('name', 'mode'))
        text(params['name'], 'name', 120)
        mode = params['mode']
        if mode not in MODES:
            raise ValueError('mode is falling or settled.')
        numeric(params.get('density', 1.0), 'density', *DENSITY)
        numeric(params.get('wind_deg', 0), 'wind_deg', *WIND)
        if params.get('layers', 3) not in (2, 3):
            raise ValueError('layers is 2 or 3 depth layers.')
        if 'seed' in params and (not isinstance(params['seed'], int) or isinstance(params['seed'], bool) or not 0 <= params['seed'] < 2 ** 31):
            raise ValueError('seed is a whole number.')
        numeric(params.get('thickness', 1.0), 'thickness', *THICKNESS)
        width, height, folder = doc.width(), doc.height(), session.get('output')
        clear = params.get('keep_clear', [])
        if not isinstance(clear, list) or len(clear) > MOST_CLEAR:
            raise ValueError('keep_clear is a list of at most %d shapes {mask_path, bounds}.' % MOST_CLEAR)
        kept = [shape_mask.read_shape(shape, folder, width, height) for shape in clear]
        parts = params.get('settle_on')
        if mode == 'falling':
            if parts:
                raise ValueError('settle_on is for mode settled: falling snow covers the whole picture.')
            if 'thickness' in params:
                raise ValueError('thickness is for mode settled.')
            return mode, kept, []
        if not isinstance(parts, list) or not 1 <= len(parts) <= MOST_PARTS:
            raise ValueError('settle_on is a list of 1-%d parts {name, inside_shape} for settled snow.' % MOST_PARTS)
        read = []
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError('A settle_on part is {name, inside_shape}.')
            fields(part, PART_FIELDS, PART_FIELDS)
            text(part['name'], 'part name', 120)
            rect, plane = shape_mask.read_shape(part['inside_shape'], folder, width, height)
            read.append((part['name'], rect, plane))
        return mode, kept, read

    def _snow_layer_params(self, params):
        layer = {key: params[key] for key in ('name', 'stage_id', 'panel') if key in params}
        layer['type'] = 'paint'
        return layer

    def _snow_validate(self, doc, session, params):
        self._snow_check(doc, session, params)
        self._craft_check_rgba(doc, 'Snow')
        self._craft_validate_create(doc, session, self._snow_layer_params(params))

    def _snow_write(self, layer, pixels, at, merge=False):
        """`pixels` (BGRA uint8) into the layer at `at` [x, y, w, h], only in the squares that hold snow; over what the layer
        already holds there when `merge`. Returns the squares written."""
        from .qt_compat import QCoreApplication
        from .texture_craft import TextureCraft
        x, y, w, h = at
        squares = 0
        for sy in range(0, h, WRITE):
            for sx in range(0, w, WRITE):
                square = pixels[sy:sy + WRITE, sx:sx + WRITE]
                if not square[..., 3].any():
                    continue
                sh, sw = square.shape[:2]
                if merge:
                    below = np.frombuffer(bytes(layer.pixelData(x + sx, y + sy, sw, sh)), np.uint8).reshape(sh, sw, 4)
                    if below[..., 3].any():
                        square = TextureCraft._texture_over(below, square)
                if layer.setPixelData(np.ascontiguousarray(square).tobytes(), x + sx, y + sy, sw, sh) is False:
                    raise RuntimeError('Krita rejected the snow pixels.')
                squares += 1
            QCoreApplication.processEvents()
        return squares

    def _snow_apply(self, doc, session, params, result=None):
        from . import canvas_projection, snow_raster
        started = time.monotonic()
        mode, clear, parts = self._snow_check(doc, session, params)
        created = self._craft_create(doc, session, self._snow_layer_params(params))
        layer = self._creative_node(doc, created['layer_id'])
        doc.waitForDone()
        width, height = doc.width(), doc.height()
        # The painting as shown, once, before any snow is written (the new layer is still empty).
        canvas = np.frombuffer(bytes(doc.rootNode().projectionPixelData(0, 0, width, height)), np.uint8).reshape(height, width, 4)
        seed = int(params.get('seed', 1))
        if mode == 'falling':
            pixels, report = snow_raster.falling(canvas, float(params.get('density', 1.0)), float(params.get('wind_deg', 0)),
                                                 int(params.get('layers', 3)), clear, seed)
            squares = self._snow_write(layer, pixels, [0, 0, width, height])
            bounds = [0, 0, width, height]
        else:
            light = snow_raster.scene_light(canvas)
            fall = snow_raster.feather(width, height)
            report, squares, boxes = {'parts': [], 'light': [int(round(v)) for v in light[0]]}, 0, []
            for index, (name, rect, plane) in enumerate(parts):
                pixels, at, part = snow_raster.settled(canvas, rect, plane, seed=seed + index, amount=float(params.get('thickness', 1.0)), light=light)
                if clear:
                    weight = snow_raster.clear_weight(at, clear, width, height, fall)
                    pixels[..., 3] = np.round(pixels[..., 3] * weight).astype(np.uint8)
                squares += self._snow_write(layer, pixels, at, merge=index > 0)
                boxes.append(at)
                report['parts'].append(dict(part, name=name, bounds=list(rect)))
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            bounds = [x0, y0, max(b[0] + b[2] for b in boxes) - x0, max(b[1] + b[3] for b in boxes) - y0]
            if clear:
                report['feather_px'] = fall
        canvas_projection.pixels_written(doc, tuple(bounds))
        report.update(mode=mode, kept_clear_shapes=len(clear), ms=int((time.monotonic() - started) * 1000))
        created.update(layer_type='snow', written_squares=squares, snow=report)
        return created

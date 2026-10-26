# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""effect and effect_preview (openspec custom-effects): the plugin side of an effect recipe. The recipe is YAML the
companion resolves to numbers; this takes the resolved blocks (effect_blocks.py documents each block's parameters) and
paints them.

  effect          {name, blocks, keep_clear: [{mask_path, bounds}], parts: {part name: {mask_path, bounds}}, seed?}
                  One new paint layer "Effect: <name>" in the move's group, one pass of the creative operation journal
                  (the move's Undo removes it), nothing inside the keep_clear shapes. Result {report}.
  effect_preview  {image_path, blocks, keep_clear, parts, out_path, canvas: [w, h]}
                  Reads image_path (a PNG of the canvas view, long side at most 4096) with OpenCV, renders the effect
                  over it and writes out_path (PNG). The part and keep-clear shapes are in canvas pixels and are scaled to the image from
                  `canvas`. It touches no document and needs none: cmd_creative runs it as soon as the session is known,
                  before the active document is looked up. Both paths must be inside the session's output folder.

The `texture` block's image arrives as `image_path` (a PNG inside the output folder, long side at most 4096) in the
block's params; it is loaded here (OpenCV, BGR or BGRA) and handed to effect_blocks as its `image`. Anything wrong is refused before anything changes.
"""
import os
import time

import numpy as np

from .creative_validation import fields, numeric, text
from .effect_blocks import BLENDS, BLOCKS, SIDES

EFFECT_FIELDS = ('name', 'blocks', 'keep_clear', 'parts', 'seed', 'stage_id', 'panel', 'expected_revision')
PREVIEW_FIELDS = ('image_path', 'blocks', 'keep_clear', 'parts', 'out_path', 'canvas', 'seed')
MOST_BLOCKS = 50            # sanity only: the engine clamps to its own cap of 8 and says so
MOST_PARTS = 16
MOST_CLEAR = 16
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_SIDE = 4096       # a picture's long side, read from its PNG header before anything is decoded
HUGE = 1e12                 # numbers are clamped by the engine, not refused: a recipe asking for too much is told so
COMMON = {'block': 'name', 'opacity': 'num', 'within': 'part'}
BLOCK_KEYS = {
    'particles': {'layers': 'num', 'density': 'num', 'count': 'num', 'wind_deg': 'num', 'streak': 'num', 'colour': ('light', 'local')},
    'wash': {'from': SIDES, 'falloff': 'num', 'lower_contrast': 'num'},
    'noise': {'scale': ('small', 'medium', 'large'), 'band': 'band'},
    'rays': {'from_point': 'point', 'from': SIDES, 'count': 'num', 'spread_deg': 'num'},
    'texture': {'image_path': 'path', 'area': 'part', 'blend': BLENDS},
    'caps': {'part': 'part', 'thickness': 'num'},
}


class EffectCraft:
    @staticmethod
    def _effect_inside(session, path, label):
        """The real path of `path`, which must be a plain absolute path inside the session's output folder."""
        folder = session.get('output')
        if not folder or not isinstance(path, str) or not os.path.isabs(path) or '..' in path.split(os.sep):
            raise ValueError('%s must be a file in the chat folder.' % label)
        root = os.path.realpath(folder)
        real = os.path.realpath(path)
        if os.path.commonpath([root, real]) != root or real == root:
            raise ValueError('%s must be a file in the chat folder.' % label)
        return real

    def _effect_blocks_check(self, session, blocks):
        """The blocks list, every key and value checked; returns copies with texture images still as paths."""
        if not isinstance(blocks, list) or not 1 <= len(blocks) <= MOST_BLOCKS:
            raise ValueError('blocks is a list of 1-%d blocks.' % MOST_BLOCKS)
        out = []
        for index, spec in enumerate(blocks):
            label = 'block %d' % (index + 1)
            if not isinstance(spec, dict) or spec.get('block') not in BLOCKS:
                raise ValueError('%s: block is one of %s.' % (label, ', '.join(sorted(BLOCKS))))
            kind = spec['block']
            allowed = dict(COMMON, **BLOCK_KEYS[kind])
            unknown = set(spec) - set(allowed)
            if unknown:
                raise ValueError('%s (%s): unknown parameters: %s.' % (label, kind, ', '.join(sorted(unknown))))
            for key, value in spec.items():
                rule = allowed[key]
                where = '%s %s' % (label, key)
                if rule == 'name':
                    continue
                if rule == 'num':
                    numeric(value, where, -HUGE, HUGE)
                elif rule == 'part':
                    text(value, where, 120)
                elif rule == 'point':
                    if not isinstance(value, list) or len(value) != 2:
                        raise ValueError('%s is [x, y].' % where)
                    for v in value:
                        numeric(v, where, -HUGE, HUGE)
                elif rule == 'band':
                    if not isinstance(value, dict) or set(value) != {'from', 'share'}:
                        raise ValueError('%s is {"from": top|bottom|left|right, "share": 0-1}.' % where)
                    if value['from'] not in SIDES:
                        raise ValueError('%s from is one of %s.' % (where, ', '.join(SIDES)))
                    numeric(value['share'], where + ' share', 0, 1)
                elif rule == 'path':
                    self._effect_inside(session, value, where)
                elif value not in rule:
                    raise ValueError('%s is one of %s.' % (where, ', '.join(rule)))
            if kind == 'texture' and ('image_path' not in spec or 'area' not in spec):
                raise ValueError('%s: texture needs image_path and area.' % label)
            if kind == 'caps' and 'part' not in spec:
                raise ValueError('%s: caps needs part.' % label)
            out.append(dict(spec))
        return out

    @staticmethod
    def _effect_png_size(path, what):
        """(width, height) from a PNG's IHDR header, refusing anything else or a long side over MAX_IMAGE_SIDE, so a
        small file declaring a huge picture is never decoded."""
        import struct
        with open(path, 'rb') as handle:
            head = handle.read(24)
        if len(head) < 24 or head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
            raise ValueError('%s is not a PNG image.' % what)
        width, height = struct.unpack('>II', head[16:24])
        if not width or not height or max(width, height) > MAX_IMAGE_SIDE:
            raise ValueError('%s is %d x %d pixels; its long side must be at most %d.' % (what, width, height, MAX_IMAGE_SIDE))
        return width, height

    @staticmethod
    def _effect_load_images(session, blocks):
        """Each texture block's image_path read into the BGR/BGRA uint8 array effect_blocks expects, as `image`."""
        import cv2
        for spec in blocks:
            path = spec.pop('image_path', None)
            if path is None:
                continue
            real = EffectCraft._effect_inside(session, path, 'texture image_path')
            if not os.path.isfile(real) or os.path.getsize(real) > MAX_IMAGE_BYTES:
                raise ValueError('The texture image is missing or too large.')
            EffectCraft._effect_png_size(real, 'The texture image')
            image = cv2.imread(real, cv2.IMREAD_UNCHANGED)
            if image is None or image.dtype != np.uint8:
                raise ValueError('The texture image is not an 8-bit image.')
            if image.ndim == 2:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            spec['image'] = image

    def _effect_shapes(self, session, params, width, height):
        """(parts {name: (rect, plane)}, keep_clear [(rect, plane)]) with every shape read."""
        from . import shape_mask
        folder = session.get('output')
        clear = params.get('keep_clear', [])
        if not isinstance(clear, list) or len(clear) > MOST_CLEAR:
            raise ValueError('keep_clear is a list of at most %d shapes {mask_path, bounds}.' % MOST_CLEAR)
        kept = [shape_mask.read_shape(shape, folder, width, height) for shape in clear]
        parts = params.get('parts', {})
        if not isinstance(parts, dict) or len(parts) > MOST_PARTS:
            raise ValueError('parts is {name: {mask_path, bounds}} with at most %d parts.' % MOST_PARTS)
        read = {}
        for name, shape in parts.items():
            text(name, 'part name', 120)
            read[name] = shape_mask.read_shape(shape, folder, width, height)
        return read, kept

    @staticmethod
    def _effect_seed(params):
        seed = params.get('seed', 1)
        if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed < 2 ** 31:
            raise ValueError('seed is a whole number.')
        return seed

    def _effect_check(self, doc, session, params):
        """(blocks, parts, keep_clear, seed), every value checked and every shape and image read."""
        fields(params, EFFECT_FIELDS, ('name', 'blocks'))
        text(params['name'], 'name', 100)
        blocks = self._effect_blocks_check(session, params['blocks'])
        seed = self._effect_seed(params)
        parts, kept = self._effect_shapes(session, params, doc.width(), doc.height())
        self._effect_load_images(session, blocks)
        return blocks, parts, kept, seed

    def _effect_layer_params(self, params):
        layer = {key: params[key] for key in ('stage_id', 'panel') if key in params}
        name = params['name'].strip()
        layer['name'] = name if name.startswith('Effect: ') else 'Effect: ' + name
        layer['type'] = 'paint'
        return layer

    def _effect_validate(self, doc, session, params):
        self._effect_check(doc, session, params)
        self._craft_check_rgba(doc, 'Effect')
        self._craft_validate_create(doc, session, self._effect_layer_params(params))

    def _effect_apply(self, doc, session, params, result=None):
        from . import canvas_projection, effect_blocks
        from .snow_craft import SnowCraft
        started = time.monotonic()
        blocks, parts, clear, seed = self._effect_check(doc, session, params)
        created = self._craft_create(doc, session, self._effect_layer_params(params))
        layer = self._creative_node(doc, created['layer_id'])
        doc.waitForDone()
        width, height = doc.width(), doc.height()
        # The painting as shown, once, before anything is written (the new layer is still empty).
        canvas = np.frombuffer(bytes(doc.rootNode().projectionPixelData(0, 0, width, height)), np.uint8).reshape(height, width, 4)
        pixels, report = effect_blocks.render(canvas, blocks, parts, clear, seed)
        squares = SnowCraft._snow_write(self, layer, pixels, [0, 0, width, height])
        canvas_projection.pixels_written(doc, (0, 0, width, height))
        report.update(kept_clear_shapes=len(clear), total_ms=int((time.monotonic() - started) * 1000))
        created.update(layer_type='effect', written_squares=squares, report=report)
        return created

    @staticmethod
    def _effect_scaled(shape, sx, sy, width, height):
        """A canvas-pixel shape ((x, y, w, h), plane) scaled to an image width x height."""
        import cv2
        (x, y, w, h), plane = shape
        x0, y0 = int(round(x * sx)), int(round(y * sy))
        x1, y1 = max(x0 + 1, int(round((x + w) * sx))), max(y0 + 1, int(round((y + h) * sy)))
        mask = np.frombuffer(plane, np.uint8).reshape(h, w)
        mask = cv2.resize(mask, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA if x1 - x0 < w else cv2.INTER_LINEAR)
        return (x0, y0, x1 - x0, y1 - y0), mask.tobytes()

    def _effect_preview(self, session, params):
        """effect_preview: the effect over a picture of the canvas view, written to out_path. No document is touched."""
        import cv2
        from . import effect_blocks
        fields(params, PREVIEW_FIELDS, ('image_path', 'blocks', 'out_path', 'canvas'))
        source = self._effect_inside(session, params['image_path'], 'image_path')
        target = self._effect_inside(session, params['out_path'], 'out_path')
        if not target.lower().endswith('.png'):
            raise ValueError('out_path is a .png file.')
        canvas_size = params['canvas']
        if not isinstance(canvas_size, list) or len(canvas_size) != 2:
            raise ValueError('canvas is [width, height] in canvas pixels.')
        cw, ch = (int(numeric(v, 'canvas', 1, 100000)) for v in canvas_size)
        blocks = self._effect_blocks_check(session, params['blocks'])
        seed = self._effect_seed(params)
        parts, kept = self._effect_shapes(session, params, cw, ch)
        if not os.path.isfile(source) or os.path.getsize(source) > MAX_IMAGE_BYTES:
            raise ValueError('image_path is missing or too large.')
        self._effect_png_size(source, 'image_path')
        image = cv2.imread(source, cv2.IMREAD_UNCHANGED)
        if image is None or image.dtype != np.uint8 or image.ndim not in (2, 3):
            raise ValueError('image_path is not an 8-bit image.')
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[2] == 3:
            image = np.dstack([image, np.full(image.shape[:2], 255, np.uint8)])
        height, width = image.shape[:2]
        self._effect_load_images(session, blocks)
        sx, sy = width / cw, height / ch
        parts = {name: self._effect_scaled(shape, sx, sy, width, height) for name, shape in parts.items()}
        kept = [self._effect_scaled(shape, sx, sy, width, height) for shape in kept]
        layer, report = effect_blocks.render(image, blocks, parts, kept, seed)
        alpha = layer[..., 3:4].astype(np.float32) / 255
        out = image.copy()
        out[..., :3] = np.clip(np.round(layer[..., :3] * alpha + image[..., :3] * (1 - alpha)), 0, 255).astype(np.uint8)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if not cv2.imwrite(target, out):
            raise RuntimeError('The preview could not be written.')
        return {'status': 'ok', 'report': report, 'out_path': target, 'size': [width, height]}

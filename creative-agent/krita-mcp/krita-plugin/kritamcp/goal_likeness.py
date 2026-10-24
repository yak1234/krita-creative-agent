# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The goal-likeness check's grid (crisp-accents goal 8): a small, blurred CIE Lab copy of an image crop.

The companion (src/goal-likeness.ts) asks for the goal reference's crop that a whole-picture transfer maps onto the
canvas, and for the same canvas area in each view before and after a painting batch, all at one grid size (about 64
cells on the long side). A cell is an average of many pixels, then a one-cell Gaussian blur: transfer dabs and brush
texture average out, while a passage that changed colour or value does not. Lab, so the companion's distance (CIE76
delta E) is perceptual. Only numbers go back; nothing here touches a document.
"""
import base64
import math
import time
from .creative_validation import fields

BLUR_CELLS = 1.0          # Gaussian sigma, in cells: texture inside a cell or two does not count
PIXELS_PER_CELL = 4       # decoded at least this many pixels a cell (reduced while read), then area-averaged
GRID_LIMIT = (4, 256)     # cells a side


def _ints(value, name, count, low, high):
    if (not isinstance(value, list) or len(value) != count
            or any(isinstance(v, bool) or not isinstance(v, int) or not low <= v <= high for v in value)):
        raise ValueError('%s must be %d whole numbers %d-%d' % (name, count, low, high))
    return value


def lab_grid(rgba, grid):
    """An RGBA crop (numpy H x W x 4, uint8) as a grid ([w, h]) of blurred CIE Lab cells (float32 h x w x 3).
    Transparent pixels count as white paper."""
    import cv2
    import numpy as np
    rgb = rgba[..., :3].astype(np.float32) / 255
    alpha = rgba[..., 3:4].astype(np.float32) / 255
    rgb = rgb * alpha + (1 - alpha)
    small = cv2.resize(rgb, (grid[0], grid[1]), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), BLUR_CELLS)
    return cv2.cvtColor(np.ascontiguousarray(small), cv2.COLOR_RGB2Lab)


def likeness_grid(params):
    """The Lab grid of `source` ([x, y, w, h], default the whole image) in the pixels the companion lists the image at
    (`size` [w, h]; the file's own size when not given), `grid` [w, h] cells. The bytes are checked against their hash,
    and the image is decoded reduced while read (PIXELS_PER_CELL a cell is enough). Returns the grid as little-endian
    float32 L, a, b per cell, row by row, and the time it took."""
    fields(params, ('image_base64', 'sha256', 'source', 'size', 'grid'), ('image_base64', 'sha256', 'grid'))
    started = time.monotonic()
    grid = _ints(params['grid'], 'grid', 2, *GRID_LIMIT)
    size = params.get('size')
    if size is not None:
        size = _ints(size, 'size', 2, 1, 100000)
    source = params.get('source')
    if source is not None:
        source = _ints(source, 'source', 4, 0, 100000)
        if size is not None and not (source[2] > 0 and source[3] > 0 and source[0] + source[2] <= size[0] and source[1] + source[3] <= size[1]):
            raise ValueError('The source crop must fit the image.')
    side = None
    if size is not None:
        crop = source or [0, 0, size[0], size[1]]
        side = max(16, math.ceil(PIXELS_PER_CELL * max(grid[0] / crop[2], grid[1] / crop[3]) * max(size)))
    from .creative_reference import _trace_decode
    image, original_width, original_height = _trace_decode(params, side)
    width, height = size if size is not None else (original_width, original_height)
    x, y, w, h = source or [0, 0, width, height]
    if not (w > 0 and h > 0 and x + w <= width and y + h <= height):
        raise ValueError('The source crop must fit the image.')
    import numpy as np
    dw, dh = image.width(), image.height()
    rows = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), np.uint8).reshape(dh, image.bytesPerLine())
    rgba = rows[:, : dw * 4].reshape(dh, dw, 4)
    kx, ky = dw / width, dh / height
    left, top = min(dw - 1, int(x * kx)), min(dh - 1, int(y * ky))
    right, bottom = max(left + 1, min(dw, math.ceil((x + w) * kx))), max(top + 1, min(dh, math.ceil((y + h) * ky)))
    lab = lab_grid(rgba[top:bottom, left:right], grid)
    return {'status': 'ok', 'grid': grid, 'ms': int((time.monotonic() - started) * 1000),
            'lab_base64': base64.b64encode(lab.astype('<f4').tobytes()).decode('ascii')}


CROP_OUT = (16, 4096)     # output pixels a side
CROP_JPEG_QUALITY = 92


def comparison_crop(params):
    """Luna's goal comparison (luna-goal-reviewer goal 1): `source` ([x, y, w, h]) of an image, in the pixels the companion
    lists it at (`size` [w, h]), resampled to `out` [w, h] and flattened onto white, as a JPEG; or several at once,
    `crops` [{source, out}], returned as `images` (the goal decoded once a comparison: review, 2026-10-24). The goal's crop
    and the canvas views' crops of one area are asked at one output size, so Luna sees them at the same scale. The views
    are JPEGs the companion does not decode; the bytes are checked against their hash and decoded reduced while read
    (never more than the outputs need). Nothing here touches a document."""
    fields(params, ('image_base64', 'sha256', 'source', 'size', 'out', 'crops'), ('image_base64', 'sha256', 'size'))
    started = time.monotonic()
    size = _ints(params['size'], 'size', 2, 1, 100000)
    many = 'crops' in params
    if many:
        if not isinstance(params['crops'], list) or not 1 <= len(params['crops']) <= 8 or 'source' in params or 'out' in params:
            raise ValueError('crops must be 1-8 {source, out}, without a source or out of their own')
        asked = params['crops']
        for crop in asked:
            if not isinstance(crop, dict) or set(crop) != {'source', 'out'}:
                raise ValueError('each crop is {source, out}')
    else:
        if 'source' not in params or 'out' not in params:
            raise ValueError('source and out are required')
        asked = [{'source': params['source'], 'out': params['out']}]
    wanted = []
    for crop in asked:
        x, y, w, h = _ints(crop['source'], 'source', 4, 0, 100000)
        out = _ints(crop['out'], 'out', 2, *CROP_OUT)
        if not (w > 0 and h > 0 and x + w <= size[0] and y + h <= size[1]):
            raise ValueError('The source crop must fit the image.')
        wanted.append(([x, y, w, h], out))
    # Decoded at the scale the largest output needs (at least), never enlarged while read.
    side = max(16, max(math.ceil(max(out[0] / s[2], out[1] / s[3]) * max(size)) for s, out in wanted))
    from .creative_reference import _trace_decode
    image, _width, _height = _trace_decode(params, side)
    from .qt_compat import QBuffer, QIODevice, QImage, QPainter, QRect, QSize, Qt
    dw, dh = image.width(), image.height()
    kx, ky = dw / size[0], dh / size[1]
    images = []
    for (x, y, w, h), out in wanted:
        left, top = min(dw - 1, int(x * kx)), min(dh - 1, int(y * ky))
        right, bottom = max(left + 1, min(dw, math.ceil((x + w) * kx))), max(top + 1, min(dh, math.ceil((y + h) * ky)))
        crop = image.copy(QRect(left, top, right - left, bottom - top)).scaled(
            QSize(out[0], out[1]), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        flat = QImage(crop.size(), QImage.Format.Format_RGB32); flat.fill(Qt.GlobalColor.white)
        painter = QPainter(flat); painter.drawImage(0, 0, crop); painter.end()
        buffer = QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not flat.save(buffer, 'JPEG', CROP_JPEG_QUALITY):
            raise ValueError('Could not encode the crop.')
        images.append({'mime_type': 'image/jpeg', 'width': flat.width(), 'height': flat.height(),
                       'image_base64': base64.b64encode(bytes(buffer.data())).decode('ascii')})
    ms = int((time.monotonic() - started) * 1000)
    if many:
        return {'status': 'ok', 'images': images, 'ms': ms}
    return dict(images[0], status='ok', ms=ms)

# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The mass map's smoothed copy of a reference crop (draw_guide from_reference masses).

The companion traces the big masses of a reference (sky, each building mass, a head, a car) with VTracer and draws their
boundaries as guide lines. Traced from the raw image the masses are blotchy (every texture speck is a region), so here
the crop is decoded at most MASS_SIDE pixels on its long side and smoothed: a few bilateral passes drop texture while
keeping edges, then mean shift flattens each mass to about one colour with a sharp boundary. Only the companion sees
these pixels; they never reach the canvas. Nothing here touches a document.
"""
import base64
import time
from .creative_validation import fields

MASS_SIDE = 720              # long side of the smoothed copy: masses, not detail
BILATERAL = (3, 9, 40, 7)    # passes, diameter, colour sigma, space sigma (at MASS_SIDE)
MEAN_SHIFT = (10, 20)        # spatial and colour window of the mean shift (24 merged a face into its hair)


def smooth(rgba):
    """The masses of an RGBA image (numpy H x W x 4, uint8): texture smoothed away, boundaries kept. Alpha unchanged."""
    import cv2
    import numpy as np
    rgb = np.ascontiguousarray(rgba[..., :3])
    passes, diameter, colour, space = BILATERAL
    for _ in range(passes):
        rgb = cv2.bilateralFilter(rgb, diameter, colour, space)
    rgb = cv2.pyrMeanShiftFiltering(rgb, *MEAN_SHIFT)
    out = rgba.copy()
    out[..., :3] = rgb
    return out


def _source(given, width, height):
    if given is None:
        return [0, 0, width, height]
    if (not isinstance(given, list) or len(given) != 4
            or any(isinstance(v, bool) or not isinstance(v, int) for v in given)):
        raise ValueError('source must be [x, y, w, h] in whole reference pixels.')
    x, y, w, h = given
    if not (w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= width and y + h <= height):
        raise ValueError('The source crop must fit the reference.')
    return [x, y, w, h]


def mass_reference(params):
    """A smoothed copy of `source` ([x, y, w, h], default all of it) at most max_side (default MASS_SIDE) pixels on its
    long side, never enlarged, as RGBA. The reference is decoded as guided trace decodes it (creative_reference.py
    _trace_decode: hash checked, at most TRACE_PIXELS); `source` is in the pixels the companion lists it at (`size`
    [w, h], the file's own size when not given), as for trace_edges. Returns its size, the source, the original size
    and the time it took. The source returned is the crop actually decoded, in listed pixels (whole decoded pixels, so
    it can differ from the one asked for by a fraction of a pixel)."""
    fields(params, ('image_base64', 'sha256', 'source', 'max_side', 'size'), ('image_base64', 'sha256'))
    side = params.get('max_side', MASS_SIDE)
    if isinstance(side, bool) or not isinstance(side, int) or not 64 <= side <= 2 * MASS_SIDE:
        raise ValueError('max_side must be 64-%d pixels' % (2 * MASS_SIDE))
    size = params.get('size')
    if size is not None and (not isinstance(size, list) or len(size) != 2
                             or any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 100000 for v in size)):
        raise ValueError('size is [w, h] in whole pixels.')
    started = time.monotonic()
    from .creative_reference import _trace_decode
    image, original_width, original_height = _trace_decode(params)
    width, height = size if size is not None else (original_width, original_height)
    x, y, w, h = source = _source(params.get('source'), width, height)
    import cv2
    import numpy as np
    dw, dh = image.width(), image.height()
    rows = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), np.uint8).reshape(dh, image.bytesPerLine())
    rgba = rows[:, : dw * 4].reshape(dh, dw, 4)
    kx, ky = dw / width, dh / height
    left, top = min(dw - 1, int(x * kx)), min(dh - 1, int(y * ky))
    right, bottom = max(left + 1, min(dw, int(np.ceil((x + w) * kx)))), max(top + 1, min(dh, int(np.ceil((y + h) * ky))))
    crop = rgba[top:bottom, left:right]
    scale = min(1.0, side / max(crop.shape[1], crop.shape[0]))
    out_w, out_h = max(1, round(crop.shape[1] * scale)), max(1, round(crop.shape[0] * scale))
    crop = cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_AREA) if scale < 1 else np.ascontiguousarray(crop)
    masses = np.ascontiguousarray(smooth(crop))
    # The crop actually decoded (whole decoded pixels), back in listed pixels, so the companion maps the copy exactly.
    shown = [round(left / kx, 4), round(top / ky, 4), round((right - left) / kx, 4), round((bottom - top) / ky, 4)]
    return {'status': 'ok', 'width': out_w, 'height': out_h, 'source': shown, 'original_width': original_width,
            'original_height': original_height, 'sha256': params['sha256'], 'ms': int((time.monotonic() - started) * 1000),
            'rgba_base64': base64.b64encode(masses.tobytes()).decode('ascii')}

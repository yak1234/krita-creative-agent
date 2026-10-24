"""Read attached image bytes without opening or mutating a Krita document."""
import base64
import math
import hashlib
from .creative_validation import fields

# A reference may be a goal image sharpened 4x (the companion's goal-sharpen.ts: 5792 x 4344 for New Moscow): the transfer
# reads it whole, the other tools decode it reduced while read. Files up to REFERENCE_FILE_BYTES (base64 up to
# REFERENCE_ENCODED), at most REFERENCE_PIXELS, the size read from the header before anything is decoded.
REFERENCE_FILE_BYTES = 64 * 1024 * 1024
REFERENCE_ENCODED = REFERENCE_FILE_BYTES * 4 // 3 + 4
REFERENCE_PIXELS = 26_000_000


def decode_reference(params):
    fields(params, ('image_base64', 'sha256'), ('image_base64', 'sha256'))
    encoded = params['image_base64']
    if not isinstance(encoded, str) or len(encoded) > REFERENCE_ENCODED:
        raise ValueError('Reference must be at most %d MB.' % (REFERENCE_FILE_BYTES // (1024 * 1024)))
    data = base64.b64decode(encoded, validate=True)
    if len(data) > REFERENCE_FILE_BYTES:
        raise ValueError('Reference must be at most %d MB.' % (REFERENCE_FILE_BYTES // (1024 * 1024)))
    if hashlib.sha256(data).hexdigest() != params['sha256']:
        raise ValueError('Reference content changed.')
    from .qt_compat import QByteArray, QBuffer, QIODevice
    from .qt_compat import QImage, QImageReader, QColorSpace
    buffer = QBuffer(); buffer.setData(QByteArray(data)); buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > REFERENCE_PIXELS:
        raise ValueError('Use a reference with at most %d million pixels.' % (REFERENCE_PIXELS // 1_000_000))
    image = reader.read()
    if image.isNull():
        raise ValueError('Could not decode the attached reference.')
    # Keep raw pixel orientation consistent with stored attachment dimensions.
    if image.colorSpace().isValid():
        image.convertToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = image.constBits().asstring(image.sizeInBytes())
    return {'width': image.width(), 'height': image.height(), 'sha256': params['sha256'],
            'rgba_base64': base64.b64encode(raw).decode('ascii'),
            'color_space': 'sRGB; untagged input assumed sRGB', 'status': 'ok'}


TRACE_PIXELS = 4_000_000    # the decode a guide traces from never holds more
LABEL_SIDE = 8192           # the shape labels' image is at most this a side (and TRACE_PIXELS in all)


def _trace_decode(params, side=None):
    """A reference's bytes checked against their hash and decoded reduced while read: at most `side` pixels on the long
    side (when given) and TRACE_PIXELS in all, never enlarged. Returns the RGBA8888 QImage and the original size."""
    encoded = params['image_base64']
    if not isinstance(encoded, str) or len(encoded) > REFERENCE_ENCODED:
        raise ValueError('A reference to trace must be at most %d MB.' % (REFERENCE_FILE_BYTES // (1024 * 1024)))
    data = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(data).hexdigest() != params['sha256']:
        raise ValueError('Reference content changed.')
    from .qt_compat import QByteArray, QBuffer, QIODevice, QSize
    from .qt_compat import QImage, QImageReader, QColorSpace
    buffer = QBuffer(); buffer.setData(QByteArray(data)); buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if not size.isValid() or size.width() <= 0 or size.height() <= 0:
        raise ValueError('Could not decode the reference to trace.')
    width, height = size.width(), size.height()
    scale = min(1.0, (TRACE_PIXELS / (width * height)) ** 0.5, side / max(width, height) if side else 1.0)
    if scale < 1:
        reader.setScaledSize(QSize(max(1, round(width * scale)), max(1, round(height * scale))))
    image = reader.read()
    if image.isNull():
        raise ValueError('Could not decode the reference to trace.')
    if image.colorSpace().isValid():
        image.convertToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    return image.convertToFormat(QImage.Format.Format_RGBA8888), width, height


def trace_reference(params):
    """Guided trace's decode of a reference (shapes on a reference or the canvas view), reduced while it is read: at
    most max_side pixels on its long side and TRACE_PIXELS in all, never enlarged. A path of its own: decode_reference
    keeps its limits for the reference tools. Returns the decoded and the original size."""
    fields(params, ('image_base64', 'sha256', 'max_side'), ('image_base64', 'sha256', 'max_side'))
    side = params['max_side']
    if isinstance(side, bool) or not isinstance(side, int) or not 16 <= side <= 8192:
        raise ValueError('max_side must be 16-8192 pixels')
    image, width, height = _trace_decode(params, side)
    raw = image.constBits().asstring(image.sizeInBytes())
    return {'status': 'ok', 'width': image.width(), 'height': image.height(), 'original_width': width, 'original_height': height,
            'sha256': params['sha256'], 'rgba_base64': base64.b64encode(raw).decode('ascii')}


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError('%s must be %s-%s' % (name, low, high))
    return value


def trace_edges(params):
    """Lines of a reference crop at full resolution (edge_trace.py; no longer drawn as guides since crisp-accents): the reference
    decoded at most TRACE_PIXELS, `source` [x, y, w, h] and the lines in its original pixels. scale: canvas pixels a
    reference pixel (simplification and the shortest line are measured on the canvas); labels: the shapes the
    companion found, an 8-bit PNG of shape ids (0 none) at `bounds` of an image of size `space` (the shapes' own
    decode), `inside` to keep only that one shape's outline and structure. Returns the lines, how the outlines were
    found (silhouette) and the time it took."""
    import time
    fields(params, ('image_base64', 'sha256', 'source', 'scale', 'detail', 'max_lines', 'lights', 'labels', 'size'),
           ('image_base64', 'sha256', 'source', 'scale'))
    from . import edge_trace
    source = params['source']
    if not isinstance(source, list) or len(source) != 4 or any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in source):
        raise ValueError('source is [x, y, w, h] in whole reference pixels.')
    scale = _number(params['scale'], 'scale', 0.01, 100)
    detail = params.get('detail', 'simple')
    if detail not in edge_trace.DETAIL:
        raise ValueError('detail must be one of: ' + ', '.join(edge_trace.DETAIL))
    max_lines = params.get('max_lines', 8)
    if isinstance(max_lines, bool) or not isinstance(max_lines, int) or not 1 <= max_lines <= 256:
        raise ValueError('max_lines must be 1-256')
    if not isinstance(params.get('lights', False), bool):
        raise ValueError('lights must be true or false')
    started = time.monotonic()
    import numpy as np
    image, width, height = _trace_decode(params)
    image_width, image_height = width, height
    # The companion's pixels: the size it lists the reference at, which source and the lines are in (the file's own
    # size when not given).
    size = params.get('size')
    if size is not None:
        if (not isinstance(size, list) or len(size) != 2 or any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 100000 for v in size)):
            raise ValueError('size is [w, h] in whole pixels.')
        width, height = size
    x, y, w, h = source
    if not (w > 0 and h > 0 and x + w <= width and y + h <= height):
        raise ValueError('Source crop must fit the reference.')
    dw, dh = image.width(), image.height()
    rows = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), np.uint8).reshape(dh, image.bytesPerLine())
    rgba = np.ascontiguousarray(rows[:, :dw * 4].reshape(dh, dw, 4))
    kx, ky = dw / width, dh / height
    left, top = min(dw - 1, int(x * kx)), min(dh - 1, int(y * ky))
    crop = [left, top, max(1, min(dw, int(np.ceil((x + w) * kx))) - left), max(1, min(dh, int(np.ceil((y + h) * ky))) - top)]
    labels, inside = None, False
    if params.get('labels') is not None:
        labels, inside = _labels(params['labels'], dw, dh)
    out = edge_trace.trace(rgba, crop, scale=scale / kx, detail=detail, max_lines=max_lines, labels=labels, inside=inside,
                           lights=params.get('lights', False))
    clamp = lambda v, low, size: min(low + size, max(low, v))
    lines = [{'kind': line['kind'], 'points': [[round(clamp(px / kx, x, w), 2), round(clamp(py / ky, y, h), 2)] for px, py in line['points']]}
             for line in out['lines']]
    return {'status': 'ok', 'lines': lines, 'silhouette': out['silhouette'], 'width': dw, 'height': dh,
            'original_width': image_width, 'original_height': image_height, 'ms': int((time.monotonic() - started) * 1000)}


def _decoded_rgba(image):
    import numpy as np
    dw, dh = image.width(), image.height()
    rows = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), np.uint8).reshape(dh, image.bytesPerLine())
    return np.ascontiguousarray(rows[:, :dw * 4].reshape(dh, dw, 4))


def find_accents(params):
    """The accents a reference crop has and the canvas lacks (paint_accents; accent_find.py): the reference decoded at most TRACE_PIXELS,
    `source` [x, y, w, h] and the accents in its listed pixels (`size`, the file's own when not given): lights, glints,
    darks and thin lines with their place, size, colour and strength (the residual). canvas (required): the canvas view
    the painter last saw ({image_base64, sha256, target}: where source sits in that view, its pixels). Only accents go
    back, with the time it took."""
    import time
    fields(params, ('image_base64', 'sha256', 'source', 'size', 'kinds', 'strength', 'max_accents', 'canvas'),
           ('image_base64', 'sha256', 'source'))
    if params.get('canvas') is None:
        raise ValueError('Finding accents needs the canvas view: accents go only where the canvas lacks a sharp light or dark '
                         'the reference has. Look at the canvas first.')
    from . import accent_find
    source = params['source']
    if not isinstance(source, list) or len(source) != 4 or any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in source):
        raise ValueError('source is [x, y, w, h] in whole reference pixels.')
    kinds = params.get('kinds', list(accent_find.KINDS))
    if not isinstance(kinds, list) or not kinds or len(set(kinds)) != len(kinds) or any(k not in accent_find.KINDS for k in kinds):
        raise ValueError('kinds are some of: ' + ', '.join(accent_find.KINDS))
    strength = params.get('strength', 'medium')
    if strength not in accent_find.STRENGTHS:
        raise ValueError('strength is one of: ' + ', '.join(accent_find.STRENGTHS))
    max_accents = params.get('max_accents', 200)
    if isinstance(max_accents, bool) or not isinstance(max_accents, int) or not 1 <= max_accents <= 1000:
        raise ValueError('max_accents must be 1-1000')
    size = params.get('size')
    if size is not None and (not isinstance(size, list) or len(size) != 2
                             or any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 100000 for v in size)):
        raise ValueError('size is [w, h] in whole pixels.')
    canvas = params['canvas']
    if not isinstance(canvas, dict) or set(canvas) != {'image_base64', 'sha256', 'target'}:
        raise ValueError('The canvas view is {image_base64, sha256, target}.')
    target = canvas['target']
    if not isinstance(target, list) or len(target) != 4 or any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in target):
        raise ValueError('The canvas target is [x, y, w, h] in whole pixels of the canvas view.')
    started = time.monotonic()
    image, width, height = _trace_decode(params)
    image_width, image_height = width, height
    if size is not None:
        width, height = size
    x, y, w, h = source
    if not (w > 0 and h > 0 and x + w <= width and y + h <= height):
        raise ValueError('Source crop must fit the reference.')
    rgba = _decoded_rgba(image)
    dw, dh = image.width(), image.height()
    kx, ky = dw / width, dh / height
    left, top = min(dw - 1, int(x * kx)), min(dh - 1, int(y * ky))
    crop = [left, top, max(1, min(dw, int(math.ceil((x + w) * kx))) - left), max(1, min(dh, int(math.ceil((y + h) * ky))) - top)]
    decoded, view_width, view_height = _trace_decode(canvas)
    if (decoded.width(), decoded.height()) != (view_width, view_height):
        raise ValueError('The canvas view must be at most %d pixels.' % TRACE_PIXELS)
    view = _decoded_rgba(decoded)
    tx, ty, tw, th = canvas['target']
    if not (tw > 0 and th > 0 and tx + tw <= view.shape[1] and ty + th <= view.shape[0]):
        raise ValueError('The canvas target must fit the canvas view.')
    out = accent_find.find(rgba, crop, kinds=kinds, strength=strength, max_accents=max_accents, canvas=view, target=canvas['target'])
    k = (kx + ky) / 2
    clamp = lambda v, low, extent: round(min(low + extent, max(low, v)), 2)
    accents = []
    for accent in out['accents']:
        item = dict(accent, x=clamp(accent['x'] / kx, x, w), y=clamp(accent['y'] / ky, y, h), size=round(accent['size'] / k, 2))
        if 'length' in item:
            item['length'] = round(item['length'] / k, 2)
        if 'points' in item:
            item['points'] = [[clamp(px / kx, x, w), clamp(py / ky, y, h)] for px, py in item['points']]
        accents.append(item)
    return {'status': 'ok', 'accents': accents, 'found': out['found'], 'width': dw, 'height': dh,
            'original_width': image_width, 'original_height': image_height, 'ms': int((time.monotonic() - started) * 1000)}


def _labels(spec, width, height):
    """The companion's shapes as an H x W uint8 of ids aligned with the decode: the PNG at its bounds of `space`,
    scaled to the decode (nearest: ids are not blended)."""
    import numpy as np
    import cv2
    if not isinstance(spec, dict) or set(spec) - {'png_base64', 'bounds', 'space', 'inside'}:
        raise ValueError('labels are {png_base64, bounds, space, inside}.')
    bounds, space = spec.get('bounds'), spec.get('space')
    if (not isinstance(bounds, list) or len(bounds) != 4 or not isinstance(space, list) or len(space) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in bounds + space) or not (space[0] > 0 and space[1] > 0)
            or bounds[0] + bounds[2] > space[0] or bounds[1] + bounds[3] > space[1] or not (bounds[2] > 0 and bounds[3] > 0)):
        raise ValueError('The shape labels need bounds [x, y, w, h] inside space [w, h].')
    if max(space) > LABEL_SIDE or space[0] * space[1] > TRACE_PIXELS or bounds[2] * bounds[3] > TRACE_PIXELS:
        raise ValueError('The shape labels\' space is at most %d pixels a side and %d in all.' % (LABEL_SIDE, TRACE_PIXELS))
    if not isinstance(spec.get('inside', False), bool):
        raise ValueError('inside must be true or false')
    encoded = spec.get('png_base64')
    if not isinstance(encoded, str) or len(encoded) > 12 * 1024 * 1024:
        raise ValueError('The shape labels must be a PNG of at most 9 MB.')
    try:
        data = base64.b64decode(encoded, validate=True)
    except Exception:
        raise ValueError('The shape labels could not be read at their bounds.')
    # The size the PNG declares, read from its header before anything is decoded: a small file can declare a huge image.
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise ValueError('The shape labels are not a PNG.')
    declared = (int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big'))
    if declared != (bounds[2], bounds[3]):
        raise ValueError('The shape labels are %d x %d, not their bounds %d x %d.' % (declared + (bounds[2], bounds[3])))
    try:
        plane = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    except Exception:
        plane = None
    if plane is None or plane.shape != (bounds[3], bounds[2]):
        raise ValueError('The shape labels could not be read at their bounds.')
    kx, ky = width / space[0], height / space[1]
    left, top = int(round(bounds[0] * kx)), int(round(bounds[1] * ky))
    right, bottom = min(width, int(round((bounds[0] + bounds[2]) * kx))), min(height, int(round((bounds[1] + bounds[3]) * ky)))
    labels = np.zeros((height, width), np.uint8)
    if right > left and bottom > top:
        size = (right - left, bottom - top)
        if size[0] <= plane.shape[1] and size[1] <= plane.shape[0]:
            labels[top:bottom, left:right] = cv2.resize(plane, size, interpolation=cv2.INTER_NEAREST)
        else:
            # Enlarged: each shape's mask is resized smoothly and each pixel takes the shape most inside it, so outlines
            # follow the shape and not the stairs of nearest-neighbour pixels.
            best = np.zeros((size[1], size[0]), np.uint8); out = labels[top:bottom, left:right]
            for value in np.unique(plane):
                soft = cv2.resize(np.where(plane == value, 255, 0).astype(np.uint8), size, interpolation=cv2.INTER_LINEAR)
                stronger = soft > best
                best[stronger] = soft[stronger]; out[stronger] = value
    return labels, spec.get('inside', False)


SMALL_REFERENCE = 1024 * 1024    # bytes; a reference this small that fits is sent as it is


def model_image(params):
    """A reference shrunk for a model request: at most max_side pixels on its long side.

    Model APIs downscale larger images themselves (to about 1568-2048 px), so sending the
    original only adds upload and chat-log bytes. The copy is a JPEG; a file over 1 MB that
    already fits is re-encoded too. Returns scaled=False when the original should be sent.
    """
    fields(params, ('image_base64', 'sha256', 'max_side'), ('image_base64', 'sha256', 'max_side'))
    encoded, side = params['image_base64'], params['max_side']
    if not isinstance(encoded, str) or len(encoded) > REFERENCE_ENCODED:
        raise ValueError('Reference must be at most %d MB.' % (REFERENCE_FILE_BYTES // (1024 * 1024)))
    if isinstance(side, bool) or not isinstance(side, int) or not 256 <= side <= 4096:
        raise ValueError('max_side must be 256-4096 pixels')
    data = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(data).hexdigest() != params['sha256']:
        raise ValueError('Reference content changed.')
    from .qt_compat import QByteArray, QBuffer, QIODevice, QSize, Qt
    from .qt_compat import QImage, QImageReader, QPainter
    buffer = QBuffer(); buffer.setData(QByteArray(data)); buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid():
        raise ValueError('Could not read the reference image.')
    fits = max(size.width(), size.height()) <= side
    if fits and len(data) <= SMALL_REFERENCE:
        return {'status': 'ok', 'scaled': False, 'width': size.width(), 'height': size.height()}
    image = reader.read()
    if image.isNull():
        raise ValueError('Could not decode the reference image.')
    if not fits:
        image = image.scaled(QSize(side, side), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    # Models ignore transparency: flatten onto white and send JPEG (a few hundred KB).
    flat = QImage(image.size(), QImage.Format.Format_RGB32); flat.fill(Qt.GlobalColor.white)
    painter = QPainter(flat); painter.drawImage(0, 0, image); painter.end()
    out = QBuffer(); out.open(QIODevice.OpenModeFlag.WriteOnly)
    if not flat.save(out, 'JPEG', 90):
        raise ValueError('Could not encode the reduced reference.')
    return {'status': 'ok', 'scaled': True, 'width': flat.width(), 'height': flat.height(), 'mime_type': 'image/jpeg',
            'image_base64': base64.b64encode(bytes(out.data())).decode('ascii')}


def _has_transparency(image):
    if not image.hasAlphaChannel():
        return False
    from .qt_compat import QImage
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    alphas = rgba.constBits().asstring(rgba.sizeInBytes())[3::4]
    return alphas.count(255) != len(alphas)


def jpeg_copy(params):
    """A JPEG copy of an opaque image, same size (stored chat images; storage-layout phase B).

    Returns kept=True for an image with any transparent pixel: JPEG would lose it.
    """
    fields(params, ('image_base64', 'sha256', 'quality'), ('image_base64', 'sha256'))
    encoded, quality = params['image_base64'], params.get('quality', 90)
    if not isinstance(encoded, str) or len(encoded) > REFERENCE_ENCODED:
        raise ValueError('Image must be at most %d MB.' % (REFERENCE_FILE_BYTES // (1024 * 1024)))
    if isinstance(quality, bool) or not isinstance(quality, int) or not 50 <= quality <= 100:
        raise ValueError('quality must be 50-100')
    data = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(data).hexdigest() != params['sha256']:
        raise ValueError('Image content changed.')
    from .qt_compat import QByteArray, QBuffer, QIODevice
    from .qt_compat import QImage
    image = QImage.fromData(QByteArray(data))
    if image.isNull():
        raise ValueError('Could not decode the image.')
    if _has_transparency(image):
        return {'status': 'ok', 'kept': True}
    out = QBuffer(); out.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.convertToFormat(QImage.Format.Format_RGB32).save(out, 'JPEG', quality):
        raise ValueError('Could not encode the JPEG copy.')
    return {'status': 'ok', 'kept': False, 'width': image.width(), 'height': image.height(),
            'image_base64': base64.b64encode(bytes(out.data())).decode('ascii')}

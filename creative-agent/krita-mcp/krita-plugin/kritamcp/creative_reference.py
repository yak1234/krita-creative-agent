"""Read attached image bytes without opening or mutating a Krita document."""
import base64
import hashlib
from .creative_validation import fields


def decode_reference(params):
    fields(params, ('image_base64', 'sha256'), ('image_base64', 'sha256'))
    encoded = params['image_base64']
    if not isinstance(encoded, str) or len(encoded) > 7 * 1024 * 1024:
        raise ValueError('Reference must be at most 5 MB.')
    data = base64.b64decode(encoded, validate=True)
    if len(data) > 5 * 1024 * 1024:
        raise ValueError('Reference must be at most 5 MB.')
    if hashlib.sha256(data).hexdigest() != params['sha256']:
        raise ValueError('Reference content changed.')
    from .qt_compat import QByteArray, QBuffer, QIODevice
    from .qt_compat import QImage, QImageReader, QColorSpace
    buffer = QBuffer(); buffer.setData(QByteArray(data)); buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 4_000_000:
        raise ValueError('Use a reference with at most four million pixels.')
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


def trace_reference(params):
    """Guided trace's decode of a reference (draw_guide from_reference), reduced while it is read so a full-size goal
    image traces: at most max_side pixels on its long side and TRACE_PIXELS in all, never enlarged. A path of its own:
    decode_reference keeps its limits for the reference tools. Returns the decoded and the original size."""
    fields(params, ('image_base64', 'sha256', 'max_side'), ('image_base64', 'sha256', 'max_side'))
    encoded, side = params['image_base64'], params['max_side']
    if not isinstance(encoded, str) or len(encoded) > 17 * 1024 * 1024:
        raise ValueError('A reference to trace must be at most 12 MB.')
    if isinstance(side, bool) or not isinstance(side, int) or not 16 <= side <= 8192:
        raise ValueError('max_side must be 16-8192 pixels')
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
    scale = min(1.0, side / max(width, height), (TRACE_PIXELS / (width * height)) ** 0.5)
    if scale < 1:
        reader.setScaledSize(QSize(max(1, round(width * scale)), max(1, round(height * scale))))
    image = reader.read()
    if image.isNull():
        raise ValueError('Could not decode the reference to trace.')
    if image.colorSpace().isValid():
        image.convertToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = image.constBits().asstring(image.sizeInBytes())
    return {'status': 'ok', 'width': image.width(), 'height': image.height(), 'original_width': width, 'original_height': height,
            'sha256': params['sha256'], 'rgba_base64': base64.b64encode(raw).decode('ascii')}


SMALL_REFERENCE = 1024 * 1024    # bytes; a reference this small that fits is sent as it is


def model_image(params):
    """A reference shrunk for a model request: at most max_side pixels on its long side.

    Model APIs downscale larger images themselves (to about 1568-2048 px), so sending the
    original only adds upload and chat-log bytes. The copy is a JPEG; a file over 1 MB that
    already fits is re-encoded too. Returns scaled=False when the original should be sent.
    """
    fields(params, ('image_base64', 'sha256', 'max_side'), ('image_base64', 'sha256', 'max_side'))
    encoded, side = params['image_base64'], params['max_side']
    if not isinstance(encoded, str) or len(encoded) > 17 * 1024 * 1024:
        raise ValueError('Reference must be at most 12 MB.')
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
    if not isinstance(encoded, str) or len(encoded) > 17 * 1024 * 1024:
        raise ValueError('Image must be at most 12 MB.')
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

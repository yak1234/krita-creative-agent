"""Pixel work for region craft and filters, done by Qt in C++: shape masks, region fills
and partial filter blends.

Kept apart from region_craft.py so its validation and layer handling can be tested
without Qt. Every buffer is 8-bit: masks one byte per pixel, colour BGRA (Krita's
RGBA/U8 pixel order, which is QImage.Format.Format_ARGB32 on little-endian Macs).
"""
from .qt_compat import Qt, QPointF, QRectF
from .qt_compat import (QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath,
                         QRadialGradient)


def _rows(image, width, height, depth):
    """The image's bytes without Qt's row padding."""
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes())
    raw, line = bytes(pointer), image.bytesPerLine()
    if line == width * depth:
        return raw[:width * height * depth]
    return b''.join(raw[row * line:row * line + width * depth] for row in range(height))


def shape_mask(shape, rect, points=None):
    """An antialiased ellipse or polygon mask covering `rect` [x, y, w, h]."""
    x, y, w, h = rect
    path = QPainterPath()
    if shape == 'ellipse':
        path.addEllipse(QRectF(x, y, w, h))
    else:
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        path.closeSubpath()
    image = QImage(w, h, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.black)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(-x, -y)
    painter.fillPath(path, Qt.GlobalColor.white)
    painter.end()
    return _rows(image.convertToFormat(QImage.Format.Format_Grayscale8), w, h, 1)


def _brush(paint):
    if paint['kind'] == 'color':
        return QBrush(QColor(paint['color']))
    if paint['kind'] == 'pattern':
        return QBrush(paint['image'])            # tiles from the canvas origin
    gradient = paint['gradient']
    start, end = QPointF(*gradient['start']), QPointF(*gradient['end'])
    if gradient['type'] == 'radial':
        dx, dy = end.x() - start.x(), end.y() - start.y()
        shader = QRadialGradient(start, max(1.0, (dx * dx + dy * dy) ** 0.5))
    else:
        shader = QLinearGradient(start, end)
    for stop in gradient['stops']:
        shader.setColorAt(stop['offset'], QColor(stop['color']))
    return QBrush(shader)


def paint(base, width, height, mask, spec, origin, alpha_lock=False):
    """BGRA pixels for `rect`: the fill limited by `mask`, over `base` when given.

    `base` is the target's current BGRA pixels (None for a new layer). With
    `alpha_lock`, only the target's existing opaque pixels change colour.
    """
    x, y = origin
    fill = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    fill.fill(Qt.GlobalColor.transparent)
    painter = QPainter(fill)
    painter.translate(-x, -y)                    # brushes use canvas coordinates
    painter.fillRect(QRectF(x, y, width, height), _brush(spec))
    painter.end()
    coverage = QImage(mask, width, height, width, QImage.Format.Format_Alpha8)
    painter = QPainter(fill)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, coverage)
    painter.end()
    if base is None:
        result = fill
    else:
        result = QImage(base, width, height, width * 4, QImage.Format.Format_ARGB32).convertToFormat(
            QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(result)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop if alpha_lock
                                   else QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.drawImage(0, 0, fill)
        painter.end()
    return _rows(result.convertToFormat(QImage.Format.Format_ARGB32), width, height, 4)


def blend(original, filtered, mask, width, height):
    """`filtered` where `mask` is set and `original` elsewhere, with soft mask edges (BGRA)."""
    coverage = QImage(mask, width, height, width, QImage.Format.Format_Alpha8)
    inside = QImage(filtered, width, height, width * 4, QImage.Format.Format_ARGB32).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(inside)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, coverage)
    painter.end()
    result = QImage(original, width, height, width * 4, QImage.Format.Format_ARGB32).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    painter.drawImage(0, 0, coverage)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    painter.drawImage(0, 0, inside)
    painter.end()
    return _rows(result.convertToFormat(QImage.Format.Format_ARGB32), width, height, 4)

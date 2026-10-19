"""Pixel work for split_by_color: a painting's main colours, and which pixels belong to each.

Buffers are 8-bit like region_raster.py: colour BGRA (Krita's RGBA/U8 order), indices and masks one byte per
pixel, no row padding. A 6000x4500 canvas has 27 million pixels and Krita's Python has no numpy, so no loop runs
per pixel at full size: the palette is found on a copy at most 400 px on its long side (a median cut over a
5-bit colour histogram), each full-size pixel gets its nearest palette colour from Qt's indexed conversion,
and masks, counts and bounds are bytes.translate, big-integer OR and bytes.find, which run in C.
"""
from .qt_compat import Qt
from .qt_compat import QImage, qRgb

SAMPLE = 400
OPAQUE = 128
_TRANSPARENT = bytes(255 if value < OPAQUE else 0 for value in range(256))


def _image(bgra, width, height):
    return QImage(bgra, width, height, width * 4, QImage.Format.Format_ARGB32).copy()


def _bytes(image, width, height, depth):
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes())
    raw, line = bytes(pointer), image.bytesPerLine()
    row = width * depth
    return raw if line == row else b''.join(raw[y * line:y * line + row] for y in range(height))


def palette(bgra, width, height, count):
    """Up to `count` main colours (r, g, b) of the opaque pixels, most distinct first by median cut."""
    image = _image(bgra, width, height)
    if max(width, height) > SAMPLE:
        image = image.scaled(SAMPLE, SAMPLE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
    data = _bytes(image, image.width(), image.height(), 4)
    bins = {}
    for b, g, r, a in zip(data[0::4], data[1::4], data[2::4], data[3::4]):
        if a < OPAQUE:
            continue
        key = (r >> 3, g >> 3, b >> 3)
        entry = bins.get(key)
        if entry is None:
            bins[key] = [1, r, g, b]
        else:
            entry[0] += 1; entry[1] += r; entry[2] += g; entry[3] += b
    boxes = [list(bins.items())] if bins else []
    while len(boxes) < count:
        splittable = [box for box in boxes if len(box) > 1]
        if not splittable:
            break
        def spread(box):
            return max(max(k[c] for k, _ in box) - min(k[c] for k, _ in box) for c in range(3))
        box = max(splittable, key=lambda b: (spread(b), sum(e[0] for _, e in b)))
        channel = max(range(3), key=lambda c: max(k[c] for k, _ in box) - min(k[c] for k, _ in box))
        box.sort(key=lambda item: item[0][channel])
        half, seen, cut = sum(e[0] for _, e in box) / 2, 0, 1
        for index, (_, entry) in enumerate(box[:-1]):
            seen += entry[0]
            cut = index + 1
            if seen >= half:
                break
        boxes.remove(box)
        boxes += [box[:cut], box[cut:]]
    colours = []
    for box in boxes:
        n = sum(e[0] for _, e in box)
        colours.append(tuple(round(sum(e[c] for _, e in box) / n) for c in (1, 2, 3)))
    return colours


def assign(bgra, width, height, colours):
    """One palette index per pixel, the nearest colour by Qt; transparent pixels get 255."""
    table = [qRgb(r, g, b) for r, g, b in colours]
    indexed = _image(bgra, width, height).convertToFormat(QImage.Format.Format_Indexed8, table, Qt.ImageConversionFlag.ThresholdDither)
    indices = _bytes(indexed, width, height, 1)
    transparent = bytes(bgra[3::4]).translate(_TRANSPARENT)
    size = width * height
    return (int.from_bytes(indices, 'big') | int.from_bytes(transparent, 'big')).to_bytes(size, 'big')


def mask(indices, index):
    """The 0/255 mask of one palette index. Build them one at a time: 24 full-canvas masks at once is ~650 MB."""
    return indices.translate(bytes(255 if value == index else 0 for value in range(256)))


def masks(indices, count):
    """One 0/255 mask per palette index."""
    return [mask(indices, k) for k in range(count)]


def crop(buffer, width, rect, depth=1):
    """The rows of `rect` [x, y, w, h] from a buffer `width` pixels wide, `depth` bytes per pixel."""
    x, y, w, h = rect
    return b''.join(buffer[((y + row) * width + x) * depth:((y + row) * width + x + w) * depth] for row in range(h))


def cut(bgra, mask):
    """The BGRA pixels where the 0/255 mask is set, transparent elsewhere."""
    wide = bytearray(len(mask) * 4)
    for channel in range(4):
        wide[channel::4] = mask
    size = len(bgra)
    return (int.from_bytes(bgra, 'big') & int.from_bytes(wide, 'big')).to_bytes(size, 'big')


def extent(mask, width, height):
    """[[x, y, w, h], pixels] of a 0/255 mask, or None when it is empty."""
    first = mask.find(b'\xff')
    if first < 0:
        return None
    top, bottom = first // width, mask.rfind(b'\xff') // width
    left, right = width, -1
    for y in range(top, bottom + 1):
        row = mask[y * width:(y + 1) * width]
        start = row.find(b'\xff')
        if start >= 0:
            left, right = min(left, start), max(right, row.rfind(b'\xff'))
    return [[left, top, right - left + 1, bottom - top + 1], mask.count(b'\xff')]

"""Pixel work for protected areas: erasing the agent's paint inside them and checking that nothing inside changed.

Buffers are 8-bit like region_raster.py: colour BGRA (straight alpha, Krita's RGBA/U8 order), masks one byte per
pixel, no row padding. A 6000x4500 canvas has 27 million pixels and Krita's Python has no numpy, so no loop runs
per pixel: arithmetic is Qt painting on 8-bit grey images (exact for opaque grey), and counting is bytes.translate
and big-integer bit operations, which run in C. Colour bytes never pass through Qt, whose premultiplied
compositing would nudge them where nothing should change.
"""
from .qt_compat import QImage, QPainter

# A pixel counts as inside a protected area from half coverage: a soft edge below that is not a violation.
INSIDE = 128
_INSIDE_FLAGS = bytes(1 if value >= INSIDE else 0 for value in range(256))
_NONZERO_FLAGS = bytes([0] + [1] * 255)
_INVERT = bytes(255 - value for value in range(256))
_INSIDE_BYTES = bytes(255 if value >= INSIDE else 0 for value in range(256))
# What the erase keeps: nothing inside, 255 - mask in the soft band.
_ERASE = bytes(0 if value >= INSIDE else 255 - value for value in range(256))


def _grey(data, width, height):
    image = QImage(data, width, height, width, QImage.Format.Format_Grayscale8)
    return image.copy()                                   # owns its bytes; `data` may be freed


def _grey_bytes(image, width, height):
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes())
    raw, line = bytes(pointer), image.bytesPerLine()
    if line == width:
        return raw[:width * height]
    return b''.join(raw[row * line:row * line + width] for row in range(height))


def _paint(base, layer, mode, width, height):
    """`layer` composited onto `base` with an opaque blend `mode`, both grey planes."""
    target = _grey(base, width, height)
    painter = QPainter(target)
    painter.setCompositionMode(mode)
    painter.drawImage(0, 0, _grey(layer, width, height))
    painter.end()
    return _grey_bytes(target, width, height)


def inside_count(mask):
    """How many pixels of a mask count as inside (>= 128)."""
    return len(mask) - mask.translate(_INSIDE_FLAGS).count(0)


def invert(mask):
    """255 - each value: where a mask keeps, the inverse lets through."""
    return mask.translate(_INVERT)


def union(masks, width, height):
    """Per-pixel maximum of the masks."""
    result = bytes(width * height)
    for mask in masks:
        result = _paint(result, mask, QPainter.CompositionMode.CompositionMode_Lighten, width, height)
    return result


def keep_alpha(bgra, mask, width, height):
    """Alpha multiplied by mask / 255, colour untouched: a part cut out with a soft selection keeps its soft edge."""
    pixels = bytearray(bgra)
    pixels[3::4] = _paint(bgra[3::4], mask, QPainter.CompositionMode.CompositionMode_Multiply, width, height)
    return bytes(pixels)


def erase_inside(bgra, mask, width, height):
    """The agent's paint taken out of a protected area: cleared where the mask counts as inside (>= 128), the same
    pixels the backstop checks, and scaled by (255 - mask) / 255 in the soft band below. Colour untouched. Returns the
    pixels and how many visible pixels were inside."""
    removed = visible_inside(bgra, mask)
    return keep_alpha(bgra, mask.translate(_ERASE), width, height), removed


def visible_inside(bgra, mask):
    """How many pixels with any alpha lie inside (mask >= 128)."""
    inside = int.from_bytes(mask.translate(_INSIDE_FLAGS), 'little') & int.from_bytes(bgra[3::4].translate(_NONZERO_FLAGS), 'little')
    return bin(inside).count('1')


def restore_inside(later, earlier, mask, width, height):
    """`later`, with `earlier`'s pixels put back where the mask counts as inside: a layer that existed before an
    operation keeps its own paint in a protected area, rather than having it erased."""
    keep = int.from_bytes(mask.translate(_INSIDE_BYTES), 'little')
    other = keep ^ ((1 << (8 * len(mask))) - 1)
    pixels = bytearray(later)
    for channel in range(4):
        old = int.from_bytes(earlier[channel::4], 'little')
        new = int.from_bytes(later[channel::4], 'little')
        pixels[channel::4] = ((old & keep) | (new & other)).to_bytes(len(mask), 'little')
    return bytes(pixels)


def changed_inside(before, after, mask, width, height):
    """How many pixels inside (mask >= 128) differ in any channel."""
    if before == after:
        return 0
    size = width * height * 4
    diff = (int.from_bytes(before, 'little') ^ int.from_bytes(after, 'little')).to_bytes(size, 'little')
    changed = 0
    for channel in range(4):
        changed |= int.from_bytes(diff[channel::4].translate(_NONZERO_FLAGS), 'little')
    return bin(changed & int.from_bytes(mask.translate(_INSIDE_FLAGS), 'little')).count('1')

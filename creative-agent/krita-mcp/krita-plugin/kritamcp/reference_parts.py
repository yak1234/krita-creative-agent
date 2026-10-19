"""A part or a crop of a reference, from a selection made in Krita.

A part keeps the reference's size, see-through outside the selection, so the agent paints it in the place it has in
the original; a crop is the selection's rectangle, opaque, for a close-up. Buffers are 8-bit BGRA (straight alpha)
and masks one byte per pixel, as in protection_raster.py; no loop runs per pixel.
"""
from .protection_raster import keep_alpha


def part_image(bgra, mask, width, height):
    """The reference with each pixel's alpha multiplied by the selection (mask / 255), colour unchanged."""
    return keep_alpha(bgra, mask, width, height)


def crop_image(bgra, width, height, rect):
    """The pixels of rect [x, y, w, h] clipped to the image, and the clipped rect."""
    left, top = max(0, rect[0]), max(0, rect[1])
    right, bottom = min(width, rect[0] + rect[2]), min(height, rect[1] + rect[3])
    if right <= left or bottom <= top:
        return b'', [left, top, 0, 0]
    rows = (bgra[(row * width + left) * 4:(row * width + right) * 4] for row in range(top, bottom))
    return b''.join(rows), [left, top, right - left, bottom - top]


def opaque_bounds(bgra, width, height):
    """[x, y, w, h] around the pixels with any alpha, or None for a clear image."""
    alpha = bgra[3::4]
    top = bottom = None
    left, right = width, 0
    for row in range(height):
        line = alpha[row * width:(row + 1) * width]
        start = width - len(line.lstrip(b'\x00'))
        if start == width:
            continue
        top = row if top is None else top
        bottom = row
        left = min(left, start)
        right = max(right, len(line.rstrip(b'\x00')))
    return None if top is None else [left, top, right - left, bottom - top + 1]

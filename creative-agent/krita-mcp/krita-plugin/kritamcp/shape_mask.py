"""Element shapes (element-shapes 1.5, 1.6): an element's shape, found by the companion, as Krita selection bytes.

The companion writes each shape it uses on the painting as an 8-bit PNG at canvas resolution, cropped to its bounds
(255 inside), into the chat folder's .shapes, and sends {mask_path, bounds}. This reads it without Qt (the tests run
without Krita): only files inside the chat folder, only the size its bounds say. The companion writes filter-0 rows,
which decode at zlib's speed; the other PNG filters are read too, more slowly. A shape is never a layer or a Krita mask:
it limits one painting call (paint_pass inside_shape) or becomes a proposed protected area (an element_shape step).
"""
import os
import stat
import struct
import zlib

from .geometry_data import bounds as checked_bounds

SIGNATURE = b'\x89PNG\r\n\x1a\n'
CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}
MAX_BYTES = 64 * 1024 * 1024
FOLDER = '.shapes'


def _unfilter(raw, width, height, channels):
    stride = width * channels
    if len(raw) != height * (stride + 1):
        raise ValueError('The shape file is damaged.')
    rows, previous = [], bytes(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if kind == 1:
            for i in range(channels, stride): line[i] = (line[i] + line[i - channels]) & 255
        elif kind == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, previous))
        elif kind == 3:
            for i in range(stride):
                line[i] = (line[i] + ((line[i - channels] if i >= channels else 0) + previous[i]) // 2) & 255
        elif kind == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b, c = previous[i], previous[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif kind != 0:
            raise ValueError('The shape file is damaged.')
        previous = bytes(line); rows.append(previous)
    return rows


def _damaged():
    return ValueError('The shape file is damaged.')


def read_png(data, expected=None):
    """(width, height, one byte per pixel) of an 8-bit, non-interlaced PNG: grey, or the first channel times alpha.
    `expected` (width, height): any other size is refused from the header, before anything is inflated, and the
    inflate never holds more than that size's rows."""
    if not isinstance(data, (bytes, bytearray)) or data[:8] != SIGNATURE:
        raise ValueError('The shape file is not a PNG.')
    if len(data) < 33 or data[8:16] != struct.pack('>I', 13) + b'IHDR':
        raise _damaged()                                   # IHDR first, 13 bytes, as the format says
    width, height, depth, colour, _compression, _filter, interlace = struct.unpack('>IIBBBBB', data[16:29])
    if depth != 8 or colour not in CHANNELS or interlace or not width or not height:
        raise ValueError('A shape is an 8-bit PNG.')
    if expected is not None and (width, height) != tuple(expected):
        raise ValueError('The shape file is %d x %d, not the %d x %d its bounds say.' % (width, height, expected[0], expected[1]))
    channels = CHANNELS[colour]
    size = height * (width * channels + 1)
    position, parts = 33, []
    while True:
        if position + 12 > len(data):
            raise _damaged()
        length, kind = struct.unpack('>I4s', data[position:position + 8])
        if position + 12 + length > len(data):
            raise _damaged()
        if kind == b'IDAT':
            parts.append(data[position + 8:position + 8 + length])
        elif kind == b'IHDR':
            raise _damaged()
        elif kind == b'IEND':
            break
        position += 12 + length
    stream = zlib.decompressobj()
    try:
        raw = stream.decompress(b''.join(parts), size + 1)
    except zlib.error:
        raise _damaged() from None
    if len(raw) != size or stream.unconsumed_tail:
        raise _damaged()
    if all(raw[y * (width * channels + 1)] == 0 for y in range(height)):
        rows = [raw[y * (width * channels + 1) + 1:(y + 1) * (width * channels + 1)] for y in range(height)]
    else:
        rows = _unfilter(raw, width, height, channels)
    plane = b''.join(rows)
    if channels == 1:
        return width, height, bytes(plane)
    first, alpha = plane[0::channels], plane[channels - 1::channels] if channels in (2, 4) else None
    if alpha is None:
        return width, height, bytes(first)
    return width, height, bytes(v * a // 255 for v, a in zip(first, alpha))


def read_shape(spec, folder, width, height):
    """((x, y, w, h), bytes) of a shape {mask_path, bounds} on a width x height canvas: the file inside the chat
    folder, its size its bounds' size, the bounds inside the canvas, something selected."""
    if not isinstance(spec, dict) or set(spec) - {'mask_path', 'bounds'} or 'mask_path' not in spec or 'bounds' not in spec:
        raise ValueError('A shape is {mask_path, bounds}.')
    rect = checked_bounds(spec['bounds'], width, height)
    path = spec['mask_path']
    refused = ValueError('A shape file must be in the chat folder.')
    if not folder or not isinstance(path, str) or not path.endswith('.png') or not os.path.isabs(path):
        raise refused
    # Directly in the chat folder's .shapes, named plainly: no "..", no link (followed or hard), a regular file.
    if '..' in path.split(os.sep) or os.path.realpath(os.path.dirname(path)) != os.path.join(os.path.realpath(folder), FOLDER):
        raise refused
    try:
        handle = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    except FileNotFoundError:
        raise ValueError('The shape file is no longer there: find the shape again.') from None
    except OSError:
        raise refused from None                            # a symbolic link (ELOOP), or unreadable
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise refused
        if info.st_size > MAX_BYTES:
            raise ValueError('The shape file is too large.')
        chunks, total = [], 0
        while total <= MAX_BYTES:
            chunk = os.read(handle, MAX_BYTES + 1 - total)
            if not chunk:
                break
            chunks.append(chunk); total += len(chunk)
        data = b''.join(chunks)
    finally:
        os.close(handle)
    if len(data) > MAX_BYTES:
        raise ValueError('The shape file is too large.')
    _w, _h, plane = read_png(data, rect[2:])
    if not plane.strip(b'\x00'):
        raise ValueError('The shape is empty.')
    return rect, plane

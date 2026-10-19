"""Materials as pixels: greyscale tips cut from a source, and dabs of them stamped into an area with one QPainter.

Pure Qt on byte buffers (Krita's BGRA, the area's one-byte selection), so it is tested without Krita
(tests/test_material_raster.py) and holds no document. material_stamp.py reads the painting and writes the layer.

A spike on New Moscow (2026-10-18) set the rules kept here:
- tips are light over its blurred surroundings, smoothed first so snow and specks do not become tips;
- each dab's colour is the canvas under it, blurred, plus 60% of its local light, so stamps stay in the painting's palette;
- compositing is premultiplied throughout: un-premultiplied RGBA made every dab nearly opaque;
- the area's selection masks the result, so nothing lands outside it.
"""
import math

from .qt_compat import Qt, QColor, QImage, QPainter, QPointF, QTransform, image_bytes

SMOOTH = Qt.TransformationMode.SmoothTransformation
STRETCH = Qt.AspectRatioMode.IgnoreAspectRatio
GREY = QImage.Format.Format_Grayscale8
ALPHA = QImage.Format.Format_Alpha8
ARGB = QImage.Format.Format_ARGB32
PREMULTIPLIED = QImage.Format.Format_ARGB32_Premultiplied
WORKING_SIDE = 512          # tips are found on a copy at most this large, then cut at full size
MIN_DETAIL = 3              # mean light over surroundings (0-255) below which a patch is flat
LOCAL_COLOUR = 40           # px: the blur a dab's colour is taken over


def _image(data, w, h, fmt, bpp):
    return QImage(data, w, h, w * bpp, fmt).copy()


def _blur(image, radius):
    """A cheap blur: down by `radius`, then smoothly back up. Keeps the image's format."""
    w, h = image.width(), image.height()
    radius = max(1.0, radius)
    small = image.scaled(max(1, round(w / radius)), max(1, round(h / radius)), STRETCH, SMOOTH)
    return small.scaled(w, h, STRETCH, SMOOTH).convertToFormat(image.format())


def _detail(grey, smooth, local):
    """Light over surroundings, per pixel: max(0, smoothed - blurred)."""
    a, b = image_bytes(_blur(grey, smooth)), image_bytes(_blur(grey, local))
    return bytes(x - y if x > y else 0 for x, y in zip(a, b))


def _overlaps(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def light_tips(bgra, w, h, count, size, mask=None, avoid=()):
    """Up to `count` tips of `size` px: (alpha bytes size*size, rect in source coords), most detailed first.
    `mask` (one byte per pixel) limits where tips come from; `avoid` rects are never cut from."""
    size = min(size, w, h)
    grey = _image(bgra, w, h, ARGB, 4).convertToFormat(GREY)
    scale = min(1.0, WORKING_SIDE / max(w, h))
    ws, hs = max(1, round(w * scale)), max(1, round(h * scale))
    small = grey.scaled(ws, hs, STRETCH, SMOOTH).convertToFormat(GREY)
    detail = _detail(small, max(1.0, 4 * scale), max(2.0, size * 0.4 * scale))
    if mask is not None:
        cover = image_bytes(_image(mask, w, h, GREY, 1).scaled(ws, hs, STRETCH, SMOOTH).convertToFormat(GREY))
        detail = bytes(d * c // 255 for d, c in zip(detail, cover))
    # Summed-area table: any patch's mean detail in four lookups.
    table = [0] * ((ws + 1) * (hs + 1))
    for y in range(hs):
        running = 0
        for x in range(ws):
            running += detail[y * ws + x]
            table[(y + 1) * (ws + 1) + x + 1] = table[y * (ws + 1) + x + 1] + running
    patch = max(2, round(size * scale))
    step = max(1, patch // 4)
    candidates = []
    for py in range(0, hs - patch + 1, step):
        for px in range(0, ws - patch + 1, step):
            total = (table[(py + patch) * (ws + 1) + px + patch] - table[py * (ws + 1) + px + patch]
                     - table[(py + patch) * (ws + 1) + px] + table[py * (ws + 1) + px])
            rect = (min(w - size, round(px / scale)), min(h - size, round(py / scale)), size, size)
            if total / (patch * patch) >= MIN_DETAIL and not any(_overlaps(rect, a) for a in avoid):
                candidates.append((total, rect))
    candidates.sort(key=lambda c: -c[0])
    chosen = []
    for _total, rect in candidates:
        if all(math.hypot(rect[0] - r[0], rect[1] - r[1]) >= size * 0.75 for r in chosen):
            chosen.append(rect)
            if len(chosen) == count:
                break
    return [(_cut(grey, mask, w, rect), rect) for rect in chosen]


def _closed(mask, w, h, rect, radius):
    """The mask around `rect` with holes narrower than about `radius` filled (a morphological closing, done with two
    blurs): a seeded sky selection skips every snowflake and star, and those holes cut into a tip stamp as hard round
    dots. Wide unselected areas (a building) keep their edge. Returns (bytes, left, top, width) of the padded crop."""
    x, y, size, _ = rect
    pad = math.ceil(2 * radius)
    left, top = max(0, x - pad), max(0, y - pad)
    right, bottom = min(w, x + size + pad), min(h, y + size + pad)
    cw, ch = right - left, bottom - top
    crop = b''.join(mask[row * w + left:row * w + right] for row in range(top, bottom))
    grown = bytes(255 if v > 40 else 0 for v in image_bytes(_blur(_image(crop, cw, ch, GREY, 1), radius)))
    closed = bytes(255 if v > 215 else 0 for v in image_bytes(_blur(_image(grown, cw, ch, GREY, 1), radius)))
    # A hole is filled, never an edge moved out: the closing only adds where the original mask was within reach.
    return bytes(max(a, b) for a, b in zip(crop, closed)), left, top, cw


def _cut(grey, mask, w, rect):
    """One tip at full size: its light over a blurred margin around it, peak-normalised, with a round falloff."""
    x, y, size, _ = rect
    pad = round(size * 0.4)
    left, top = max(0, x - pad), max(0, y - pad)
    right, bottom = min(grey.width(), x + size + pad), min(grey.height(), y + size + pad)
    crop = grey.copy(left, top, right - left, bottom - top)
    detail = _detail(crop, max(2.0, size * 0.03), size * 0.4)          # specks (snow, stars) smoothed away
    cw = right - left
    if mask is not None:
        filled, mleft, mtop, mw = _closed(mask, w, grey.height(), rect, max(4.0, size * 0.04))
    values = []
    for row in range(size):
        start = (y - top + row) * cw + (x - left)
        line = detail[start:start + size]
        if mask is not None:
            m = filled[(y - mtop + row) * mw + (x - mleft):(y - mtop + row) * mw + (x - mleft) + size]
            line = bytes(a * b // 255 for a, b in zip(line, m))
        values.append(line)
    half = size / 2
    shaped = [0.0] * (size * size)
    for row, line in enumerate(values):
        for col, value in enumerate(line):
            fall = 1 - math.hypot(col + 0.5 - half, row + 0.5 - half) / half
            if fall > 0 and value:
                shaped[row * size + col] = value ** 1.5 * fall ** 1.5
    # Normalised after the falloff, to the 99.5th percentile: the tip reaches full strength, and a few bright specks
    # cannot set its peak and leave the rest faint.
    lit = sorted(v for v in shaped if v)
    peak = lit[min(len(lit) - 1, int(len(lit) * 0.995))] if lit else 1
    return bytes(min(255, round(255 * v / peak)) for v in shaped)


def shape_tip(bgra, w, h, size):
    """The source's alpha, fitted into size*size and centred: a cut-out leaf, snowflake or figure."""
    source = _image(bgra, w, h, ARGB, 4).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, SMOOTH)
    canvas = QImage(size, size, PREMULTIPLIED)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawImage(QPointF((size - source.width()) / 2, (size - source.height()) / 2), source)
    painter.end()
    return bytes(image_bytes(canvas)[3::4])


def _rgb(value):
    return (value >> 16) & 255, (value >> 8) & 255, value & 255


def _colour(source, local, w, h, x, y, tint):
    """The canvas colour at a dab: blurred, plus 60% of its local light, then moved toward the tint."""
    lx, ly = min(local.width() - 1, int(x * local.width() / w)), min(local.height() - 1, int(y * local.height() / h))
    around, here = _rgb(local.pixel(lx, ly)), _rgb(source.pixel(int(x), int(y)))
    colour = [a + 0.6 * max(0, c - a) for a, c in zip(around, here)]
    if tint:
        target = QColor(tint['color'])
        strength = tint['amount'] * (1.0 if tint.get('toward', 'all') == 'all' else 0.35 + 0.65 * (1 - y / h))
        colour = [c + (t - c) * strength for c, t in zip(colour, (target.red(), target.green(), target.blue()))]
    return QColor(*(max(0, min(255, round(c))) for c in colour))


SELECTED = bytes(1 if v >= 128 else 0 for v in range(256))
EDGE_FADE = 0.15            # the area's edge fades inward over this share of the median dab size


def coverage(dabs, tips, size, mask):
    """Ink a stamp lays per selected pixel: each dab's opacity times the area its tip really covers (scaled, stretched),
    summed, over the selected pixels of `mask`. Above about 0.6 the dabs merge into an even veil over the area."""
    selected = mask.translate(SELECTED).count(1) or 1
    share = [sum(tip) / 255 / (size * size) for tip in tips]
    return sum(d['opacity'] * (size * d['scale']) ** 2 * d['stretch'] * share[d['tip']] for d in dabs) / selected


def stamp(colour_bgra, w, h, mask, tips, size, dabs, tint=None):
    """Stamp `dabs` ({x, y, scale, stretch, rotation, opacity, tip}, area coords) onto a transparent w*h layer.
    Colour comes from `colour_bgra` (the painting under the area). Returns (BGRA bytes, dabs placed)."""
    source = _image(colour_bgra, w, h, ARGB, 4)
    local = source.scaled(max(1, w // LOCAL_COLOUR), max(1, h // LOCAL_COLOUR), STRETCH, SMOOTH)
    alphas = [_image(tip, size, size, ALPHA, 1) for tip in tips]
    canvas = QImage(w, h, PREMULTIPLIED)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    placed = 0
    for dab in dabs:
        x, y = dab['x'], dab['y']
        if not (0 <= x < w and 0 <= y < h) or mask[int(y) * w + int(x)] < 128:
            continue
        tinted = QImage(size, size, PREMULTIPLIED)
        tinted.fill(_colour(source, local, w, h, x, y, tint))
        shaper = QPainter(tinted)
        shaper.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        shaper.drawImage(0, 0, alphas[dab['tip']])
        shaper.end()
        painter.setOpacity(dab['opacity'])
        painter.setTransform(QTransform().translate(x, y).rotate(dab['rotation']).scale(dab['scale'] * dab['stretch'], dab['scale']))
        painter.drawImage(QPointF(-size / 2, -size / 2), tinted)
        placed += 1
    painter.resetTransform()
    painter.setOpacity(1)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, _image(mask, w, h, ALPHA, 1))
    # Then the edge, faded inward: a selection bounded by a rectangle otherwise cuts the stamp off in a straight line.
    sizes = sorted(size * d['scale'] for d in dabs)
    fade = EDGE_FADE * sizes[len(sizes) // 2] if sizes else 0
    if fade >= 1:
        painter.drawImage(0, 0, _image(image_bytes(_blur(_image(mask, w, h, GREY, 1), fade)), w, h, ALPHA, 1))
    painter.end()
    return image_bytes(canvas.convertToFormat(ARGB)), placed


def contact_sheet(tips, size, gap=4):
    """All tips side by side, white on dark grey: what the painter sees of a material."""
    sheet = QImage(len(tips) * size + (len(tips) + 1) * gap, size + 2 * gap, PREMULTIPLIED)
    sheet.fill(QColor(48, 48, 52))
    painter = QPainter(sheet)
    for index, tip in enumerate(tips):
        white = QImage(size, size, PREMULTIPLIED)
        white.fill(QColor(255, 255, 255))
        shaper = QPainter(white)
        shaper.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        shaper.drawImage(0, 0, _image(tip, size, size, ALPHA, 1))
        shaper.end()
        painter.drawImage(gap + index * (size + gap), gap, white)
    painter.end()
    return sheet


def decode(data):
    """An encoded image (PNG, JPEG, WebP) as (BGRA bytes, width, height), or None when Qt cannot read it."""
    image = QImage.fromData(data)
    if image.isNull():
        return None
    image = image.convertToFormat(ARGB)
    return image_bytes(image), image.width(), image.height()


def save_tip(data, size, path):
    """One tip as a greyscale PNG: what a material keeps on disk, readable by any image viewer."""
    if not _image(data, size, size, GREY, 1).save(path, 'PNG'):
        raise RuntimeError('Could not save the tip ' + path)


def load_tip(path, size):
    image = QImage(path)
    if image.isNull() or (image.width(), image.height()) != (size, size):
        raise ValueError('The material tip %s is missing or damaged; make the material again.' % path)
    return image_bytes(image.convertToFormat(GREY))

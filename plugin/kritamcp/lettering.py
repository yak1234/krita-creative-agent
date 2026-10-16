"""Comic lettering as SVG for VectorLayer.addShapesFromSvg: caption boxes and balloons with text.

Text is broken into lines here, with a measure function (QFontMetricsF in Krita, a fake in
tests), and written as one <tspan> per line, so it never depends on Krita's text wrapping.
Pure Python: no Krita or Qt import.
"""
import math
from xml.sax.saxutils import escape, quoteattr

KINDS = ('caption', 'speech', 'thought', 'shout')
PADDING = {'caption': (0.6, 0.45), 'speech': (0.9, 0.7), 'thought': (1.0, 0.8), 'shout': (1.4, 1.1)}   # × font size
LINE_HEIGHT = 1.2


def wrap(text, width, measure):
    """Lines of `text` no wider than `width` where possible; a single long word stays whole."""
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for word in paragraph.split():
            candidate = (line + ' ' + word).strip()
            if line and measure(candidate) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def _attrs(**values):
    return ' '.join('%s=%s' % (key.replace('_', '-'), quoteattr(str(value))) for key, value in values.items())


def _text(lines, left, top, size, font, ink, anchor='start'):
    spans = ''.join('<tspan x="%.1f" %s>%s</tspan>' % (left, 'y="%.1f"' % (top + size) if index == 0 else 'dy="%.1f"' % (size * LINE_HEIGHT), escape(line))
                    for index, line in enumerate(lines))
    return '<text %s>%s</text>' % (_attrs(font_family=font, font_size=size, fill=ink, text_anchor=anchor), spans)


def _speech_path(cx, cy, rx, ry, tip):
    """An ellipse and its tail as one outline, so no stroke crosses the tail's base."""
    theta = math.atan2((tip[1] - cy) / ry, (tip[0] - cx) / rx)
    spread = 0.28
    a = (cx + rx * math.cos(theta - spread), cy + ry * math.sin(theta - spread))
    b = (cx + rx * math.cos(theta + spread), cy + ry * math.sin(theta + spread))
    return 'M %.1f %.1f L %.1f %.1f L %.1f %.1f A %.1f %.1f 0 1 1 %.1f %.1f Z' % (a + tuple(tip) + b + (rx, ry) + a)


def _burst(cx, cy, rx, ry, points=14):
    corners = []
    for index in range(points * 2):
        angle = math.pi * index / points
        scale = 1.0 if index % 2 == 0 else 0.78
        corners.append('%.1f,%.1f' % (cx + rx * scale * math.cos(angle), cy + ry * scale * math.sin(angle)))
    return ' '.join(corners)


def balloon(kind, text, at, width, measure, font='sans-serif', size=28, fill='#ffffff', ink='#000000', stroke=3, tail_to=None):
    """(SVG markup, bounds [x, y, w, h], lines) for one caption or balloon with its top-left at `at`."""
    pad_x, pad_y = (size * p for p in PADDING[kind])
    inner = max(size * 2, width - 2 * pad_x)
    lines = wrap(text, inner, measure)
    text_w = max(measure(line) for line in lines) if lines else 0
    text_h = size + size * LINE_HEIGHT * (len(lines) - 1) + size * 0.25
    box_w, box_h = (width, text_h + 2 * pad_y) if kind == 'caption' else (text_w + 2 * pad_x, text_h + 2 * pad_y)
    x, y = at
    stroke_attrs = _attrs(fill=fill, stroke=ink, stroke_width=stroke, stroke_linejoin='round')
    shapes = []
    if kind == 'caption':
        shapes.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" %s/>' % (x, y, box_w, box_h, stroke_attrs))
        body = _text(lines, x + pad_x, y + pad_y, size, font, ink)
    else:
        cx, cy, rx, ry = x + box_w / 2, y + box_h / 2, box_w / 2, box_h / 2
        if kind == 'speech' and tail_to is not None:
            shapes.append('<path d="%s" %s/>' % (_speech_path(cx, cy, rx, ry, tail_to), stroke_attrs))
        elif kind == 'shout':
            shapes.append('<polygon points="%s" %s/>' % (_burst(cx, cy, rx * 1.12, ry * 1.18), stroke_attrs))
        else:
            shapes.append('<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" %s/>' % (cx, cy, rx, ry, stroke_attrs))
        if kind == 'thought' and tail_to is not None:
            for step, radius in ((0.35, 0.16), (0.65, 0.11), (0.9, 0.07)):
                bx = cx + (tail_to[0] - cx) * step
                by = cy + ry * 0.8 + (tail_to[1] - cy - ry * 0.8) * step
                shapes.append('<circle cx="%.1f" cy="%.1f" r="%.1f" %s/>' % (bx, by, size * radius * 3, stroke_attrs))
        body = _text(lines, cx, cy - text_h / 2, size, font, ink, 'middle')
    bounds = [x, y, box_w, box_h]
    if tail_to is not None and kind in ('speech', 'thought'):
        left, top = min(x, tail_to[0]), min(y, tail_to[1])
        bounds = [left, top, max(x + box_w, tail_to[0]) - left, max(y + box_h, tail_to[1]) - top]
    return ''.join(shapes) + body, [round(v) for v in bounds], lines


def document(markup, width, height):
    """Shapes in an SVG the size of the painting, so its units are the painting's pixels."""
    return '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d">%s</svg>' % (width, height, markup)

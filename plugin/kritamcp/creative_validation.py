"""Pure validation for the creative assistant's bounded native painting operations."""
import math
import re

MAX_PASS_STROKES = 1024


def fields(value, allowed, required=()):
    if not isinstance(value, dict):
        raise ValueError('Expected an object')
    unknown = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unknown:
        raise ValueError('Unknown parameters: ' + ', '.join(sorted(unknown)))
    if missing:
        raise ValueError('Missing parameters: ' + ', '.join(sorted(missing)))


def numeric(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + ' must be a finite number')
    if not low <= value <= high:
        raise ValueError('%s must be between %s and %s' % (label, low, high))
    return value


def text(value, label, maximum=120):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(label + ' must be nonempty text (up to %d characters)' % maximum)
    return value.strip()


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise ValueError('Color must be #RRGGBB')
    return value


def validate_pass(params, width, height, presets):
    fields(params, ('name', 'preset', 'strokes', 'layer_opacity', 'region', 'stage_id', 'expected_revision', 'continue_layer_id', 'panel', 'blend_mode', 'clip_to', 'smudge_overlay', 'smudge_rate'), ('name', 'preset', 'strokes'))
    if 'smudge_overlay' in params and not isinstance(params['smudge_overlay'], bool):
        raise ValueError('smudge_overlay must be boolean')
    if 'smudge_rate' in params:
        if not params.get('smudge_overlay'):
            raise ValueError('smudge_rate needs smudge_overlay')
        numeric(params['smudge_rate'], 'smudge_rate', 0.05, 1)
    if 'continue_layer_id' in params:
        text(params['continue_layer_id'], 'continue_layer_id', 100)
    if 'expected_revision' in params:
        text(params['expected_revision'], 'expected_revision', 100)
    if 'stage_id' in params:
        text(params['stage_id'], 'stage_id', 100)
    if 'region' in params:
        region = params['region']
        if not isinstance(region, list) or len(region) != 4 or any(isinstance(v, bool) or not isinstance(v, int) for v in region):
            raise ValueError('Region must contain four integer coordinates')
        x, y, w, h = region
        if min(x, y) < 0 or min(w, h) < 1 or x + w > width or y + h > height:
            raise ValueError('Region must fit the canvas')
    text(params['name'], 'Layer name')
    if params['preset'] not in presets:
        raise ValueError('Use an exact installed preset name from list_brushes')
    numeric(params.get('layer_opacity', 1), 'layer_opacity', 0, 1)
    strokes = params['strokes']
    # Models send up to 256; the host's reference painter sends bigger batches to save per-call overhead.
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= MAX_PASS_STROKES:
        raise ValueError('A pass needs 1–%d curves' % MAX_PASS_STROKES)
    for stroke in strokes:
        fields(stroke, ('start', 'segments', 'size', 'opacity', 'flow', 'color'),
               ('start', 'segments', 'size', 'opacity', 'flow', 'color'))
        color(stroke['color'])
        numeric(stroke['size'], 'size', 1, 10000)
        numeric(stroke['opacity'], 'opacity', 0.01, 1)
        numeric(stroke['flow'], 'flow', 0.01, 1)
        points = stroke['start']
        segments = stroke['segments']
        if not isinstance(points, list) or len(points) != 2:
            raise ValueError('start needs two coordinates')
        if not isinstance(segments, list) or not 1 <= len(segments) <= 1000:
            raise ValueError('Use 1–1000 cubic segments per curve')
        coordinates = list(points)
        for segment in segments:
            if not isinstance(segment, list) or len(segment) != 6:
                raise ValueError('Each segment needs c1x,c1y,c2x,c2y,endx,endy')
            coordinates.extend(segment)
        # Up to one brush size past the edge, so a stroke can run edge to edge without tapering inside; Krita clips it.
        margin = stroke['size']
        for index, value in enumerate(coordinates):
            numeric(value, 'coordinate', -margin, (width if index % 2 == 0 else height) + margin)
    return params


def painted_share(pixels, tolerance=12):
    """The share of pixels that differ from the canvas's dominant colour (0 for a blank canvas).

    pixels: 4-byte pixels of a small thumbnail of the whole canvas. Whether a canvas is already a
    painting is a question about what is visible, not about how many layers or whether it was
    saved: Krita's new document has a Background and an empty Paint Layer 1.
    """
    count = len(pixels) // 4
    if not count:
        return 0.0
    quads = [pixels[i:i + 4] for i in range(0, count * 4, 4)]
    from collections import Counter
    dominant = Counter(quads).most_common(1)[0][0]
    differing = sum(1 for quad in quads if max(abs(a - b) for a, b in zip(quad, dominant)) > tolerance)
    return round(differing / count, 4)


"""Pure validation for the creative assistant's bounded native painting operations."""
import math
import re

MAX_PASS_STROKES = 1024
# A stroke's optional pen input, one entry per point (the start, then each segment end), in the units Krita's tablet
# input gives its brush engine (krita-native/agent-accel/stroke_points.h). The fork's Node.paintStrokes reads them as
# given; on stock Krita only the native helper paints them.
PEN_INPUTS = ('pressure', 'tilt', 'rotation', 'speed', 'time_ms')
MAX_STROKE_MS = 3600000


def fields(value, allowed, required=()):
    if not isinstance(value, dict):
        raise ValueError('Expected an object')
    unknown = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unknown:
        raise ValueError('Unknown parameters: ' + ', '.join(sorted(unknown)))
    if missing:
        raise ValueError('Missing parameters: ' + ', '.join(sorted(missing)))


def _finite_number(value):
    """True for a real, finite int or float; a bool, NaN, infinity or an int too big for a float (10**400) is not."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def numeric(value, label, low, high):
    if not _finite_number(value):
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
    fields(params, ('name', 'preset', 'strokes', 'layer_opacity', 'region', 'stage_id', 'expected_revision', 'continue_layer_id', 'panel', 'blend_mode', 'clip_to', 'smudge_overlay', 'smudge_rate', 'selection', 'inside_shape'), ('name', 'preset', 'strokes'))
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
        fields(stroke, ('start', 'segments', 'size', 'opacity', 'flow', 'color') + PEN_INPUTS,
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
        # The pen at the start and at each segment's end; Krita eases it along each curve.
        for name in PEN_INPUTS:
            if name in stroke:
                pen_input(stroke[name], name, len(segments) + 1)
        # Up to one brush size past the edge, so a stroke can run edge to edge without tapering inside; Krita clips it.
        margin = stroke['size']
        for index, value in enumerate(coordinates):
            numeric(value, 'coordinate', -margin, (width if index % 2 == 0 else height) + margin)
    return params


GUIDE_FIELDS = ('element', 'strokes', 'stage_id', 'expected_revision', 'replace')
GUIDE_STROKE_FIELDS = ('start', 'segments', 'opacity', 'flow', 'color', 'weight')   # no size: the weight sets the width
GUIDE_WEIGHTS = ('construction', 'contour', 'light')   # guide_craft.py: thin construction, stronger contour, warm light
MAX_GUIDE_STROKES = 256
GUIDE_ELEMENT_LIMIT = 60
GUIDE_MARGIN = 16                      # the widest guide line, past the canvas edge, as a pass allows one brush size


# Characters an element's name never holds: controls and DEL, line and paragraph separators, and the bidirectional
# overrides and isolates that would make a layer name read differently from what it is.
GUIDE_NAME_FORBIDDEN = frozenset([0x7f, 0x2028, 0x2029] + list(range(0x202a, 0x202f)) + list(range(0x2066, 0x206a)))


def guide_element(value):
    """An element's name as guides use it: plain text on one line, spacing normalised. Guides compare names ignoring
    case and spacing ("Towers" and " towers " are one element), so one element shares its guide however it is written."""
    element = ' '.join(text(value, 'element', GUIDE_ELEMENT_LIMIT).split())
    if any(ord(character) < 32 or ord(character) in GUIDE_NAME_FORBIDDEN for character in value):
        raise ValueError('element must be plain text on one line')
    return element


def validate_guide(params, width, height):
    """draw_guide: the element it is for and its lines, in the paint_pass stroke shape. The plugin forces the guide brush
    (colour, opacity, flow, a thin size), so those keys are optional and only checked; pen input is not taken. Returns
    the element's name with its spacing normalised."""
    fields(params, GUIDE_FIELDS, ('element', 'strokes'))
    element = guide_element(params['element'])
    for key in ('stage_id', 'expected_revision'):
        if key in params:
            text(params[key], key, 100)
    if 'replace' in params and not isinstance(params['replace'], bool):
        raise ValueError('replace must be true or false')
    strokes = params['strokes']
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= MAX_GUIDE_STROKES:
        raise ValueError('A guide needs 1–%d lines' % MAX_GUIDE_STROKES)
    for stroke in strokes:
        fields(stroke, GUIDE_STROKE_FIELDS, ('start', 'segments'))
        for key in ('opacity', 'flow'):
            if key in stroke:
                numeric(stroke[key], key, 0.01, 1)
        if 'color' in stroke:
            color(stroke['color'])
        if 'weight' in stroke and stroke['weight'] not in GUIDE_WEIGHTS:
            raise ValueError('weight must be one of: ' + ', '.join(GUIDE_WEIGHTS))
        start, segments = stroke['start'], stroke['segments']
        if not isinstance(start, list) or len(start) != 2:
            raise ValueError('start needs two coordinates')
        if not isinstance(segments, list) or not 1 <= len(segments) <= 1000:
            raise ValueError('Use 1–1000 cubic segments per line')
        coordinates = list(start)
        for segment in segments:
            if not isinstance(segment, list) or len(segment) != 6:
                raise ValueError('Each segment needs c1x,c1y,c2x,c2y,endx,endy')
            coordinates.extend(segment)
        for index, value in enumerate(coordinates):
            numeric(value, 'coordinate', -GUIDE_MARGIN, (width if index % 2 == 0 else height) + GUIDE_MARGIN)
    return element


def pen_input(values, name, count):
    """One pen input's list: `count` entries, each in Krita's range for it (tilt an [x, y] pair of degrees)."""
    if not isinstance(values, list) or len(values) != count:
        raise ValueError(name + ' needs one value per point: the start, then each segment end')
    for value in values:
        if name == 'tilt':
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError('tilt needs [x, y] degrees per point')
            for degrees in value:
                numeric(degrees, 'tilt', -60, 60)
        else:
            numeric(value, name, *{'pressure': (0, 1), 'rotation': (-180, 180), 'speed': (0, 1), 'time_ms': (0, MAX_STROKE_MS)}[name])
    if name == 'time_ms' and any(later < earlier for earlier, later in zip(values, values[1:])):
        raise ValueError('time_ms must not go back along the stroke')


def painted_share(pixels, tolerance=12, ignore=None):
    """The share of pixels that differ from the canvas's dominant colour (0 for a blank canvas).

    pixels: 4-byte pixels of a small thumbnail of the whole canvas. Whether a canvas is already a
    painting is a question about what is visible, not about how many layers or whether it was
    saved: Krita's new document has a Background and an empty Paint Layer 1.
    ignore: one byte per pixel, non-zero under a guide line. Guides are not paint: block-in guides on a
    blank New Moscow canvas measured 10% painted and the whole-picture underpainting was refused.
    """
    count = len(pixels) // 4
    if not count:
        return 0.0
    quads = [pixels[i:i + 4] for i in range(0, count * 4, 4)]
    if ignore is not None:
        quads = [quad for quad, skip in zip(quads, ignore) if not skip]
        if not quads:
            return 0.0
    from collections import Counter
    dominant = Counter(quads).most_common(1)[0][0]
    differing = sum(1 for quad in quads if max(abs(a - b) for a, b in zip(quad, dominant)) > tolerance)
    return round(differing / count, 4)



# ----- Krita's tools as operations (krita-fork 5.3): bucket_fill, enclose_and_fill, krita_gradient, smart_patch ------------
# Each tool's `options` is a dict the fork checks key by key (unknown keys, wrong kinds and out-of-range values are refused
# with only a warning and a false return). Checked here first, from the documented keys and ranges, so a bad option is a
# plain error before anything is queued; and NaN, infinity, bools-as-numbers and huge numbers never reach Krita.
FILL_SAMPLES = ('layer', 'all', 'labels')
FILL_MODES = ('contiguous', 'similar', 'selection')
ENCLOSE_REGIONS = ('all', 'color', 'transparent', 'colorOrTransparent', 'allExceptColor', 'allExceptTransparent',
                   'allExceptColorOrTransparent', 'surroundedByColor', 'surroundedByTransparent', 'surroundedByColorOrTransparent')
COLOUR_REGIONS = ('color', 'colorOrTransparent', 'allExceptColor', 'allExceptColorOrTransparent', 'surroundedByColor',
                  'surroundedByColorOrTransparent')
GRADIENT_SHAPES = ('linear', 'bilinear', 'radial', 'square', 'conical', 'conicalSymmetric', 'spiral', 'reverseSpiral', 'polygonal')
GRADIENT_REPEATS = ('none', 'forwards', 'alternate')
GRADIENT_DITHERS = ('blueNoise', 'bayer2', 'bayer4', 'bayer8')
MAX_GRADIENT_COLORS = 16
PATCH_AREA_LIMIT = 512 * 512            # the fork refuses a larger bounding rectangle (about 5 s at the limit)
# (kind, low, high) per key; 'choice' keys carry their words, 'bool' and 'color' and 'blend' need nothing.
_SHARED_FILL = {
    'sample': ('choice', FILL_SAMPLES), 'labels': ('ints', 0, 8), 'threshold': ('int', 1, 100), 'spread': ('int', 0, 100),
    'closeGap': ('int', 0, 32), 'grow': ('int', -400, 400), 'feather': ('int', 0, 400), 'antialias': ('bool',),
    'stopGrowingAtDarkestPixel': ('bool',), 'useSelectionAsBoundary': ('bool',), 'opacity': ('float', 0, 1), 'compositeOp': ('blend',)}
TOOL_OPTIONS = {
    'fill': dict(_SHARED_FILL, mode=('choice', FILL_MODES), boundaryColor=('color',)),
    'enclose': dict(_SHARED_FILL, regions=('choice', ENCLOSE_REGIONS), regionColor=('color',), invert=('bool',),
                    includeContourRegions=('bool',), includeSurroundingRegions=('bool',)),
    'gradient': {'colors': ('colors',), 'gradient': ('text', 200), 'shape': ('choice', GRADIENT_SHAPES), 'repeat': ('choice', GRADIENT_REPEATS),
                 'reverse': ('bool',), 'dither': ('dither',), 'antiAliasThreshold': ('float', 0, 1), 'opacity': ('float', 0, 1),
                 'compositeOp': ('blend',)},
    'patch': {'accuracy': ('int', 0, 99), 'patchRadius': ('int', 2, 8)},
}


def _colour(value, label):
    try:
        return color(value)
    except ValueError:
        raise ValueError(label + ' must be a colour as #RRGGBB')


def whole_number(value, label, low, high):
    """An integer from a whole number (12 or 12.0), never a bool, NaN, infinity or a fraction."""
    if not _finite_number(value) or value != int(value):
        raise ValueError('%s must be a whole number from %s to %s' % (label, low, high))
    if not low <= value <= high:
        raise ValueError('%s must be a whole number from %s to %s' % (label, low, high))
    return int(value)


def tool_options(kind, options):
    """The checked options dict of one of Krita's tools ('fill', 'enclose', 'gradient', 'patch'), in the fork's own keys."""
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError('options must be an object')
    known = TOOL_OPTIONS[kind]
    unknown = sorted(set(options) - set(known))
    if unknown:
        raise ValueError('Unknown options: %s. This tool takes: %s' % (', '.join(unknown), ', '.join(sorted(known))))
    out = {}
    for key, value in options.items():
        spec = known[key]
        label = 'options.' + key
        if spec[0] == 'int':
            out[key] = whole_number(value, label, spec[1], spec[2])
        elif spec[0] == 'float':
            out[key] = numeric(value, label, spec[1], spec[2])
        elif spec[0] == 'bool':
            if not isinstance(value, bool):
                raise ValueError(label + ' must be true or false')
            out[key] = value
        elif spec[0] == 'choice':
            if value not in spec[1] or not isinstance(value, str):
                raise ValueError('%s must be one of: %s' % (label, ', '.join(spec[1])))
            out[key] = value
        elif spec[0] == 'color':
            out[key] = _colour(value, label)
        elif spec[0] == 'text':
            out[key] = text(value, label, spec[1])
        elif spec[0] == 'ints':
            if not isinstance(value, list) or not 1 <= len(value) <= spec[2] + 1:
                raise ValueError('%s must be a list of 1-%d colour labels (%d to %d)' % (label, spec[2] + 1, spec[1], spec[2]))
            out[key] = [whole_number(item, label, spec[1], spec[2]) for item in value]
        elif spec[0] == 'colors':
            if not isinstance(value, list) or not 2 <= len(value) <= MAX_GRADIENT_COLORS:
                raise ValueError('%s must be a list of 2-%d colours (#RRGGBB)' % (label, MAX_GRADIENT_COLORS))
            out[key] = [_colour(item, label) for item in value]
        elif spec[0] == 'dither':
            if not isinstance(value, bool) and value not in GRADIENT_DITHERS:
                raise ValueError('%s must be true, false or one of: %s' % (label, ', '.join(GRADIENT_DITHERS)))
            out[key] = value
        elif spec[0] == 'blend':
            from .capabilities import validate_blend_mode
            out[key] = validate_blend_mode(value)
    if 'labels' in out and out.get('sample') != 'labels':
        raise ValueError('options.labels go with options.sample "labels"')
    if out.get('sample') == 'labels' and 'labels' not in out:
        raise ValueError('options.sample "labels" needs options.labels (colour label numbers 0 to 8)')
    if kind == 'enclose':
        if out.get('regions') in COLOUR_REGIONS and 'regionColor' not in out:
            raise ValueError('options.regionColor (#RRGGBB) is required for regions "%s"' % out['regions'])
    if kind == 'gradient' and 'colors' not in out and 'gradient' not in out:
        raise ValueError('A gradient needs options.colors or options.gradient (the name of a gradient)')
    return out


def canvas_point(value, label, width, height, margin):
    """[x, y] as two finite numbers within `margin` pixels of the canvas (0 for a point that must lie on it)."""
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(label + ' must be [x, y]')
    x = numeric(value[0], label + ' x', -margin, width + margin - (1 if margin == 0 else 0))
    y = numeric(value[1], label + ' y', -margin, height + margin - (1 if margin == 0 else 0))
    return [x, y]


def canvas_pixel(x, y, x_label, y_label, width, height):
    """(x, y) as whole pixels inside the canvas: where a bucket fill starts."""
    return whole_number(x, x_label, 0, width - 1), whole_number(y, y_label, 0, height - 1)


def check_patch_area(width, height):
    """Smart patch takes an area whose bounding rectangle is at most 512 x 512 pixels (262144): refuse a larger one with
    its numbers, as the fork would only warn."""
    if width * height > PATCH_AREA_LIMIT:
        raise ValueError('The area to patch is %d x %d pixels (%d), larger than the %d-pixel limit (512 x 512). Patch it in '
                         'pieces: select a smaller area around the seam or damage.' % (width, height, width * height, PATCH_AREA_LIMIT))


def command_error(error):
    """A command's failure as the bridge's error result. A ValueError is a refused request (bad or forbidden input), so the
    companion gets validation_rejected, not an internal error."""
    code = 'validation_rejected' if isinstance(error, ValueError) else 'internal'
    return {'error': '%s: %s' % (type(error).__name__, error), 'error_code': code}

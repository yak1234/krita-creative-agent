"""What the running Krita offers the painter, and validation against it.

The manifest is read from the installed Krita (filters and their default
configurations, fill generators, installed resources) and cached per Krita
version. Craft operations validate every filter, generator, blend mode and
configuration value against it before any mutation, so an unknown name or a
mistyped value is refused instead of guessed.
"""
import json
import re
from krita import Krita, InfoObject, Selection

MANIFEST_VERSION = 3   # 2: generator settings, colour settings, unsupported settings recorded; 3: gradient generator settings
SETTINGS_GROUP = 'creative_agent_capabilities'

# Krita exposes no list of blend modes, and setBlendingMode stores any string, so a
# probe cannot prove support. These are Krita's composite-op ids (KoCompositeOpRegistry)
# that matter for painting, grouped for the painter. The live acceptance check
# confirms them on the installed Krita.
BLEND_MODES = {
    'basic': ['normal', 'erase', 'behind', 'dissolve'],
    'darken': ['multiply', 'darken', 'burn', 'linear_burn'],
    'lighten': ['screen', 'lighten', 'dodge', 'linear_dodge', 'add'],
    'contrast': ['overlay', 'soft_light', 'hard_light', 'vivid_light', 'linear light', 'pin_light', 'hard mix'],
    'difference': ['diff', 'exclusion', 'subtract', 'divide'],
    'colour': ['hue', 'saturation', 'color', 'luminize'],
    'texture': ['grain_merge', 'grain_extract'],
}
BLEND_MODE_IDS = frozenset(mode for modes in BLEND_MODES.values() for mode in modes)

# Generators a fill layer may use, when the installed Krita has them.
GENERATOR_CANDIDATES = ('color', 'gradient', 'pattern', 'screentone', 'simplexnoise', 'multigrid')

# A new fill layer reports an empty configuration, so the settings each generator
# reads are listed here (from the Krita API docs). InfoObject.setProperty takes a
# '#RRGGBB' string for a colour setting.
UNITS = ['pixels', 'percent_of_width', 'percent_of_height', 'percent_of_longest_side', 'percent_of_shortest_side']
# A new gradient fill layer reports an empty configuration, so its keys come from Krita's
# gradient generator (KisGradientGeneratorConfiguration). start_color and end_color are ours:
# they become the generator's `gradient` stops (KoStopGradient XML).
GENERATOR_SETTINGS = {
    'color': {'color': {'type': 'color', 'default': '#000000'}},
    'pattern': {'pattern': {'type': 'string', 'default': ''}},
    'gradient': {
        'shape': {'type': 'string', 'default': 'linear', 'options': ['linear', 'bilinear', 'radial', 'square', 'conical', 'conical_symetric', 'spiral', 'reverse_spiral']},
        'repeat': {'type': 'string', 'default': 'none', 'options': ['none', 'forwards', 'alternate']},
        'reverse': {'type': 'bool', 'default': False},
        'dither': {'type': 'bool', 'default': True},
        'start_position_x': {'type': 'float', 'default': 0.0},
        'start_position_y': {'type': 'float', 'default': 50.0},
        'start_position_x_units': {'type': 'string', 'default': 'percent_of_width', 'options': UNITS},
        'start_position_y_units': {'type': 'string', 'default': 'percent_of_height', 'options': UNITS},
        'end_position_x': {'type': 'float', 'default': 100.0},
        'end_position_y': {'type': 'float', 'default': 50.0},
        'end_position_x_units': {'type': 'string', 'default': 'percent_of_width', 'options': UNITS},
        'end_position_y_units': {'type': 'string', 'default': 'percent_of_height', 'options': UNITS},
        'start_color': {'type': 'color', 'default': '#000000', 'into': 'gradient'},
        'end_color': {'type': 'color', 'default': '#ffffff', 'into': 'gradient'},
    },
}


def gradient_xml(start, end):
    """A two-stop gradient in the XML Krita's gradient generator reads."""
    def stop(offset, colour):
        r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return ('<stop offset="%g" bitdepth="U8" alpha="1" type="0"><RGB r="%.6f" g="%.6f" b="%.6f"/></stop>'
                % (offset, r, g, b))
    return '<gradient name="Creative Agent" type="stop">%s%s</gradient>' % (stop(0, start), stop(1, end))
HEX_COLOUR = re.compile(r'^#[0-9a-fA-F]{6}$')

# Filters the painter reaches for first; the compact manifest shows their key settings.
COMMON_FILTERS = ('colorbalance', 'perchannel', 'hsvadjustment', 'levels', 'brightnesscontrast', 'desaturate',
                  'gaussian blur', 'blur', 'lens blur', 'unsharp', 'noise', 'posterize', 'gradientmap', 'colortransfer')
COMPACT_BUDGET = 3800   # characters; the painter's result budget is 6000


def _kind(value):
    if isinstance(value, bool): return 'bool'
    if isinstance(value, int): return 'int'
    if isinstance(value, float): return 'float'
    if isinstance(value, str): return 'string'
    if type(value).__name__ == 'QColor': return 'color'
    return None


def _default(kind, value):
    return value.name() if kind == 'color' else value


def _properties(info, unsupported=None):
    """Settable properties of an InfoObject, as {name: {type, default}}.

    Settings of other types are listed in `unsupported` (name: type name), so a live
    run shows what a filter or generator holds that the painter cannot set yet.
    """
    result = {}
    for name, value in (info.properties() if info is not None else {}).items():
        kind = _kind(value)
        if kind:
            result[str(name)] = {'type': kind, 'default': _default(kind, value)}
        elif unsupported is not None:
            unsupported[str(name)] = type(value).__name__
    return result


def _filters(app, unsupported):
    filters = {}
    for name in sorted(app.filters()):
        try:
            item = app.filter(name)
            filters[name] = _properties(item.configuration() if item is not None else None, unsupported.setdefault('filter:' + name, {}))
        except Exception:
            filters[name] = {}
    return filters


def _generators(app, doc, unsupported):
    """Generators that create a fill layer on the installed Krita, with their defaults.

    The probe layer is never added to the document, so the artwork is untouched.
    """
    found = {}
    if doc is None:
        return found
    for name in GENERATOR_CANDIDATES:
        try:
            node = doc.createFillLayer('Creative Agent probe', name, InfoObject(), Selection())
        except Exception:
            node = None
        if node is not None:
            try:
                found[name] = _properties(node.filterConfig(), unsupported.setdefault('generator:' + name, {}))
            except Exception:
                found[name] = {}
            found[name] = {**GENERATOR_SETTINGS.get(name, {}), **found[name]}
    return found


def _resources(app, kind):
    try:
        return sorted(app.resources(kind).keys())
    except Exception:
        return []


def collect(app=None, doc=None):
    """Read the full manifest from the running Krita."""
    app = app or Krita.instance()
    unsupported = {}
    result = {'manifest_version': MANIFEST_VERSION, 'krita_version': app.version(),
              'blend_modes': BLEND_MODES, 'filters': _filters(app, unsupported), 'generators': _generators(app, doc, unsupported),
              'presets': _resources(app, 'preset'), 'patterns': _resources(app, 'pattern'),
              'gradients': _resources(app, 'gradient')}
    result['unsupported_settings'] = {key: value for key, value in unsupported.items() if value}
    return result


def manifest(app=None, doc=None, refresh=False):
    """The cached manifest for this Krita version, collected on first use or on refresh.

    Generators need a document to probe; a manifest collected without one is not
    cached, so the next call with a document completes it.
    """
    app = app or Krita.instance()
    if not refresh:
        try:
            cached = json.loads(app.readSetting(SETTINGS_GROUP, 'manifest', '') or '{}')
        except ValueError:
            cached = {}
        if (cached.get('manifest_version') == MANIFEST_VERSION and cached.get('krita_version') == app.version()
                and cached.get('generators')):
            return cached
    result = collect(app, doc)
    if result['generators']:
        app.writeSetting(SETTINGS_GROUP, 'manifest', json.dumps(result))
    return result


def compact(full, budget=COMPACT_BUDGET):
    """A short manifest for the painter: names everywhere, key settings for common filters.

    It trims itself to `budget` characters: fewer settings per common filter first,
    then fewer pattern and gradient names.
    """
    for properties, resources in ((5, 20), (4, 16), (3, 12), (2, 8), (1, 4), (0, 0)):
        common = {}
        for name in COMMON_FILTERS:
            if name in full['filters']:
                items = list(full['filters'][name].items())[:properties]
                common[name] = {key: spec['default'] for key, spec in items}
        result = {'krita_version': full['krita_version'], 'blend_modes': full['blend_modes'],
                  'common_filters': common, 'other_filters': sorted(set(full['filters']) - set(common)),
                  'generators': {name: {key: spec['default'] for key, spec in props.items()} for name, props in full['generators'].items()},
                  'preset_count': len(full['presets']), 'patterns': full['patterns'][:resources], 'gradients': full['gradients'][:resources],
                  'note': 'Call krita_capabilities with full=true for every filter setting, or list_brushes for presets.'}
        if len(json.dumps(result)) <= budget:
            break
    return result


def validate_blend_mode(mode):
    if not isinstance(mode, str) or mode not in BLEND_MODE_IDS:
        raise ValueError('Unknown blend mode %r. Use one of: %s' % (mode, ', '.join(sorted(BLEND_MODE_IDS))))
    return mode


def validate_config(kind, name, config, available):
    """Check a filter or generator configuration against its default properties."""
    if name not in available:
        raise ValueError('Unknown %s %r. Call krita_capabilities to see what this Krita offers.' % (kind, name))
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError('%s configuration must be an object' % kind.capitalize())
    properties = available[name]
    for key, value in config.items():
        spec = properties.get(key)
        if spec is None:
            raise ValueError('%s %r has no setting %r. Settings: %s' % (kind.capitalize(), name, key, ', '.join(sorted(properties)) or 'none'))
        expected, actual = spec['type'], _kind(value)
        if expected == 'color':
            if not isinstance(value, str) or not HEX_COLOUR.match(value):
                raise ValueError('%s %r setting %r must be a colour like #3a6ea5, not %r' % (kind.capitalize(), name, key, value))
            continue
        if spec.get('options') and value not in spec['options']:
            raise ValueError('%s %r setting %r must be one of: %s' % (kind.capitalize(), name, key, ', '.join(spec['options'])))
        if expected == 'float' and actual == 'int':
            continue
        if expected == 'int' and actual == 'float' and float(value).is_integer():
            continue
        if actual != expected:
            raise ValueError('%s %r setting %r must be %s, not %r' % (kind.capitalize(), name, key, expected, value))
    return config


def validate_filter(name, config, full):
    return validate_config('filter', name, config, full['filters'])


def validate_generator(name, config, full):
    return validate_config('generator', name, config, full['generators'])


def configured(info, config):
    """Override validated settings on a configuration that already holds every default.

    Filters start from Krita's own configuration (`Filter.configuration()`), so
    non-scalar defaults such as curves survive untouched.
    """
    for key, value in (config or {}).items():
        info.setProperty(key, value)
    return info


def info_object(defaults, config):
    """A new InfoObject holding scalar defaults overridden by config (for fill generators)."""
    info = InfoObject()
    config = dict(config or {})
    derived = {}
    for key, spec in defaults.items():
        if spec.get('into'):
            derived[key] = config.pop(key, spec['default'])
        elif spec['default'] != '':        # an unset setting keeps the generator's own default
            info.setProperty(key, spec['default'])
    if derived:
        info.setProperty('gradient', gradient_xml(derived['start_color'], derived['end_color']))
    return configured(info, config)

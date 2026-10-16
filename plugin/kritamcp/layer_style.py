"""Layer styles (drop shadow, inner shadow, outer glow, outline) as the ASL XML Krita reads.

`Node.setLayerStyleFromAsl` takes the XML form of a Photoshop layer style that Krita's
own serializer writes (KisAslXmlWriter): a root descriptor holding one descriptor per
effect, each with four-character Photoshop keys. Only the settings below are written;
Krita fills in its defaults for the rest. Pure Python, so it is tested without Krita.
"""
from xml.sax.saxutils import quoteattr
from .creative_validation import color as hex_colour, fields, numeric

BLEND = {'normal': 'Nrml', 'multiply': 'Mltp', 'screen': 'Scrn', 'overlay': 'Ovrl', 'color_dodge': 'CDdg', 'linear_dodge': 'lddg'}
EFFECTS = {
    # name: (descriptor key, settings, defaults)
    'drop_shadow': ('DrSh', ('color', 'opacity', 'angle', 'distance', 'size', 'spread', 'blend_mode'),
                    {'color': '#000000', 'opacity': 0.6, 'angle': 120, 'distance': 8, 'size': 10, 'spread': 0, 'blend_mode': 'multiply'}),
    'inner_shadow': ('IrSh', ('color', 'opacity', 'angle', 'distance', 'size', 'spread', 'blend_mode'),
                     {'color': '#000000', 'opacity': 0.5, 'angle': 120, 'distance': 5, 'size': 8, 'spread': 0, 'blend_mode': 'multiply'}),
    'outer_glow': ('OrGl', ('color', 'opacity', 'size', 'spread', 'blend_mode'),
                   {'color': '#fff2b0', 'opacity': 0.75, 'size': 16, 'spread': 0, 'blend_mode': 'screen'}),
    'outline': ('FrFX', ('color', 'opacity', 'size', 'position', 'blend_mode'),
                {'color': '#000000', 'opacity': 1.0, 'size': 3, 'position': 'outside', 'blend_mode': 'normal'}),
}
POSITIONS = {'outside': 'OutF', 'inside': 'InsF', 'center': 'CtrF'}
LIMITS = {'opacity': (0, 1), 'angle': (-180, 180), 'distance': (0, 1000), 'size': (0, 250), 'spread': (0, 100)}


def validate(style):
    """Check a style object: each effect is a settings object, or null to turn it off."""
    fields(style, tuple(EFFECTS))
    if not style:
        raise ValueError('style needs at least one effect: ' + ', '.join(EFFECTS))
    for name, settings in style.items():
        if settings is None:
            continue
        label = name + ': '
        try:
            fields(settings, EFFECTS[name][1])
            for key, value in settings.items():
                if key == 'color':
                    hex_colour(value)
                elif key == 'blend_mode':
                    if value not in BLEND:
                        raise ValueError('blend_mode must be one of: ' + ', '.join(BLEND))
                elif key == 'position':
                    if value not in POSITIONS:
                        raise ValueError('position must be outside, inside or center')
                else:
                    numeric(value, key, *LIMITS[key])
        except ValueError as error:
            raise ValueError(label + str(error)) from None
    return style


def _node(kind, key, value, **extra):
    attributes = ' '.join('%s=%s' % (k, quoteattr(str(v))) for k, v in [('type', kind), ('key', key)] + list(extra.items()) + [('value', value)])
    return '<node %s/>' % attributes


def _colour(value):
    r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
    return ('<node type="Descriptor" key="Clr " name="" classId="RGBC">%s%s%s</node>'
            % (_node('Double', 'Rd  ', r), _node('Double', 'Grn ', g), _node('Double', 'Bl  ', b)))


def _effect(name, settings):
    key, _keys, defaults = EFFECTS[name]
    if settings is None:
        return '<node type="Descriptor" key="%s" name="" classId="%s">%s</node>' % (key, key, _node('Boolean', 'enab', 0))
    s = dict(defaults, **settings)
    parts = [_node('Boolean', 'enab', 1), _node('Enum', 'Md  ', BLEND[s['blend_mode']], typeId='BlnM'), _colour(s['color']),
             _node('UnitFloat', 'Opct', round(s['opacity'] * 100, 3), unit='#Prc')]
    if name == 'outline':
        parts += [_node('Enum', 'Styl', POSITIONS[s['position']], typeId='FStl'), _node('Enum', 'PntT', 'SClr', typeId='FrFl'),
                  _node('UnitFloat', 'Sz  ', s['size'], unit='#Pxl')]
    else:
        if 'angle' in s:
            parts += [_node('Boolean', 'uglg', 0), _node('UnitFloat', 'lagl', s['angle'], unit='#Ang'),
                      _node('UnitFloat', 'Dstn', s['distance'], unit='#Pxl')]
        parts += [_node('UnitFloat', 'Ckmt', s['spread'], unit='#Prc' if name == 'outer_glow' else '#Pxl'),
                  _node('UnitFloat', 'blur', s['size'], unit='#Pxl'), _node('UnitFloat', 'Nose', 0, unit='#Prc'),
                  _node('Boolean', 'AntA', 0)]
        if name == 'drop_shadow':
            parts.append(_node('Boolean', 'layerConceals', 1))
        if name == 'outer_glow':
            parts += [_node('Enum', 'GlwT', 'SfBL', typeId='BETE'), _node('UnitFloat', 'Inpr', 50, unit='#Prc')]
    return '<node type="Descriptor" key="%s" name="" classId="%s">%s</node>' % (key, key, ''.join(parts))


def asl(style, enabled=True):
    """The ASL XML for `style`: {effect: settings or None}. enabled=False writes a style that shows nothing."""
    effects = ''.join(_effect(name, settings) for name, settings in style.items())
    return ('<asl><node type="Descriptor" name="" classId="null">%s%s%s</node></asl>'
            % (_node('UnitFloat', 'Scl ', 100, unit='#Prc'), _node('Boolean', 'masterFXSwitch', 1 if enabled else 0), effects))


def cleared():
    """A style with every effect off, for a layer that had none before."""
    return asl({name: None for name in EFFECTS}, enabled=False)

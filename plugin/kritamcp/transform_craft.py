"""Move, scale and rotate an agent layer without repainting it, through a transform mask.

Runs inside the creative operation journal (creative_tools.py). A transform mask (Krita
5.2+) holds a free transform; the layer's own pixels never change, so rejecting the pass
hides the mask and the layer is back where it was. Only the agent's own layers move:
the artist's layers are never transformed.

The mask's parameters are the XML of Krita's transform tool (ToolTransformArgs). The
mask's own XML is edited when Krita supplies one; otherwise the same document is
written from FREE_TRANSFORM, with every element Krita's reader requires.
"""
import math
import xml.etree.ElementTree as ElementTree
from .creative_validation import fields, numeric, text

TRANSFORM_FIELDS = ('layer_id', 'move', 'scale', 'rotate', 'pivot', 'name', 'stage_id', 'region', 'expected_revision')
MOVABLE = ('paintlayer', 'grouplayer', 'filllayer', 'vectorlayer')
FREE_TRANSFORM = '''<!DOCTYPE transform_params>
<transform_params>
 <main id="tooltransformparams"/>
 <data mode="0">
  <free_transform>
   <transformedCenter type="pointf" x="0" y="0"/>
   <originalCenter type="pointf" x="0" y="0"/>
   <rotationCenterOffset type="pointf" x="0" y="0"/>
   <transformAroundRotationCenter type="value" value="0"/>
   <aX type="value" value="0"/>
   <aY type="value" value="0"/>
   <aZ type="value" value="0"/>
   <cameraPos type="vector3d" x="0" y="0" z="1024"/>
   <scaleX type="value" value="1"/>
   <scaleY type="value" value="1"/>
   <shearX type="value" value="0"/>
   <shearY type="value" value="0"/>
   <keepAspectRatio type="value" value="0"/>
   <flattenedPerspectiveTransform type="transform" m11="1" m12="0" m13="0" m21="0" m22="1" m23="0" m31="0" m32="0" m33="1"/>
   <filterId type="value" value="Bicubic"/>
  </free_transform>
 </data>
</transform_params>'''


def free_transform_xml(base, center, move, scale, rotate):
    """Transform parameters moving `center` by `move`, scaled and rotated (degrees) about it."""
    try:
        root = ElementTree.fromstring(base) if base else None
    except ElementTree.ParseError:
        root = None
    if root is None or root.find('./data/free_transform') is None or root.find('./data').get('mode', '0') != '0':
        root = ElementTree.fromstring(FREE_TRANSFORM.split('\n', 1)[1])
    free = root.find('./data/free_transform')
    def put(tag, **values):
        element = free.find(tag)
        for key, value in values.items():
            element.set(key, '%.6g' % value if isinstance(value, float) else str(value))
    put('originalCenter', x=float(center[0]), y=float(center[1]))
    put('transformedCenter', x=float(center[0] + move[0]), y=float(center[1] + move[1]))
    put('rotationCenterOffset', x=0.0, y=0.0)
    put('aZ', value=float(math.radians(rotate) % (2 * math.pi)))
    put('scaleX', value=float(scale[0]))
    put('scaleY', value=float(scale[1]))
    return '<!DOCTYPE transform_params>' + ElementTree.tostring(root, encoding='unicode')


class TransformCraft:
    def _transform_validate(self, doc, session, params):
        fields(params, TRANSFORM_FIELDS, ('layer_id',))
        node = self._creative_node(doc, text(params['layer_id'], 'layer_id', 200))
        if not self._craft_owned(session, params['layer_id']):
            raise ValueError("The artist's layers are never moved. Transform one of your own layers.")
        if node.type() not in MOVABLE:
            raise ValueError('A transform goes on a paint, group, fill or vector layer.')
        if node.locked():
            raise ValueError('The layer is locked.')
        if not any(key in params for key in ('move', 'scale', 'rotate')):
            raise ValueError('Give move, scale or rotate.')
        if 'move' in params:
            self._transform_pair(params['move'], 'move', -100000, 100000)
        if 'scale' in params:
            if isinstance(params['scale'], list):
                self._transform_pair(params['scale'], 'scale', 0.02, 50)
            else:
                numeric(params['scale'], 'scale', 0.02, 50)
        if 'rotate' in params:
            numeric(params['rotate'], 'rotate', -360, 360)
        if 'pivot' in params:
            self._transform_pair(params['pivot'], 'pivot', -100000, 100000)
        if 'name' in params:
            text(params['name'], 'name', 120)

    def _transform_pair(self, value, label, low, high):
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(label + ' must be [x, y]')
        for item in value:
            numeric(item, label, low, high)

    def _transform_center(self, doc, node, params):
        if 'pivot' in params:
            return params['pivot']
        bounds = node.bounds() if hasattr(node, 'bounds') else None
        if bounds is None or bounds.isEmpty():
            return [doc.width() / 2, doc.height() / 2]
        return [bounds.x() + bounds.width() / 2, bounds.y() + bounds.height() / 2]

    def _transform_apply(self, doc, session, params):
        node = self._creative_node(doc, params['layer_id'])
        doc.waitForDone()
        center = self._transform_center(doc, node, params)
        scale = params.get('scale', 1)
        scale = scale if isinstance(scale, list) else [scale, scale]
        mask = doc.createTransformMask(params.get('name') or 'Transform')
        if mask is None or not node.addChildNode(mask, None):
            raise RuntimeError('Krita could not add the transform mask.')
        xml = free_transform_xml(mask.toXML(), center, params.get('move', [0, 0]), scale, params.get('rotate', 0))
        if mask.fromXML(xml) is False:
            raise RuntimeError('Krita rejected the transform.')
        doc.waitForDone()
        doc.refreshProjection()
        identifier = mask.uniqueId().toString()
        session['layers'].add(identifier)
        return {'layer_id': identifier, 'layer_type': 'transform_mask', 'target_id': params['layer_id'],
                'transform': {'center': center, 'move': params.get('move', [0, 0]), 'scale': scale, 'rotate': params.get('rotate', 0)}}

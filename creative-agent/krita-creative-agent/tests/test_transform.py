"""Move, scale and rotate an agent layer through a transform mask, on a fake layer tree. Files go to a temporary folder that is removed."""
import math
import sys
import unittest
import xml.etree.ElementTree as ElementTree
import test_region_craft as region_tests

transform = sys.modules['creative_test_package.transform_craft']


class TransformMask(region_tests.Layer):
    def __init__(self, doc, name, own_xml=''):
        super().__init__(doc, name, 'transformmask'); self.own_xml, self.xml = own_xml, None
    def toXML(self): return self.own_xml
    def fromXML(self, xml): self.xml = xml; return True


class Bounds:
    def __init__(self, x, y, w, h): self.box = (x, y, w, h)
    def x(self): return self.box[0]
    def y(self): return self.box[1]
    def width(self): return self.box[2]
    def height(self): return self.box[3]
    def isEmpty(self): return not self.box[2] or not self.box[3]


class Document(region_tests.Document):
    own_xml = ''
    def createTransformMask(self, name): return TransformMask(self, name, self.own_xml)


def values(xml):
    free = ElementTree.fromstring(xml.replace('<!DOCTYPE transform_params>', '')).find('./data/free_transform')
    point = lambda tag: (float(free.find(tag).get('x')), float(free.find(tag).get('y')))
    value = lambda tag: float(free.find(tag).get('value'))
    return {'original': point('originalCenter'), 'transformed': point('transformedCenter'), 'aZ': value('aZ'),
            'scale': (value('scaleX'), value('scaleY')), 'elements': len(list(free))}


class TransformTests(region_tests.RegionSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.h.doc = Document()
        self.h._creative_session.update(document_id=region_tests.native.module.document_id(self.h.doc))

    def agent_layer(self):
        region_tests.run(self.h, 'create_layer', {'name': 'Moon', 'type': 'paint'}, 'moon')
        layer = self.h.doc.root.childNodes()[-1]; layer.bounds = lambda: Bounds(0, 0, 2, 2)
        return layer

    def test_a_transform_mask_moves_scales_and_rotates_without_touching_pixels(self):
        layer = self.agent_layer(); pixels = bytes(layer.pixels)
        result = region_tests.run(self.h, 'transform_layer', {'layer_id': layer.id, 'move': [1, -1], 'scale': 1.5, 'rotate': 90}, 'lift')
        mask, = layer.childNodes()
        self.assertEqual((result['status'], result['layer_id'], result['layer_type'], mask.kind), ('ok', mask.id, 'transform_mask', 'transformmask'))
        got = values(mask.xml)
        self.assertEqual((got['original'], got['transformed'], got['scale'], got['elements']), ((1, 1), (2, 0), (1.5, 1.5), 15))
        self.assertAlmostEqual(got['aZ'], math.pi / 2, places=5)
        self.assertEqual(bytes(layer.pixels), pixels)
        entry = self.h._creative_session['passes'][-1]
        self.assertEqual((entry['kind'], entry['title'], entry['target_id']), ('transform_layer', 'Transform', layer.id))
        region_tests.run(self.h, 'review_pass', {'pass_id': 'lift', 'action': 'reject'}, 'reject')
        self.assertEqual((mask.shown, layer.shown), (False, True))
        region_tests.run(self.h, 'review_pass', {'pass_id': 'moon', 'action': 'reject'}, 'reject-moon')     # the layer's own pass still rejects

    def test_krita_s_own_parameters_are_edited_and_a_pivot_is_honoured(self):
        own = transform.FREE_TRANSFORM.replace('value="Bicubic"', 'value="Lanczos3"')
        self.h.doc.own_xml = own.split('\n', 1)[1]
        layer = self.agent_layer()
        region_tests.run(self.h, 'transform_layer', {'layer_id': layer.id, 'scale': [2, 0.5], 'pivot': [0, 0]}, 'stretch')
        mask, = layer.childNodes()
        self.assertIn('Lanczos3', mask.xml, "Krita's other settings are kept")
        self.assertEqual((values(mask.xml)['original'], values(mask.xml)['scale']), ((0, 0), (2, 0.5)))

    def test_a_negative_scale_flips_for_a_reflection(self):
        layer = self.agent_layer()
        region_tests.run(self.h, 'transform_layer', {'layer_id': layer.id, 'scale': [1, -1], 'move': [0, 3]}, 'reflect')
        mask, = layer.childNodes()
        self.assertEqual(values(mask.xml)['scale'], (1, -1))
        for scale in (0.01, -0.01, [1, -0.001], -60):
            with self.assertRaisesRegex(ValueError, 'scale must be between'):
                region_tests.run(self.h, 'transform_layer', {'layer_id': layer.id, 'scale': scale}, 'tiny')

    def test_refusals_change_nothing(self):
        layer = self.agent_layer()
        figure = self.artist_layer()
        for params, message in (({'layer_id': figure.id, 'move': [1, 1]}, 'never moved'),
                                ({'layer_id': layer.id}, 'move, scale or rotate'),
                                ({'layer_id': layer.id, 'scale': 0}, 'scale must be between'),
                                ({'layer_id': layer.id, 'move': [1]}, r'move must be \[x, y\]'),
                                ({'layer_id': layer.id, 'rotate': 720}, 'rotate must be between')):
            with self.assertRaisesRegex(ValueError, message):
                region_tests.run(self.h, 'transform_layer', params, 'bad')
        self.assertEqual((layer.childNodes(), figure.childNodes()), ([], []))


if __name__ == '__main__':
    unittest.main()

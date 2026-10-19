"""make_material and stamp, the native operations (material_stamp.py), on the 4x4 fake painting of the protection
tests with the real material_raster. Materials go to a temporary study folder that is removed."""
import base64
import json
import os
import sys
import unittest
import test_protection as protection_tests
import test_material_raster as raster_tests

region_tests = protection_tests.region_tests
native = protection_tests.native
qt = raster_tests.qt_compat
DISC = [{'shape': 'rectangle', 'bounds': [0, 0, 4, 4]}]


def disc_png(size=64):
    """A white disc on transparency, as an asset cut-out would be."""
    image = qt.QImage(size, size, qt.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(qt.Qt.GlobalColor.transparent)
    painter = qt.QPainter(image)
    painter.setBrush(qt.QColor(255, 255, 255)); painter.setPen(qt.QColor(255, 255, 255))
    painter.drawEllipse(4, 4, size - 8, size - 8); painter.end()
    buffer = qt.QtCore.QBuffer(); buffer.open(qt.QtCore.QIODevice.OpenModeFlag.WriteOnly); image.save(buffer, 'PNG')
    return base64.b64encode(bytes(buffer.data())).decode()


class MaterialSetup(protection_tests.ProtectionSetup):
    def setUp(self):
        super().setUp()
        name = 'creative_test_package.material_raster'
        prior = sys.modules.get(name)
        sys.modules[name] = raster_tests.raster; native.package.material_raster = raster_tests.raster
        self.addCleanup(lambda: sys.modules.__setitem__(name, prior) if prior else sys.modules.pop(name, None))
        self.background = self.artist_layer('Sky')
        self.background.pixels = bytearray(bytes([150, 90, 40, 255]) * 16)    # opaque blue sky, BGRA

    def make(self, **extra):
        params = dict({'name': 'Disc', 'kind': 'shape', 'size': 64, 'source': {'image_base64': disc_png()}}, **extra)
        return region_tests.run(self.h, 'make_material', params)

    def dab(self, **extra):
        return dict({'x': 1.5, 'y': 1.5, 'scale': 0.08, 'stretch': 1, 'rotation': 0, 'opacity': 1, 'tip': 0}, **extra)

    def stamp(self, identifier='stamp', **extra):
        params = dict({'name': 'Clouds', 'material': 'Disc', 'area': DISC, 'dabs': [self.dab()], 'stage_id': 's'}, **extra)
        return region_tests.run(self.h, 'stamp', params, identifier)

    def stamped(self, result):
        return self.h._creative_node(self.h.doc, result['layer_id'])


class MakeMaterialTests(MaterialSetup, unittest.TestCase):
    def test_a_material_is_saved_with_the_chat_and_changes_nothing_on_the_canvas(self):
        before = (self.h.doc.pixelData(0, 0, 4, 4), len(self.h.doc.root.children))
        result = self.make()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual((result['material'], result['kind'], result['tips'], result['size']), ('Disc', 'shape', 1, 64))
        folder = os.path.dirname(result['sheet_path'])
        self.assertTrue(os.path.isfile(result['sheet_path']))
        self.assertEqual(json.load(open(os.path.join(folder, 'material.json')))['tips'], 1)
        self.assertNotIn('image_path', result, 'the sheet is not the canvas view')
        self.assertEqual((self.h.doc.pixelData(0, 0, 4, 4), len(self.h.doc.root.children)), before)
        self.assertEqual(self.h._creative_session['passes'], [], 'not a pass')

    def test_light_tips_from_the_painting_avoid_protected_areas(self):
        self.keep('Moon', (2, 0, 2, 2))
        seen = {}
        real = raster_tests.raster.light_tips
        def spy(*args, **kw):
            seen.update(kw); return real(*args, **kw)
        raster_tests.raster.light_tips = spy
        self.addCleanup(setattr, raster_tests.raster, 'light_tips', real)
        self.background.pixels[0:4] = bytes([255, 255, 255, 255])                       # one bright pixel of light
        try:
            self.make(name='Sky light', kind='light', source={'area': DISC})
        except ValueError as refused:                                                   # 4x4 may hold too little light
            self.assertIn('No light', str(refused))
        self.assertEqual(seen['avoid'], [(2, 0, 2, 2)], 'the protected Moon, in source coordinates')

    def test_any_readable_name_up_to_40_characters(self):
        # Run 7: the painter named it "Cloud tips — cut from the painting" and the ASCII-only rule refused it.
        self.assertEqual(self.make(name='Cloud tips — cut from the painting')['material'], 'Cloud tips — cut from the painting')
        for bad in ('', 'x' * 41, 'tab\there'):
            with self.assertRaisesRegex(ValueError, 'name'):
                self.make(name=bad)

    def test_refusals(self):
        for params, message in (({'kind': 'glitter'}, 'kind'), ({'count': 9}, 'count'), ({'size': 8}, 'size'),
                                ({'source': {}}, 'source'), ({'name': ' '}, 'name')):
            with self.assertRaisesRegex(ValueError, message):
                self.make(**params)
        with self.assertRaisesRegex(ValueError, 'No light'):
            self.make(name='Flat', kind='light', source={'area': DISC})                  # a flat sky has no light to cut


class StampTests(MaterialSetup, unittest.TestCase):
    def setUp(self):
        super().setUp(); self.make()

    def test_a_stamp_is_one_pass_on_one_new_layer_inside_its_area(self):
        result = self.stamp(area=[{'shape': 'rectangle', 'bounds': [0, 0, 2, 4]}], dabs=[self.dab(x=1, y=2, scale=0.1)])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['dabs_placed'], 1)
        layer, fresh = self.stamped(result), region_tests.Layer(self.h.doc, 'fresh', 'paintlayer').pixels
        outside = lambda pixels: [bytes(pixels[(y * 4 + x) * 4:(y * 4 + x) * 4 + 4]) for y in range(4) for x in range(2, 4)]
        self.assertTrue(any(layer.pixels[(y * 4 + x) * 4 + 3] for y in range(4) for x in range(2)))
        self.assertEqual(outside(layer.pixels), outside(fresh), 'nothing written outside the area')
        self.assertEqual([p['layer_id'] for p in self.h._creative_session['passes']], [result['layer_id']])

    def test_a_heavy_stamp_is_thinned_to_the_coverage_cap_and_says_so(self):
        # 1400 dabs at 0.22-0.42 laid a pale veil over the whole sky (Luna: texture over forms, flat block).
        heavy = self.stamp(dabs=[self.dab(x=x + 0.5, y=y + 0.5) for x in range(4) for y in range(4)])
        self.assertEqual(heavy['status'], 'ok', heavy.get('error'))
        self.assertLess(heavy['opacity_scaled'], 1)
        self.assertAlmostEqual(heavy['coverage'], native.package.material_stamp.MAX_COVERAGE, places=2)
        light = self.stamp('light', dabs=[self.dab(opacity=0.01, scale=0.02)])
        self.assertNotIn('opacity_scaled', light)
        self.assertLess(light['coverage'], native.package.material_stamp.MAX_COVERAGE)

    def test_dabs_that_all_miss_the_area_make_no_layer(self):
        layers = len(self.h.doc.root.children)
        result = self.stamp(area=[{'shape': 'rectangle', 'bounds': [0, 0, 1, 1]}], dabs=[self.dab(x=3.5, y=3.5)])
        self.assertEqual(result['error_code'], 'validation_rejected')
        self.assertEqual(len(self.h.doc.root.children), layers)

    def test_protection_erases_the_stamp_inside_a_kept_area(self):
        self.keep('Moon', (0, 0, 2, 2)); before = self.inside()
        result = self.stamp(dabs=[self.dab(x=x + 0.5, y=y + 0.5) for x in range(4) for y in range(4)])
        self.assertEqual(result['protected'][0]['name'], 'Moon')
        self.assertEqual(self.inside(), before)

    def test_refusals(self):
        for extra, message in (({'material': 'Nope'}, 'No material'), ({'dabs': []}, 'dabs'),
                               ({'dabs': [self.dab()] * 2001}, '2000'), ({'dabs': [self.dab(tip=3)]}, 'tip'),
                               ({'dabs': [self.dab(opacity=2)]}, 'opacity'), ({'tint': {'color': '#ffffff', 'amount': 2}}, 'amount'),
                               ({'area': None}, 'area')):
            params = dict({'name': 'Clouds', 'material': 'Disc', 'area': DISC, 'dabs': [self.dab()], 'stage_id': 's'}, **extra)
            if params['area'] is None: params.pop('area')
            with self.assertRaisesRegex(ValueError, message):
                region_tests.run(self.h, 'stamp', params, 'bad-' + message)
        self.assertEqual(self.h._creative_session['passes'], [])


if __name__ == '__main__':
    unittest.main()

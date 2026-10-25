# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""texture (texture_craft.py), the architecture texture pass: the parts' found areas get the material's detail in their
luminance only, baked into one layer "Texture: <part>" in the move's group, as one pass the move's Undo hides; anything
wrong is refused before anything changes. The pixel layer tree of the finish tests, the real texture_raster (real Qt),
small synthetic textures; files in a temporary folder."""
import base64
import os
import sys
import types
import unittest

import numpy as np
import test_finish_pass as finish_tests
import test_texture_raster as raster_tests
from test_element_shapes import png

region_tests = finish_tests.region_tests


def b64(data):
    return base64.b64encode(data).decode()


class TextureTests(finish_tests.FinishOperationTests):
    def setUp(self):
        super().setUp()
        name = 'creative_test_package.texture_raster'
        prior, package = sys.modules.get(name), sys.modules['creative_test_package']
        attribute = getattr(package, 'texture_raster', None)
        sys.modules[name] = package.texture_raster = raster_tests.raster
        self.addCleanup(lambda: sys.modules.__setitem__(name, prior) if prior else sys.modules.pop(name, None))
        self.addCleanup(lambda: setattr(package, 'texture_raster', attribute) if attribute else delattr(package, 'texture_raster'))
        brick = raster_tests.jpeg(raster_tests.bricks(128, 64, 8))
        self.materials = {'Bricks085': {'color': b64(brick), 'displacement': b64(brick)}}

    def shape(self, name, box):
        """A found area: a mask file in the chat folder's .shapes, white over `box` [x, y, w, h] of a 600 x 400 canvas."""
        folder = os.path.join(self.h._creative_session['output'], '.shapes')
        os.makedirs(folder, exist_ok=True)
        x, y, w, h = box
        path = os.path.join(folder, 'found-%s.png' % name)
        with open(path, 'wb') as stream:
            stream.write(png(w, h, [bytes([255]) * w for _ in range(h)]))
        return {'mask_path': path, 'bounds': [x, y, w, h]}

    def part(self, box, **extra):
        return dict({'name': 'church', 'inside_shape': self.shape('church', box), 'materials': [{'id': 'Bricks085', 'weight': 1}],
                     'tile_px': {'near': 60, 'far': 60}, 'direction_deg': 0, 'vanishing': None, 'strength': 0.3, 'blend': 'overlay'}, **extra)

    def texture(self, parts, identifier='t1', **extra):
        params = dict({'name': 'Texture: church', 'stage_id': 'move-1', 'materials': self.materials, 'parts': parts}, **extra)
        return region_tests.run(self.h, 'texture', params, identifier)

    def stage(self):
        return self.h.doc.root.childNodes()[1]

    def test_one_layer_in_the_moves_group_detail_in_luminance_only_inside_the_area(self):
        before = self.shown()
        result = self.texture([self.part([100, 50, 300, 250])])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual([c.label for c in self.stage().childNodes()], ['Texture: church'])
        layer = self.stage().childNodes()[0]
        self.assertEqual(layer.blend, 'normal')
        after = self.shown()
        change = after - before
        self.assertEqual(float(np.abs(change[:50]).max()) + float(np.abs(change[:, :100]).max()), 0, 'nothing outside the area')
        inside = change[80:270, 130:370, :3]
        self.assertGreater(float(np.abs(inside).max()), 3, 'detail inside')
        spread = np.abs(inside - inside.mean(axis=2, keepdims=True)).max()
        self.assertLessEqual(float(spread), 2, 'the same change on every channel: hue and chroma kept')
        self.assertLess(abs(float(inside.mean())), 2, 'no overall darkening or lightening')
        entry = next(p for p in self.h._creative_session['passes'] if p['id'] == 't1')
        self.assertEqual((entry['kind'], entry['stage_id'], entry['title']), ('texture', 'move-1', 'Texture: church'))
        self.assertEqual(result['texture']['parts'][0]['name'], 'church')
        # Redo undoes it with the step: the move's Undo hides the layer, the painting as before.
        undone = region_tests.run(self.h, 'review_pass', {'pass_id': 'stage:move-1', 'action': 'reject'}, 'undo')
        self.assertEqual(undone['status'], 'ok', undone.get('error'))
        self.assertLessEqual(float(np.abs(self.shown() - before).max()), 1)

    def test_two_parts_two_materials_still_one_layer(self):
        stone = raster_tests.jpeg(np.random.default_rng(5).integers(60, 200, (64, 64)).astype(np.float32))
        self.materials['Tiles130'] = {'color': b64(stone), 'displacement': b64(stone), 'detail_from': ['displacement']}
        street = dict(self.part([0, 300, 600, 100]), name='street', inside_shape=self.shape('street', [0, 300, 600, 100]),
                      materials=[{'id': 'Tiles130', 'weight': 0.7}, {'id': 'Bricks085', 'weight': 0.3}], tile_px={'near': 120, 'far': 40},
                      direction_deg=-90, blend='soft_light')
        result = self.texture([self.part([100, 50, 300, 200]), street])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(len(self.stage().childNodes()), 1)
        self.assertEqual([p['name'] for p in result['texture']['parts']], ['church', 'street'])
        layer = self.stage().childNodes()[0]
        self.assertGreater(int(layer.data[350, 300, 3]), 200)
        self.assertEqual(int(layer.data[270:300, :, 3].max()), 0, 'between the parts: nothing')

    def test_anything_wrong_is_refused_before_anything_changes(self):
        layers = len(self.stage().childNodes()) if len(self.h.doc.root.childNodes()) > 1 else 0
        cases = [
            ([self.part([0, 0, 100, 100], materials=[{'id': 'Nope', 'weight': 1}])], {}, 'material'),
            ([self.part([0, 0, 100, 100], strength=0.9)], {}, 'strength'),
            ([self.part([0, 0, 100, 100], blend='multiply')], {}, 'blend'),
            ([self.part([0, 0, 100, 100], tile_px={'near': 2, 'far': 2})], {}, 'tile'),
            ([self.part([0, 0, 100, 100], inside_shape={'mask_path': '/etc/hosts.png', 'bounds': [0, 0, 10, 10]})], {}, 'chat folder'),
            ([], {}, 'parts'),
            ([self.part([0, 0, 100, 100])], {'materials': {'Bricks085': {'color': 'not base64!', 'displacement': 'x'}}}, 'map'),
        ]
        for i, (parts, extra, message) in enumerate(cases):
            with self.assertRaisesRegex(ValueError, message):
                self.texture(parts, 'bad%d' % i, **extra)
        self.assertEqual(len(self.h.doc.root.childNodes()), 1 if not layers else 2, 'no layer was added')


class PatternTests(TextureTests):
    """Goal 6: the library's materials as Krita patterns, and the Finish's form strokes carrying one as grain in a part."""
    def setUp(self):
        super().setUp()
        import krita
        import test_texture_patterns as pattern_tests
        name = 'creative_test_package.texture_patterns'
        prior, package = sys.modules.get(name), sys.modules['creative_test_package']
        attribute = getattr(package, 'texture_patterns', None)
        sys.modules[name] = package.texture_patterns = pattern_tests.patterns     # `from . import` reads the package first
        pattern_tests.patterns.REGISTERED.clear()
        self.addCleanup(lambda: sys.modules.__setitem__(name, prior) if prior else sys.modules.pop(name, None))
        self.addCleanup(lambda: setattr(package, 'texture_patterns', attribute) if attribute else delattr(package, 'texture_patterns'))
        self.app = pattern_tests.FakeKrita()
        before = krita.Krita
        krita.Krita = types.SimpleNamespace(instance=lambda: self.app)
        self.addCleanup(lambda: setattr(krita, 'Krita', before))

    def test_the_texture_pass_and_register_patterns_make_texture_patterns(self):
        result = self.texture([self.part([100, 50, 300, 250])])
        self.assertEqual(result['patterns'], {'Bricks085': 'Texture: Bricks085'})
        registered = region_tests.run(self.h, 'register_patterns', {'materials': self.materials})
        self.assertEqual(registered, {'status': 'ok', 'patterns': {'Bricks085': 'Texture: Bricks085'}})
        self.assertEqual(self.app.calls, ['Texture: Bricks085'], 'registered once a session')

    def test_form_strokes_carry_the_grain_inside_the_part_only(self):
        region_tests.run(self.h, 'register_patterns', {'materials': self.materials})
        plain = self.run_finish('plain', box=[0, 0, 600, 400])
        self.assertEqual(plain['status'], 'ok', plain.get('error'))
        group = self.h._creative_node(self.h.doc, plain['layer_id'])
        smooth = next(c for c in group.childNodes() if c.label.endswith('strokes')).data[..., 3].astype(int)
        review = region_tests.run(self.h, 'review_pass', {'pass_id': 'plain', 'action': 'reject'}, 'undo-plain')
        self.assertEqual(review['status'], 'ok', review.get('error'))
        grain = [{'pattern': 'Texture: Bricks085', 'inside_shape': self.shape('church', [300, 0, 300, 400]), 'tile_px': 40, 'strength': 0.4}]
        grained = self.run_finish('grained', box=[0, 0, 600, 400], grain=grain)
        self.assertEqual(grained['status'], 'ok', grained.get('error'))
        self.assertEqual(grained['finish']['grain_parts'], 1)
        group = self.h._creative_node(self.h.doc, grained['layer_id'])
        rough = next(c for c in group.childNodes() if c.label.endswith('strokes')).data[..., 3].astype(int)
        self.assertTrue((rough[:, :300] == smooth[:, :300]).all(), 'outside the part: the same strokes')
        self.assertLess(rough[:, 300:].sum(), smooth[:, 300:].sum(), 'inside: thinned by the pattern')
        with self.assertRaisesRegex(ValueError, 'pattern'):
            self.run_finish('bad', box=[0, 0, 600, 400], grain=[dict(grain[0], pattern='Texture: Nope')])
        with self.assertRaisesRegex(ValueError, 'strength'):
            self.run_finish('bad2', box=[0, 0, 600, 400], grain=[dict(grain[0], strength=0.9)])


def load_tests(loader, tests, pattern):
    """Only this file's tests, without running the finish tests again here."""
    return unittest.TestSuite([TextureTests(name) for name in sorted(vars(TextureTests)) if name.startswith('test_')]
                              + [PatternTests(name) for name in sorted(vars(PatternTests)) if name.startswith('test_')])


if __name__ == '__main__':
    unittest.main()

# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Textured brushes (texture_patterns.py, architecture-texture goal 6): the library's materials registered as Krita
patterns through the fork's Krita.createPattern (stubbed here), and the grain a pattern gives the Finish's form strokes
inside an architectural part: their alpha thinned where the pattern is low, never outside the part. Real Qt, small
synthetic maps; writes no files."""
import types
import unittest

import numpy as np
import test_texture_raster as raster_tests

qt = raster_tests.qt


def load():
    import importlib
    return importlib.import_module('texture_test_package.texture_patterns')


patterns = load()


class FakePattern:
    def __init__(self, name, image, filename=''): self.label, self.picture, self.file = name, image, filename or name + '.pat'
    def name(self): return self.label
    def filename(self): return self.file
    def image(self): return self.picture


class FakeKrita:
    """Krita.createPattern as the fork documents it: replaces the agent's own pattern of that name; resources lists them."""
    def __init__(self): self.made, self.calls = {}, []
    def createPattern(self, image, name):
        self.calls.append(name)
        if image.isNull() or not name: return None
        self.made[name] = FakePattern(name, image.copy()); return self.made[name]
    def resources(self, kind): return dict(self.made) if kind == 'pattern' else {}


def maps():
    brick = raster_tests.bricks(128, 64, 8)
    return {'color': brick, 'displacement': brick}


class RegisterTests(unittest.TestCase):
    def setUp(self):
        patterns.REGISTERED.clear()

    def test_each_material_becomes_a_pattern_once(self):
        app = FakeKrita()
        names = patterns.register(app, {'Bricks085': (maps(), None)})
        self.assertEqual(names, {'Bricks085': 'Texture: Bricks085'})
        image = app.made['Texture: Bricks085'].image()
        self.assertEqual((image.width(), image.height()), (128, 64))
        patterns.register(app, {'Bricks085': (maps(), None)})
        self.assertEqual(app.calls, ['Texture: Bricks085'], 'the same maps are not registered again')

    def test_without_create_pattern_nothing_is_registered(self):
        self.assertEqual(patterns.register(object(), {'Bricks085': (maps(), None)}), {})

    def test_a_pattern_reads_back_as_a_height_map(self):
        app = FakeKrita()
        patterns.register(app, {'Bricks085': (maps(), None)})
        height = patterns.pattern_height(app, 'Texture: Bricks085')
        self.assertEqual(height.shape, (64, 128))
        self.assertTrue(0 <= height.min() and height.max() <= 1)
        self.assertLess(height[0].mean(), height[4].mean(), 'the mortar is low, the brick high')
        with self.assertRaisesRegex(ValueError, 'pattern'):
            patterns.pattern_height(app, 'Texture: Nope')


class BrushPatternTests(unittest.TestCase):
    def test_set_brush_texture_registers_the_file_itself_no_manual_import(self):
        app = FakeKrita()
        image = qt.QImage(8, 8, qt.QImage.Format.Format_Grayscale8); image.fill(128)
        made = patterns.brush_pattern(app, image, '/textures/stone_height.png')
        self.assertEqual(made.name(), 'Texture: stone_height')
        app.made['imported'] = FakePattern('imported', image, '/res/patterns/stone_height.png')
        del app.made['Texture: stone_height']
        self.assertEqual(patterns.brush_pattern(app, image, '/textures/stone_height.png').name(), 'imported', 'an imported one is used')

    def test_stock_krita_still_asks_for_the_import(self):
        stock = types.SimpleNamespace(resources=lambda kind: {})
        self.assertIn('Import this file', patterns.brush_pattern(stock, None, '/t/x.png')['error'])


class GrainTests(unittest.TestCase):
    def test_grain_thins_the_strokes_alpha_inside_the_part_only(self):
        strokes = np.zeros((40, 80, 4), np.uint8); strokes[..., 2] = 200; strokes[..., 3] = 255
        mask = np.zeros((40, 40), np.uint8); mask[:, :] = 255                     # the part: the right half of the tile
        height = np.tile(np.linspace(0, 1, 16, dtype=np.float32), (16, 1))
        out = patterns.apply_grain(strokes.copy(), (100, 200, 80, 40), [(mask, (140, 200, 40, 40), height, 16.0, 0.4)])
        self.assertTrue((out[:, :40, 3] == 255).all(), 'outside the part: untouched')
        inside = out[:, 40:, 3].astype(int)
        self.assertGreaterEqual(int(inside.min()), round(255 * 0.6) - 1)
        self.assertLess(int(inside.min()), 250, 'low places of the pattern thin the paint')
        self.assertTrue((out[..., :3] == strokes[..., :3]).all(), 'the colour stays the strokes’ own')


if __name__ == '__main__':
    unittest.main()

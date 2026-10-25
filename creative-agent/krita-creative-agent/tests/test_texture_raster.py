"""The architecture texture pass as pixels (texture_raster.py), on small synthetic textures and canvases with real Qt (PyQt5
or PyQt6, qt_compat.py picks the binding) and numpy. Writes no files."""
import importlib
import pathlib
import sys
import types
import unittest

import numpy as np

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'


def load_with_real_qt():
    """test_native.py replaces PyQt5 with stubs in this process: load under a package name of our own with the real binding."""
    stubs = {name: sys.modules.pop(name) for name in list(sys.modules) if name == 'PyQt5' or name.startswith('PyQt5.')}
    try:
        package = types.ModuleType('texture_test_package'); package.__path__ = [str(PLUGIN)]
        sys.modules['texture_test_package'] = package
        qt = importlib.import_module('texture_test_package.qt_compat')
        return qt, importlib.import_module('texture_test_package.texture_raster')
    finally:
        sys.modules.update(stubs)


qt, raster = load_with_real_qt()


def jpeg(grey):
    """A greyscale numpy image as JPEG bytes (what a library map is)."""
    h, w = grey.shape
    data = np.ascontiguousarray(np.clip(grey, 0, 255).astype(np.uint8))
    image = qt.QImage(data.tobytes(), w, h, w, qt.QImage.Format.Format_Grayscale8).copy()
    buffer = qt.QBuffer(); buffer.open(qt.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'JPG', 95)
    return bytes(buffer.data())


def bricks(w=128, h=64, courses=8):
    """A tileable brick-like map: light bricks, dark mortar lines every course, joints offset each course."""
    y, x = np.mgrid[0:h, 0:w]
    course = h // courses
    mortar = (y % course) < 2
    joint = ((x + (y // course % 2) * (w // 8)) % (w // 4)) < 2
    return np.where(mortar | joint, 60, 190).astype(np.float32)


def canvas(w, h, colour=(40, 110, 200)):
    """BGRA uint8, one colour (B, G, R)."""
    out = np.zeros((h, w, 4), np.uint8)
    out[..., 0], out[..., 1], out[..., 2], out[..., 3] = colour[0], colour[1], colour[2], 255
    return out


class DetailTest(unittest.TestCase):
    def test_detail_is_zero_mean_unit_spread_and_keeps_the_courses(self):
        maps = {'color': raster.decode_grey(jpeg(bricks())), 'displacement': raster.decode_grey(jpeg(bricks()))}
        tile = raster.detail_tile(maps)
        self.assertEqual(tile.shape, (64, 128))
        self.assertAlmostEqual(float(tile.mean()), 0.0, places=3)
        self.assertAlmostEqual(float(tile.std()), 1.0, places=1)
        rows = tile.mean(axis=1)
        self.assertLess(rows[0], rows[4])                         # the mortar line is darker than the brick

    def test_detail_from_only_the_named_maps(self):
        flat = np.full((32, 32), 128, np.float32)
        maps = {'color': raster.decode_grey(jpeg(bricks(32, 32, 4))), 'displacement': flat}
        tile = raster.detail_tile(maps, detail_from=['displacement'])
        self.assertLess(float(np.abs(tile).max()), 1e-3)          # a flat displacement: no detail, whatever the colour shows

    def test_a_pyramid_halves_down(self):
        levels = raster.pyramid(np.random.default_rng(1).standard_normal((64, 128)).astype(np.float32))
        self.assertEqual([lv.shape for lv in levels][:3], [(64, 128), (32, 64), (16, 32)])


class PerspectiveTest(unittest.TestCase):
    def grid(self, w, h):
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        return x, y

    def test_front_on_is_an_even_grid(self):
        x, y = self.grid(200, 100)
        u, v, scale = raster.perspective(x, y, near=50, far=50, direction_deg=0, vanishing=None, bounds=(0, 0, 200, 100))
        self.assertTrue(np.allclose(scale, 50))
        self.assertAlmostEqual(float(u[0, 100] - u[0, 0]), 2.0, places=4)       # along the courses: 100 px is two tiles
        self.assertAlmostEqual(float(v[50, 0] - v[0, 0]), 1.0, places=4)

    def test_receding_ground_gets_smaller_toward_the_far_side(self):
        x, y = self.grid(100, 200)
        _u, _v, scale = raster.perspective(x, y, near=80, far=20, direction_deg=-90, vanishing=None, bounds=(0, 0, 100, 200))
        self.assertAlmostEqual(float(scale[199, 50]), 80, delta=2)              # the near side is the bottom (direction up)
        self.assertAlmostEqual(float(scale[0, 50]), 20, delta=2)

    def test_courses_converge_on_the_vanishing_point(self):
        x, y = self.grid(200, 100)
        u, v, _scale = raster.perspective(x, y, near=40, far=40, direction_deg=0, vanishing=(600, 50), bounds=(0, 0, 200, 100))
        # Along the line through the vanishing point at the middle row the across coordinate does not change;
        # the line from (0, 0) toward the vanishing point keeps its across coordinate too.
        self.assertAlmostEqual(float(v[50, 0]), float(v[50, 199]), places=3)
        t = 150 / 600
        self.assertAlmostEqual(float(v[0, 0]), float(v[int(round(50 * t)), 150]), delta=0.05)


class ApplyTest(unittest.TestCase):
    def test_luminance_only_never_the_colour(self):
        base = canvas(64, 64, colour=(40, 110, 200))
        detail = np.random.default_rng(2).standard_normal((64, 64)).astype(np.float32)
        alpha = np.ones((64, 64), np.float32)
        for blend in ('soft_light', 'overlay'):
            out = raster.apply_detail(base, detail, alpha, strength=0.3, blend=blend)
            b, g, r = (out[..., i].astype(int) - base[..., i].astype(int) for i in range(3))
            self.assertTrue(np.array_equal(b, g) and np.array_equal(g, r), blend)   # the same change on every channel
            self.assertGreater(int(np.abs(r).max()), 3)
            self.assertLess(abs(float(r.mean())), 1.5)                            # no overall darkening or lightening
            self.assertTrue((out[..., 3] == 255).all())

    def test_strength_scales_the_change(self):
        base = canvas(32, 32, colour=(128, 128, 128))
        detail = np.random.default_rng(3).standard_normal((32, 32)).astype(np.float32)
        alpha = np.ones((32, 32), np.float32)
        weak = raster.apply_detail(base, detail, alpha, 0.1, 'overlay')[..., 0].astype(int) - 128
        strong = raster.apply_detail(base, detail, alpha, 0.3, 'overlay')[..., 0].astype(int) - 128
        self.assertGreater(np.abs(strong).mean(), 2 * np.abs(weak).mean())

    def test_feather_stays_inside_and_fades_at_the_edge(self):
        mask = np.zeros((60, 60), np.uint8); mask[10:50, 10:50] = 255
        alpha = raster.feather(mask, 4)
        self.assertEqual(float(alpha[5, 30]), 0.0)                     # outside: nothing
        self.assertEqual(float(alpha[:10].max()), 0.0)
        self.assertAlmostEqual(float(alpha[30, 30]), 1.0, places=3)     # deep inside: all
        self.assertTrue(0 < alpha[11, 30] < 1)                          # at the edge: a soft fade


class PartTest(unittest.TestCase):
    def material(self):
        return raster.detail_tile({'color': raster.decode_grey(jpeg(bricks())), 'displacement': raster.decode_grey(jpeg(bricks()))})

    def test_a_part_is_textured_inside_its_mask_only(self):
        base = canvas(160, 120)
        mask = np.zeros((120, 160), np.uint8); mask[20:100, 30:130] = 255
        part = dict(materials=[(raster.pyramid(self.material()), 1.0)], tile_near=40, tile_far=40, direction_deg=0, vanishing=None,
                    strength=0.25, blend='soft_light', seed=7)
        layer = raster.texture_part(base, mask, (0, 0, 160, 120), part)
        self.assertEqual(layer.shape, (120, 160, 4))
        self.assertEqual(int(layer[..., 3][:20].max()), 0)
        self.assertEqual(int(layer[..., 3][:, :30].max()), 0)
        self.assertGreater(int(layer[60, 80, 3]), 250)
        inside = layer[30:90, 40:120, 2].astype(int)
        self.assertGreater(inside.std(), 1.0)                          # detail is there

    def test_no_visible_tiling_two_tiles_apart_differ(self):
        size = 256
        base = canvas(size * 2, size, colour=(128, 128, 128))
        mask = np.full((size, size * 2), 255, np.uint8)
        noise = np.random.default_rng(4).standard_normal((64, 64)).astype(np.float32)
        noise -= noise.mean(); noise /= noise.std()
        part = dict(materials=[(raster.pyramid(noise), 1.0)], tile_near=64, tile_far=64, direction_deg=0, vanishing=None,
                    strength=0.3, blend='overlay', seed=1)
        lum = raster.texture_part(base, mask, (0, 0, size * 2, size), part)[..., 2].astype(np.float32)
        a, b = lum[64:192, 64:192], lum[64:192, 64 + 128:192 + 128]     # exactly two tiles apart
        correlation = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
        self.assertLess(correlation, 0.9)                              # a plain repeat would be 1.0


if __name__ == '__main__':
    unittest.main()

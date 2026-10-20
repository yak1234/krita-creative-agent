"""Material tips and stamping (material_raster.py) with real Qt on small synthetic images, under PyQt5 or PyQt6
(qt_compat.py picks the binding). Writes no files."""
import importlib
import math
import pathlib
import sys
import types
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'


def load_with_real_qt():
    """test_native.py replaces PyQt5 with stubs in this process. Load qt_compat and material_raster under their own
    package name with the real binding in place, then put the stubs back: the modules keep the real Qt classes."""
    stubs = {name: sys.modules.pop(name) for name in list(sys.modules) if name == 'PyQt5' or name.startswith('PyQt5.')}
    try:
        package = types.ModuleType('material_test_package'); package.__path__ = [str(PLUGIN)]
        sys.modules['material_test_package'] = package
        return (importlib.import_module('material_test_package.qt_compat'),
                importlib.import_module('material_test_package.material_raster'))
    finally:
        sys.modules.update(stubs)


qt_compat, raster = load_with_real_qt()


def sky(w, h, blobs, background=(90, 40, 20)):
    """BGRA, a dark blue sky with soft bright cloud blobs [(x, y, radius)]."""
    out = bytearray()
    for y in range(h):
        for x in range(w):
            light = sum(max(0.0, 1 - math.hypot(x - bx, y - by) / r) for bx, by, r in blobs)
            v = min(1.0, light)
            out += bytes([int(background[0] + (230 - background[0]) * v), int(background[1] + (220 - background[1]) * v),
                          int(background[2] + (210 - background[2]) * v), 255])
    return bytes(out)


def pixel(bgra, w, x, y):
    i = (y * w + x) * 4
    return tuple(bgra[i:i + 4])


def inside(rect, point):
    x, y, w, h = rect
    return x <= point[0] < x + w and y <= point[1] < y + h


class QtCompatTests(unittest.TestCase):
    def test_one_binding_with_scoped_names(self):
        self.assertIn(qt_compat.QtCore.__name__.split('.')[0], ('PyQt5', 'PyQt6'))
        self.assertEqual(qt_compat.QT6, qt_compat.QtCore.__name__.startswith('PyQt6'))
        for name in (qt_compat.Qt.TransformationMode.SmoothTransformation, qt_compat.QImage.Format.Format_Alpha8,
                     qt_compat.QPainter.CompositionMode.CompositionMode_DestinationIn):
            self.assertIsNotNone(name)


class TipTests(unittest.TestCase):
    W, H = 240, 120
    BLOBS = [(50, 40, 30), (130, 70, 34), (200, 45, 26)]

    def test_light_tips_come_from_the_clouds_soft_and_round(self):
        tips = raster.light_tips(sky(self.W, self.H, self.BLOBS), self.W, self.H, count=3, size=48)
        self.assertEqual(len(tips), 3)
        for data, rect in tips:
            self.assertEqual(len(data), 48 * 48)
            self.assertEqual(rect[2:], (48, 48))
            self.assertTrue(any(inside(rect, b[:2]) for b in self.BLOBS), rect)
            self.assertEqual(max(data), 255, 'normalised to its own peak')
            self.assertEqual((data[0], data[47], data[-48], data[-1]), (0, 0, 0, 0), 'a round falloff: corners are clear')

    def test_tips_are_never_cut_from_an_avoided_area_or_outside_the_mask(self):
        avoid = [(100, 30, 70, 80)]                                              # the middle blob, like the moon
        tips = raster.light_tips(sky(self.W, self.H, self.BLOBS), self.W, self.H, count=3, size=48, avoid=avoid)
        for _data, (x, y, w, h) in tips:
            self.assertTrue(x + w <= 100 or x >= 170 or y + h <= 30, (x, y))
        left = bytes([255 if x < self.W // 2 else 0 for _y in range(self.H) for x in range(self.W)])
        for _data, (x, _y, w, _h) in raster.light_tips(sky(self.W, self.H, self.BLOBS), self.W, self.H, count=2, size=40, mask=left):
            self.assertLessEqual(x + w, self.W // 2 + 4)

    def test_snowflake_holes_in_the_mask_leave_no_hard_holes_in_a_tip(self):
        # A seeded sky selection skips every snowflake: small holes. Cut from it, a tip had hard round holes that
        # stamped as "pasted ellipses". A large unselected area (a building) still stays out of the tip.
        w, h, flakes = 160, 120, [(60, 50), (72, 62), (54, 70), (80, 45), (66, 40)]
        mask = bytearray(255 for _ in range(w * h))
        for y in range(h):
            for x in range(w):
                if any(math.hypot(x - fx, y - fy) < 2.5 for fx, fy in flakes) or x >= 110:
                    mask[y * w + x] = 0
        source = sky(w, h, [(66, 55, 40)])
        data, (rx, ry, size, _) = raster.light_tips(source, w, h, count=1, size=48, mask=bytes(mask))[0]
        unflaked = bytes(255 if x < 110 else 0 for _y in range(h) for x in range(w))
        clean, rect = raster.light_tips(source, w, h, count=1, size=48, mask=unflaked)[0]
        self.assertEqual(rect, (rx, ry, size, size))
        at = lambda x, y: data[(y - ry) * size + (x - rx)]
        inside_tip = [(fx, fy) for fx, fy in flakes if rx <= fx < rx + size and ry <= fy < ry + size]
        self.assertTrue(inside_tip)
        for fx, fy in inside_tip:
            self.assertLessEqual(abs(at(fx, fy) - clean[(fy - ry) * size + (fx - rx)]), 8, ('a hard hole at', fx, fy))
        building = [at(x, y) for y in range(ry, ry + size) for x in range(max(rx, 114), rx + size)]
        self.assertTrue(not building or max(building) == 0, 'the unselected building stays out of the tip')

    def test_a_flat_source_gives_no_tips(self):
        self.assertEqual(raster.light_tips(sky(80, 60, []), 80, 60, count=4, size=32), [])

    def test_a_shape_tip_is_the_source_alpha_centred(self):
        w = h = 60
        disc = bytearray()
        for y in range(h):
            for x in range(w):
                disc += bytes([20, 120, 30, 255 if math.hypot(x - 30, y - 30) < 20 else 0])
        tip = raster.shape_tip(bytes(disc), w, h, size=40)
        self.assertEqual(len(tip), 40 * 40)
        self.assertGreater(tip[20 * 40 + 20], 240)
        self.assertEqual(tip[0], 0)


class StampTests(unittest.TestCase):
    W = H = 100
    BASE = bytes([120, 60, 40, 255]) * (100 * 100)                              # BGR 120,60,40 everywhere
    FULL = bytes([255]) * (100 * 100)
    SQUARE = bytes([255]) * (20 * 20)

    def dab(self, **kw):
        return dict(dict(x=50, y=50, scale=1, stretch=1, rotation=0, opacity=0.2, tip=0), **kw)

    def test_a_dab_at_20_percent_covers_20_percent_in_the_canvas_colour(self):
        out, placed = raster.stamp(self.BASE, self.W, self.H, self.FULL, [self.SQUARE], 20, [self.dab()])
        self.assertEqual(placed, 1)
        b, g, r, a = pixel(out, self.W, 50, 50)
        self.assertLess(abs(a - 51), 4, 'premultiplied compositing: 0.2 opacity is about 51 alpha, not 255')
        self.assertLess(max(abs(b - 120), abs(g - 60), abs(r - 40)), 6, (b, g, r))
        self.assertEqual(pixel(out, self.W, 5, 5)[3], 0)

    def test_nothing_lands_outside_the_mask_and_dabs_outside_it_are_skipped(self):
        left = bytes([255 if x < 50 else 0 for _y in range(self.H) for x in range(self.W)])
        out, placed = raster.stamp(self.BASE, self.W, self.H, left, [self.SQUARE], 20,
                                   [self.dab(x=48, opacity=1), self.dab(x=80, opacity=1)])
        self.assertEqual(placed, 1, 'the dab centred outside the area is skipped')
        self.assertGreater(pixel(out, self.W, 45, 50)[3], 200)
        self.assertEqual(pixel(out, self.W, 55, 50)[3], 0)

    def test_the_same_dabs_give_the_same_pixels(self):
        dabs = [self.dab(x=30 + i * 7, y=40 + i * 3, rotation=i * 11, scale=1 + i / 10, stretch=1.4) for i in range(6)]
        first = raster.stamp(self.BASE, self.W, self.H, self.FULL, [self.SQUARE], 20, dabs)
        self.assertEqual(first, raster.stamp(self.BASE, self.W, self.H, self.FULL, [self.SQUARE], 20, dabs))

    def test_coverage_is_ink_laid_per_selected_pixel(self):
        dab = self.dab(opacity=0.5)
        self.assertAlmostEqual(raster.coverage([dab], [self.SQUARE], 20, self.FULL), 0.5 * 400 / 10000)
        left = bytes([255 if x < 50 else 0 for _y in range(self.H) for x in range(self.W)])
        self.assertAlmostEqual(raster.coverage([dab], [self.SQUARE], 20, left), 0.5 * 400 / 5000)
        self.assertAlmostEqual(raster.coverage([self.dab(opacity=0.5, stretch=2, scale=0.5)], [self.SQUARE], 20, self.FULL), 0.5 * 100 * 2 / 10000)
        half = bytes([128]) * (20 * 20)                                         # a tip that covers half its square
        self.assertAlmostEqual(raster.coverage([dab], [half], 20, self.FULL), 0.5 * 400 * 128 / 255 / 10000, places=4)

    def test_the_area_edge_fades_inward_so_a_straight_selection_edge_never_prints(self):
        # A selection bounded by a rectangle cut the stamped clouds off in a straight line: Luna's "flat block".
        left = bytes([255 if x < 50 else 0 for _y in range(self.H) for x in range(self.W)])
        out, _ = raster.stamp(self.BASE, self.W, self.H, left, [self.SQUARE], 20, [self.dab(x=40, scale=3, opacity=1)])
        alpha = lambda x: pixel(out, self.W, x, 50)[3]
        self.assertEqual(alpha(55), 0, 'never past the area')
        self.assertLess(alpha(49), alpha(30) * 0.6, 'faint at the edge')
        self.assertGreater(alpha(15), 240, 'full strength well inside')

    def test_a_tint_toward_the_top_lightens_the_top_more(self):
        tint = {'color': '#ffffff', 'amount': 0.6, 'toward': 'top'}
        out, _ = raster.stamp(self.BASE, self.W, self.H, self.FULL, [self.SQUARE], 20,
                              [self.dab(y=12, opacity=1), self.dab(y=88, opacity=1)], tint)
        top, bottom = pixel(out, self.W, 50, 12), pixel(out, self.W, 50, 88)
        self.assertGreater(sum(top[:3]), sum(bottom[:3]) + 30, (top, bottom))
        self.assertGreater(sum(bottom[:3]), 120 + 60 + 40, 'the bottom is tinted a little too')

    def test_contact_sheet_shows_every_tip(self):
        sheet = raster.contact_sheet([self.SQUARE, bytes(20 * 20)], 20)
        self.assertEqual((sheet.width(), sheet.height()), (2 * 20 + 3 * 4, 20 + 2 * 4))


class KritaBrushStampTests(unittest.TestCase):
    """What the Krita-brush stamp (krita-fork 5.1) needs of the raster: tips as variants for a dab's rotation and
    stretch, the brush tip image, the area's faded clip and each dab's colour."""
    W = H = 100
    BASE = bytes([120, 60, 40, 255]) * (100 * 100)
    FULL = bytes([255]) * (100 * 100)
    SQUARE = bytes([255]) * (20 * 20)

    def dab(self, **kw):
        return dict(dict(x=50, y=50, scale=1, stretch=1, rotation=0, opacity=0.2, tip=0), **kw)

    def test_a_plain_dab_uses_the_tip_itself(self):
        side, alpha = raster.tip_variant(self.SQUARE, 20, 0, 1)
        self.assertEqual((side, alpha), (20, self.SQUARE))

    def test_a_stretched_tip_is_wide_and_a_rotated_one_turns(self):
        disc = bytes(255 if math.hypot(x - 10, y - 10) < 9 else 0 for y in range(20) for x in range(20))
        side, wide = raster.tip_variant(disc, 20, 0, 2)
        self.assertGreaterEqual(side, 20 * 1.41)
        self.assertEqual(len(wide), side * side)
        rows = lambda a: [y for y in range(side) if any(a[y * side + x] > 128 for x in range(side))]
        cols = lambda a: [x for x in range(side) if any(a[y * side + x] > 128 for y in range(side))]
        self.assertGreater(len(cols(wide)), 1.7 * len(rows(wide)), 'twice as wide as tall')
        self.assertGreaterEqual(len(cols(wide)), 15, 'the long axis keeps the tip size')
        _side, turned = raster.tip_variant(disc, 20, 90, 2)
        self.assertGreater(len(rows(turned)), 1.7 * len(cols(turned)), 'rotated a quarter turn: taller than wide')
        side2, narrow = raster.tip_variant(disc, 20, 0, 0.5)
        self.assertGreater(len(rows(narrow)), 1.7 * len(cols(narrow)), 'stretch under 1 is narrower than tall')

    def test_the_brush_tip_image_carries_the_tip_as_its_alpha(self):
        image = raster.tip_image(bytes(range(16)), 4)
        self.assertEqual((image.width(), image.height()), (4, 4))
        self.assertEqual([image.pixelColor(x, 0).alpha() for x in range(4)], [0, 1, 2, 3])
        self.assertEqual(image.pixelColor(3, 3).alpha(), 15)

    def test_rotation_and_stretch_fall_in_buckets_and_few_variants_are_made(self):
        dabs = [self.dab(rotation=r, stretch=s) for r in (-25, -5, 0, 14, 31, 200) for s in (1.0, 1.3, 1.6, 0.4)]
        keys, level = raster.bucket_variants(dabs, max_variants=96)
        self.assertEqual(level, 'fine')
        self.assertEqual(keys[4], keys[8], 'a dab 5 degrees from 0 shares the bucket of 0')
        self.assertEqual(len({(d['tip'],) + k for d, k in zip(dabs, keys)}), len(set(keys)))
        self.assertEqual(keys[dabs.index(self.dab(rotation=0, stretch=1.0))], (0, 1.0))
        self.assertTrue(all(rotation % 30 == 0 and rotation < 360 for rotation, _s in keys))
        self.assertEqual({k[1] for k in keys}, {0.4444, 1.0, 1.5}, 'stretch in steps of 1.5')
        many = [self.dab(rotation=r, stretch=s, tip=t) for r in range(0, 360, 10) for s in (0.3, 0.5, 1, 1.4, 2, 3, 4) for t in range(2)]
        keys, level = raster.bucket_variants(many, max_variants=40)
        self.assertEqual(level, 'coarse')
        self.assertLessEqual(len({(d['tip'],) + k for d, k in zip(many, keys)}), 40)
        keys, level = raster.bucket_variants(many, max_variants=6)
        self.assertEqual((level, set(keys)), ('plain', {(0, 1.0)}), 'one variant per tip: rotation and stretch are dropped')

    def test_the_clip_is_the_area_faded_at_its_edge_and_nothing_past_it(self):
        left = bytes([255 if x < 50 else 0 for _y in range(self.H) for x in range(self.W)])
        clip = raster.clip_mask(left, self.W, self.H, [self.dab(scale=3)], 20)
        at = lambda x: clip[50 * self.W + x]
        self.assertEqual(at(55), 0)
        self.assertLess(at(49), at(30) * 0.6)
        self.assertGreater(at(15), 240)
        self.assertEqual(len(clip), self.W * self.H)
        self.assertEqual(raster.clip_mask(left, self.W, self.H, [], 20), left, 'no dabs: the mask itself')

    def test_a_dab_takes_the_colour_the_qpainter_stamp_took(self):
        tint = {'color': '#ffffff', 'amount': 0.6, 'toward': 'top'}
        colours = raster.dab_colours(self.BASE, self.W, self.H, [self.dab(y=12), self.dab(y=88)], tint)
        self.assertEqual(len(colours), 2)
        self.assertTrue(all(len(c) == 7 and c[0] == '#' for c in colours))
        top, bottom = (int(c[1:3], 16) + int(c[3:5], 16) + int(c[5:7], 16) for c in colours)
        self.assertGreater(top, bottom + 30)
        self.assertEqual(raster.dab_colours(self.BASE, self.W, self.H, [self.dab()], None), ['#%02x%02x%02x' % (40, 60, 120)])


if __name__ == '__main__':
    unittest.main()

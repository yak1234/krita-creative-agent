# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""paint_snow as pixels (snow_raster.py; openspec snow): falling snow in depth layers over a synthetic scene, settled
snow caps on the top edges of synthetic masks. Numpy and OpenCV only; writes no files. The live test (2026-10-25,
Dostoevsky, 6000 x 4500) got ~20 dashes of one size and angle: these tests hold the counts, the size spread between
layers, a low alpha, faces kept clear, caps only on upward edges and the scene's light in the colour."""
import importlib
import pathlib
import sys
import time
import types
import unittest

import numpy as np

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'


def load():
    package = types.ModuleType('snow_test_package'); package.__path__ = [str(PLUGIN)]
    sys.modules['snow_test_package'] = package
    return importlib.import_module('snow_test_package.snow_raster')


snow = load()


def scene(w, h, top=(200, 150, 120), bottom=(60, 70, 90), light=None):
    """BGRA uint8: a vertical gradient (B, G, R) from `top` to `bottom`, with a bright patch of `light` up right (a sun)."""
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    rgb = np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = np.broadcast_to(rgb, (h, w, 3)).astype(np.uint8)
    out[..., 3] = 255
    if light is not None:
        out[h // 8:h // 4, int(w * 0.7):int(w * 0.8), :3] = light
    return out


def disc(w, h, cx, cy, r):
    y, x = np.mgrid[0:h, 0:w]
    return ((x - cx) ** 2 + (y - cy) ** 2 <= r * r).astype(np.uint8) * 255


class FallingTests(unittest.TestCase):
    def test_thousands_of_flakes_in_three_layers_far_small_and_many_near_few_and_large(self):
        plan = snow.plan_flakes(6000, 4500, density=1.0, wind_deg=15, layers=3, seed=1)
        self.assertEqual(list(plan), ['far', 'mid', 'near'])
        counts = {name: len(layer['x']) for name, layer in plan.items()}
        self.assertGreater(sum(counts.values()), 2000, 'thousands at 6000 x 4500')
        self.assertGreater(counts['far'], counts['mid']); self.assertGreater(counts['mid'], counts['near'])
        self.assertGreaterEqual(counts['near'], 10)
        size = {name: float(np.median(layer['r'])) for name, layer in plan.items()}
        self.assertLess(size['far'] * 1.8, size['mid']); self.assertLess(size['mid'] * 2, size['near'])
        self.assertGreater(float(np.std(plan['far']['r'])), 0, 'not one size')
        self.assertGreater(float(np.ptp(plan['mid']['angle'])), 4, 'not one angle: each flake drifts a little')
        alpha = {name: float(np.mean(layer['alpha'])) for name, layer in plan.items()}
        self.assertLess(alpha['far'], alpha['mid'], 'far flakes dimmer')
        # Denser: more flakes. A smaller copy of the picture: the same flakes, smaller (the same look), never below a dab.
        dense = snow.plan_flakes(6000, 4500, density=2.0, wind_deg=15, layers=3, seed=1)
        self.assertGreater(len(dense['far']['x']), 1.8 * counts['far'])
        small = snow.plan_flakes(1500, 1125, density=1.0, wind_deg=15, layers=3, seed=1)
        self.assertEqual({name: len(layer['x']) for name, layer in small.items()}, counts)
        self.assertAlmostEqual(float(np.median(small['mid']['r'])), size['mid'] / 4, delta=size['mid'] / 20)
        self.assertGreaterEqual(float(small['far']['r'].min()), snow.MIN_RADIUS)
        square = snow.plan_flakes(4500, 4500, density=1.0, wind_deg=15, layers=3, seed=1)
        self.assertGreater(len(square['far']['x']), 1.2 * counts['far'], 'a squarer picture of the same long side: more sky')
        self.assertEqual(list(snow.plan_flakes(6000, 4500, 1.0, 0, 2, 1)), ['far', 'near'], 'two layers: far and near')

    def test_the_wind_slants_the_streaks(self):
        still = snow.plan_flakes(3000, 2250, 1.0, 0, 3, seed=3)
        windy = snow.plan_flakes(3000, 2250, 1.0, 30, 3, seed=3)
        self.assertAlmostEqual(float(np.median(still['mid']['angle'])), 90, delta=4)
        self.assertAlmostEqual(float(np.median(windy['mid']['angle'])), 60, delta=4)
        self.assertTrue((windy['mid']['streak'] >= 1).all(), 'a slight motion streak')

    def test_soft_low_alpha_flakes_in_the_scenes_light_and_none_on_a_face(self):
        w, h = 1500, 1125
        canvas = scene(w, h, top=(150, 170, 230), bottom=(70, 80, 120), light=(170, 215, 255))     # a warm sunset (BGR)
        face = disc(w, h, 600, 500, 90)
        rect = [500, 400, 200, 200]
        clear = [(rect, face[400:600, 500:700].tobytes())]
        pixels, report = snow.falling(canvas, density=1.0, wind_deg=15, layers=3, keep_clear=clear, seed=2)
        self.assertEqual(pixels.shape, (h, w, 4))
        a = pixels[..., 3].astype(np.float32) / 255
        self.assertEqual(int(pixels[face > 0, 3].max()), 0, 'nothing on the face')
        feather = report['feather_px']
        ring = (disc(w, h, 600, 500, 90 + feather * 0.5) > 0) & (face == 0)
        self.assertLess(float(a[ring].mean()), float(a.mean()), 'thinned in the feather')
        self.assertTrue(0.004 < float(a.mean()) < 0.08, 'reads as snowfall, not a white-out: %.4f' % a.mean())
        flakes = a[a > 0.02]
        self.assertLess(float(np.median(flakes)), 0.6, 'soft, not opaque dots')
        self.assertGreater(int((a > 0).sum()), 20000)
        self.assertEqual(set(report['layers']), {'far', 'mid', 'near'})
        for name in ('far', 'mid', 'near'):
            self.assertGreater(report['layers'][name]['flakes'], 0)
        self.assertGreater(report['kept_clear'], 0, 'the flakes taken off the face are counted')
        b, g, r = (float(v) for v in pixels[a > 0.2][:, :3].mean(axis=0))
        self.assertGreater(r, b + 8, 'warm-white flakes in a warm scene')
        self.assertGreater(min(b, g, r), 170, 'light flakes')

    def test_a_cool_scene_gets_cool_white_flakes(self):
        canvas = scene(1200, 900, top=(230, 190, 150), bottom=(120, 90, 60), light=(255, 230, 200))
        pixels, report = snow.falling(canvas, 1.0, 0, 3, [], seed=4)
        a = pixels[..., 3]
        b, g, r = (float(v) for v in pixels[a > 50][:, :3].mean(axis=0))
        self.assertGreater(b, r + 8)
        self.assertGreater(report['light'][0], report['light'][2], 'the light is reported as B, G, R: blue first here')

    def test_timing_at_6000_by_4500(self):
        canvas = scene(6000, 4500, light=(200, 230, 255))
        face = disc(400, 400, 200, 200, 180)
        started = time.monotonic()
        pixels, report = snow.falling(canvas, 1.0, 15, 3, [([2000, 1000, 400, 400], face.tobytes())], seed=5)
        seconds = time.monotonic() - started
        print('\nsnow falling 6000x4500: %.2f s, flakes %s' % (seconds, {k: v['flakes'] for k, v in report['layers'].items()}))
        self.assertGreater(sum(v['flakes'] for v in report['layers'].values()), 2000)
        self.assertLess(seconds, 30)


def post(w, h, box):
    m = np.zeros((h, w), np.uint8); x, y, bw, bh = box; m[y:y + bh, x:x + bw] = 255; return m


def hat(w, h):
    """A top hat: a crown (narrow, tall) on a brim (wide, thin): two upward edges, the crown's top and the brim's shoulders."""
    m = np.zeros((h, w), np.uint8)
    m[100:200, 160:240] = 255                     # crown
    m[200:220, 120:280] = 255                     # brim
    return m


class SettledTests(unittest.TestCase):
    def cap(self, mask, canvas=None, **extra):
        h, w = mask.shape
        canvas = scene(w, h) if canvas is None else canvas
        ys, xs = np.nonzero(mask)
        rect = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]
        plane = mask[rect[1]:rect[1] + rect[3], rect[0]:rect[0] + rect[2]].tobytes()
        pixels, at, report = snow.settled(canvas, rect, plane, seed=1, **extra)
        out = np.zeros((h, w, 4), np.uint8)
        x, y, cw, ch = at
        out[y:y + ch, x:x + cw] = pixels
        return out, report

    def test_a_cap_on_a_posts_top_and_nothing_on_its_sides_or_bottom(self):
        mask = post(600, 600, [250, 200, 100, 300])
        out, report = self.cap(mask)
        a = out[..., 3].astype(np.float32) / 255
        t = report['thickness_px']
        self.assertTrue(4 <= t <= 30, t)
        top = a[200 - int(t * 0.5):203, 255:345]
        self.assertGreater(float((top > 0.6).mean()), 0.5, 'snow along the top')
        self.assertGreater(float(a[200 - int(t * 0.4), 300]), 0.6, 'standing up above the edge')
        # The sides below the cap and the bottom: nothing but the cap's thin shadow just under it.
        self.assertLess(float(a[200 + 2 * int(t) + 6:, :].max()), 0.05, 'nothing down the sides or at the bottom')
        self.assertLess(float(a[:, :250 - int(t)].max()) + float(a[:, 350 + int(t):].max()), 0.05, 'overhangs only slightly')
        self.assertLess(float(a[:200 - 2 * int(t) - 4].max()), 0.05, 'not floating above')
        self.assertEqual(report['caps'], 1)
        # A slight overhang past the corners.
        self.assertGreater(float(a[200 - int(t * 0.3), 248]), 0.1)
        # The shadow under it: the post just below the cap is darker than the scene there.
        plain = scene(600, 600)
        darker = [y for y in range(200, 200 + int(2 * t) + 4) if out[y, 300, 3] > 10
                  and out[y, 300, :3].astype(int).sum() < plain[y, 300, :3].astype(int).sum()]
        self.assertTrue(darker, 'a soft shadow under the cap, on the post')

    def test_a_hat_gets_a_cap_on_the_crown_and_on_the_brim_not_under_the_brim(self):
        out, report = self.cap(hat(400, 300))
        a = out[..., 3].astype(np.float32) / 255
        self.assertGreater(float(a[97, 200]), 0.6, 'on the crown')
        self.assertGreater(float(a[198, 130]), 0.5, 'on the brim beside the crown')
        self.assertLess(float(a[240:, :].max()), 0.05, 'nothing under the brim')
        self.assertLess(float(a[110:180, 120:150].max()), 0.05, 'nothing beside the crown’s sides above the brim cap')
        self.assertGreaterEqual(report['caps'], 2)

    def test_thickness_scales_with_the_shape(self):
        _small, small = self.cap(post(600, 600, [280, 300, 40, 100]))
        _large, large = self.cap(post(1200, 900, [200, 300, 600, 300]))
        self.assertGreater(large['thickness_px'], 2.5 * small['thickness_px'])
        self.assertGreaterEqual(small['thickness_px'], snow.MIN_THICK)
        _thick, thick = self.cap(post(600, 600, [250, 200, 100, 300]), amount=1.6)
        _thin, thin = self.cap(post(600, 600, [250, 200, 100, 300]), amount=0.6)
        self.assertGreater(thick['thickness_px'], thin['thickness_px'] * 2)

    def test_a_shoulder_slope_holds_snow_and_a_steep_side_none(self):
        h, w = 500, 500
        y, x = np.mgrid[0:h, 0:w]
        shoulder = ((y > 200 + 0.6 * np.abs(x - 250)) & (np.abs(x - 250) < 200) & (y < 450)).astype(np.uint8) * 255
        out, _ = self.cap(shoulder)
        a = out[..., 3].astype(np.float32) / 255
        self.assertGreater(float(a[200 + int(0.6 * 100) - 2, 350]), 0.4, 'a gentle slope: snow')
        steep = ((np.abs(x - 250) < 20 + (y - 100) * 0.05) & (y > 100) & (y < 450)).astype(np.uint8) * 255
        out, _ = self.cap(steep)
        a = out[..., 3].astype(np.float32) / 255
        self.assertLess(float(a[200:400].max()), 0.05, 'a near-vertical side: none')

    def test_the_cap_takes_the_scenes_light(self):
        mask = post(600, 600, [250, 200, 100, 300])
        warm, _ = self.cap(mask, canvas=scene(600, 600, top=(140, 170, 235), bottom=(80, 90, 140), light=(170, 215, 255)))
        cool, _ = self.cap(mask, canvas=scene(600, 600, top=(235, 190, 150), bottom=(140, 100, 70), light=(255, 230, 200)))
        def colour(out): return out[out[..., 3] > 200][:, :3].astype(float).mean(axis=0)
        wb, _wg, wr = colour(warm); cb, _cg, cr = colour(cool)
        self.assertGreater(wr, wb + 5); self.assertGreater(cb, cr + 5)
        self.assertGreater(min(colour(warm)), 150, 'snow is light')

    # Lead review of the Dostoevsky preview (2026-10-25): the far palace roof got a thick bright band floating above it, a
    # continuous rim on every edge, and a rim on the main figure's thin collar.
    def test_a_far_roofline_gets_a_hairline_and_the_same_shape_near_a_thicker_cap(self):
        w, h = 1568, 1176
        far, far_report = self.cap(post(w, h, [500, 450, 360, 40]), canvas=scene(w, h))
        near, near_report = self.cap(post(w, h, [500, 1000, 360, 40]), canvas=scene(w, h))
        self.assertLessEqual(far_report['thickness_px'], 4, 'a far roof: hairline to a few px')
        self.assertGreater(near_report['thickness_px'], 1.5 * far_report['thickness_px'], 'lower in the picture: nearer, thicker')
        def lum(out): return float((out[out[..., 3] > 150][:, :3].astype(float) @ [0.114, 0.587, 0.299]).mean())
        self.assertLess(lum(far), lum(near), 'aerial perspective: a far cap is dimmer')

    def test_a_long_cap_is_broken_and_uneven_with_a_soft_lower_edge(self):
        out, report = self.cap(post(1200, 900, [100, 600, 1000, 250]))
        a = out[..., 3].astype(np.float32) / 255
        t = report['thickness_px']
        columns = a[600 - int(2 * t) - 2:600, 110:1090]
        present = (columns > 0.5).any(axis=0)
        self.assertTrue(0.4 < float(present.mean()) < 0.95, 'gaps along the edge: %.2f' % present.mean())
        height = (columns > 0.5).sum(axis=0)[present]
        self.assertGreater(float(height.std()), 0.2 * float(height.mean()), 'varying thickness, lumps')
        lower = a[600 + max(1, int(0.25 * t)), 110:1090][present]
        upper = a[600 - max(1, int(0.25 * t)), 110:1090][present]
        self.assertLess(float(lower.mean()), float(upper.mean()), 'melting into the form below the edge')

    def test_the_lit_side_is_warmer_than_the_shadow_side_and_never_brighter_than_the_scene(self):
        w, h = 800, 600
        canvas = scene(w, h, top=(150, 170, 230), bottom=(70, 80, 120), light=(170, 215, 255))     # the sun up right
        y, x = np.mgrid[0:h, 0:w]
        roof = ((y > 250 + 0.5 * np.abs(x - 400)) & (np.abs(x - 400) < 300) & (y < 560)).astype(np.uint8) * 255
        out, _ = self.cap(roof, canvas=canvas)
        def warmth(side):
            px = out[:, side][out[:, side, 3] > 150][:, :3].astype(float)
            return float((px[:, 2] - px[:, 0]).mean())
        self.assertGreater(warmth(slice(420, 680)), warmth(slice(120, 380)) + 4, 'sunlit side warm, shadow side bluish')
        brightest = float((canvas[..., :3].astype(float) @ [0.114, 0.587, 0.299]).max())
        capped = out[out[..., 3] > 150][:, :3].astype(float) @ [0.114, 0.587, 0.299]
        self.assertLessEqual(float(capped.max()), brightest + 1)

    def test_no_cap_where_the_mask_is_cut_by_the_canvas_top(self):
        out, _ = self.cap(post(600, 600, [200, 0, 200, 300]))
        self.assertLess(int(out[:, :, 3].max()), 13, 'the top of a mask cut at the canvas edge is not a surface')

    def test_a_thin_rim_and_a_narrow_spike_get_none(self):
        rim = post(600, 600, [150, 300, 300, 2])
        out, _ = self.cap(rim)
        self.assertLess(int(out[..., 3].max()), 13, 'a thin rim (a collar edge) holds no snow')
        spike = post(600, 600, [300, 100, 3, 300])
        out, _ = self.cap(spike)
        self.assertLess(int(out[:110, :, 3].max()), 13, 'a narrow top holds no snow')

    def test_timing_of_large_parts(self):
        mask = post(6000, 4500, [500, 1500, 2500, 1500])
        canvas = scene(6000, 4500)
        rect = [500, 1500, 2500, 1500]
        started = time.monotonic()
        pixels, at, report = snow.settled(canvas, rect, mask[1500:3000, 500:3000].tobytes(), seed=1)
        seconds = time.monotonic() - started
        print('\nsnow settled on a 2500 x 1500 roof at 6000x4500: %.2f s, thickness %s px' % (seconds, report['thickness_px']))
        self.assertLess(seconds, 10)


if __name__ == '__main__':
    unittest.main()

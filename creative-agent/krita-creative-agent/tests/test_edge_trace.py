# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""edge_trace.py: guide lines from a reference at full resolution (OpenCV). A stepped tower keeps its spire and tiers,
a blue tower on a blue sky still gets its edges, a thin mast is kept, a shape's labels give the outlines (each shared
border once), caps and simplification follow the size on the canvas. Synthetic images in memory; writes no files."""
import importlib.util
import pathlib
import time
import tracemalloc
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('edge_trace', pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp/edge_trace.py')
edge_trace = importlib.util.module_from_spec(spec); spec.loader.exec_module(edge_trace)

# The tower's outline (reference pixels at 800 x 1200), base on the bottom edge: base block, middle tier, top tier, spire.
TOWER = [(200, 1200), (200, 800), (280, 800), (280, 500), (350, 500), (350, 300), (380, 300), (400, 80), (420, 300), (450, 300),
         (450, 500), (520, 500), (520, 800), (600, 800), (600, 1200)]


def polygon_mask(width, height, polygon):
    import cv2
    mask = np.zeros((height, width), np.uint8)
    cv2.fillPoly(mask, [np.array(polygon, np.int32)], 1)
    return mask.astype(bool)


def rgba(rgb, alpha=None):
    out = np.empty(rgb.shape[:2] + (4,), np.uint8)
    out[..., :3] = np.clip(rgb, 0, 255); out[..., 3] = 255 if alpha is None else alpha
    return out


def tower_image(noise=12, windows=True):
    rng = np.random.default_rng(7)
    inside = polygon_mask(800, 1200, TOWER)
    grey = np.where(inside, 50.0, 210.0)
    if windows:                                   # lit windows: texture a guide should not outline
        yy, xx = np.mgrid[0:1200, 0:800]
        grey = np.where(inside & (yy > 520) & (xx % 32 < 6) & (yy % 32 < 6), 200.0, grey)
    grey = grey + rng.uniform(-noise, noise, grey.shape)
    return rgba(np.repeat(grey[..., None], 3, axis=2))


def seg_distance(p, a, b):
    a, b, p = np.asarray(a, float), np.asarray(b, float), np.asarray(p, float)
    d = b - a; n = d @ d
    t = 0 if n == 0 else max(0.0, min(1.0, (p - a) @ d / n))
    return float(np.hypot(*(p - a - t * d)))


def poly_distance(p, points):
    return min(seg_distance(p, points[i - 1], points[i]) for i in range(1, len(points)))


def samples(points, step=3.0):
    out = []
    for a, b in zip(points, points[1:]):
        n = max(1, int(np.ceil(np.hypot(b[0] - a[0], b[1] - a[1]) / step)))
        out += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n + 1)]
    return out


def covered(lines, outline, tolerance):
    along = samples(outline, 4)
    pts = [p for line in lines for p in samples(line, 2)]
    if not pts:
        return 0.0
    arr = np.array(pts)
    hit = sum(1 for p in along if np.min(np.hypot(arr[:, 0] - p[0], arr[:, 1] - p[1])) <= tolerance)
    return hit / len(along)


def lines_of(result, kind=None):
    return [line['points'] for line in result['lines'] if kind is None or line['kind'] == kind]


class EdgeTraceTests(unittest.TestCase):
    def test_the_tower_keeps_its_spire_and_tiers_within_the_caps(self):
        for detail, cap in (('simple', 12), ('medium', 40)):
            out = edge_trace.trace(tower_image(), [0, 0, 800, 1200], scale=1.0, detail=detail, max_lines=cap)
            lines = lines_of(out)
            self.assertTrue(1 <= len(lines) <= cap, (detail, len(lines)))
            self.assertTrue(all(2 <= len(line) <= edge_trace.MAX_POINTS for line in lines))
            self.assertGreaterEqual(covered(lines, TOWER, 5), 0.9, detail + ': the outline is covered, tiers included')
            spire = [(380, 300), (400, 80), (420, 300)]
            self.assertGreaterEqual(covered(lines, spire, 5), 0.85, detail + ': the spire is kept')
            self.assertEqual(out['silhouette'], 'brightness', 'no shapes: the brightness split, and it says so')

    def test_a_source_crop_traces_inside_it_in_image_pixels(self):
        out = edge_trace.trace(tower_image(), [240, 0, 320, 600], scale=1.0, detail='simple', max_lines=12)
        lines = lines_of(out)
        self.assertTrue(lines)
        for line in lines:
            for x, y in line:
                self.assertTrue(240 <= x <= 560 and 0 <= y <= 600, (x, y))
        self.assertGreaterEqual(covered(lines, [(280, 600), (280, 500), (350, 500), (350, 300), (380, 300), (400, 80), (420, 300),
                                                (450, 300), (450, 500), (520, 500), (520, 600)], 5), 0.85)

    def test_a_blue_tower_on_a_blue_sky_still_has_edges(self):
        # Same brightness, different hue: a brightness split cannot see it.
        inside = polygon_mask(600, 800, [(200, 800), (200, 200), (300, 120), (400, 200), (400, 800)])
        sky = np.array([200, 140, 70], float)           # RGB: a mid blue
        glass = np.array([100, 150, 175], float)        # a cyan-grey glass of about the same luminance
        rgb = np.where(inside[..., None], glass, sky) + np.random.default_rng(1).uniform(-6, 6, (800, 600, 3))
        out = edge_trace.trace(rgba(rgb), [0, 0, 600, 800], scale=1.0, detail='simple', max_lines=12)
        self.assertGreaterEqual(covered(lines_of(out), [(200, 790), (200, 200), (300, 120), (400, 200), (400, 790)], 5), 0.85)

    def test_a_thin_mast_is_kept(self):
        grey = np.full((900, 900), 200.0)
        grey[500:, 100:800] = 60                           # a wide dark building
        grey[150:500, 448:452] = 60                        # a 4 px mast on it, 350 px tall
        out = edge_trace.trace(rgba(np.repeat(grey[..., None], 3, axis=2)), [0, 0, 900, 900], scale=1.0, detail='simple', max_lines=8)
        lines = lines_of(out)
        mast = [p for line in lines for p in samples(line) if 440 <= p[0] <= 460 and 160 <= p[1] <= 490]
        self.assertGreaterEqual(len({round(p[1] / 20) for p in mast}), 12, 'the mast runs most of its height')

    def test_texture_noise_and_flat_areas_give_few_or_no_lines(self):
        rng = np.random.default_rng(3)
        noise = rgba(np.repeat(rng.uniform(0, 255, (600, 600))[..., None], 3, axis=2))
        self.assertLessEqual(len(lines_of(edge_trace.trace(noise, [0, 0, 600, 600], scale=1.0, detail='medium', max_lines=40))), 3)
        flat = rgba(np.full((200, 200, 3), 128.0))
        self.assertEqual(lines_of(edge_trace.trace(flat, [0, 0, 200, 200], scale=1.0, detail='medium', max_lines=40)), [])
        self.assertEqual(lines_of(edge_trace.trace(tower_image(), [0, 0, 120, 120], scale=1.0, detail='medium', max_lines=40)), [], 'all sky')
        for source in ([0, 0, 1, 1], [10, 10, 3, 2]):
            self.assertIsInstance(edge_trace.trace(tower_image(), source, scale=1.0)['lines'], list)

    def test_simplification_is_measured_on_the_canvas(self):
        circle = np.full((800, 800), 210.0)
        yy, xx = np.mgrid[0:800, 0:800]
        circle[np.hypot(xx - 400, yy - 400) <= 300] = 50
        image = rgba(np.repeat(circle[..., None], 3, axis=2))
        small = edge_trace.trace(image, [0, 0, 800, 800], scale=0.25, detail='simple', max_lines=8)
        large = edge_trace.trace(image, [0, 0, 800, 800], scale=4.0, detail='simple', max_lines=8)
        count = lambda out: sum(len(line) for line in lines_of(out))
        self.assertLess(count(small), count(large), 'a circle drawn small needs fewer points than drawn large')
        for out in (small, large):
            for line in lines_of(out):
                for p in samples(line, 4):
                    self.assertLess(abs(np.hypot(p[0] - 400, p[1] - 400) - 300), 6 if out is large else 12)

    def test_labels_give_the_outlines_and_a_shared_border_is_drawn_once(self):
        # A sky (1) above a building mass (2); a figure (3) in front of the building. Same grey everywhere: only the
        # labels can say where the shapes are.
        labels = np.ones((600, 800), np.uint8)
        labels[300:, :] = 2
        labels[380:560, 360:440] = 3
        image = rgba(np.full((600, 800, 3), 128.0))
        out = edge_trace.trace(image, [0, 0, 800, 600], scale=1.0, detail='simple', max_lines=12, labels=labels)
        self.assertEqual(out['silhouette'], 'shapes')
        outlines = lines_of(out, 'outline')
        self.assertGreaterEqual(covered(outlines, [(4, 300), (796, 300)], 4), 0.9, 'the skyline border')
        self.assertGreaterEqual(covered(outlines, [(360, 380), (440, 380), (440, 560), (360, 560), (360, 380)], 4), 0.9, 'the figure')
        border = [p for line in outlines for p in samples(line, 2) if abs(p[1] - 300) <= 3 and 20 < p[0] < 780]
        xs = sorted(round(p[0]) for p in border)
        self.assertLess(len(xs), 1.4 * 760 / 2 + 10, 'the sky and the building share one line, not two')
        for line in outlines:                      # the image's own edge is never an outline
            for x, y in samples(line, 2):
                self.assertFalse(x < 2 or y < 2 or x > 798 or y > 598, (x, y))

    def test_labels_with_no_outline_fall_back_and_say_so(self):
        # One shape covering the whole crop has no border in it: the brightness split outlines the tower instead.
        labels = np.ones((1200, 800), np.uint8)
        out = edge_trace.trace(tower_image(), [0, 0, 800, 1200], scale=1.0, detail='simple', max_lines=12, labels=labels)
        self.assertEqual(out['silhouette'], 'brightness')
        self.assertGreaterEqual(covered(lines_of(out, 'outline'), TOWER, 5), 0.8)
        empty = edge_trace.trace(tower_image(), [0, 0, 800, 1200], scale=1.0, labels=np.zeros((1200, 800), np.uint8))
        self.assertEqual(empty['silhouette'], 'brightness')

    def test_inside_one_shape_only_its_outline_and_structure(self):
        # The tower among clutter, with its shape: nothing on the clutter.
        image = tower_image(noise=4, windows=False)
        clutter = polygon_mask(800, 1200, [(40, 600), (180, 600), (180, 1200), (40, 1200)])
        image[clutter] = [50, 50, 50, 255]
        labels = polygon_mask(800, 1200, TOWER).astype(np.uint8)
        out = edge_trace.trace(image, [0, 0, 800, 1200], scale=1.0, detail='medium', max_lines=24, labels=labels, inside=True)
        lines = lines_of(out)
        self.assertGreaterEqual(covered(lines, TOWER, 5), 0.85)
        for line in lines:
            for p in samples(line, 3):
                self.assertGreater(poly_distance(p, [(40, 600), (180, 600), (180, 1200)]), 8, 'never on the clutter')

    def test_lights_outline_the_brightest_shapes(self):
        grey = np.full((600, 800), 20.0)
        yy, xx = np.mgrid[0:600, 0:800]
        grey[np.hypot(xx - 600, yy - 160) <= 60] = 245     # the moon
        grey[320:, :480] = 60                               # a dim building
        out = edge_trace.trace(rgba(np.repeat(grey[..., None], 3, axis=2)), [0, 0, 800, 600], scale=1.0, lights=True)
        lights = lines_of(out, 'light')
        self.assertTrue(1 <= len(lights) <= edge_trace.LIGHT_LIMIT)
        for line in lights:
            for p in samples(line):
                self.assertLess(abs(np.hypot(p[0] - 600, p[1] - 160) - 60), 4)

    def test_a_part_is_outlined_by_its_alpha(self):
        yy, xx = np.mgrid[0:400, 0:400]
        alpha = np.where(np.hypot(xx - 200, yy - 200) <= 120, 255, 0).astype(np.uint8)
        out = edge_trace.trace(rgba(np.full((400, 400, 3), 128.0), alpha), [0, 0, 400, 400], scale=1.0)
        self.assertEqual(out['silhouette'], 'alpha')
        lines = lines_of(out, 'outline')
        self.assertTrue(lines)
        for line in lines:
            for p in samples(line):
                self.assertLess(abs(np.hypot(p[0] - 200, p[1] - 200) - 120), 4)

    def test_the_cap_holds_however_busy_the_picture(self):
        rng = np.random.default_rng(5)
        grey = np.full((1000, 1000), 200.0)
        for _ in range(300):                               # many crisp rectangles: lots of real edges
            x, y, w, h = rng.integers(0, 900, 2).tolist() + rng.integers(20, 100, 2).tolist()
            grey[y:y + h, x:x + w] = rng.uniform(0, 255)
        out = edge_trace.trace(rgba(np.repeat(grey[..., None], 3, axis=2)), [0, 0, 1000, 1000], scale=2.0, detail='medium', max_lines=30)
        self.assertLessEqual(len(out['lines']), 30)
        self.assertTrue(all(len(line['points']) <= edge_trace.MAX_POINTS for line in out['lines']))

    def test_a_full_resolution_trace_is_timed_and_bounded(self):
        # About four million pixels (TRACE_PIXELS): the most the plugin ever traces.
        image = np.ascontiguousarray(tower_image(noise=10).repeat(2, axis=0).repeat(2, axis=1))
        tracemalloc.start()
        started = time.monotonic()
        out = edge_trace.trace(image, [0, 0, 1600, 2400], scale=1.5, detail='medium', max_lines=80, lights=True)
        seconds = time.monotonic() - started
        _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
        print('\nfull-resolution trace, 3.8 MP: %.2f s, numpy peak %.0f MB, %d lines' % (seconds, peak / 1e6, len(out['lines'])))
        self.assertTrue(out['lines'])
        self.assertLess(seconds, 10)
        self.assertLess(peak / 1e6, 600)


if __name__ == '__main__':
    unittest.main()

# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""accent_find.py: the accents a reference shows that the canvas lacks (openspec crisp-accents goals 1-4, and the
artist's decision of 2026-10-23: accents only where the canvas is measurably missing a sharp light or dark the
reference has): lights, glints, darks and thin lines, each with its place, size, colour by role and a strength.
The canvas in most tests is the reference blurred, as an underpainting is. A night street made in memory: lamps with a glow,
faint specks, a wet-road streak, thin posts, a dark gap and a big lit facade (a mass: never a light, never outlined).
Writes no files."""
import importlib.util
import math
import pathlib
import time
import unittest
import numpy as np
import cv2

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
spec = importlib.util.spec_from_file_location('accent_find', PLUGIN / 'accent_find.py',
                                              submodule_search_locations=None)
accent_find = importlib.util.module_from_spec(spec); spec.loader.exec_module(accent_find)

LAMPS = [(150, 120), (400, 140), (650, 110)]
FACADE = (480, 380, 220, 150)                     # x, y, w, h
POST = (300, 200, 300, 520)                       # a thin dark post: x0, y0, x1, y1
WIRE = ((560, 220), (760, 320))                   # a thin bright line
STREAK = (220, 600, 30)                           # a short bright streak at 30 degrees: x, y, angle
GAP = (120, 470)                                  # a small dark gap in a light wall


def street(noise=6, seed=3):
    rng = np.random.default_rng(seed)
    img = np.zeros((800, 900, 3), np.float32); img[:] = (40, 50, 90)          # RGB: a dark blue night
    img[420:560, 60:220] = (190, 180, 160)                                       # a pale wall round the gap
    x, y, w, h = FACADE
    img[y:y + h, x:x + w] = (235, 200, 120)                                      # a big lit facade: a mass
    cv2.circle(img, GAP, 4, (25, 20, 20), -1, cv2.LINE_AA)
    for cx, cy in LAMPS:                                                         # a lamp: a glow, then its hot core
        glow = np.zeros((800, 900), np.float32); cv2.circle(glow, (cx, cy), 22, 1.0, -1, cv2.LINE_AA)
        glow = cv2.GaussianBlur(glow, (0, 0), 8)[..., None]
        img = img * (1 - 0.5 * glow) + np.array([200, 150, 70], np.float32) * 0.5 * glow
        cv2.circle(img, (cx, cy), 6, (255, 236, 170), -1, cv2.LINE_AA)
    cv2.line(img, POST[:2], POST[2:], (12, 12, 18), 3, cv2.LINE_AA)
    cv2.line(img, WIRE[0], WIRE[1], (220, 220, 235), 2, cv2.LINE_AA)
    sx, sy, angle = STREAK
    dx, dy = math.cos(math.radians(angle)) * 7, math.sin(math.radians(angle)) * 7
    cv2.line(img, (int(sx - dx), int(sy - dy)), (int(sx + dx), int(sy + dy)), (250, 245, 230), 2, cv2.LINE_AA)
    for _ in range(60):                                                          # faint specks: snow, not accents
        px, py = int(rng.integers(20, 880)), int(rng.integers(20, 380))
        if all(math.hypot(px - lx, py - ly) > 40 for lx, ly in LAMPS):
            cv2.circle(img, (px, py), 1, (95, 100, 130), -1)
    img += rng.uniform(-noise, noise, img.shape)
    out = np.empty((800, 900, 4), np.uint8); out[..., :3] = np.clip(img, 0, 255); out[..., 3] = 255
    return out


def soft(rgba, sigma=4):
    """An underpainting of the reference: the same picture with its sharp lights and darks blurred away."""
    out = rgba.copy(); out[..., :3] = cv2.GaussianBlur(rgba[..., :3], (0, 0), sigma); return out


def find_on_soft(image, source, **options):
    """Accents of `image` against its own blurred copy as the canvas view (at full size: the crop sits at `source`)."""
    return accent_find.find(image, source, canvas=soft(image), target=list(source), **options)


def of(result, kind):
    return [a for a in result['accents'] if a['kind'] == kind]


def near(accents, x, y, tolerance):
    return [a for a in accents if math.hypot(a['x'] - x, a['y'] - y) <= tolerance]


def luma(hex_colour):
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def segment_distance(p, a, b):
    a, b, p = (np.asarray(v, float) for v in (a, b, p))
    d = b - a; t = max(0.0, min(1.0, float((p - a) @ d / (d @ d))))
    return float(np.hypot(*(p - a - t * d)))


class AccentFindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = street()
        cls.all = find_on_soft(cls.image, [0, 0, 900, 800], strength='subtle', max_accents=200)

    def test_lamps_are_lights_strongest_first_in_their_brightest_colour(self):
        lights = of(self.all, 'lights')
        for x, y in LAMPS:
            found = near(lights, x, y, 4)
            self.assertEqual(len(found), 1, ('one light a lamp', x, y))
            light = found[0]
            self.assertGreater(luma(light['colour']), 215, 'from the brightest core, not an averaged glow: ' + light['colour'])
            self.assertTrue(8 <= light['size'] <= 16, light['size'])
            self.assertGreater(light['glow'], 0.05, 'a lamp has a glow round it')
        ranked = [a['strength'] for a in self.all['accents']]
        self.assertEqual(ranked, sorted(ranked, reverse=True), 'strongest first')
        lamp_low = min(near(lights, x, y, 4)[0]['strength'] for x, y in LAMPS)
        specks = [a for a in lights if all(math.hypot(a['x'] - x, a['y'] - y) > 30 for x, y in LAMPS) and a['y'] < 380]
        self.assertTrue(all(a['strength'] < lamp_low for a in specks), 'faint specks rank under every lamp')
        bold = find_on_soft(self.image, [0, 0, 900, 800], kinds=['lights'], strength='bold', max_accents=200)
        self.assertFalse([a for a in bold['accents'] if a['y'] < 380 and all(math.hypot(a['x'] - x, a['y'] - y) > 30 for x, y in LAMPS)],
                         'bold keeps the lamps without the sprinkle of specks')

    def test_a_streak_is_a_glint_along_its_direction(self):
        sx, sy, angle = STREAK
        found = near(of(self.all, 'glints'), sx, sy, 5)
        self.assertEqual(len(found), 1, of(self.all, 'glints'))
        glint = found[0]
        dx, dy = glint['direction']
        self.assertLess(abs(abs(math.degrees(math.atan2(dy, dx)) % 180 - angle)), 12, glint['direction'])
        self.assertTrue(10 <= glint['length'] <= 22, glint['length'])
        self.assertGreater(luma(glint['colour']), 220)

    def test_thin_posts_and_wires_are_lines_in_their_own_colour_and_masses_are_never_outlined(self):
        lines = of(self.all, 'lines')
        def along(a, b):
            return [line for line in lines if np.mean([segment_distance(p, a, b) <= 3 for p in line['points']]) > 0.9
                    and math.hypot(line['points'][-1][0] - line['points'][0][0], line['points'][-1][1] - line['points'][0][1]) > 0.6 * math.hypot(b[0] - a[0], b[1] - a[1])]
        post = along(POST[:2], POST[2:])
        self.assertEqual(len(post), 1, 'the post is one line, not its two edges')
        self.assertLess(luma(post[0]['colour']), 40, 'a dark post keeps its darkness')
        wire = along(*WIRE)
        self.assertEqual(len(wire), 1)
        self.assertGreater(luma(wire[0]['colour']), 180)
        for line in lines:
            self.assertLessEqual(len(line['points']), accent_find.MAX_POINTS)
        x, y, w, h = FACADE
        border = [((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)), ((x, y + h), (x + w, y + h)), ((x, y), (x, y + h))]
        for line in lines:
            on_border = np.mean([min(segment_distance(p, a, b) for a, b in border) <= 4 for p in line['points']])
            self.assertLess(on_border, 0.5, 'a mass’s outline is never a line')
        self.assertFalse(near(of(self.all, 'lights'), x + w / 2, y + h / 2, 60), 'a lit mass is no light')

    def test_a_dark_gap_is_a_dark_in_its_darkest_colour(self):
        found = near(of(self.all, 'darks'), *GAP, 4)
        self.assertEqual(len(found), 1)
        self.assertLess(luma(found[0]['colour']), 45)
        self.assertEqual(found[0]['shape'], 'dot')

    def test_kinds_caps_and_a_source_crop(self):
        out = find_on_soft(self.image, [100, 80, 400, 200], kinds=['lights'], strength='subtle', max_accents=1)
        self.assertEqual({a['kind'] for a in out['accents']}, {'lights'})
        self.assertEqual(len(out['accents']), 1, 'at most max_accents a kind')
        a = out['accents'][0]
        self.assertTrue(100 <= a['x'] <= 500 and 80 <= a['y'] <= 280, (a['x'], a['y']))
        self.assertGreaterEqual(out['found']['lights'], 2, 'found counts every one above the strength')
        with self.assertRaises(ValueError):
            find_on_soft(self.image, [0, 0, 901, 800])
        with self.assertRaises(ValueError):
            find_on_soft(self.image, [0, 0, 900, 800], kinds=['outlines'])
        flat = np.full((300, 300, 4), 128, np.uint8)
        self.assertEqual(find_on_soft(flat, [0, 0, 300, 300])['accents'], [], 'a flat picture has no accents')

    def test_only_where_the_canvas_lacks_them_a_canvas_with_its_accents_gets_none(self):
        same = accent_find.find(self.image, [0, 0, 900, 800], strength='subtle', canvas=self.image.copy(), target=[0, 0, 900, 800])
        self.assertEqual(same['accents'], [], 'the canvas already has every accent: nothing to add')
        half = cv2.resize(self.image, (450, 400), interpolation=cv2.INTER_AREA)
        view = soft(half, 2)
        view[:, :225, :3] = half[:, :225, :3]                                         # the left half kept its accents
        out = accent_find.find(self.image, [0, 0, 900, 800], kinds=['lights'], strength='subtle', canvas=view, target=[0, 0, 450, 400])
        self.assertFalse(near(of(out, 'lights'), *LAMPS[0], 6), 'the left lamp is on the canvas already')
        self.assertTrue(near(of(out, 'lights'), *LAMPS[2], 6), 'the right lamp was blurred away: an accent')

    def test_a_repainted_area_gets_none_and_strength_is_the_residual(self):
        view = soft(self.image)
        view[:, 500:, :3] = (90, 160, 90)                                             # repainted flat: nothing sharp to restore
        out = accent_find.find(self.image, [0, 0, 900, 800], kinds=['lights'], strength='subtle', canvas=view, target=[0, 0, 900, 800])
        self.assertTrue(near(of(out, 'lights'), *LAMPS[0], 6))
        self.assertFalse(near(of(out, 'lights'), *LAMPS[2], 6), 'repainted where the right lamp was: no lamp there now')
        for accent in out['accents']:
            self.assertTrue(0 < accent['strength'] <= 1 and accent['residual'] >= accent_find.RESIDUAL_MIN)

    def test_without_a_canvas_view_it_refuses(self):
        with self.assertRaisesRegex(ValueError, 'canvas'):
            accent_find.find(self.image, [0, 0, 900, 800])

    def test_a_full_resolution_find_is_bounded(self):
        big = cv2.resize(self.image, (2400, 1600), interpolation=cv2.INTER_CUBIC)   # about four million pixels
        started = time.monotonic()
        out = find_on_soft(big, [0, 0, 2400, 1600], max_accents=1000, strength='subtle')
        self.assertLess(time.monotonic() - started, 20)
        self.assertLessEqual(max(out['found'].values()), accent_find.CANDIDATES)
        self.assertTrue(near(of(out, 'lights'), 150 * 2400 / 900, 120 * 2, 10), 'the same lamps at the larger size')


if __name__ == '__main__':
    unittest.main()


def night(width=900, height=800):
    img = np.zeros((height, width, 3), np.float32); img[:] = (40, 50, 90)
    return img


def as_rgba(img):
    out = np.empty(img.shape[:2] + (4,), np.uint8); out[..., :3] = np.clip(img, 0, 255); out[..., 3] = 255
    return out


class NoWeirdStrokesTests(unittest.TestCase):
    """The coordinator's review of the first renders: no floating or long glints, no wiggly lines, no speck darks."""

    def test_a_wiggly_dark_line_is_no_line_and_a_gently_curved_one_is(self):
        img = night()
        ys = np.arange(150, 650)
        wiggle = np.stack([300 + 7 * np.sin(ys / 9.0), ys], axis=1).astype(np.int32)       # zig-zags along its length
        cv2.polylines(img, [wiggle.reshape(-1, 1, 2)], False, (10, 10, 15), 2, cv2.LINE_AA)
        curve = np.stack([600 + 0.0008 * (ys - 400) ** 2, ys], axis=1).astype(np.int32)      # a gentle bow
        cv2.polylines(img, [curve.reshape(-1, 1, 2)], False, (10, 10, 15), 2, cv2.LINE_AA)
        out = find_on_soft(as_rgba(img), [0, 0, 900, 800], kinds=['lines'], strength='subtle')
        lines = of(out, 'lines')
        self.assertFalse([l for l in lines if np.mean([abs(p[0] - 300) < 15 for p in l['points']]) > 0.8], 'the wiggle is dropped')
        hook = night()
        cv2.polylines(hook, [np.array([[450, 650], [450, 300], [470, 260], [500, 240]], np.int32).reshape(-1, 1, 2)], False, (10, 10, 15), 2, cv2.LINE_AA)
        hooked = of(find_on_soft(as_rgba(hook), [0, 0, 900, 800], kinds=['lines'], strength='subtle'), 'lines')
        self.assertFalse([l for l in hooked if any(p[1] < 270 for p in l['points'])], 'a branch that hooks is no line: %s' % hooked)
        self.assertTrue([l for l in lines if np.mean([abs(p[0] - 600) < 80 for p in l['points']]) > 0.8], 'the gentle bow is kept')

    def test_long_streaks_are_ledges_not_glints_and_weakly_long_spots_are_lights(self):
        img = night()
        cv2.line(img, (100, 300), (190, 300), (250, 250, 250), 3, cv2.LINE_AA)            # a lit ledge: too long for a glint
        cv2.ellipse(img, (500, 300), (6, 4), 0, 0, 360, (250, 240, 200), -1, cv2.LINE_AA)    # barely elongated: a light
        cv2.line(img, (700, 296), (700, 310), (250, 250, 250), 2, cv2.LINE_AA)            # a short sharp streak: a glint
        out = find_on_soft(as_rgba(img), [0, 0, 900, 800], kinds=['lights', 'glints'], strength='subtle')
        self.assertFalse(near(of(out, 'glints'), 145, 300, 30), 'no glint along the ledge')
        self.assertTrue(near(of(out, 'lights'), 500, 300, 4) and not near(of(out, 'glints'), 500, 300, 6))
        glint = near(of(out, 'glints'), 700, 303, 5)
        self.assertEqual(len(glint), 1)
        self.assertGreater(abs(glint[0]['direction'][1]), 0.95, 'along the streak')

    def test_a_glint_is_no_whiter_than_its_core_in_the_reference(self):
        img = night()
        cv2.line(img, (450, 300), (450, 314), (200, 170, 120), 3, cv2.LINE_AA)            # a warm highlight
        cv2.line(img, (450, 305), (450, 309), (255, 255, 255), 1)                         # with one white pixel run
        out = find_on_soft(as_rgba(img), [0, 0, 900, 800], kinds=['glints'], strength='subtle')
        glint = near(of(out, 'glints'), 450, 307, 6)
        self.assertEqual(len(glint), 1)
        self.assertLess(luma(glint[0]['colour']), 235, 'its colour from the core, not its one whitest pixel')

    def test_glints_are_capped_per_area_so_they_never_sprinkle(self):
        img = night()
        for x in range(30, 880, 30):
            for y in range(30, 780, 30):
                cv2.line(img, (x, y), (x, y + 10), (240, 240, 230), 2, cv2.LINE_AA)
        out = find_on_soft(as_rgba(img), [0, 0, 900, 800], kinds=['glints'], strength='subtle', max_accents=1000)
        glints = of(out, 'glints')
        cells = {}
        for g in glints:
            key = (int(g['x'] // (900 / accent_find.GLINT_GRID)), int(g['y'] // (800 / accent_find.GLINT_GRID)))
            cells[key] = cells.get(key, 0) + 1
        self.assertLessEqual(max(cells.values()), accent_find.GLINTS_PER_CELL)

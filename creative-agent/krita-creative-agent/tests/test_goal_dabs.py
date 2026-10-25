# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Goal dabs (goal_dabs.py, openspec architecture-texture goal 9): a few impasto dabs cut from the goal at a part's found
area, cleaned into soft-edged alpha shapes, and the Finish's form strokes in that part stamped with them along their path
instead of a plain line: rougher edges, about the same covered area, strokes elsewhere unchanged, and fast. Pure numpy and
OpenCV on synthetic images; writes no files."""
import importlib
import math
import time
import unittest

import os

import cv2
import numpy as np
import test_finish_pass as finish_tests
from test_element_shapes import png

finish = finish_tests.finish
dabs = importlib.import_module(finish.__name__.rsplit('.', 1)[0] + '.goal_dabs')


def blobs(w=96, h=96, seed=4, count=14, base=110):
    """A goal crop of impasto: irregular dabs (each three overlapping ellipses), lighter or darker than the paint around
    them, a little noise (BGR uint8)."""
    rng = np.random.default_rng(seed)
    grey = np.full((h, w), base, np.float32) + rng.normal(0, 1.5, (h, w)).astype(np.float32)
    for _ in range(count):
        cx, cy = rng.uniform(8, w - 8), rng.uniform(8, h - 8)
        shape = np.zeros((h, w), np.uint8)
        for _part in range(3):
            centre = (int(cx + rng.uniform(-3, 3)), int(cy + rng.uniform(-3, 3)))
            axes = (int(rng.uniform(2, 5)), int(rng.uniform(1.5, 3.5)))
            cv2.ellipse(shape, centre, axes, float(rng.uniform(0, 180)), 0, 360, 255, -1)
        grey += (70 if rng.random() < 0.6 else -55) * cv2.GaussianBlur(shape.astype(np.float32) / 255, (0, 0), 0.8)
    return np.repeat(np.clip(grey, 0, 255)[..., None], 3, axis=2).astype(np.uint8)


def flat(w=96, h=96):
    rng = np.random.default_rng(1)
    return np.repeat(np.clip(140 + rng.normal(0, 1, (h, w)), 0, 255)[..., None], 3, 2).astype(np.uint8)


def perimeter_ratio(alpha):
    """Perimeter over area of where `alpha` (0-1) is at least half: higher is a rougher edge."""
    shape = (alpha >= 0.5).astype(np.uint8)
    contours, _ = cv2.findContours(shape, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return sum(cv2.arcLength(c, True) for c in contours) / max(1, int(shape.sum()))


class DabCutting(unittest.TestCase):
    def test_a_crop_of_dab_like_blobs_gives_soft_centred_dabs(self):
        found = dabs.cut_dabs(blobs())
        self.assertTrue(1 <= len(found) <= dabs.MOST_DABS, len(found))
        for alpha, contrast in found:
            self.assertEqual(alpha.shape, (dabs.TIP_SIDE, dabs.TIP_SIDE))
            self.assertEqual(alpha.dtype, np.float32)
            self.assertGreaterEqual(contrast, dabs.ENERGY_MIN)
            self.assertGreater(float(alpha.max()), 0.9, 'the dab is solid at its heart')
            self.assertLess(float(alpha.min()), 0.0 + 1e-6)
            self.assertEqual(float(np.abs(np.r_[alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]]).max()), 0.0, 'nothing at the tip edge')
            seen = alpha[alpha > 0.05]
            self.assertGreater(float(((seen > 0.05) & (seen < 0.95)).mean()), 0.1, 'a soft edge, not a cut-out')
            ys, xs = np.mgrid[:dabs.TIP_SIDE, :dabs.TIP_SIDE]
            centre = (dabs.TIP_SIDE - 1) / 2
            cx, cy = float((alpha * xs).sum() / alpha.sum()), float((alpha * ys).sum() / alpha.sum())
            self.assertLess(math.hypot(cx - centre, cy - centre), 0.08 * dabs.TIP_SIDE, 'centred')
            cover = float((alpha > 0.5).mean())
            self.assertTrue(0.05 < cover < 0.75, cover)

    def test_a_flat_crop_or_shading_gives_none(self):
        self.assertEqual(dabs.cut_dabs(flat()), [])
        shading = np.linspace(20, 230, 96, dtype=np.float32)[None, :, None].repeat(96, 0).repeat(3, 2).astype(np.uint8)
        self.assertEqual(dabs.cut_dabs(shading), [])
        self.assertEqual(dabs.cut_dabs(blobs()[:8, :8]), [], 'smaller than a patch')

    def test_the_mask_keeps_only_the_part(self):
        crop = blobs()
        crop[:, 48:] = 140                                  # the part: the right half, flat paint; the blobs are outside it
        mask = np.zeros(crop.shape[:2], np.uint8); mask[:, 48:] = 255
        self.assertEqual(dabs.cut_dabs(crop, mask), [])
        mask[:] = 0; mask[:, :48] = 255
        self.assertGreater(len(dabs.cut_dabs(crop, mask)), 0)

    def test_the_patch_follows_the_goals_enlargement(self):
        self.assertEqual(dabs.patch_for(4.0), dabs.DAB_CANVAS_PX // 4)
        self.assertEqual(dabs.patch_for(100.0), dabs.MIN_PATCH)
        self.assertEqual(dabs.patch_for(0.5), dabs.MAX_PATCH)


class DabStrokes(unittest.TestCase):
    def setUp(self):
        self.alphas = [a for a, _c in dabs.cut_dabs(blobs())]
        self.strips = dabs.strips(self.alphas)

    def test_a_stamped_stroke_has_a_rougher_edge_and_about_the_same_area(self):
        w = 24.0
        poly = np.array([[60.0 + i * 2, 80.0 + 0.05 * i] for i in range(61)])
        box = [0, 0, 320, 160]
        plain = finish.plain_mask(poly, w, box).astype(np.float32) / 255
        for variant in range(dabs.VARIANTS):
            stamped = dabs.dab_mask(poly, w, box, self.strips, variant)
            self.assertEqual(stamped.shape, plain.shape)
            area, ours = float(plain.sum()), float(stamped.sum())
            self.assertLess(abs(ours / area - 1), 0.3, 'covered area %.0f against %.0f' % (ours, area))
            self.assertGreater(perimeter_ratio(stamped), 1.15 * perimeter_ratio(plain), 'the edge breaks up')
            self.assertLess(float(stamped[:, :20].max()) + float(stamped[:, 300:].max()), 1e-6, 'nothing far past the ends')

    def test_a_turned_stroke_is_stamped_along_its_direction(self):
        poly = np.array([[100.0, 40.0 + i * 2] for i in range(41)])     # vertical
        stamped = dabs.dab_mask(poly, 16.0, [0, 0, 200, 160], self.strips, 0)
        rows, cols = np.nonzero(stamped > 0.5)
        self.assertGreater(np.ptp(rows), 3 * np.ptp(cols), 'long along the stroke, its width across')
        dot = dabs.dab_mask(np.array([[50.0, 50.0]]), 12.0, [0, 0, 100, 100], self.strips, 1)
        self.assertGreater(float(dot.max()), 0.5, 'a one-point stroke is one dab')

    def synthetic_tile(self):
        """A 512 px tile of a 6000 x 4500 canvas over a goal of busy 'building' blocks, padded as finish_tile reads it."""
        width, height = 6000, 4500
        size = finish.sizes(width, height, dabbed=True)
        tile = [1024, 1024, 512, 512]
        goal_rect = finish.grow(tile, size['goal_pad'], width, height)
        rng = np.random.default_rng(9)
        blocks = rng.integers(30, 225, (goal_rect[3] // 6 + 1, goal_rect[2] // 6 + 1, 3)).astype(np.uint8)
        goal = np.repeat(np.repeat(blocks, 6, 0), 6, 1)[:goal_rect[3], :goal_rect[2]].astype(np.float32) / 255
        hard = 1 - finish.soft_mask(goal, size)
        # The part: the tile's left half.
        mask = np.zeros((1024, 512), np.uint8); mask[:, :] = 255
        part = (mask, (768, 768, 512, 1024))
        return width, height, size, tile, goal, goal_rect, hard, part

    def test_strokes_outside_the_part_are_unchanged_and_inside_are_stamped(self):
        width, height, size, tile, goal, goal_rect, hard, (mask, rect) = self.synthetic_tile()
        limit = [0, 0, width, height]
        plain, count = finish.strokes_for(tile, goal, goal_rect, hard, limit, width, height, size)
        stamped, again = finish.strokes_for(tile, goal, goal_rect, hard, limit, width, height, size, dabs=[(mask, rect, self.strips)])
        self.assertEqual(count, again)
        edge = rect[0] + rect[2] - tile[0] + size['reach']               # past the part and the reach of its strokes
        self.assertTrue(np.array_equal(plain[:, edge:], stamped[:, edge:]), 'outside the part: the same strokes')
        inside = (slice(None), slice(0, rect[0] + rect[2] - tile[0] - size['reach']))
        self.assertGreater(float(np.abs(plain[inside] - stamped[inside]).mean()), 0.005, 'inside: stamped')
        a, b = float(plain[inside][..., 3].mean()), float(stamped[inside][..., 3].mean())
        self.assertLess(abs(b / a - 1), 0.3, 'the part stays as covered')
        none, _ = finish.strokes_for(tile, goal, goal_rect, hard, limit, width, height, size, dabs=[])
        self.assertTrue(np.array_equal(none, plain), 'no dabs: plain strokes')

    def test_the_dab_path_stays_within_one_and_a_half_times_the_plain_strokes(self):
        width, height, size, tile, goal, goal_rect, hard, (_mask, _rect) = self.synthetic_tile()
        whole = (np.full((1024, 1024), 255, np.uint8), (768, 768, 1024, 1024))     # every stroke of the tile stamped
        limit = [0, 0, width, height]

        def best(**extra):
            times = []
            for _ in range(3):
                started = time.perf_counter()
                finish.strokes_for(tile, goal, goal_rect, hard, limit, width, height, size, **extra)
                times.append(time.perf_counter() - started)
            return min(times)
        dabs.strips(self.alphas)                                           # built once a set (cached)
        plain, stamped = best(), best(dabs=[(whole[0], whole[1], self.strips)])
        self.assertLess(stamped, 1.5 * plain, 'dabs %.3f s against plain %.3f s' % (stamped, plain))


class DabFinishOperation(finish_tests.FinishOperationTests):
    """paint_finish with `dab`: the form strokes in the part are stamped with its goal dabs (named tips cut earlier),
    nothing changes outside it, an unknown tip leaves the plain strokes, a malformed entry is refused."""
    def setUp(self):
        super().setUp()
        dabs._MADE.clear()
        self.addCleanup(dabs._MADE.clear)
        for n, (alpha, _e) in enumerate(dabs.cut_dabs(blobs()), 1):
            dabs._MADE['Goal dab: church %d' % n] = alpha

    def shape(self, name, box):
        folder = os.path.join(self.h._creative_session['output'], '.shapes')
        os.makedirs(folder, exist_ok=True)
        x, y, w, h = box
        path = os.path.join(folder, 'found-%s.png' % name)
        with open(path, 'wb') as stream:
            stream.write(png(w, h, [bytes([255]) * w for _ in range(h)]))
        return {'mask_path': path, 'bounds': [x, y, w, h]}

    def strokes(self, result):
        group = self.h._creative_node(self.h.doc, result['layer_id'])
        return next(c for c in group.childNodes() if c.label.endswith('strokes')).data.astype(int)

    def undo(self, identifier):
        review = finish_tests.region_tests.run(self.h, 'review_pass', {'pass_id': identifier, 'action': 'reject'}, 'undo-' + identifier)
        self.assertEqual(review['status'], 'ok', review.get('error'))

    def test_form_strokes_in_the_part_are_stamped_with_its_dabs_and_nowhere_else(self):
        plain = self.run_finish('plain', box=[0, 0, 600, 400])
        self.assertEqual(plain['status'], 'ok', plain.get('error'))
        smooth = self.strokes(plain)
        self.undo('plain')
        entry = {'tips': sorted(dabs._MADE), 'inside_shape': self.shape('church', [450, 0, 150, 400])}
        stamped = self.run_finish('dabbed', box=[0, 0, 600, 400], dab=[entry])
        self.assertEqual(stamped['status'], 'ok', stamped.get('error'))
        self.assertEqual(stamped['finish']['dab_parts'], 1)
        rough = self.strokes(stamped)
        reach = finish.sizes(600, 400, dabbed=True)['reach']
        self.assertTrue((rough[:, :450 - reach] == smooth[:, :450 - reach]).all(), 'outside the part: the same strokes')
        self.assertGreater(int(np.abs(rough[:, 450 + reach:] - smooth[:, 450 + reach:]).sum()), 0, 'inside: stamped')
        self.undo('dabbed')
        unknown = self.run_finish('unknown', box=[0, 0, 600, 400], dab=[dict(entry, tips=['Goal dab: nothing 1'])])
        self.assertEqual(unknown['status'], 'ok', unknown.get('error'))
        self.assertNotIn('dab_parts', unknown['finish'])
        self.assertTrue((self.strokes(unknown) == smooth).all(), 'no usable dab: the plain strokes')
        for bad in ([dict(entry, tips='Goal dab: church 1')], [dict(entry, tips=[])], [dict(entry, extra=1)], {'tips': []}):
            with self.assertRaises(ValueError):
                self.run_finish('bad', box=[0, 0, 600, 400], dab=bad)


def load_tests(loader, tests, pattern):
    """This file's tests, without running the inherited finish tests again here."""
    own = [DabCutting, DabStrokes]
    suite = unittest.TestSuite([loader.loadTestsFromTestCase(case) for case in own])
    suite.addTests(DabFinishOperation(name) for name in sorted(vars(DabFinishOperation)) if name.startswith('test_'))
    return suite


if __name__ == '__main__':
    unittest.main()

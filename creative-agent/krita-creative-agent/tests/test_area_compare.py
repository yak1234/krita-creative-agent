# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""area_compare.py: the full-size checks for an area (openspec finish-stage goals 7-8): the area's difference to the goal
at full canvas resolution, paint_accents' finder there, and the refine map. Pure parts on numpy and OpenCV; the session
operations on the pixel layer tree of the accents tests. Files go to a temporary folder that is removed."""
import hashlib
import os
import sys
import unittest
import numpy as np
import cv2
import test_finish_pass as finish_tests

accent_tests = finish_tests.accent_tests
region_tests = finish_tests.region_tests
compare = sys.modules.get('creative_test_package.area_compare')
if compare is None:
    import importlib
    compare = importlib.import_module('creative_test_package.area_compare')


def windows(width, height, step=12, size=3):
    """A goal: a warm wall with small lit windows (size px) every `step` px, as the church's 2-4 px windows (BGR uint8)."""
    goal = np.zeros((height, width, 3), np.uint8); goal[:] = (70, 90, 120)
    for y in range(step // 2, height - size, step):
        for x in range(step // 2, width - size, step):
            goal[y:y + size, x:x + size] = (90, 210, 250)
    return goal


def blobby(goal, sigma=3):
    """The goal painted with strokes too wide for it: blurred."""
    return cv2.GaussianBlur(goal, (0, 0), sigma)


class MeasureTests(unittest.TestCase):
    def setUp(self):
        self.goal = windows(300, 200)

    def run_measure(self, canvas, rect, **extra):
        read = lambda r: canvas[r[1]:r[1] + r[3], r[0]:r[0] + r[2]]
        goal = lambda r: self.goal[r[1]:r[1] + r[3], r[0]:r[0] + r[2]]
        return compare.measure(read, goal, rect, 6000, 4500, **extra)

    def test_a_canvas_blurred_at_the_goals_detail_size_measures_far_the_goal_itself_zero(self):
        far = self.run_measure(blobby(self.goal), [0, 0, 300, 200])
        self.assertGreater(far['colour'], 2); self.assertGreater(far['edges'], 1)
        same = self.run_measure(self.goal, [0, 0, 300, 200])
        self.assertEqual((same['colour'], same['edges']), (0, 0))
        self.assertEqual(far['pixels'], 300 * 200)

    def test_the_squares_never_change_the_numbers(self):
        canvas = blobby(self.goal)
        one = self.run_measure(canvas, [10, 20, 250, 170], tile=1024)
        many = self.run_measure(canvas, [10, 20, 250, 170], tile=64)
        self.assertAlmostEqual(one['colour'], many['colour'], places=2); self.assertAlmostEqual(one['edges'], many['edges'], places=2)

    def test_the_refine_map_ranks_the_blobby_cells_first(self):
        canvas = self.goal.copy(); canvas[:, 150:] = blobby(self.goal)[:, 150:]
        mapped = self.run_measure(canvas, [0, 0, 300, 200], cell=50, tile=64)
        self.assertEqual(len(mapped['cells']), 6 * 4)
        self.assertTrue(all(c['rect'][0] >= 150 for c in mapped['cells'][:12]), 'the right half first')
        self.assertLess(mapped['cells'][-1]['score'], 0.5)
        self.assertEqual([c['rect'] for c in mapped['cells'] if c['rect'][:2] == [0, 0]], [[0, 0, 50, 50]])

    def test_blurs_scale_with_the_canvas(self):
        self.assertEqual(compare.blurs(6000, 4500), (2.0, 1.0))
        self.assertEqual(compare.blurs(12000, 9000), (4.0, 2.0))
        self.assertEqual(compare.blurs(600, 450), (1.0, 0.7))


class FindTests(unittest.TestCase):
    def test_the_windows_the_canvas_lacks_are_found_at_their_real_size_and_none_where_it_has_them(self):
        goal = windows(240, 180)
        found = compare.find_on(goal, blobby(goal), ['lights'], 'subtle', 400)
        self.assertGreater(found['found']['lights'], 50, found['found'])
        a = found['accents'][0]
        self.assertTrue(abs((a['x'] - 6 - 1.5) % 12) < 2.5 or abs((a['x'] - 6 - 1.5) % 12) > 9.5, a)
        self.assertLess(a['size'], 6, 'a window, not a blob')
        self.assertEqual(compare.find_on(goal, goal, ['lights'], 'subtle', 400)['found']['lights'], 0)

    def test_accents_of_a_reduced_area_come_back_in_canvas_pixels(self):
        accents = [{'kind': 'lines', 'x': 10, 'y': 20, 'size': 2, 'length': 30, 'points': [[0, 0], [10, 20]]}]
        out = compare.to_canvas(accents, [100, 200, 400, 400], 0.5)
        self.assertEqual((out[0]['x'], out[0]['y'], out[0]['size'], out[0]['length']), (120, 240, 4, 60))
        self.assertEqual(out[0]['points'], [[100, 200], [120, 240]])


class AreaOperationTests(finish_tests.SpikeScale, region_tests.RegionSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.h = accent_tests.filter_tests.Harness(self.h._creative_session['output'])
        doc = self.h.doc = finish_tests.FinishDocument(600, 400)
        self.h._creative_session.update(document_id=accent_tests.filter_tests.native.module.document_id(doc), width=600, height=400)
        base = doc.createNode('Underpainting', 'paintlayer'); doc.root.addChildNode(base, None)
        self.goal = windows(600, 400)
        base.data[...] = np.dstack([blobby(self.goal), np.full((400, 600), 255, np.uint8)])
        base.data[:, :300, :3] = self.goal[:, :300]                     # the left half already as the goal
        self.base = base
        data = cv2.imencode('.png', self.goal)[1].tobytes()
        path = os.path.join(self.h._creative_session['output'], 'goal.png')
        with open(path, 'wb') as stream:
            stream.write(data)
        self.spec = {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': [600, 400], 'source': [0, 0, 600, 400], 'target': [0, 0, 600, 400]}

    def run_op(self, operation, **params):
        return region_tests.run(self.h, operation, dict({'goal': self.spec}, **params))

    def test_area_likeness_measures_an_area_at_full_size_reading_only_around_it(self):
        right = self.run_op('area_likeness', rect=[350, 100, 200, 200])
        left = self.run_op('area_likeness', rect=[50, 100, 200, 200])
        self.assertEqual(right['status'], 'ok', right.get('error'))
        self.assertGreater(right['colour'], 2); self.assertLess(left['colour'], 0.5)
        self.assertEqual(right['rect'], [350, 100, 200, 200])
        self.assertTrue(all(x >= 340 and x + w <= 560 for x, _y, w, _h in self.h.doc.reads[:1]), self.h.doc.reads)

    def test_area_accents_finds_the_windows_in_canvas_pixels_inside_the_area_only(self):
        result = self.run_op('area_accents', rect=[300, 100, 200, 200], kinds=['lights'], strength='subtle', max_accents=400)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['scale'], 1)
        self.assertGreater(len(result['accents']), 50)
        self.assertTrue(all(300 <= a['x'] <= 500 and 100 <= a['y'] <= 300 for a in result['accents']))
        none = self.run_op('area_accents', rect=[50, 100, 200, 200], kinds=['lights'], strength='subtle', max_accents=400)
        self.assertEqual(len(none['accents']), 0, 'the left half already has its windows')

    def test_a_large_area_is_reduced_for_the_finder_and_still_answers_in_canvas_pixels(self):
        previous = compare.AREA_PIXELS
        compare.AREA_PIXELS = 100 * 100
        self.addCleanup(setattr, compare, 'AREA_PIXELS', previous)
        result = self.run_op('area_accents', rect=[300, 0, 300, 400], kinds=['lights'], strength='subtle', max_accents=400)
        self.assertLess(result['scale'], 0.6)
        self.assertTrue(all(300 <= a['x'] <= 600 for a in result['accents']))

    def test_the_refine_map_ranks_the_canvas_by_what_is_left(self):
        result = self.run_op('refine_map', cell=100)
        self.assertEqual(len(result['cells']), 24)
        self.assertTrue(all(c['rect'][0] >= 300 for c in result['cells'][:12]), [c['rect'] for c in result['cells'][:12]])

    def test_nothing_is_written_and_guides_are_left_out(self):
        guides = self.h.doc.createNode('Guides', 'grouplayer'); self.h.doc.root.addChildNode(guides, None)
        line = self.h.doc.createNode('Guide', 'paintlayer'); guides.addChildNode(line, None)
        line.data[:, :, :] = (255, 0, 255, 255)
        self.h._guide_group = lambda doc, session=None, create=False: guides
        before = [c.label for c in self.h.doc.root.childNodes()]
        left = self.run_op('area_likeness', rect=[50, 100, 200, 200])
        self.assertLess(left['colour'], 0.5, 'the magenta guide is not read')
        self.assertTrue(guides.visible(), 'shown again')
        self.assertEqual([c.label for c in self.h.doc.root.childNodes()], before)

    def test_a_goal_outside_the_chat_folder_or_an_area_off_the_goal_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'outside where the goal sits'):
            self.run_op('area_likeness', goal=dict(self.spec, target=[0, 0, 300, 200]), rect=[400, 300, 100, 100])
        with self.assertRaisesRegex(ValueError, 'chat folder'):
            self.run_op('area_likeness', goal=dict(self.spec, path='/tmp/elsewhere.png'), rect=[0, 0, 10, 10])


if __name__ == '__main__':
    unittest.main()

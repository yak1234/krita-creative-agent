"""stage_mask.py: the mask a paint pass's region clips to. A hard 255 rectangle cut strokes that ran past it along a
dead-straight line: the fork's first Agent-mode chat (19 October, "Cloud field veil — upper left sky", region
[250, 250, 2000, 1050]) printed a soft band with straight top and bottom edges into the sky. Writes no files."""
import importlib.util
import pathlib
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('stage_mask', pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp/stage_mask.py')
stage_mask = importlib.util.module_from_spec(spec); spec.loader.exec_module(stage_mask)


class StageMaskTest(unittest.TestCase):
    def test_inner_edges_fade_in_and_the_middle_is_full(self):
        m = stage_mask.mask([250, 250, 2000, 1050], 6000, 4500)
        self.assertEqual(m.shape, (1050, 2000))
        self.assertEqual(m.dtype, np.uint8)
        self.assertEqual(m[525, 1000], 255)
        for edge in (m[0, 1000], m[-1, 1000], m[525, 0], m[525, -1]):
            self.assertLess(edge, 16)                         # no straight cut at full strength

    def test_fade_rises_steadily_from_the_edge(self):
        m = stage_mask.mask([250, 250, 2000, 1050], 6000, 4500)
        column = m[:stage_mask.FEATHER + 1, 1000].astype(int)
        self.assertTrue(np.all(np.diff(column) >= 0))
        self.assertEqual(column[-1], 255)

    def test_edges_on_the_canvas_border_stay_full(self):
        m = stage_mask.mask([0, 0, 6000, 1700], 6000, 4500)    # a full-width sky pass reaches the frame
        self.assertEqual(m[0, 3000], 255)
        self.assertEqual(m[850, 0], 255)
        self.assertEqual(m[850, -1], 255)
        self.assertLess(m[-1, 3000], 16)                      # only its lower edge is inside the painting

    def test_nothing_outside_the_region(self):
        m = stage_mask.mask([100, 40, 300, 200], 1000, 800)
        self.assertEqual(m.shape, (200, 300))                 # the mask covers the region and no more

    def test_small_region_keeps_a_full_core(self):
        m = stage_mask.mask([10, 10, 40, 24], 1000, 800)
        self.assertEqual(m[12, 20], 255)
        self.assertLess(m[0, 20], 255)

    def test_whole_canvas_region_is_all_full(self):
        self.assertTrue(np.all(stage_mask.mask([0, 0, 640, 480], 640, 480) == 255))


if __name__ == '__main__':
    unittest.main()

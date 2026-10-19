"""selection_edges.py: straight edges of a selection that cut through open paint (run 10-12: a seeded sky selection
clipped by a rectangle, or stopped at a pasted panel, printed its straight edge as a 'flat block' Luna undid).
Synthetic masks and images; writes no files."""
import importlib.util
import pathlib
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('selection_edges', pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp/selection_edges.py')
edges = importlib.util.module_from_spec(spec); spec.loader.exec_module(edges)

W, H = 400, 300


def sky(building_from=None):
    """BGRA: a smooth sky gradient; below `building_from` a dark building."""
    img = np.zeros((H, W, 4), np.uint8)
    for y in range(H):
        img[y, :, :3] = (150 - y // 6, 90 - y // 10, 40)
    img[..., 3] = 255
    if building_from is not None:
        img[building_from:, :, :3] = (20, 25, 30)
    return img


def mask(rows=None, cols=None):
    m = np.zeros((H, W), np.uint8)
    m[rows or slice(None), cols or slice(None)] = 255
    return m


def find(m, img, rect=(0, 0, W, H), **kw):
    return edges.open_edges(m.tobytes(), img.tobytes(), rect, (W, H), **kw)


class OpenEdgeTests(unittest.TestCase):
    def test_a_selection_cut_off_in_open_sky_has_an_open_straight_edge(self):
        found = find(mask(rows=slice(0, 120)), sky())
        self.assertEqual(len(found), 1, found)
        self.assertEqual({k: found[0][k] for k in ('edge', 'at', 'from', 'to')}, {'edge': 'horizontal', 'at': 120, 'from': 0, 'to': W})

    def test_a_straight_edge_along_a_real_object_is_fine(self):
        self.assertEqual(find(mask(rows=slice(0, 120)), sky(building_from=120)), [], 'a flat roofline: different paint on each side')

    def test_the_canvas_border_is_never_an_edge(self):
        self.assertEqual(find(mask(), sky()), [])

    def test_a_vertical_cut_is_found_too(self):
        found = find(mask(cols=slice(0, 250)), sky())
        self.assertEqual([(e['edge'], e['at'], e['from'], e['to']) for e in found], [('vertical', 250, 0, H)])

    def test_a_round_selection_has_no_long_straight_edge(self):
        yy, xx = np.mgrid[:H, :W]
        disc = (((xx - 200) ** 2 + (yy - 150) ** 2) < 120 ** 2).astype(np.uint8) * 255
        self.assertEqual(find(disc, sky()), [])

    def test_short_straight_runs_below_the_minimum_are_ignored(self):
        m = mask(rows=slice(0, 120)); m[:, 15:] = 0                # a 15 px wide strip: its bottom edge is short
        self.assertEqual([e for e in find(m, sky()) if e['edge'] == 'horizontal'], [])

    def test_coordinates_are_in_canvas_pixels_for_a_partial_rect(self):
        # The caller passes the selection's rect grown by a pixel (inside the canvas), with mask and image of that rect.
        rect = (0, 0, W, 200)
        found = find(mask(rows=slice(0, 120))[:200], sky()[:200], rect=rect)
        self.assertEqual([(e['at'], e['to']) for e in found], [(120, W)])

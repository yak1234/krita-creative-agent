"""seams.py: straight joins baked into a painting (pasted panels, upscaling tiles), the candidates Luna then confirms
from a close-up. Synthetic images; crops go to a temporary folder that is removed."""
import importlib.util
import os
import pathlib
import tempfile
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('seams', pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp/seams.py')
seams = importlib.util.module_from_spec(spec); spec.loader.exec_module(seams)

W, H = 3000, 2000


def painting(panel=None, step=8, wall=None):
    """BGRA: a softly textured sky gradient; `panel` (x0, y0, x1, y1) pasted `step` levels brighter;
    `wall` (y) a dark building from that row down: a strong object edge, not a seam."""
    rng = np.random.default_rng(3)
    yy = np.arange(H)[:, None]
    base = 60 + yy * 40 / H + rng.normal(0, 2.0, (H, W))
    img = np.repeat(base[..., None], 3, axis=2)
    if panel:
        x0, y0, x1, y1 = panel
        img[y0:y1, x0:x1] += step
    if wall is not None:
        img[wall:] = 15
    out = np.empty((H, W, 4), np.uint8); out[..., :3] = img.clip(0, 255); out[..., 3] = 255
    return out


class SeamTests(unittest.TestCase):
    def test_a_pasted_panel_gives_its_straight_edges_in_canvas_pixels(self):
        found = seams.candidates(painting(panel=(600, 400, 1800, 1200)))
        lines = {(c['axis'], c['at']) for c in found}
        for axis, at in (('h', 400), ('h', 1200), ('v', 600), ('v', 1800)):
            self.assertTrue(any(a == axis and abs(p - at) <= 8 for a, p in lines), (axis, at, found))
        top = next(c for c in found if c['axis'] == 'h' and abs(c['at'] - 400) <= 8)
        self.assertLess(abs(top['from'] - 600), 60); self.assertLess(abs(top['to'] - 1800), 60)

    def test_a_seamless_painting_has_none(self):
        self.assertEqual(seams.candidates(painting()), [])

    def test_a_strong_object_edge_is_not_a_seam(self):
        self.assertEqual(seams.candidates(painting(wall=1400)), [], 'a building against the sky: a big step, not a faint join')

    def test_each_candidate_gets_a_close_up_with_the_line_across_its_middle(self):
        img = painting(panel=(600, 400, 1800, 1200))
        found = seams.candidates(img)
        with tempfile.TemporaryDirectory() as folder:
            cut = seams.close_ups(img, found, folder)
            self.assertEqual(len(cut), len(found))
            for c in cut:
                self.assertTrue(os.path.isfile(c['crop']))
                self.assertLessEqual(max(c['crop_size']), seams.CROP_SIDE)

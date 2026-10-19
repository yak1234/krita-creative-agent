import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'krita-plugin/kritamcp'))
from geometry_data import bounds,curve
class GeometryTests(unittest.TestCase):
    def test_exact_image_edges(self):
        self.assertEqual(bounds([0,0,640,480],640,480),(0,0,640,480))
    def test_reject_bad_crop_before_export(self):
        for v in [[-1,0,4,4],[0,0,0,4],[0,0,641,480],[.5,0,4,4],[True,0,4,4],[0,0,float('nan'),4]]:
            with self.assertRaises(ValueError): bounds(v,640,480)
    def test_multi_segment_curve_and_late_invalid_segment(self):
        start,parts=curve([0,0],[[1,2,3,4,5,6],[6,7,8,9,10,11]])
        self.assertEqual(parts[-1][-2:],(10,11))
        with self.assertRaises(ValueError):curve([0,0],[[1,2,3,4,5,6],[1,2,3]])
        with self.assertRaises(ValueError):curve([0,0],[[1,2,3,4,5,float('inf')]])

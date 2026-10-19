import importlib.util
from pathlib import Path
import unittest
spec = importlib.util.spec_from_file_location('stroke_data', Path(__file__).parents[1] / 'krita-plugin/kritamcp/stroke_data.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class StrokeValidation(unittest.TestCase):
    def test_legacy_path(self):
        points, explicit = m.normalize_stroke({'points': [[0, 0], [5, 10]]})
        self.assertFalse(explicit)
        self.assertEqual(points[-1], (5, 10, 1))
    def test_scalar_and_profile(self):
        for pressure, expected in [(.4, [.4,.4]), ([.9,.05], [.9,.05])]:
            points, explicit = m.normalize_stroke({'points': [[0,0],[5,10]], 'pressure': pressure})
            self.assertTrue(explicit)
            self.assertEqual([p[2] for p in points], expected)
    def test_point_pressure_overrides_scalar(self):
        points, _ = m.normalize_stroke({'points': [[0,0,.8],[3,4,0]], 'pressure': .5})
        self.assertEqual([p[2] for p in points], [.8,0])
    def test_reject_entire_invalid_stroke(self):
        bad = [dict(points=[[0,0]]),dict(points=[[0,0],[1,2]],pressure=[.5]),
               dict(points=[[0,0],[1,2,1.1]]),dict(points=[[0,0],[float('nan'),1]]),
               dict(points=[[0,0],[1,2]],pressure=-1)]
        for params in bad:
            with self.subTest(params=params), self.assertRaises(ValueError):
                m.normalize_stroke(params)

if __name__ == '__main__': unittest.main()

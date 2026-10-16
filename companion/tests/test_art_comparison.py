import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / 'scripts/compare-stage-one.py'
spec = importlib.util.spec_from_file_location('art_comparison', path)
comparison = importlib.util.module_from_spec(spec); spec.loader.exec_module(comparison)


class Pixels:
    size = (4, 4)
    def __init__(self, changes=None):
        self.values = [(80,80,80,255)]*16
        for index, value in (changes or {}).items(): self.values[index] = value
    def convert(self, _mode): return self
    def getdata(self): return self.values


class ArtComparisonTests(unittest.TestCase):
    def test_inside_change_is_measured_without_claiming_artistic_success(self):
        result = comparison.pixel_checks(Pixels(), Pixels({5:(84,78,80,255)}), [1,1,2,2])
        self.assertEqual(result['inside_changed_pixels'], 1)
        self.assertEqual(result['outside_changed_pixels'], 0)
        self.assertTrue(result['protected_pixels_unchanged'])
        self.assertIsNone(result['artistic_success'])

    def test_single_pixel_outside_including_alpha_fails_preservation(self):
        result = comparison.pixel_checks(Pixels(), Pixels({0:(80,80,80,254)}), [1,1,2,2])
        self.assertFalse(result['protected_pixels_unchanged'])
        self.assertEqual(result['outside_changed_pixels'], 1)


if __name__ == '__main__': unittest.main()

"""protection_raster with real Qt. test_native.py replaces PyQt5 with stubs in this process, so each check runs
in a child Python with the plugin folder on its path. Writes no files."""
import json
import pathlib
import subprocess
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'plugin/kritamcp'
# A 4x2 BGRA image, every pixel opaque enough to see (alpha 200), and a mask with soft values around one half.
SETUP = '''
import sys, json
sys.path.insert(0, %r)
import protection_raster as r
W, H = 4, 2
mask = bytes([255, 128, 127, 0, 255, 0, 0, 0])
image = bytes(b for i in range(W * H) for b in (10 + i, 20 + i, 30 + i, 200))
''' % str(PLUGIN)


def run(body):
    done = subprocess.run([sys.executable, '-c', SETUP + body], capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise AssertionError(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else 'child failed')
    return json.loads(done.stdout)


class ProtectionRasterTests(unittest.TestCase):
    def test_erase_inside_scales_alpha_by_the_mask(self):
        out = run('pixels, removed = r.erase_inside(image, mask, W, H)\n'
                  'print(json.dumps({"alpha": list(pixels[3::4]), "colour": list(pixels[0::4]), "removed": removed}))')
        self.assertEqual(out['alpha'][0], 0, 'fully protected: erased')
        self.assertEqual(out['alpha'][3], 200, 'unprotected: untouched')
        self.assertEqual(out['alpha'][1], 0, 'inside from half coverage: cleared, so the backstop and the erase agree')
        self.assertLessEqual(abs(out['alpha'][2] - round(200 * 128 / 255)), 1, 'the soft band below half: scaled')
        self.assertEqual(out['colour'], [10 + i for i in range(8)], 'colour bytes never change')
        self.assertEqual(out['removed'], 3, 'opaque pixels at mask >= 128')

    def test_changed_inside_ignores_soft_edges_below_half(self):
        out = run('edge = bytearray(image); edge[2 * 4] = 99\n'      # only the mask-127 pixel changes
                  'inside = bytearray(image); inside[1 * 4 + 1] = 0\n'  # the mask-128 pixel changes
                  'print(json.dumps([r.changed_inside(image, bytes(edge), mask, W, H),'
                  ' r.changed_inside(image, bytes(inside), mask, W, H), r.changed_inside(image, image, mask, W, H)]))')
        self.assertEqual(out, [0, 1, 0])

    def test_union_is_the_maximum(self):
        out = run('print(json.dumps(list(r.union([mask, bytes([0, 200, 200, 7, 0, 0, 0, 255])], W, H))))')
        self.assertEqual(out, [255, 200, 200, 7, 255, 0, 0, 255])

    def test_inside_count_and_invert(self):
        out = run('print(json.dumps([r.inside_count(mask), list(r.invert(mask))]))')
        self.assertEqual(out, [3, [0, 127, 128, 255, 0, 255, 255, 255]])


    def test_a_soft_edge_erase_leaves_nothing_the_backstop_counts(self):
        out = run('pixels, _ = r.erase_inside(image, mask, W, H)\n'
                  'print(json.dumps(r.visible_inside(pixels, mask)))')
        self.assertEqual(out, 0)

    def test_keep_alpha_multiplies_softly(self):
        out = run('print(json.dumps(list(r.keep_alpha(image, mask, W, H)[3::4])))')
        self.assertEqual(out[0], 200); self.assertEqual(out[3], 0)
        self.assertLessEqual(abs(out[1] - round(200 * 128 / 255)), 1)

    def test_restore_inside_puts_back_the_earlier_pixels_only_inside(self):
        out = run('later = bytes([1, 2, 3, 255]) * (W * H)\n'
                  'print(json.dumps(list(r.restore_inside(later, image, mask, W, H))))')
        pixel = lambda i: out[i * 4:i * 4 + 4]
        self.assertEqual(pixel(0), [10, 20, 30, 200], 'inside: the earlier pixel')
        self.assertEqual(pixel(1), [11, 21, 31, 200], 'inside from half coverage')
        self.assertEqual(pixel(2), [1, 2, 3, 255], 'the soft band keeps the new paint')
        self.assertEqual(pixel(3), [1, 2, 3, 255], 'outside: the new paint')

    def test_visible_inside_counts_opaque_pixels_at_half_or_more(self):
        out = run('print(json.dumps(r.visible_inside(image, mask)))')
        self.assertEqual(out, 3)

if __name__ == '__main__':
    unittest.main()

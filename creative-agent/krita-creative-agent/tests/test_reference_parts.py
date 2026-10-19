"""reference_parts with real Qt, in a child Python (test_native.py stubs PyQt5 in this process). The plugin folder is
loaded as a package so the module's relative imports work. Writes no files."""
import json
import pathlib
import subprocess
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
# A 3x2 reference that has its own transparency in one pixel, and a soft selection.
SETUP = '''
import sys, json, types
package = types.ModuleType('plugin'); package.__path__ = [%r]; sys.modules['plugin'] = package
import plugin.reference_parts as r
W, H = 3, 2
image = bytes([10, 20, 30, 255,  11, 21, 31, 128,  12, 22, 32, 255,
               13, 23, 33, 255,  14, 24, 34, 255,  15, 25, 35, 255])
mask = bytes([255, 255, 0,  128, 0, 0])
''' % str(PLUGIN)


def run(body):
    done = subprocess.run([sys.executable, '-c', SETUP + body], capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise AssertionError(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else 'child failed')
    return json.loads(done.stdout)


class ReferencePartTests(unittest.TestCase):
    def test_part_keeps_size_and_multiplies_alpha(self):
        out = run('part = r.part_image(image, mask, W, H)\n'
                  'print(json.dumps({"size": len(part), "alpha": list(part[3::4]), "colour": list(part[0::4])}))')
        self.assertEqual(out['size'], len(b'x' * 24), 'the size of the original')
        self.assertEqual(out['alpha'][:3], [255, 128, 0], "selected: the reference's own alpha; unselected: clear")
        self.assertLessEqual(abs(out['alpha'][3] - 128), 1, 'a soft selection edge is soft')
        self.assertEqual(out['colour'], [10, 11, 12, 13, 14, 15], 'colour bytes unchanged')

    def test_crop_is_clipped_to_the_image(self):
        out = run('pixels, rect = r.crop_image(image, W, H, [1, 1, 5, 5])\n'
                  'print(json.dumps({"rect": rect, "pixels": list(pixels)}))')
        self.assertEqual(out['rect'], [1, 1, 2, 1])
        self.assertEqual(out['pixels'], [14, 24, 34, 255, 15, 25, 35, 255])

    def test_opaque_bounds_of_an_empty_part_is_none(self):
        out = run('print(json.dumps([r.opaque_bounds(r.part_image(image, mask, W, H), W, H),'
                  ' r.opaque_bounds(r.part_image(image, bytes(6), W, H), W, H)]))')
        self.assertEqual(out, [[0, 0, 2, 2], None])


if __name__ == '__main__':
    unittest.main()

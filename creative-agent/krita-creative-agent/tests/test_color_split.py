"""color_split with real Qt. test_native.py replaces PyQt5 with stubs in this process, so each check runs
in a child Python with the plugin folder on its path. Writes no files."""
import json
import pathlib
import subprocess
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
# An 8x4 BGRA image of three flat colours (red, green, blue columns) and a transparent last row.
SETUP = '''
import sys, json, time, random
package = __import__('types').ModuleType('kritamcp_child'); package.__path__ = [%r]; sys.modules['kritamcp_child'] = package
from kritamcp_child.qt_compat import QApplication
app = QApplication.instance() or QApplication([])
import kritamcp_child.color_split as c
W, H = 8, 4
def pixel(x, y):
    if y == 3: return (0, 0, 0, 0)
    return [(30, 30, 220, 255), (40, 200, 40, 255), (210, 50, 20, 255)][min(2, x // 3)]   # BGRA
image = bytes(b for y in range(H) for x in range(W) for b in pixel(x, y))
''' % str(PLUGIN)


def run(body, timeout=120):
    done = subprocess.run([sys.executable, '-c', SETUP + body], capture_output=True, text=True, timeout=timeout)
    if done.returncode:
        raise AssertionError(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else 'child failed')
    return json.loads(done.stdout)


class ColorSplitTests(unittest.TestCase):
    def test_palette_finds_the_main_colours(self):
        out = run('print(json.dumps(c.palette(image, W, H, 3)))')
        wanted = [(220, 30, 30), (40, 200, 40), (20, 50, 210)]                                        # RGB
        self.assertEqual(len(out), 3)
        for colour in wanted:
            self.assertTrue(any(all(abs(a - b) <= 8 for a, b in zip(colour, found)) for found in out), (colour, out))

    def test_assign_and_masks_partition_the_pixels(self):
        out = run('p = c.palette(image, W, H, 3); i = c.assign(image, W, H, p); m = c.masks(i, 3)\n'
                  'print(json.dumps({"indices": list(i), "masks": [list(x) for x in m], "palette": p}))')
        self.assertEqual(len(out['indices']), 32)
        self.assertEqual(out['indices'][24:], [255] * 8, 'transparent pixels belong to no colour')
        for k in range(32):
            covering = [m[k] for m in out['masks']].count(255)
            self.assertEqual(covering, 0 if k >= 24 else 1, k)
        self.assertEqual(len({out['indices'][0], out['indices'][4], out['indices'][7]}), 3, 'three columns, three colours')

    def test_bounds_and_counts_of_a_mask(self):
        out = run('m = bytes([0] * 8 + [0, 255, 255, 0, 0, 0, 0, 0] + [0, 0, 0, 255, 0, 0, 0, 0] + [0] * 8)\n'
                  'print(json.dumps(c.extent(m, W, H)))')
        self.assertEqual(out, [[1, 1, 3, 2], 3])

    def test_crop_and_one_mask_at_a_time(self):
        out = run('i = c.assign(image, W, H, c.palette(image, W, H, 3)); k = i[0]\n'
                  'm = c.mask(i, k)\n'
                  'print(json.dumps({"same": m == c.masks(i, 3)[k], "crop": list(c.crop(m, W, [0, 0, 3, 2])),'
                  ' "pixels": list(c.crop(image, W, [1, 1, 1, 1], 4))}))')
        self.assertTrue(out['same'])
        self.assertEqual(out['crop'], [255] * 6, 'the first three columns of the top two rows are that colour')
        self.assertEqual(out['pixels'], [30, 30, 220, 255])

    def test_a_full_size_split_takes_seconds(self):
        out = run('''
random.seed(1)
W, H = 6000, 4500
# Hundreds of thousands of distinct colours, as in a painting: Qt's nearest-colour cache cannot shortcut it.
rows = [bytes(b for x in range(W) for b in ((x * 7 + y) % 256, (x // 3 + y * 5) % 256, (x + y // 2) % 256, 255)) for y in range(64)]
noisy = b''.join(rows[y % 64] for y in range(H))
start = time.monotonic()
p = c.palette(bytes(noisy), W, H, 8); i = c.assign(bytes(noisy), W, H, p); m = c.masks(i, len(p))
e = [c.extent(x, W, H) for x in m]
print(json.dumps({"seconds": time.monotonic() - start, "colours": len(p)}))
''', timeout=300)
        self.assertLess(out['seconds'], 5, out)


if __name__ == '__main__':
    unittest.main()

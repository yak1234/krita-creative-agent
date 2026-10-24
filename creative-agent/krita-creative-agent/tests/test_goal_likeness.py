# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""likeness_grid: the goal-likeness check's small, blurred CIE Lab copy of an image crop (goal_likeness.py). The goal
reference and each canvas view are reduced to the same grid, so the companion compares them cell by cell where brushwork
texture no longer counts. Runs real Qt in a child process (the other plugin tests stub Qt in this one), under PyQt5 and,
when the test runs with it, PyQt6. Images are made in memory; nothing is written to disk."""
import json
import pathlib
import subprocess
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
SETUP = '''
import sys, json, base64, hashlib, time
import numpy as np, cv2
package = __import__('types').ModuleType('kritamcp_child'); package.__path__ = [%r]; sys.modules['kritamcp_child'] = package
from kritamcp_child.qt_compat import QApplication
app = QApplication.instance() or QApplication([])
import kritamcp_child.goal_likeness as g
def flat(w, h, rgb):
    out = np.zeros((h, w, 3), np.uint8); out[:] = rgb; return out
def dabs(w, h, rgb, spread=40, size=9, seed=1):
    """rgb laid as round dabs of +-spread around it (a transfer's texture), whose mean is rgb."""
    rng = np.random.default_rng(seed); out = flat(w, h, rgb)
    for _ in range(w * h // (size * size // 2)):
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h)); d = rng.integers(-spread, spread + 1, 3)
        cv2.circle(out, (x, y), size // 2, [int(v) for v in np.clip(np.array(rgb) + d, 0, 255)], -1, cv2.LINE_AA)
    return out
def encode(rgb, ext='.png'):
    ok, data = cv2.imencode(ext, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)); return bytes(data)
def ask(data, **extra):
    try:
        got = g.likeness_grid(dict({'image_base64': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()}, **extra))
        lab = np.frombuffer(base64.b64decode(got['lab_base64']), '<f4').reshape(got['grid'][1], got['grid'][0], 3)
        return got, lab
    except ValueError as error:
        return {'error': str(error)}, None
def de(a, b):
    return float(np.sqrt(((a - b) ** 2).sum(-1)).mean())
''' % str(PLUGIN)


def run(body, timeout=180):
    done = subprocess.run([sys.executable, '-c', SETUP + body], capture_output=True, text=True, timeout=timeout)
    if done.returncode:
        raise AssertionError(done.stderr.strip()[-2000:] or 'child failed')
    return json.loads(done.stdout.strip().splitlines()[-1])


class LikenessGridTests(unittest.TestCase):
    def test_a_flat_image_is_its_own_lab_colour_in_every_cell(self):
        out = run('''
got, lab = ask(encode(flat(320, 240, (255, 255, 255))), grid=[64, 48])
_, grey = ask(encode(flat(320, 240, (119, 119, 119))), grid=[16, 12])
print(json.dumps([got['status'], got['grid'], [round(float(v), 1) for v in lab.reshape(-1, 3).mean(0)], round(float(grey[..., 0].mean()), 0), got['ms'] >= 0]))
''')
        self.assertEqual(out[0:2], ['ok', [64, 48]])
        self.assertEqual(out[2], [100.0, 0.0, 0.0], 'white is L 100, a 0, b 0 (CIE Lab, D65)')
        self.assertEqual(out[3], 50, 'sRGB 119 grey is about L 50')
        self.assertTrue(out[4])

    def test_source_is_in_listed_pixels_and_maps_the_crop(self):
        # The canvas view is 1/4 of the canvas; the companion asks in canvas pixels (size) for the transfer's target.
        out = run('''
img = flat(400, 300, (40, 60, 120)); img[:, 200:] = (200, 180, 90)
_, right = ask(encode(img), grid=[8, 12], source=[800, 0, 800, 1200], size=[1600, 1200])
_, left = ask(encode(img), grid=[8, 12], source=[0, 0, 800, 1200], size=[1600, 1200])
ochre = cv2.cvtColor(np.float32([[[200 / 255, 180 / 255, 90 / 255]]]), cv2.COLOR_RGB2Lab)[0, 0]
blue = cv2.cvtColor(np.float32([[[40 / 255, 60 / 255, 120 / 255]]]), cv2.COLOR_RGB2Lab)[0, 0]
print(json.dumps([de(right[:, 2:], ochre), de(left[:, :-2], blue)]))
''')
        self.assertLess(out[0], 1.0, 'the right half, away from the edge the blur crosses')
        self.assertLess(out[1], 1.0)

    def test_dab_texture_does_not_count_but_a_change_of_colour_does(self):
        out = run('''
w, h = 1568, 1176
base = encode(dabs(w, h, (70, 90, 140)), '.jpg')
again = encode(dabs(w, h, (70, 90, 140), seed=7), '.jpg')
darker = encode(dabs(w, h, (45, 60, 100), seed=7), '.jpg')
# as the companion asks: in canvas pixels (a 6000 x 4500 canvas), so the view is decoded reduced while read
sized = dict(grid=[64, 48], size=[6000, 4500])
_, a = ask(base, **sized); _, b = ask(again, **sized); ask(darker, **sized); got, c = ask(darker, **sized)
print(json.dumps([de(a, b), de(a, c), got['ms']]))
''')
        self.assertLess(out[0], 2.5, 'the same colours laid by other dabs (+-40 a channel): about one just-noticeable difference at this scale')
        self.assertGreater(out[1], 10, 'a darker passage is clearly different')
        print('likeness_grid on a 1568x1176 JPEG view of a 6000 px canvas (warm): %d ms' % out[2])

    def test_bad_requests_are_refused(self):
        out = run('''
data = encode(flat(64, 48, (1, 2, 3)))
errors = []
for extra in ({'grid': [2, 2]}, {'grid': [64]}, {'grid': [64, 48], 'source': [0, 0, 100, 100]}, {'grid': [64, 48], 'source': [0, 0, 10, 10], 'size': [5, 5]}):
    errors.append(ask(data, **extra)[0].get('error'))
try:
    g.likeness_grid({'image_base64': base64.b64encode(data).decode(), 'sha256': '0' * 64, 'grid': [8, 8]}); errors.append(None)
except ValueError as error:
    errors.append(str(error))
print(json.dumps(errors))
''')
        self.assertTrue(all(out), out)
        self.assertRegex(out[0], 'grid')
        self.assertRegex(out[2], 'source')
        self.assertRegex(out[4], 'changed')


class ComparisonCropTests(unittest.TestCase):
    """comparison_crop (luna-goal-reviewer goal 1): one area of an image, in the pixels the companion lists it at, at a
    given output size, as a JPEG for Luna. The goal's crop and the canvas views' crops come out at one size, so BEFORE,
    AFTER and GOAL have the same scale; a JPEG view is decoded here, as the companion cannot."""
    def test_the_crop_is_the_listed_area_at_the_output_size(self):
        out = run('''
img = flat(600, 450, (200, 200, 200)); img[150:300, 300:450] = (200, 30, 30)   # a red square, listed at 6000 x 4500 (10x)
data = encode(img, '.jpg')
got = g.comparison_crop({'image_base64': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest(),
    'source': [3000, 1500, 1500, 1500], 'size': [6000, 4500], 'out': [300, 300]})
raw = base64.b64decode(got['image_base64'])
crop = cv2.cvtColor(cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
print(json.dumps([got['status'], got['mime_type'], got['width'], got['height'], list(crop.shape), [int(v) for v in crop[150, 150]], got['ms'] >= 0]))
''')
        self.assertEqual(out[0:5], ['ok', 'image/jpeg', 300, 300, [300, 300, 3]])
        self.assertTrue(out[5][0] > 170 and out[5][1] < 70, 'the red square fills the crop: %s' % out[5])

    def test_several_crops_of_one_image_in_one_call(self):
        # Review, 2026-10-24: the goal is sent and decoded once a comparison, not once a crop.
        out = run('''
img = flat(600, 450, (200, 200, 200)); img[0:225, 0:300] = (30, 30, 200)
data = encode(img)
got = g.comparison_crop({'image_base64': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest(), 'size': [6000, 4500],
    'crops': [{'source': [0, 0, 3000, 2250], 'out': [64, 48]}, {'source': [3000, 2250, 3000, 2250], 'out': [32, 24]}]})
def rgb(b):
    c = cv2.cvtColor(cv2.imdecode(np.frombuffer(base64.b64decode(b), np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    return [list(c.shape), [int(v) for v in c[c.shape[0] // 2, c.shape[1] // 2]]]
print(json.dumps([got['status'], [[i['width'], i['height']] for i in got['images']], [rgb(i['image_base64']) for i in got['images']]]))
''')
        self.assertEqual(out[0:2], ['ok', [[64, 48], [32, 24]]])
        self.assertTrue(out[2][0][1][2] > 170 and out[2][1][1][2] < 220 and out[2][1][1][0] > 170, out[2])

    def test_bad_requests_are_refused(self):
        out = run('''
data = encode(flat(64, 48, (1, 2, 3)))
errors = []
for extra in ({'source': [0, 0, 10, 10], 'size': [64, 48], 'out': [8, 8]}, {'source': [60, 0, 10, 10], 'size': [64, 48], 'out': [32, 32]},
              {'source': [0, 0, 10, 10], 'size': [64, 48], 'out': [5000, 32]}):
    try:
        g.comparison_crop(dict({'image_base64': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()}, **extra)); errors.append(None)
    except ValueError as error:
        errors.append(str(error))
print(json.dumps(errors))
''')
        self.assertTrue(all(out), out)
        self.assertRegex(out[1], 'source')


if __name__ == '__main__':
    unittest.main()

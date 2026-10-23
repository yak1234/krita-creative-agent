# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""mass_reference: the mass map's smoothed copy of a reference crop (draw_guide from_reference masses). The crop is
decoded at most MASS_SIDE on its long side, then smoothed (bilateral passes, then mean shift) so texture goes and the
big masses stay with sharp boundaries. Runs real Qt in a child process (the other plugin tests stub Qt in this one).
Images are made in memory; nothing is written to disk."""
import json
import pathlib
import subprocess
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
SETUP = '''
import sys, json, base64, hashlib
import numpy as np, cv2
package = __import__('types').ModuleType('kritamcp_child'); package.__path__ = [%r]; sys.modules['kritamcp_child'] = package
from kritamcp_child.qt_compat import QApplication
app = QApplication.instance() or QApplication([])
import kritamcp_child.creative_masses as m
def two_tone(w, h, noise=30, seed=1):
    """Left half blue, right half ochre, both with strong per-pixel noise (texture), as RGBA."""
    rng = np.random.default_rng(seed)
    rgba = np.zeros((h, w, 4), np.uint8); rgba[..., 3] = 255
    rgba[:, : w // 2, :3] = (40, 60, 120); rgba[:, w // 2 :, :3] = (200, 180, 90)
    rgba[..., :3] = np.clip(rgba[..., :3].astype(int) + rng.integers(-noise, noise + 1, (h, w, 3)), 0, 255)
    return rgba
def png(rgba):
    ok, data = cv2.imencode('.png', cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)); return bytes(data)
def ask(data, **extra):
    try:
        got = m.mass_reference(dict({'image_base64': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()}, **extra))
        pixels = np.frombuffer(base64.b64decode(got['rgba_base64']), np.uint8)
        assert pixels.size == got['width'] * got['height'] * 4
        return got, pixels.reshape(got['height'], got['width'], 4)
    except ValueError as error:
        return {'error': str(error)}, None
''' % str(PLUGIN)


def run(body, timeout=180):
    done = subprocess.run([sys.executable, '-c', SETUP + body], capture_output=True, text=True, timeout=timeout)
    if done.returncode:
        raise AssertionError(done.stderr.strip()[-2000:] or 'child failed')
    return json.loads(done.stdout.strip().splitlines()[-1])


class MassReferenceTests(unittest.TestCase):
    def test_a_crop_is_decoded_at_most_mass_side_and_reports_its_source(self):
        out = run('''
got, px = ask(png(two_tone(1600, 1000, noise=0)), source=[200, 100, 1200, 800])
whole, _ = ask(png(two_tone(300, 200, noise=0)))
small, _ = ask(png(two_tone(1600, 1000, noise=0)), max_side=360)
print(json.dumps([{k: got[k] for k in ('width', 'height', 'source', 'original_width', 'original_height', 'status')},
                  {k: whole[k] for k in ('width', 'height', 'source')}, [small['width'], small['height']], got['ms'] >= 0]))
''')
        self.assertEqual(out[0], {'width': 720, 'height': 480, 'source': [200, 100, 1200, 800], 'original_width': 1600,
                                  'original_height': 1000, 'status': 'ok'}, 'the crop, reduced to 720 px on its long side')
        self.assertEqual(out[1], {'width': 300, 'height': 200, 'source': [0, 0, 300, 200]}, 'never enlarged; the whole image by default')
        self.assertEqual(out[2], [360, 225])
        self.assertTrue(out[3], 'the smoothing time is reported')

    def test_source_is_in_the_listed_size_as_for_trace_edges(self):
        out = run('''
src = two_tone(1600, 1000, noise=0)
got, px = ask(png(src), source=[100, 50, 600, 400], size=[800, 500])
bad = ask(png(src), size=[0, 5])[0]
off = ask(png(src), source=[0, 0, 900, 500], size=[800, 500])[0]
print(json.dumps([got['width'], got['height'], got['source'], int(px[240, 10, 2]), int(px[240, 700, 2]), bad['error'], off['error']]))
''')
        self.assertEqual(out[:3], [720, 480, [100, 50, 600, 400]], 'listed pixels [100,50,600,400] are file pixels [200,100,1200,800]')
        self.assertGreater(out[3], 100, 'its left is the blue half')
        self.assertLess(out[4], 100, 'its right the ochre half')
        self.assertIn('size', out[5])
        self.assertIn('source', out[6])

    def test_the_source_returned_is_the_crop_actually_decoded_in_listed_pixels(self):
        out = run('''
got, px = ask(png(two_tone(1000, 666, noise=0)), source=[100, 50, 100, 60], size=[333, 222])
print(json.dumps([got['source'], got['width'], got['height']]))
''')
        import math
        kx, ky = 1000 / 333, 666 / 222
        left, top = int(100 * kx), int(50 * ky)
        right, bottom = math.ceil(200 * kx), math.ceil(110 * ky)
        want = [left / kx, top / ky, (right - left) / kx, (bottom - top) / ky]
        for got, expected in zip(out[0], want):
            self.assertAlmostEqual(got, expected, places=3)
        self.assertEqual(out[1:], [right - left, bottom - top], 'whole decoded pixels, not the rounded request')

    def test_texture_goes_and_the_boundary_between_masses_stays_sharp(self):
        out = run('''
src = two_tone(480, 320)
got, px = ask(png(src))
rgb = px[..., :3].astype(float); w = got['width']
left, right = rgb[40:-40, 40 : w // 2 - 40], rgb[40:-40, w // 2 + 40 : -40]
before = src[40:-40, 40 : w // 2 - 40, :3].astype(float)
row = rgb[160, :, 0]
ramp = int(np.sum((row > 60) & (row < 180)))     # pixels between the two reds: the width of the boundary
print(json.dumps({'noise_before': before.std(axis=(0, 1)).mean(), 'noise_left': left.std(axis=(0, 1)).mean(),
                  'noise_right': right.std(axis=(0, 1)).mean(), 'left': left.mean(axis=(0, 1)).tolist(),
                  'right': right.mean(axis=(0, 1)).tolist(), 'ramp': ramp, 'alpha': int(px[..., 3].min())}))
''')
        self.assertGreater(out['noise_before'], 15)
        self.assertLess(out['noise_left'], out['noise_before'] / 4, 'texture smoothed away')
        self.assertLess(out['noise_right'], out['noise_before'] / 4)
        for got, want in ((out['left'], (40, 60, 120)), (out['right'], (200, 180, 90))):
            self.assertLess(max(abs(a - b) for a, b in zip(got, want)), 12, 'each mass keeps its colour')
        self.assertLessEqual(out['ramp'], 6, 'the boundary stays sharp')
        self.assertEqual(out['alpha'], 255)

    def test_transparency_is_kept(self):
        out = run('''
src = two_tone(200, 120); src[:, :50, 3] = 0
got, px = ask(png(src))
print(json.dumps([int(px[:, :48, 3].max()), int(px[:, 52:, 3].min())]))
''')
        self.assertEqual(out, [0, 255], 'a part stays see-through outside its area')

    def test_refusals(self):
        out = run('''
data = png(two_tone(64, 48, noise=0))
answers = [ask(data, sha256='0' * 64)[0], ask(data, source=[0, 0, 65, 48])[0], ask(data, source=[10, 10, 0, 5])[0],
           ask(data, source=[1, 2, 3])[0], ask(data, max_side=8)[0], ask(data, max_side=5000)[0], ask(b'not an image')[0]]
print(json.dumps([a.get('error', '') for a in answers]))
''')
        self.assertIn('changed', out[0])
        for message in out[1:4]:
            self.assertIn('source', message)
        self.assertIn('max_side', out[4])
        self.assertIn('max_side', out[5])
        self.assertIn('decode', out[6])


if __name__ == '__main__':
    unittest.main()

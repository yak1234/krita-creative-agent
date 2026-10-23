# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""closeup_align: where a close-up (a sharper picture of part of the goal) sits in the goal image, by feature matching.
The geometry is tested on numpy images in this process; the operation (bounded decode, header checks, the preview) runs
real Qt in a child process, as test_trace_edges does. Images are made in memory; nothing is written."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest
import numpy as np
import cv2

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
spec = importlib.util.spec_from_file_location('closeup_align', PLUGIN / 'closeup_align.py')
closeup_align = importlib.util.module_from_spec(spec); spec.loader.exec_module(closeup_align)


def scene(width=1600, height=1200, seed=5):
    """A busy grey picture: random discs, bars and noise, so features are everywhere (a painting's texture)."""
    rng = np.random.default_rng(seed)
    image = np.full((height, width), 120, np.uint8)
    for _ in range(900):
        x, y = int(rng.integers(0, width)), int(rng.integers(0, height))
        if rng.random() < .5:
            cv2.circle(image, (x, y), int(rng.integers(3, 30)), int(rng.integers(0, 255)), -1)
        else:
            cv2.line(image, (x, y), (x + int(rng.integers(-60, 60)), y + int(rng.integers(-60, 60))), int(rng.integers(0, 255)), int(rng.integers(1, 6)))
    noise = rng.normal(0, 6, image.shape)
    return np.clip(image + noise, 0, 255).astype(np.uint8)


def shrink(image, k):
    return cv2.resize(image, (round(image.shape[1] * k), round(image.shape[0] * k)), interpolation=cv2.INTER_AREA)


class AlignTests(unittest.TestCase):
    def test_a_sharp_crop_is_found_where_it_sits_in_a_smaller_goal(self):
        # The goal is the picture at 0.35x; the close-up is a crop of the full-size picture: about 2.9x sharper there.
        full = scene()
        goal, close = shrink(full, .35), full[300:800, 500:1100]
        out = closeup_align.align(goal, close)
        self.assertTrue(out['aligned'], out.get('reason'))
        for (x, y), (ex, ey) in zip(out['quad'], [(175, 105), (385, 105), (385, 280), (175, 280)]):
            self.assertAlmostEqual(x, ex, delta=2); self.assertAlmostEqual(y, ey, delta=2)
        self.assertEqual(out['box'], [175, 105, 210, 175])
        self.assertAlmostEqual(out['scale'], 1 / .35, delta=.1)
        self.assertAlmostEqual(out['rotation'], 0, delta=1)
        self.assertGreaterEqual(out['inliers'], closeup_align.MIN_INLIERS)
        self.assertGreater(out['similarity'], .9)
        self.assertGreater(out['score'], .8)
        self.assertEqual(len(out['matrix']), 9)
        # The matrix maps close-up pixels to goal pixels: the crop's centre lands at the box's centre.
        m = np.array(out['matrix']).reshape(3, 3); p = m @ [300, 250, 1]
        self.assertAlmostEqual(p[0] / p[2], 280, delta=2); self.assertAlmostEqual(p[1] / p[2], 192.5, delta=2)

    def test_a_turned_close_up_reports_its_rotation(self):
        full = scene(seed=8)
        turned = cv2.warpAffine(full, cv2.getRotationMatrix2D((800, 600), 8, 1.0), (1600, 1200))[350:850, 500:1100]
        out = closeup_align.align(shrink(full, .4), turned)
        self.assertTrue(out['aligned'], out.get('reason'))
        self.assertAlmostEqual(abs(out['rotation']), 8, delta=1)
        self.assertAlmostEqual(out['scale'], 2.5, delta=.15)

    def test_a_different_picture_is_refused_with_a_reason(self):
        out = closeup_align.align(shrink(scene(seed=1), .5), scene(seed=2)[200:700, 200:900])
        self.assertFalse(out['aligned'])
        self.assertTrue(out['reason'])
        self.assertNotIn('matrix', out)
        self.assertNotIn('quad', out)

    def test_a_flat_close_up_has_too_little_detail(self):
        flat = np.full((400, 600), 90, np.uint8)
        out = closeup_align.align(shrink(scene(), .5), flat)
        self.assertFalse(out['aligned'])
        self.assertIn('detail', out['reason'])

    def test_a_mirrored_softened_copy_is_refused(self):
        # Mirrored, blurred and re-textured: the same subject but not the goal's own pixels (as a regenerated element).
        # A blurred and re-textured copy that is not mirrored is the goal's own picture, and aligns.
        full = scene(seed=11)
        other = cv2.GaussianBlur(full, (0, 0), 3)
        other = np.clip(other.astype(np.int16) + np.random.default_rng(4).normal(0, 25, other.shape), 0, 255).astype(np.uint8)
        out = closeup_align.align(shrink(full, .35), cv2.flip(other[300:800, 500:1100], 1))
        self.assertFalse(out['aligned'])


class GuardTests(unittest.TestCase):
    def test_a_stretched_placement_is_refused(self):
        # The goal squashed: 0.35 across, 0.5 down. The crop would paint the area stretched, so it is not a close-up of it.
        full = scene(seed=3)
        goal = cv2.resize(full, (560, 600), interpolation=cv2.INTER_AREA)
        out = closeup_align.align(goal, full[300:800, 500:1100])
        self.assertFalse(out['aligned'])
        self.assertIn('stretch', out['reason'])

    def test_the_jpeg_header_may_pad_markers_with_fill_bytes(self):
        sof = bytes([0xff, 0xc0, 0, 17, 8, 0x01, 0x2c, 0x02, 0x58]) + bytes(12)     # 600 x 300
        data = bytes([0xff, 0xd8, 0xff, 0xff, 0xff]) + sof[1:]
        self.assertEqual(closeup_align._header(bytes([0xff, 0xd8]) + sof), ('jpeg', 600, 300))
        self.assertEqual(closeup_align._header(data), ('jpeg', 600, 300))

    def test_the_goals_features_are_kept_by_content(self):
        full = scene(seed=6)
        goal, close = shrink(full, .35), full[300:800, 500:1100]
        closeup_align._GOALS.clear()
        first = closeup_align.align(goal, close, goal_key='abc')
        self.assertIn('abc', closeup_align._GOALS)
        second = closeup_align.align(goal, close, goal_key='abc')
        self.assertEqual(first['box'], second['box'])
        self.assertLessEqual(len(closeup_align._GOALS), closeup_align.GOAL_CACHE)


SETUP = '''
import sys, json, base64, hashlib
import numpy as np, cv2
package = __import__('types').ModuleType('kritamcp_child'); package.__path__ = [%r]; sys.modules['kritamcp_child'] = package
from kritamcp_child.qt_compat import QApplication
app = QApplication.instance() or QApplication([])
import kritamcp_child.closeup_align as a
rng = np.random.default_rng(5)
full = np.full((1200, 1600, 3), 120, np.uint8)
for _ in range(900):
    x, y = int(rng.integers(0, 1600)), int(rng.integers(0, 1200))
    cv2.circle(full, (x, y), int(rng.integers(3, 30)), tuple(int(v) for v in rng.integers(0, 255, 3)), -1)
def encode(image, ext='.png'):
    ok, data = cv2.imencode(ext, image); return data.tobytes()
def item(data, sha=None):
    return {'image_base64': base64.b64encode(data).decode(), 'sha256': sha or hashlib.sha256(data).hexdigest()}
goal = encode(cv2.resize(full, (560, 420), interpolation=cv2.INTER_AREA))
close = encode(full[300:800, 500:1100], '.jpg')
def ask(params):
    try:
        return a.align_closeup(params)
    except ValueError as error:
        return {'error': str(error)}
def bomb_png(width, height):
    import struct, zlib
    chunk = lambda kind, body: struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    head = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)
    return bytes([137, 80, 78, 71, 13, 10, 26, 10]) + chunk(b'IHDR', head) + chunk(b'IDAT', zlib.compress(bytes(64))) + chunk(b'IEND', b'')
''' % str(PLUGIN)


def run(body, timeout=180):
    done = subprocess.run([sys.executable, '-c', SETUP + body], capture_output=True, text=True, timeout=timeout)
    if done.returncode:
        raise AssertionError(done.stderr.strip()[-2000:] or 'child failed')
    return json.loads(done.stdout)


class OperationTests(unittest.TestCase):
    def test_the_operation_decodes_both_images_and_answers_in_their_own_pixels(self):
        out = run('print(json.dumps(ask({"goal": item(goal), "closeup": item(close), "preview": True})))')
        self.assertEqual(out['status'], 'ok')
        self.assertTrue(out['aligned'], out.get('reason'))
        self.assertEqual(out['goal_size'], [560, 420]); self.assertEqual(out['closeup_size'], [600, 500])
        self.assertEqual(out['box'], [175, 105, 210, 175])
        self.assertIsInstance(out['ms'], int)
        preview = cv2.imdecode(np.frombuffer(__import__('base64').b64decode(out['preview_jpeg_base64']), np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(preview)
        self.assertLessEqual(max(preview.shape[:2]), closeup_align.PREVIEW_SIDE)

    def test_inputs_are_checked_before_anything_is_decoded(self):
        out = run('''
print(json.dumps([ask({"goal": item(goal), "closeup": item(close, "0" * 64)}),
                  ask({"goal": item(goal), "closeup": item(b"GIF89a" + bytes(64))}),
                  ask({"goal": item(goal), "closeup": item(bomb_png(60000, 60000))}),
                  ask({"goal": item(goal), "closeup": item(bomb_png(20000, 20000))}),
                  ask({"goal": item(goal)}),
                  ask({"goal": item(goal), "closeup": item(close), "extra": 1}),
                  ask({"goal": item(goal), "closeup": item(close), "preview": "yes"}),
                  ask({"goal": "x", "closeup": item(close)})]))
''')
        self.assertIn('changed', out[0]['error'])
        self.assertIn('PNG or JPEG', out[1]['error'])
        self.assertIn('60000 x 60000', out[2]['error'], 'the declared size is read from the header and refused')
        self.assertIn('20000 x 20000', out[3]['error'], 'at most 100 million pixels, whatever the sides')
        self.assertIn('closeup', out[4]['error'])
        self.assertIn('extra', out[5]['error'])
        self.assertIn('preview', out[6]['error'])
        self.assertIn('goal', out[7]['error'])


if __name__ == '__main__':
    unittest.main()

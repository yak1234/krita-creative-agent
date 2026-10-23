# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""find_accents: the plugin decodes a reference at full resolution (at most TRACE_PIXELS), finds the accents the canvas
view lacks (accent_find.py) and returns them in the reference's listed pixels. The canvas view is required. Hardened
like trace_edges. Runs real Qt in a child process. Images in memory."""
import json
import pathlib
import subprocess
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
SETUP = '''
import sys, json, base64, hashlib
package = __import__('types').ModuleType('kritamcp_child'); package.__path__ = [%r]; sys.modules['kritamcp_child'] = package
from kritamcp_child.qt_compat import QApplication, QImage, QBuffer, QIODevice, QColor, QPainter, QRect, Qt
app = QApplication.instance() or QApplication([])
import kritamcp_child.creative_reference as r
def png(w, h, spots, ground='#202840', fill=None):
    """A dark picture with bright round spots [x, y, radius] (and a filled box [x, y, w, h, colour])."""
    image = QImage(w, h, QImage.Format.Format_RGB32); image.fill(QColor(ground))
    painter = QPainter(image); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if fill:
        painter.fillRect(QRect(*fill[:4]), QColor(fill[4]))
    painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#fff0c0'))
    for x, y, radius in spots:
        painter.drawEllipse(x - radius, y - radius, 2 * radius, 2 * radius)
    painter.end()
    out = QBuffer(); out.open(QIODevice.OpenModeFlag.WriteOnly); image.save(out, 'PNG'); return bytes(out.data())
def encoded(data):
    return {'image_base64': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()}
def flat_view(w, h):
    """The canvas view: the ground alone, every spot still to paint."""
    return dict(encoded(png(w, h, [])), target=[0, 0, w, h])
def ask(data, **params):
    params.setdefault('canvas', flat_view(400, 300))
    try:
        return r.find_accents(dict(encoded(data), **params))
    except ValueError as error:
        return {'error': str(error)}
''' % str(PLUGIN)


def run(body, timeout=180):
    done = subprocess.run([sys.executable, '-c', SETUP + body], capture_output=True, text=True, timeout=timeout)
    if done.returncode:
        raise AssertionError(done.stderr.strip()[-2000:] or 'child failed')
    return json.loads(done.stdout)


class FindAccentsTests(unittest.TestCase):
    def test_accents_come_back_in_the_listed_pixels_even_from_a_reduced_decode(self):
        # 3000 x 2000 is six million pixels: decoded at most four million, accents scaled back to the listed size.
        big, crop = run('print(json.dumps([ask(png(3000, 2000, [[600, 500, 12], [2400, 1500, 12]]), source=[0, 0, 3000, 2000], kinds=["lights"], canvas=flat_view(1500, 1000)),'
                        ' ask(png(800, 600, [[200, 150, 5], [600, 450, 5]]), source=[800, 600, 800, 600], kinds=["lights"], size=[1600, 1200], canvas=flat_view(200, 150))]))')
        self.assertEqual(big['status'], 'ok')
        self.assertLessEqual(big['width'] * big['height'], 4_000_000)
        self.assertEqual([big['original_width'], big['original_height']], [3000, 2000])
        self.assertEqual(len(big['accents']), 2)
        for accent, (x, y) in zip(sorted(big['accents'], key=lambda a: a['x']), ((600, 500), (2400, 1500))):
            self.assertLess(abs(accent['x'] - x) + abs(accent['y'] - y), 6, accent)
            self.assertTrue(18 <= accent['size'] <= 30, 'the size in listed pixels: %s' % accent['size'])
            self.assertRegex(accent['colour'], '^#[0-9a-f]{6}$')
        self.assertIsInstance(big['ms'], int)
        self.assertEqual(big['found'], {'lights': 2})
        # Listed at twice its size: the spot at (600, 450) of the file is (1200, 900) listed, inside the source.
        self.assertEqual(len(crop['accents']), 1)
        self.assertLess(abs(crop['accents'][0]['x'] - 1200) + abs(crop['accents'][0]['y'] - 900), 6)

    def test_only_the_accents_the_canvas_view_lacks(self):
        out = run('''
reference = png(800, 600, [[200, 150, 6], [600, 450, 6]])
canvas = png(400, 300, [[300, 225, 3]])                         # the right spot is painted already
print(json.dumps(ask(reference, source=[0, 0, 800, 600], kinds=['lights'], canvas=dict(encoded(canvas), target=[0, 0, 400, 300]))))
''')
        self.assertEqual([round(a['x'] / 100) for a in out['accents']], [2])
        self.assertGreaterEqual(out['accents'][0]['residual'], 30)

    def test_hardened_like_trace_edges(self):
        out = run('''
data = png(200, 200, [[100, 100, 5]])
bad = dict(encoded(data)); bad['sha256'] = '0' * 64
def attempt(call):
    try:
        return call()
    except ValueError as error:
        return {'error': str(error)}
print(json.dumps([
    ask(data, source=[0, 0, 201, 200]), ask(data, source=[0, 0, 200]), ask(data, source=[0, 0, 200, 200], kinds=['outlines']),
    ask(data, source=[0, 0, 200, 200], kinds=[]), ask(data, source=[0, 0, 200, 200], strength='loud'),
    ask(data, source=[0, 0, 200, 200], max_accents=0), ask(data, source=[0, 0, 200, 200], max_accents=True),
    ask(data, source=[0, 0, 200, 200], extra=1),
    ask(data, source=[0, 0, 200, 200], canvas=dict(encoded(data), target=[0, 0, 300, 200])),
    ask(data, source=[0, 0, 200, 200], canvas={'image_base64': encoded(data)['image_base64'], 'sha256': '0' * 64, 'target': [0, 0, 200, 200]}),
    ask(data, source=[0, 0, 200, 200], canvas=dict(encoded(data))),
    ask(data, source=[0, 0, 200, 200], size=[0, 200]),
    ask(data, source=[0, 0, 200, 200], canvas=None),
    attempt(lambda: r.find_accents(dict(bad, source=[0, 0, 200, 200]))),
]))
''')
        for answer in out:
            self.assertIn('error', answer, answer)
        self.assertRegex(out[0]['error'], 'fit')
        self.assertRegex(out[2]['error'], 'kinds')
        self.assertRegex(out[4]['error'], 'strength')
        self.assertRegex(out[8]['error'], 'canvas')
        self.assertRegex(out[12]['error'], 'canvas view', 'no canvas view: refused, never guessed')


if __name__ == '__main__':
    unittest.main()

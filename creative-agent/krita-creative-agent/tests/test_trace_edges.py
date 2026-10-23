# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""trace_edges: the plugin decodes a reference at full resolution (at most TRACE_PIXELS), traces its guide lines
(edge_trace.py) and returns them in the reference's own pixels; shapes come in as a label map. Runs real Qt in a child
process (the other plugin tests stub Qt in this one). Images are made in memory."""
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
from kritamcp_child.qt_compat import QApplication, QImage, QBuffer, QIODevice, QColor, QPainter, QRect
app = QApplication.instance() or QApplication([])
import kritamcp_child.creative_reference as r
def png(w, h, box):
    """A pale picture with a dark box [x, y, w, h]."""
    image = QImage(w, h, QImage.Format.Format_RGB32); image.fill(QColor('#d0d0d0'))
    painter = QPainter(image); painter.fillRect(QRect(*box), QColor('#303030')); painter.end()
    out = QBuffer(); out.open(QIODevice.OpenModeFlag.WriteOnly); image.save(out, 'PNG'); return bytes(out.data())
def ask(data, **params):
    try:
        return r.trace_edges(dict({'image_base64': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()}, **params))
    except ValueError as error:
        return {'error': str(error)}
def bomb_png(width, height):
    """A tiny PNG whose header declares width x height: decoding it would allocate the whole of it."""
    import struct, zlib
    chunk = lambda kind, body: struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    head = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)
    data = bytes([137, 80, 78, 71, 13, 10, 26, 10]) + chunk(b'IHDR', head) + chunk(b'IDAT', zlib.compress(bytes(64))) + chunk(b'IEND', b'')
    return base64.b64encode(data).decode()
def label_png(plane):
    ok, encoded = cv2.imencode('.png', plane); return base64.b64encode(encoded.tobytes()).decode()
''' % str(PLUGIN)


def run(body, timeout=180):
    done = subprocess.run([sys.executable, '-c', SETUP + body], capture_output=True, text=True, timeout=timeout)
    if done.returncode:
        raise AssertionError(done.stderr.strip()[-2000:] or 'child failed')
    return json.loads(done.stdout)


def near(lines, x, y, tolerance):
    return any(abs(px - x) <= tolerance and abs(py - y) <= tolerance for line in lines for px, py in line['points'])


class TraceEdgesTests(unittest.TestCase):
    def test_lines_come_back_in_the_references_pixels_even_from_a_reduced_decode(self):
        # 3000 x 2000 is six million pixels: decoded at most four million, lines scaled back to the listed size.
        out = run('print(json.dumps([ask(png(3000, 2000, [1000, 600, 800, 900]), source=[0, 0, 3000, 2000], scale=1.0),'
                  ' ask(png(800, 600, [200, 150, 300, 250]), source=[100, 100, 600, 450], scale=2.0, detail="medium", max_lines=20)]))')
        big, small = out
        self.assertEqual(big['status'], 'ok')
        self.assertLessEqual(big['width'] * big['height'], 4_000_000)
        self.assertEqual([big['original_width'], big['original_height']], [3000, 2000])
        for corner in ((1000, 600), (1800, 600), (1800, 1500), (1000, 1500)):
            self.assertTrue(near(big['lines'], *corner, 8), corner)
        self.assertEqual(big['silhouette'], 'brightness')
        self.assertIsInstance(big['ms'], int)
        self.assertTrue(near(small['lines'], 200, 150, 4) and near(small['lines'], 500, 400, 4))
        for line in small['lines']:
            for x, y in line['points']:
                self.assertTrue(100 <= x <= 700 and 100 <= y <= 550, (x, y))

    def test_a_label_map_gives_the_outlines(self):
        # A flat picture: only the labels (found on a half-size copy) can say where the shape is.
        out = run('''
plane = np.zeros((300, 400), np.uint8); plane[100:250, 100:300] = 1
print(json.dumps(ask(png(800, 600, [0, 0, 0, 0]), source=[0, 0, 800, 600], scale=1.0,
                     labels={'png_base64': label_png(plane), 'bounds': [0, 0, 400, 300], 'space': [400, 300]})))
''')
        self.assertEqual(out['silhouette'], 'shapes')
        for corner in ((200, 200), (600, 200), (600, 500), (200, 500)):
            self.assertTrue(near(out['lines'], *corner, 6), corner)

    def test_shape_labels_are_bounded_before_they_are_decoded(self):
        out = run('''
data = png(64, 64, [10, 10, 20, 20])
ask_l = lambda labels: ask(data, source=[0, 0, 64, 64], scale=1.0, labels=labels)
print(json.dumps([ask_l({'png_base64': bomb_png(60000, 60000), 'bounds': [0, 0, 4, 4], 'space': [64, 64]}),
                  ask_l({'png_base64': bomb_png(60000, 60000), 'bounds': [0, 0, 60000, 60000], 'space': [60000, 60000]}),
                  ask_l({'png_base64': bomb_png(9000, 10), 'bounds': [0, 0, 9000, 10], 'space': [9000, 10]}),
                  ask_l({'png_base64': bomb_png(4, 4), 'bounds': [0, 0, 4, 4], 'space': [64, 64]})]))
''')
        self.assertIn('60000 x 60000', out[0]['error'], 'the header is read and compared with the bounds before any decode')
        self.assertIn('space', out[1]['error'])
        self.assertIn('space', out[2]['error'], 'each side at most 8192')
        self.assertNotIn('60000', out[3].get('error', ''))

    def test_source_and_lines_are_in_the_listed_size_when_it_differs_from_the_file(self):
        # The file is 800 x 600; the companion lists it at 400 x 300: source and lines are in the listed pixels.
        out = run('print(json.dumps(ask(png(800, 600, [200, 150, 300, 250]), source=[50, 50, 300, 225], size=[400, 300], scale=2.0)))')
        self.assertEqual(out['status'], 'ok')
        self.assertTrue(near(out['lines'], 100, 75, 3) and near(out['lines'], 250, 200, 3), out['lines'][:2])
        for line in out['lines']:
            for x, y in line['points']:
                self.assertTrue(50 <= x <= 350 and 50 <= y <= 275, (x, y))

    def test_refusals(self):
        out = run('''
data = png(64, 64, [10, 10, 20, 20])
print(json.dumps([ask(data, source=[0, 0, 64, 64], scale=1.0, sha256='0' * 64), ask(data, source=[0, 0, 65, 64], scale=1.0),
                  ask(data, source=[0, 0, 64, 64], scale=0), ask(data, source=[0, 0, 64, 64], scale=1.0, detail='fine'),
                  ask(data, source=[0, 0, 64, 64], scale=1.0, max_lines=1000), ask(b'not an image', source=[0, 0, 4, 4], scale=1.0),
                  ask(data, source=[0, 0, 64, 64], scale=1.0, labels={'png_base64': 'AAAA', 'bounds': [0, 0, 4, 4], 'space': [64, 64]})]))
''')
        self.assertIn('changed', out[0]['error'])
        self.assertIn('fit', out[1]['error'])
        self.assertIn('scale', out[2]['error'])
        self.assertIn('detail', out[3]['error'])
        self.assertIn('max_lines', out[4]['error'])
        self.assertIn('decode', out[5]['error'])
        self.assertIn('shape', out[6]['error'])


if __name__ == '__main__':
    unittest.main()

# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""trace_reference: guided trace's own decode of a reference, reduced to max_side, so a full-size goal image traces.
Runs real Qt in a child process (the other plugin tests stub Qt in this one). Images are made in memory."""
import json
import pathlib
import subprocess
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
SETUP = '''
import sys, json, base64, hashlib
package = __import__('types').ModuleType('kritamcp_child'); package.__path__ = [%r]; sys.modules['kritamcp_child'] = package
from kritamcp_child.qt_compat import QApplication, QImage, QBuffer, QIODevice, QColor
app = QApplication.instance() or QApplication([])
import kritamcp_child.creative_reference as r
def png(w, h):
    image = QImage(w, h, QImage.Format.Format_RGB32); image.fill(QColor('#204060'))
    out = QBuffer(); out.open(QIODevice.OpenModeFlag.WriteOnly); image.save(out, 'PNG'); return bytes(out.data())
def ask(data, side, sha=None):
    try:
        got = r.trace_reference({'image_base64': base64.b64encode(data).decode(), 'sha256': sha or hashlib.sha256(data).hexdigest(), 'max_side': side})
        return {'width': got['width'], 'height': got['height'], 'bytes': len(base64.b64decode(got['rgba_base64'])),
                'original': [got['original_width'], got['original_height']]}
    except ValueError as error:
        return {'error': str(error)}
''' % str(PLUGIN)


def run(body, timeout=120):
    done = subprocess.run([sys.executable, '-c', SETUP + body], capture_output=True, text=True, timeout=timeout)
    if done.returncode:
        raise AssertionError(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else 'child failed')
    return json.loads(done.stdout)


class TraceReferenceTests(unittest.TestCase):
    def test_a_full_size_goal_image_is_decoded_reduced(self):
        out = run('print(json.dumps([ask(png(4800, 3200), 1440), ask(png(800, 600), 1440), ask(png(30, 20), 1440)]))')
        self.assertEqual(out[0], {'width': 1440, 'height': 960, 'bytes': 1440 * 960 * 4, 'original': [4800, 3200]},
                         'a 15 MP goal image traces from a 1440 px decode')
        self.assertEqual(out[1]['width'], 800, 'never enlarged')
        self.assertEqual(out[2]['width'], 30)

    def test_refusals(self):
        out = run('print(json.dumps([ask(png(64, 64), 1440, sha="0" * 64), ask(png(64, 64), 100000), ask(png(64, 64), 10), '
                  'ask(b"not an image", 1440)]))')
        self.assertIn('changed', out[0]['error'])
        self.assertIn('max_side', out[1]['error'])
        self.assertIn('max_side', out[2]['error'])
        self.assertIn('decode', out[3]['error'])

    def test_the_reference_tools_decode_is_unchanged(self):
        out = run('''
data = png(2100, 2000)
try:
    r.decode_reference({'image_base64': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()})
    print(json.dumps('decoded'))
except ValueError as error:
    print(json.dumps(str(error)))
''')
        self.assertIn('four million pixels', out, 'its own limit stays')


if __name__ == '__main__':
    unittest.main()

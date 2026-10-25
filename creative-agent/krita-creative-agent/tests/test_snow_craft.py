# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""snow (snow_craft.py; openspec snow), paint_snow's plugin operation: one layer per call ("Snow: falling" or "Snow: settled
on <parts>") in the move's group, one pass of the creative operation journal, so the move's Undo removes it; keep_clear
shapes (faces) get no snow; anything wrong is refused before anything changes. The pixel layer tree of the finish tests;
the found areas are mask files in the chat folder's .shapes, a temporary folder removed after each test."""
import os
import unittest

import numpy as np
import test_finish_pass as finish_tests
from test_element_shapes import png

region_tests = finish_tests.region_tests


class SnowTests(finish_tests.FinishOperationTests):
    def shape(self, name, mask, box):
        """A found area: `mask` (uint8, 255 inside) over `box` [x, y, w, h] of the 600 x 400 canvas, in .shapes."""
        folder = os.path.join(self.h._creative_session['output'], '.shapes')
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, 'found-%s.png' % name)
        with open(path, 'wb') as stream:
            stream.write(png(box[2], box[3], [bytes(row) for row in mask]))
        return {'mask_path': path, 'bounds': list(box)}

    def full(self, name, box):
        return self.shape(name, np.full((box[3], box[2]), 255, np.uint8), box)

    def snow(self, params, identifier='s1'):
        return region_tests.run(self.h, 'snow', dict({'stage_id': 'move-1'}, **params), identifier)

    def stage(self):
        return self.h.doc.root.childNodes()[1]

    def test_falling_snow_is_one_layer_in_the_moves_group_and_the_moves_undo_removes_it(self):
        before = self.shown()
        y, x = np.mgrid[0:120, 0:100]
        face = ((x - 50) ** 2 + (y - 60) ** 2 <= 45 ** 2).astype(np.uint8) * 255
        clear = self.shape('face', face, [250, 100, 100, 120])
        result = self.snow({'name': 'Snow: falling', 'mode': 'falling', 'density': 2.0, 'wind_deg': 20, 'layers': 3, 'keep_clear': [clear]})
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual([c.label for c in self.stage().childNodes()], ['Snow: falling'])
        layer = self.stage().childNodes()[0]
        self.assertEqual(layer.blend, 'normal')
        report = result['snow']
        self.assertEqual(report['mode'], 'falling')
        self.assertEqual(set(report['layers']), {'far', 'mid', 'near'})
        self.assertGreater(sum(v['flakes'] for v in report['layers'].values()), 50)
        self.assertEqual(int(layer.data[100:220, 250:350][face > 0, 3].max()), 0, 'no snow on the face')
        self.assertGreater(int((layer.data[..., 3] > 0).sum()), 500)
        entry = next(p for p in self.h._creative_session['passes'] if p['id'] == 's1')
        self.assertEqual((entry['kind'], entry['stage_id'], entry['title']), ('snow', 'move-1', 'Snow: falling'))
        undone = region_tests.run(self.h, 'review_pass', {'pass_id': 'stage:move-1', 'action': 'reject'}, 'undo')
        self.assertEqual(undone['status'], 'ok', undone.get('error'))
        self.assertLessEqual(float(np.abs(self.shown() - before).max()), 1)

    def test_settled_snow_caps_the_named_parts_tops_in_one_layer(self):
        posts = self.full('posts', [100, 150, 40, 200])
        roof = self.full('roof', [300, 120, 250, 100])
        result = self.snow({'name': 'Snow: settled on posts, roof', 'mode': 'settled',
                            'settle_on': [{'name': 'posts', 'inside_shape': posts}, {'name': 'roof', 'inside_shape': roof}]})
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual([c.label for c in self.stage().childNodes()], ['Snow: settled on posts, roof'])
        layer = self.stage().childNodes()[0].data[..., 3]
        parts = {p['name']: p for p in result['snow']['parts']}
        self.assertEqual(set(parts), {'posts', 'roof'})
        self.assertGreater(parts['roof']['thickness_px'], parts['posts']['thickness_px'])
        self.assertGreaterEqual(parts['posts']['caps'], 1)
        self.assertGreater(int(layer[150 - 2, 120]), 150, 'on the post’s top')
        self.assertGreater(int(layer[120 - 2, 420]), 150, 'on the roof')
        self.assertEqual(int(layer[260:, :].max()), 0, 'nothing down the posts or under the roof')

    def test_anything_wrong_is_refused_before_anything_changes(self):
        layers = len(self.h.doc.root.childNodes())
        roof = self.full('roof', [300, 120, 250, 100])
        cases = [
            ({'name': 'Snow', 'mode': 'blizzard'}, 'mode'),
            ({'name': 'Snow', 'mode': 'falling', 'density': 9}, 'density'),
            ({'name': 'Snow', 'mode': 'falling', 'wind_deg': 80}, 'wind_deg'),
            ({'name': 'Snow', 'mode': 'falling', 'layers': 5}, 'layers'),
            ({'name': 'Snow', 'mode': 'settled'}, 'settle_on'),
            ({'name': 'Snow', 'mode': 'falling', 'settle_on': [{'name': 'roof', 'inside_shape': roof}]}, 'settle_on'),
            ({'name': 'Snow', 'mode': 'settled', 'settle_on': [{'name': 'roof', 'inside_shape': {'mask_path': '/etc/hosts.png', 'bounds': [0, 0, 10, 10]}}]}, 'chat folder'),
            ({'name': 'Snow', 'mode': 'falling', 'keep_clear': [{'mask_path': '/etc/hosts.png', 'bounds': [0, 0, 10, 10]}]}, 'chat folder'),
            ({'name': 'Snow', 'mode': 'settled', 'thickness': 5, 'settle_on': [{'name': 'roof', 'inside_shape': roof}]}, 'thickness'),
        ]
        for i, (params, message) in enumerate(cases):
            with self.assertRaisesRegex(ValueError, message):
                self.snow(params, 'bad%d' % i)
        self.assertEqual(len(self.h.doc.root.childNodes()), layers, 'no layer was added')


def load_tests(loader, tests, pattern):
    """Only this file's tests, without running the finish tests again here."""
    return unittest.TestSuite([SnowTests(name) for name in sorted(vars(SnowTests)) if name.startswith('test_')])


if __name__ == '__main__':
    unittest.main()

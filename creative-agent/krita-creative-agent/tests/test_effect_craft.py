# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""effect and effect_preview (effect_craft.py; openspec custom-effects): one layer "Effect: <name>" per call in the move's
group, one journal pass; effect_preview renders on a picture of the canvas view and opens no document. The pixel layer
tree of the snow tests; shapes and pictures are files in a temporary chat folder that is removed."""
import os
import types
import unittest

import cv2
import numpy as np
import test_finish_pass as finish_tests
import test_snow_craft as snow_tests

region_tests = finish_tests.region_tests
native = region_tests.native

SNOWFALL = {'block': 'particles', 'density': 1.0, 'layers': 3}


class EffectTests(snow_tests.SnowTests):
    def effect(self, params, identifier='e1'):
        return region_tests.run(self.h, 'effect', dict({'stage_id': 'move-1'}, **params), identifier)

    def preview(self, params, identifier='p1'):
        return region_tests.run(self.h, 'effect_preview', params, identifier)

    def folder(self):
        return self.h._creative_session['output']

    def test_effect_paints_one_layer_named_after_it(self):
        before = self.shown()
        y, x = np.mgrid[0:120, 0:100]
        face = ((x - 50) ** 2 + (y - 60) ** 2 <= 45 ** 2).astype(np.uint8) * 255
        clear = self.shape('face', face, [250, 100, 100, 120])
        roof = self.full('roof', [300, 120, 250, 100])
        result = self.effect({'name': 'Light snow', 'blocks': [SNOWFALL, {'block': 'caps', 'part': 'roof'}],
                              'keep_clear': [clear], 'parts': {'roof': roof}})
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual([c.label for c in self.stage().childNodes()], ['Effect: Light snow'])
        layer = self.stage().childNodes()[0]
        self.assertEqual(layer.blend, 'normal')
        self.assertEqual([row['block'] for row in result['report']['blocks']], ['particles', 'caps'])
        self.assertGreater(result['report']['blocks'][0]['painted'], 500)
        self.assertEqual(int(layer.data[100:220, 250:350][face > 0, 3].max()), 0, 'nothing on the face')
        entry = next(p for p in self.h._creative_session['passes'] if p['id'] == 'e1')
        self.assertEqual((entry['kind'], entry['stage_id']), ('effect', 'move-1'))
        undone = region_tests.run(self.h, 'review_pass', {'pass_id': 'stage:move-1', 'action': 'reject'}, 'undo')
        self.assertEqual(undone['status'], 'ok', undone.get('error'))
        self.assertLessEqual(float(np.abs(self.shown() - before).max()), 1)

    def test_effect_loads_a_texture_image_from_its_path(self):
        roof = self.full('roof', [300, 120, 250, 100])
        path = os.path.join(self.folder(), 'tex.png')
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        cv2.imwrite(path, np.full((8, 8, 3), (10, 200, 30), np.uint8))
        result = self.effect({'name': 'Moss', 'blocks': [{'block': 'texture', 'image_path': path, 'area': 'roof'}], 'parts': {'roof': roof}})
        self.assertEqual(result['status'], 'ok', result.get('error'))
        pixel = self.stage().childNodes()[0].data[150, 400]
        self.assertEqual(list(pixel[:3]), [10, 200, 30])

    def test_effect_rejects_unknown_fields_and_blocks(self):
        layers = len(self.h.doc.root.childNodes())
        roof = self.full('roof', [300, 120, 250, 100])
        outside = os.path.join(os.path.dirname(self.folder()), 'x.png')
        cases = [
            ({'name': 'E', 'blocks': [SNOWFALL], 'colour': 'red'}, 'Unknown parameters'),
            ({'name': 'E', 'blocks': [{'block': 'lightning'}]}, 'block is one of'),
            ({'name': 'E', 'blocks': [{'block': 'particles', 'code': '1+1'}]}, 'unknown parameters'),
            ({'name': 'E', 'blocks': [{'block': 'wash', 'from': 'sideways'}]}, 'from is one of'),
            ({'name': 'E', 'blocks': [{'block': 'noise', 'opacity': 'lots'}]}, 'opacity'),
            ({'name': 'E', 'blocks': [{'block': 'noise', 'band': {'from': 'middle', 'share': 0.5}}]}, 'from is one of'),
            ({'name': 'E', 'blocks': [{'block': 'noise', 'band': {'from': 'bottom', 'share': 1.5}}]}, 'between'),
            ({'name': 'E', 'blocks': [{'block': 'noise', 'band': 0.5}]}, 'band'),
            ({'name': 'E', 'blocks': [{'block': 'wash', 'band': {'from': 'bottom', 'share': 0.5}}]}, 'unknown parameters'),
            ({'name': 'E', 'blocks': []}, 'blocks'),
            ({'name': 'E', 'blocks': [{'block': 'caps'}]}, 'caps needs part'),
            ({'name': 'E', 'blocks': [SNOWFALL], 'seed': -1}, 'seed'),
            ({'name': 'E', 'blocks': [SNOWFALL], 'keep_clear': [{'mask_path': '/etc/hosts.png', 'bounds': [0, 0, 10, 10]}]}, 'chat folder'),
            ({'name': 'E', 'blocks': [{'block': 'texture', 'image_path': outside, 'area': 'roof'}], 'parts': {'roof': roof}}, 'chat folder'),
        ]
        for i, (params, message) in enumerate(cases):
            with self.assertRaisesRegex(ValueError, message):
                self.effect(params, 'bad%d' % i)
        self.assertEqual(len(self.h.doc.root.childNodes()), layers, 'no layer was added')

    def picture(self, name='view.png', size=(300, 200)):
        path = os.path.join(self.folder(), name)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        cv2.imwrite(path, np.full((size[1], size[0], 3), (120, 90, 60), np.uint8))
        return path

    def test_preview_writes_a_png_and_opens_no_document(self):
        opened = []
        fake = types.SimpleNamespace(openDocument=lambda *a: opened.append(a), createDocument=lambda *a: opened.append(a))
        previous = native.module.Krita
        native.module.Krita = types.SimpleNamespace(instance=lambda: fake)
        self.addCleanup(setattr, native.module, 'Krita', previous)
        self.h.get_active_document = lambda: self.fail('the preview must not look up a document')
        view, out = self.picture(), os.path.join(self.folder(), 'preview.png')
        self.addCleanup(lambda: os.path.exists(out) and os.remove(out))
        roof = self.full('roof', [300, 120, 250, 100])                 # canvas pixels (600 x 400); the picture is half that
        result = self.preview({'image_path': view, 'out_path': out, 'canvas': [600, 400], 'parts': {'roof': roof},
                               'blocks': [{'block': 'caps', 'part': 'roof'}, {'block': 'wash', 'opacity': 0.4}]})
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['size'], [300, 200])
        self.assertEqual([row['block'] for row in result['report']['blocks']], ['caps', 'wash'])
        image = cv2.imread(out, cv2.IMREAD_UNCHANGED)
        self.assertEqual(image.shape[:2], (200, 300))
        self.assertGreater(int(np.abs(image[..., :3].astype(int) - np.array((120, 90, 60))).max()), 20, 'the effect is on it')
        self.assertEqual(opened, [])

    def huge_png(self, name):
        """A small PNG file whose header declares 20 000 x 20 000 pixels (under OpenCV's own limit): decoding it would need 1.6 GB."""
        import struct
        import zlib
        path = os.path.join(self.folder(), name)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        ihdr = struct.pack('>IIBBBBB', 20000, 20000, 8, 6, 0, 0, 0)
        chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
        with open(path, 'wb') as handle:
            handle.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(b'\0' * 64)) + chunk(b'IEND', b''))
        return path

    def test_images_declaring_a_huge_size_are_refused_before_decoding(self):
        decoded = []
        real_imread = cv2.imread
        cv2.imread = lambda *a, **k: decoded.append(a) or real_imread(*a, **k)
        self.addCleanup(setattr, cv2, 'imread', real_imread)
        huge = self.huge_png('huge.png')
        roof = self.full('roof', [300, 120, 250, 100])
        with self.assertRaisesRegex(ValueError, '4096'):
            self.effect({'name': 'Moss', 'blocks': [{'block': 'texture', 'image_path': huge, 'area': 'roof'}], 'parts': {'roof': roof}})
        out = os.path.join(self.folder(), 'o.png')
        with self.assertRaisesRegex(ValueError, '4096'):
            self.preview({'image_path': huge, 'out_path': out, 'canvas': [600, 400], 'blocks': [{'block': 'noise'}]})
        self.assertFalse(os.path.exists(out))
        self.assertEqual(decoded, [], 'nothing was decoded')

    def test_preview_refuses_a_path_outside_the_chat_folder(self):
        view = self.picture()
        elsewhere = os.path.join(os.path.dirname(self.folder()), 'elsewhere.png')
        blocks = [{'block': 'noise'}]
        with self.assertRaisesRegex(ValueError, 'out_path must be a file in the chat folder'):
            self.preview({'image_path': view, 'out_path': elsewhere, 'canvas': [600, 400], 'blocks': blocks})
        with self.assertRaisesRegex(ValueError, 'image_path must be a file in the chat folder'):
            self.preview({'image_path': '/etc/hosts', 'out_path': os.path.join(self.folder(), 'o.png'), 'canvas': [600, 400], 'blocks': blocks})
        self.assertFalse(os.path.exists(elsewhere))


def load_tests(loader, tests, pattern):
    """Only this file's tests, without running the snow or finish tests again here."""
    return unittest.TestSuite([EffectTests(name) for name in sorted(vars(EffectTests)) if name.startswith('test_')])


if __name__ == '__main__':
    unittest.main()

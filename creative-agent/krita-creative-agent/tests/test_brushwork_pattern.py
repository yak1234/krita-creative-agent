# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Goal brushwork patterns (brushwork_pattern.py, openspec architecture-texture goal 8): a goal crop high-passed (its light
and shading removed, the stroke grain kept), made seamless, and measured; a flat or tiny crop gives none. Then the plugin
operation brushwork_patterns: each part's found area cut from the goal where it sits on the canvas, registered through a
stubbed Krita.createPattern as "Goal brushwork: <part>", and recorded for the brush texture. Synthetic images, real Qt
(PyQt5 or PyQt6, qt_compat.py picks the binding); files only in a temporary folder that is removed."""
import hashlib
import importlib
import os
import pathlib
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

import cv2
import numpy as np

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'


def load():
    """Loaded under a package name of our own with the real Qt binding (test_native.py replaces PyQt5 with stubs in this
    process): qt_compat is imported first, while the stubs are out of the way, so the operation's QImage is real."""
    stubs = {name: sys.modules.pop(name) for name in list(sys.modules) if name == 'PyQt5' or name.startswith('PyQt5.')}
    try:
        package = types.ModuleType('brushwork_test_package'); package.__path__ = [str(PLUGIN)]
        sys.modules['brushwork_test_package'] = package
        return importlib.import_module('brushwork_test_package.qt_compat'), importlib.import_module('brushwork_test_package.brushwork_pattern')
    finally:
        sys.modules.update(stubs)


qt, pattern = load()


def gradient_stripes(w=160, h=120, light=(40, 220), period=7, amplitude=24, grain=40, seed=3):
    """A goal crop: a strong left-to-right light gradient (shading) with vertical brush-stroke stripes and a soft dab grain
    on it (smoothed noise: neighbouring pixels alike, opposite edges not), BGR uint8."""
    x = np.linspace(light[0], light[1], w, dtype=np.float32)[None, :].repeat(h, 0)
    stripes = amplitude * np.sin(2 * np.pi * np.arange(w) / period)[None, :]
    grain = cv2.GaussianBlur(np.random.default_rng(seed).normal(0, grain, (h, w)).astype(np.float32), (0, 0), 2)
    grey = np.clip(x + stripes + grain, 0, 255)
    return np.repeat(grey[..., None], 3, axis=2).astype(np.uint8)


def wrap_step(tile, axis):
    """The mean step across the tile's wrap-around edge (last row/column to first) on `axis`."""
    t = tile.astype(np.float32)
    first, last = (t[0], t[-1]) if axis == 0 else (t[:, 0], t[:, -1])
    return float(np.abs(first - last).mean())


def inner_step(tile, axis):
    """The mean step between neighbouring rows/columns inside the tile."""
    return float(np.abs(np.diff(tile.astype(np.float32), axis=axis)).mean())


def largest_inner_step(tile, axis):
    """The largest of the mean steps between each pair of neighbouring rows/columns inside the tile."""
    return float(np.abs(np.diff(tile.astype(np.float32), axis=axis)).mean(axis=1 - axis).max())


class BrushworkPixels(unittest.TestCase):
    def test_a_gradient_with_dab_grain_gives_a_seamless_tile_with_the_light_removed(self):
        crop = gradient_stripes(amplitude=0)
        raw = crop[..., 0]
        for axis in (0, 1):
            self.assertGreater(wrap_step(raw, axis), 2 * largest_inner_step(raw, axis), 'the raw crop does not tile (axis %d)' % axis)
        tile, energy, reason = pattern.brushwork_tile(crop)
        self.assertIsNone(reason)
        self.assertGreater(energy, pattern.ENERGY_MIN)
        self.assertEqual(tile.dtype, np.uint8)
        self.assertEqual(tile.ndim, 2)
        self.assertEqual(tile.shape[0], tile.shape[1], 'a square pattern')
        for axis in (0, 1):
            self.assertLessEqual(wrap_step(tile, axis), largest_inner_step(tile, axis), 'opposite edges meet (axis %d)' % axis)
        # The light is gone: mid grey on average, and the left (dark) and right (light) halves the same.
        self.assertLess(abs(float(tile.mean()) - 128), 4)
        half = tile.shape[1] // 2
        self.assertLess(abs(float(tile[:, :half].mean()) - float(tile[:, half:].mean())), 4, 'no shading left')
        self.assertGreater(float(tile.std()), 10, 'the grain kept')

    def test_stroke_stripes_are_kept(self):
        tile, energy, reason = pattern.brushwork_tile(gradient_stripes())
        self.assertIsNone(reason)
        # Vertical strokes: the tile varies along x far more than along y, and its edges still meet.
        self.assertGreater(inner_step(tile, 1), 4 * inner_step(tile, 0))
        for axis in (0, 1):
            self.assertLessEqual(wrap_step(tile, axis), largest_inner_step(tile, axis) + 1)
        self.assertLess(abs(float(tile.mean()) - 128), 4)

    def test_a_dark_and_a_light_crop_of_the_same_strokes_give_the_same_mid_grey(self):
        dark, _e1, _r1 = pattern.brushwork_tile(gradient_stripes(light=(30, 60)))
        light, _e2, _r2 = pattern.brushwork_tile(gradient_stripes(light=(190, 220)))
        self.assertLess(abs(float(dark.mean()) - float(light.mean())), 4)

    def test_a_flat_crop_gives_no_pattern(self):
        flat = np.full((120, 160, 3), 140, np.uint8)
        tile, energy, reason = pattern.brushwork_tile(flat)
        self.assertIsNone(tile)
        self.assertEqual(reason, 'flat')
        self.assertLess(energy, pattern.ENERGY_MIN)
        # A smooth gradient is shading, not brushwork: flat too.
        shading = np.linspace(20, 230, 160, dtype=np.float32)[None, :, None].repeat(120, 0).repeat(3, 2).astype(np.uint8)
        tile, energy, reason = pattern.brushwork_tile(shading)
        self.assertIsNone(tile)
        self.assertEqual(reason, 'flat')

    def test_a_tiny_crop_gives_no_pattern(self):
        tile, _energy, reason = pattern.brushwork_tile(gradient_stripes(w=12, h=40))
        self.assertIsNone(tile)
        self.assertEqual(reason, 'tiny')

    def test_the_mask_keeps_only_the_part(self):
        crop = gradient_stripes()
        mask = np.zeros(crop.shape[:2], np.uint8)
        flat = crop.copy(); flat[:] = 140                     # outside the part: flat paint (the sky)
        flat[20:100, 30:130] = crop[20:100, 30:130]
        mask[20:100, 30:130] = 255
        tile, energy, reason = pattern.brushwork_tile(flat, mask)
        self.assertIsNone(reason)
        self.assertGreater(energy, pattern.ENERGY_MIN)
        self.assertLessEqual(tile.shape[0], 80, 'cut to the part, not the flat paint around it')
        # The part's edge against the flat paint is no stroke: the energy is the part's own, near the unmasked crop's.
        _t, whole, _r = pattern.brushwork_tile(crop)
        self.assertLess(abs(energy - whole) / whole, 0.35)
        # A part with almost nothing in its mask is tiny.
        speck = np.zeros(crop.shape[:2], np.uint8); speck[50:58, 50:58] = 255
        self.assertEqual(pattern.brushwork_tile(crop, speck)[2], 'tiny')


class FakeResource:
    def __init__(self, name, image):
        self._name, self.image = name, image
    def name(self): return self._name


class PatternKrita:
    """Application.createPattern as the fork documents it: the agent's own pattern of a name is replaced; a name that is
    another resource's (`artist`) gets "name (2)"; None when it refuses."""
    def __init__(self, artist=(), refuse=False):
        self.artist, self.refuse, self.patterns, self.calls = set(artist), refuse, {}, []
    def createPattern(self, image, name):
        self.calls.append(name)
        if self.refuse or image.isNull():
            return None
        label = name + ' (2)' if name in self.artist else name
        self.patterns[label] = FakeResource(label, image.copy())
        return self.patterns[label]


class FakeDocument:
    def __init__(self, width, height):
        self._w, self._h = width, height
    def width(self): return self._w
    def height(self): return self._h


def pixels(image):
    """A Grayscale8 QImage as (h, w) uint8."""
    image = image.convertToFormat(qt.QImage.Format.Format_Grayscale8)
    return np.frombuffer(qt.image_bytes(image), np.uint8).reshape(image.height(), image.width())


class BrushworkOperation(unittest.TestCase):
    """A 600 x 400 canvas; the goal listed at 300 x 200 over all of it (enlarged 2x): stone strokes on its left half (the
    church), flat paint on its right (the sky)."""
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='brushwork-test-')
        self.addCleanup(shutil.rmtree, self.folder, True)
        os.makedirs(os.path.join(self.folder, '.shapes'))
        goal = np.full((200, 300, 3), 150, np.uint8)
        goal[:, :150] = gradient_stripes(w=150, h=200)
        data = cv2.imencode('.png', goal)[1].tobytes()
        path = os.path.join(self.folder, 'goal.png')
        with open(path, 'wb') as stream:
            stream.write(data)
        self.goal = {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': [300, 200], 'source': [0, 0, 300, 200], 'target': [0, 0, 600, 400]}
        self.doc, self.session = FakeDocument(600, 400), {'output': self.folder}
        self.krita = PatternKrita()
        pattern._REGISTERED.clear()
        self.addCleanup(pattern._REGISTERED.clear)

    def area(self, name, box):
        """A found area: .shapes/found-<name>.png, white over `box` on the canvas."""
        x, y, w, h = box
        path = os.path.join(self.folder, '.shapes', 'found-%s.png' % name)
        with open(path, 'wb') as stream:
            stream.write(cv2.imencode('.png', np.full((h, w), 255, np.uint8))[1].tobytes())
        return {'mask_path': path, 'bounds': [x, y, w, h]}

    def run_op(self, parts, krita=None):
        fake = types.ModuleType('krita'); fake.Krita = types.SimpleNamespace(instance=lambda: krita or self.krita)
        with mock.patch.dict(sys.modules, {'krita': fake}):
            return pattern.BrushworkCraft()._brushwork_patterns(self.doc, self.session, {'goal': self.goal, 'parts': parts})

    def test_each_part_gets_its_goal_brushwork_pattern_or_none_when_flat(self):
        result = self.run_op([{'name': 'the church', 'inside_shape': self.area('church', [20, 20, 260, 360])},
                              {'name': 'Moonlit sky', 'inside_shape': self.area('sky', [320, 20, 260, 360])}])
        self.assertEqual(result['status'], 'ok')
        church, sky = result['brushwork']
        self.assertEqual(church['pattern'], 'Goal brushwork: the church')
        self.assertGreater(church['energy'], pattern.ENERGY_MIN)
        self.assertEqual(church['scale'], 2.0, 'canvas px per pattern px: the goal is drawn 2x')
        self.assertIsNone(sky['pattern'])
        self.assertEqual(sky['reason'], 'flat')
        self.assertEqual(self.krita.calls, ['Goal brushwork: the church'], 'no pattern for a flat part')
        # The registered image: the church's crop (130 x 180 goal px: a 130 px square), seamless, mid grey.
        tile = pixels(self.krita.patterns['Goal brushwork: the church'].image)
        self.assertEqual(tile.shape, (church['size'], church['size']))
        self.assertEqual(church['size'], 130)
        self.assertLess(abs(float(tile.mean()) - 128), 4)
        for axis in (0, 1):
            self.assertLessEqual(wrap_step(tile, axis), largest_inner_step(tile, axis) + 1)
        # Recorded for the brush texture (goal 6), by part name whatever its spacing or case.
        self.assertEqual(pattern.goal_brushwork_pattern('The  Church'), {'name': 'Goal brushwork: the church', 'energy': church['energy'], 'size': 130, 'scale': 2.0})
        self.assertIsNone(pattern.goal_brushwork_pattern('Moonlit sky'))

    def test_another_resource_of_the_name_and_a_refusal(self):
        self.krita = PatternKrita(artist={'Goal brushwork: the church'})
        result = self.run_op([{'name': 'the church', 'inside_shape': self.area('church', [20, 20, 260, 360])}])
        self.assertEqual(result['brushwork'][0]['pattern'], 'Goal brushwork: the church (2)', 'the name Krita gave it')
        self.assertEqual(pattern.goal_brushwork_pattern('the church')['name'], 'Goal brushwork: the church (2)')
        refused = self.run_op([{'name': 'the church', 'inside_shape': self.area('church', [20, 20, 260, 360])}], PatternKrita(refuse=True))
        self.assertEqual((refused['brushwork'][0]['pattern'], refused['brushwork'][0]['reason']), (None, 'refused'))
        self.assertIsNone(pattern.goal_brushwork_pattern('the church'), 'a part that lost its pattern has none recorded')

    def test_a_tiny_part_and_stock_krita_and_bad_calls(self):
        tiny = self.run_op([{'name': 'lamp', 'inside_shape': self.area('lamp', [100, 100, 30, 30])}])['brushwork'][0]
        self.assertEqual((tiny['pattern'], tiny['reason']), (None, 'tiny'))
        with self.assertRaisesRegex(ValueError, 'Toska'):
            self.run_op([{'name': 'the church', 'inside_shape': self.area('church', [20, 20, 260, 360])}], krita=types.SimpleNamespace())
        with self.assertRaisesRegex(ValueError, 'chat folder'):
            self.run_op([{'name': 'the church', 'inside_shape': {'mask_path': '/elsewhere/found-a.png', 'bounds': [0, 0, 10, 10]}}])
        with self.assertRaises(ValueError):
            self.run_op([])
        self.goal['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.run_op([{'name': 'the church', 'inside_shape': self.area('church', [20, 20, 260, 360])}])
        self.assertEqual(self.krita.calls, [], 'nothing made by a call that was refused')


class BrushworkDispatch(unittest.TestCase):
    """creative_tools.py routes brushwork_patterns to the craft in a chat, as a call that changes no document (no pass)."""
    def test_routed_in_a_chat_without_a_pass(self):
        import test_region_craft as region_tests
        setup = type('Setup', (region_tests.RegionSetup, unittest.TestCase), {'runTest': lambda self: None})()
        setup.setUp()
        self.addCleanup(setup.doCleanups)
        seen = []
        setup.h._brushwork_patterns = lambda doc, session, params: seen.append(params) or {'status': 'ok', 'brushwork': []}
        result = region_tests.run(setup.h, 'brushwork_patterns', {'goal': {}, 'parts': []})
        self.assertEqual(result, {'status': 'ok', 'brushwork': []})
        self.assertEqual(seen, [{'goal': {}, 'parts': []}])
        self.assertEqual(setup.h._creative_session['passes'], [])


if __name__ == '__main__':
    unittest.main()

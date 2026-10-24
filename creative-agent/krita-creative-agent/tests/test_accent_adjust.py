# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""accent_adjust.py: paint_accents adjusts the painting's own paint with Krita's filters (the artist, 2026-10-23):
soft masks from the accents; one group of baked layers made from the canvas's visible pixels, Dodge for lights (with a
Screen bloom), Burn for darks, High Pass in Overlay for detail. Pure parts on numpy; the operation on the fake layer
tree of the filter tests. Files go to a temporary folder that is removed."""
import sys
import types
import unittest
import numpy as np
import test_filters as filter_tests

region_tests = filter_tests.region_tests
adjust = sys.modules['creative_test_package.accent_adjust']


def light(x, y, size=1.5, strength=0.8):
    return {'kind': 'lights', 'x': x, 'y': y, 'size': size, 'strength': strength}


class MaskTests(unittest.TestCase):
    def test_a_light_is_a_soft_disc_its_value_from_the_strength_and_a_line_a_soft_band(self):
        rect = [0, 0, 64, 64]
        m = adjust.mask([dict(light(32, 32, size=16, strength=0.6))], rect)
        # Rehearsal (2026-10-24): a mask at the strength itself halved an already gentle Dodge: at least MASK_FLOOR.
        self.assertAlmostEqual(float(m[32, 32]), adjust.MASK_FLOOR + (1 - adjust.MASK_FLOOR) * 0.6, places=2)
        self.assertAlmostEqual(float(adjust.mask([dict(light(32, 32, size=16, strength=0.0))], rect)[32, 32]), adjust.MASK_FLOOR, places=2)
        self.assertEqual(float(m[2, 2]), 0.0, 'nothing far from it')
        edge = m[32, 32 + 7]
        self.assertTrue(0.0 < edge < float(m[32, 32]), 'feathered, not a hard cut')

        band = adjust.mask([{'kind': 'detail', 'x': 32, 'y': 32, 'size': 2, 'strength': 1, 'points': [[10, 32], [54, 32]]}], rect)
        self.assertGreater(float(band[32, 30]), 0.8); self.assertEqual(float(band[10 + 0, 10]), 0.0)
        self.assertEqual(adjust.rect_of([light(-50, -50)], 64, 64), None, 'off the canvas: nothing')

    def test_the_rehearsal_defaults_are_noticeable(self):
        # Measured on the rehearsal canvas view (New Moscow, 140 accents): mean ΔE inside the masks lights 13.3 -> 16.3,
        # darks 9.9 -> 17.5, detail 2.7 -> 5.5, the ring just outside unchanged (no halo).
        self.assertEqual((adjust.EXPOSURE, adjust.MASK_FLOOR, adjust.DETAIL_GAIN, adjust.BLOOM_OPACITY), ((0.3, 0.9), 0.5, 2.5, 0.35))


    def test_the_plan_dodges_lights_with_a_bloom_burns_darks_and_high_passes_detail(self):
        accents = [light(5, 5, strength=1.0), light(9, 9, strength=0.0), {'kind': 'darks', 'x': 2, 'y': 2, 'size': 2, 'strength': 0.5},
                   {'kind': 'detail', 'x': 3, 'y': 3, 'size': 2, 'strength': 0.5, 'points': [[1, 1], [6, 6]]}]
        layers = {label: (how, setting, opacity) for _kind, label, how, setting, opacity, _g in adjust.plan(accents)}
        self.assertEqual(layers['lights (dodge)'][:2], ('dodge', {'type': adjust.HIGHLIGHTS, 'exposure': adjust.exposure(accents[:2])}))
        self.assertEqual(layers['bloom (screen)'][0], 'screen'); self.assertEqual(layers['bloom (screen)'][2], adjust.BLOOM_OPACITY)
        self.assertEqual(layers['darks (burn)'][:2], ('burn', {'type': adjust.SHADOWS, 'exposure': adjust.exposure(accents[2:3])}))
        self.assertEqual(layers['detail (high pass, overlay)'][0], 'overlay')
        self.assertTrue(adjust.EXPOSURE[0] <= adjust.exposure(accents[:2]) <= adjust.EXPOSURE[1])
        self.assertEqual([label for _k, label, *_ in adjust.plan(accents)][-1], 'bloom (screen)', 'the bloom on top')
        self.assertEqual(adjust.tiles([light(10, 10, size=8), light(5990, 4490, size=8)], 6000, 4500), [[0, 0, 256, 256], [5888, 4352, 112, 148]])

    def test_the_cut_keeps_the_filtered_pixels_only_under_the_mask(self):
        pixels = bytes([10, 20, 30, 255]) * 4
        out = np.frombuffer(adjust.cut(pixels, np.array([[1.0, 0.5], [0.0, 0.25]], np.float32)), np.uint8).reshape(2, 2, 4)
        self.assertEqual(out[..., 3].tolist(), [[255, 128], [0, 64]])
        self.assertEqual(out[0, 0, :3].tolist(), [10, 20, 30])


import test_layer_craft as layer_tests


def composite(node, width, height):
    """What Krita shows of `node`: a paint layer's pixels at its opacity; a group isolated (its children composited over
    transparency, each by its blend mode: Overlay and Screen against the group's own backdrop), then laid over what is
    below it. Float RGBA 0-1, BGR order kept."""
    if node.kind != 'grouplayer':
        out = node.data.astype(np.float32) / 255
        out[..., 3] *= node.alpha / 255
        return out
    out = np.zeros((height, width, 4), np.float32)
    for child in node.children:
        if not child.shown:
            continue
        src = composite(child, width, height)
        a, base, top = src[..., 3:4], out[..., :3], src[..., :3]
        if child.blend == 'overlay':
            top = np.where(base < 0.5, 2 * base * top, 1 - 2 * (1 - base) * (1 - top)) * out[..., 3:4] + top * (1 - out[..., 3:4])
        elif child.blend == 'screen':
            top = (1 - (1 - base) * (1 - top)) * out[..., 3:4] + top * (1 - out[..., 3:4])
        alpha = a + out[..., 3:4] * (1 - a)
        out[..., :3] = np.where(alpha > 0, (top * a + base * out[..., 3:4] * (1 - a)) / np.maximum(alpha, 1e-6), 0)
        out[..., 3:4] = alpha
    out[..., 3] *= node.alpha / 255
    return out


class PixelNode(layer_tests.Node):
    """A layer of a W x H painting that holds real pixels (BGRA) and composites like Krita (composite above)."""
    def __init__(self, doc, name, kind):
        super().__init__(doc, name, kind)
        self.data = np.zeros((doc.height(), doc.width(), 4), np.uint8)
    def pixelData(self, x, y, w, h): return self.data[y:y + h, x:x + w].tobytes()
    def setPixelData(self, data, x, y, w, h):
        self.data[y:y + h, x:x + w] = np.frombuffer(bytes(data), np.uint8).reshape(h, w, 4); return True
    def projectionPixelData(self, x, y, w, h):
        self.doc.reads.append((x, y, w, h))
        return np.clip(np.round(composite(self, self.doc.width(), self.doc.height())[y:y + h, x:x + w] * 255), 0, 255).astype(np.uint8).tobytes()


class PixelDocument(filter_tests.Document):
    def __init__(self, width=64, height=64):
        self.size = (width, height); self.reads = []
        super().__init__()
        self.root = PixelNode(self, 'root', 'grouplayer')
    def width(self): return self.size[0]
    def height(self): return self.size[1]
    def createNode(self, name, kind): return PixelNode(self, name, kind)


def dodged(v, exposure): return np.clip(v * (1 + exposure / 3), 0, 255)
def burned(v, exposure):
    f = exposure / 3 * 255; return np.clip((v - f) / (1 - exposure / 3), 0, 255)


class PixelFilter:
    """Krita's Dodge and Burn on a layer's rect, as plugins/color/colorspaceextensions computes them; it records the
    document's selection when it runs (an active selection would limit it)."""
    def __init__(self, name, log):
        self.name, self.log, self.config = name, log, {}
    def configuration(self): return filter_tests.native.InfoObject()
    def setConfiguration(self, info): self.config = info.properties()
    def apply(self, node, x, y, w, h):
        self.log.append((self.name, dict(self.config), (x, y, w, h), node.doc.chosen))
        part = node.data[y:y + h, x:x + w, :3].astype(np.float32)
        node.data[y:y + h, x:x + w, :3] = (dodged if self.name == 'dodge' else burned)(part, self.config['exposure']).round().astype(np.uint8)
        return True


class AccentsOperationTests(region_tests.RegionSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.log = []
        previous = adjust.Krita
        adjust.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(filter=lambda name: PixelFilter(name, self.log)))
        self.addCleanup(setattr, adjust, 'Krita', previous)
        self.painting(64, 64)

    def painting(self, width, height):
        """An artist's painting: a mid-grey ground, a soft light blob at (16, 16), a dark bar at x 40-42; lettering above."""
        self.h = filter_tests.Harness(self.h._creative_session['output'])
        doc = self.h.doc = PixelDocument(width, height)
        self.h._creative_session.update(document_id=filter_tests.native.module.document_id(doc), width=width, height=height)
        base = doc.createNode('Painting', 'paintlayer'); doc.root.addChildNode(base, None)
        base.data[...] = (120, 120, 120, 255)
        ys, xs = np.mgrid[0:height, 0:width]
        blob = np.exp(-((xs - 16) ** 2 + (ys - 16) ** 2) / 30.0)
        base.data[..., :3] = np.clip(120 + 100 * blob, 0, 255)[..., None].astype(np.uint8)
        base.data[:, 40:43, :3] = 40
        self.base = base
        return doc

    def run_accents(self, accents, identifier='a1', **extra):
        return region_tests.run(self.h, 'accents', dict({'name': 'Accents', 'accents': accents, 'stage_id': 'move-1'}, **extra), identifier)

    def shown(self):
        return np.round(composite(self.h.doc.root, self.h.doc.width(), self.h.doc.height()) * 255)

    def group(self, result):
        return self.h._creative_node(self.h.doc, result['layer_id'])

    def test_what_the_painting_shows_is_brightened_deepened_and_sharpened_never_a_grey_haze_or_a_soft_copy(self):
        before = self.shown()
        result = self.run_accents([light(16, 16, size=10, strength=1.0), {'kind': 'detail', 'x': 41, 'y': 32, 'size': 3, 'strength': 1.0,
                                   'points': [[41, 8], [41, 56]]}, {'kind': 'detail', 'x': 56, 'y': 56, 'size': 3, 'strength': 1.0,
                                   'points': [[52, 56], [60, 56]]}])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        after = self.shown()
        self.assertTrue(all(c.blend == 'normal' for c in self.group(result).childNodes()), 'every blend baked')
        self.assertGreater(after[16, 16, :3].mean(), before[16, 16, :3].mean() + 5, 'the light is brighter')
        self.assertTrue((after[8:24, 8:24, :3] >= before[8:24, 8:24, :3] - 1).all(), 'a light and its bloom never darken')
        self.assertLess(after[32, 41, :3].mean(), before[32, 41, :3].mean(), 'the dark bar is crisper (darker in its middle)')
        flat = np.abs(after[56, 54:59, :3] - before[56, 54:59, :3]).max()
        self.assertLessEqual(flat, 2, 'on flat paint the high pass changes nothing: no grey haze')

    def test_every_kind_adjusts_the_same_clean_paint(self):
        result = self.run_accents([light(16, 16, size=8, strength=1.0), {'kind': 'darks', 'x': 16, 'y': 16, 'size': 8, 'strength': 1.0}])
        darks, lights, _bloom = self.group(result).childNodes()
        exposure = self.log[1][1]['exposure']
        expected = dodged(self.base.data[16, 16, :3].astype(np.float32), exposure).round()
        self.assertEqual(lights.data[16, 16, :3].tolist(), expected.tolist(), 'dodged from the painting, not from the burned layer')

    def test_an_active_selection_never_limits_a_filter_and_is_put_back(self):
        chosen = object()
        self.h.doc.chosen = chosen
        self.run_accents([light(16, 16, size=8)])
        self.assertTrue(self.log and all(entry[3] is None for entry in self.log), 'no selection while filtering')
        self.assertIs(self.h.doc.chosen, chosen)

    def test_guides_lettering_and_later_layers_are_never_read_into_the_accents(self):
        doc = self.h.doc
        self.run_accents([light(50, 50, size=4)], 'first')                 # the move's group exists; lettering goes above it
        guides = doc.createNode(adjust_guides_name(), 'grouplayer'); doc.root.addChildNode(guides, None)
        line = doc.createNode('Guide', 'paintlayer'); guides.addChildNode(line, None)
        line.data[14:19, :, :] = (255, 128, 0, 255)                     # a guide line across the light
        letters = doc.createNode('Lettering', 'paintlayer'); doc.root.addChildNode(letters, None)
        letters.data[10:13, :, :] = (0, 0, 255, 255)
        self.h._creative_session.setdefault('passes', []).append({'kind': 'letter', 'layer_id': letters.id})
        self.h._guide_group = lambda doc, session=None, create=False: guides
        result = self.run_accents([light(16, 16, size=10, strength=1.0)], 'second')
        dodge = self.group(result).childNodes()[0]
        for y in (11, 16):
            expected = dodged(self.base.data[y, 16, :3].astype(np.float32), self.log[-1][1]['exposure']).round()
            self.assertEqual(dodge.data[y, 16, :3].tolist(), expected.tolist(), 'row %d: only the painting below' % y)
        self.assertTrue(guides.shown and letters.shown, 'shown again')

    def test_nothing_on_the_canvas_makes_no_group(self):
        before = len(self.h.doc.root.childNodes())
        with self.assertRaisesRegex(ValueError, 'canvas'):
            self.run_accents([light(-30, -30)])
        self.assertEqual(len(self.h.doc.root.childNodes()), before)

    def test_only_the_squares_the_masks_touch_are_read_and_written(self):
        doc = self.painting(600, 520)
        self.run_accents([light(10, 10, size=8), light(590, 510, size=8)])
        self.assertTrue(doc.reads and all(w <= adjust.TILE + 40 and h <= adjust.TILE + 40 for _x, _y, w, h in doc.reads), doc.reads)
        self.assertLessEqual(sum(w * h for _x, _y, w, h in doc.reads), 4 * (adjust.TILE + 40) ** 2, 'two corners, never the whole canvas')

    def test_caps_and_bounds(self):
        for accents, message in (([dict(light(1, 1), size=adjust.MAX_SIZE + 1)], 'size'), ([light(1, 1)] * (adjust.MOST + 1), 'accents'),
                                 ([{'kind': 'detail', 'x': 5, 'y': 5, 'size': 2, 'strength': 1, 'points': [[5, 5], [500, 5]]}], 'points'),
                                 ([dict(light(1, 1), strength=2)], 'strength'), ([dict(light(1, 1), colour='#ffffff')], 'accent is')):
            with self.assertRaisesRegex(ValueError, message):
                self.run_accents(accents, 'bad-' + message)

    def test_a_selection_area_cuts_the_masks_to_its_own_pixels(self):
        coverage = np.zeros((64, 64), np.uint8); coverage[:, :16] = 255                # the left half of the light only
        class Sel:
            def pixelData(self, x, y, w, h): return coverage[y:y + h, x:x + w].tobytes()
        self.h._region_check_named = lambda doc, session, name: None
        self.h._region_load = lambda session, name, doc=None: Sel()
        result = self.run_accents([light(16, 16, size=10, strength=1.0)], selection='Lamp')
        for layer in self.group(result).childNodes():
            self.assertEqual(int(layer.data[:, 17:, 3].max()), 0, layer.label + ': nothing outside the selection')
            self.assertGreater(int(layer.data[16, 14, 3]), 0)


def adjust_guides_name():
    return sys.modules['creative_test_package.guide_craft'].GUIDES_GROUP


if __name__ == '__main__':
    unittest.main()

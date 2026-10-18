"""Selections and region fills on a fake 4x4 canvas. Saved selections go to a temporary folder that is removed."""
import os
import sys
import tempfile
import types
import unittest
import test_layer_craft as layer_tests

native = layer_tests.native
craft = layer_tests.craft
region = sys.modules['creative_test_package.region_craft']
SIZE = 4


class Mask:
    """A selection over the whole 4x4 canvas, one byte per pixel."""
    def __init__(self): self.m, self.ops = bytearray(SIZE * SIZE), []
    def _rows(self, x, y, w, h): return [(row, row * SIZE + x, row * SIZE + x + w) for row in range(y, y + h)]
    def select(self, x, y, w, h, value):
        for _row, a, b in self._rows(x, y, w, h): self.m[a:b] = bytes([value]) * (b - a)
    def setPixelData(self, data, x, y, w, h):
        data = bytes(data)
        for index, (_row, a, b) in enumerate(self._rows(x, y, w, h)): self.m[a:b] = data[index * w:(index + 1) * w]
    def pixelData(self, x, y, w, h): return b''.join(bytes(self.m[a:b]) for _row, a, b in self._rows(x, y, w, h))
    def _box(self):
        cells = [(i % SIZE, i // SIZE) for i, v in enumerate(self.m) if v]
        if not cells: return 0, 0, 0, 0
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    def x(self): return self._box()[0]
    def y(self): return self._box()[1]
    def width(self): return self._box()[2]
    def height(self): return self._box()[3]
    def add(self, other): self.m = bytearray(max(a, b) for a, b in zip(self.m, other.m))
    def subtract(self, other): self.m = bytearray(max(0, a - b) for a, b in zip(self.m, other.m))
    def intersect(self, other): self.m = bytearray(min(a, b) for a, b in zip(self.m, other.m))
    def invert(self): self.m = bytearray(255 - v for v in self.m); self.ops.append('invert')
    def grow(self, x, y): self.ops.append(('grow', x))
    def shrink(self, x, y, lock): self.ops.append(('shrink', x))
    def border(self, x, y): self.ops.append(('border', x))
    def feather(self, value): self.ops.append(('feather', value))
    def smooth(self): self.ops.append('smooth')


class Layer(layer_tests.Node):
    """A layer whose pixel reads and writes honour their rectangle."""
    def __init__(self, doc, name, kind):
        super().__init__(doc, name, kind); self.pixels = bytearray(self.pixels)
    def _rows(self, x, y, w, h): return [((row * SIZE + x) * 4, (row * SIZE + x + w) * 4) for row in range(y, y + h)]
    def pixelData(self, x, y, w, h): return b''.join(bytes(self.pixels[a:b]) for a, b in self._rows(x, y, w, h))
    def projectionPixelData(self, x, y, w, h): return self.pixelData(x, y, w, h)
    def setPixelData(self, data, x, y, w, h):
        for index, (a, b) in enumerate(self._rows(x, y, w, h)): self.pixels[a:b] = data[index * w * 4:(index + 1) * w * 4]
        return True
    def clone(self):
        copy = Layer(self.doc, self.label, self.kind)
        copy.pixels, copy.alpha_locked, copy.blend, copy.inherit = bytearray(self.pixels), self.alpha_locked, self.blend, self.inherit
        return copy


class Document(layer_tests.TreeDocument):
    def __init__(self):
        super().__init__(); self.root = Layer(self, 'root', 'grouplayer')
    def createNode(self, name, kind): return Layer(self, name, kind)


def fake_raster():
    """region_raster without Qt: shapes fill their rectangle; a fill is its colour where the mask is set."""
    raster = types.ModuleType('creative_test_package.region_raster'); raster.calls = []
    raster.shape_mask = lambda shape, rect, points=None: bytes([255]) * (rect[2] * rect[3])
    def paint(base, w, h, mask, spec, origin, alpha_lock=False):
        raster.calls.append(dict(base=base, rect=(origin[0], origin[1], w, h), mask=mask, spec=spec, alpha_lock=alpha_lock))
        colour = bytes.fromhex(spec.get('color', '#808080')[1:])[::-1]          # BGR
        out = bytearray(base if base is not None else bytes(w * h * 4))
        for i, coverage in enumerate(mask):
            if coverage and not (alpha_lock and out[i * 4 + 3] == 0):
                out[i * 4:i * 4 + 3] = colour
                if not alpha_lock: out[i * 4 + 3] = coverage
        return bytes(out)
    raster.paint = paint
    return raster


class Harness(layer_tests.Harness):
    def __init__(self, folder):
        super().__init__(); self.doc = Document()
        self._creative_session.update(document_id=native.module.document_id(self.doc), output=folder)
    def _region_pattern_image(self, name): return 'image of ' + name


def run(h, operation, params, identifier=None):
    request = {'operation': operation, 'session_id': 'session', 'params': params}
    if identifier: request['operation_id'] = identifier
    return h.cmd_creative(request)


class RegionSetup:
    """A harness with fake selections and a fake raster, and a temporary study folder."""
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        previous = native.module.Selection, craft.Selection, region.Selection
        native.module.Selection = craft.Selection = region.Selection = Mask
        self.addCleanup(lambda: setattr(native.module, 'Selection', previous[0]) or setattr(craft, 'Selection', previous[1])
                        or setattr(region, 'Selection', previous[2]))
        self.raster = fake_raster()
        prior = sys.modules.get(self.raster.__name__)
        sys.modules[self.raster.__name__] = self.raster; native.package.region_raster = self.raster
        self.addCleanup(lambda: sys.modules.__setitem__(self.raster.__name__, prior) if prior else sys.modules.pop(self.raster.__name__, None))
        self.h = Harness(folder.name)

    def artist_layer(self, name='Figure'):
        node = Layer(self.h.doc, name, 'paintlayer'); self.h.doc.root.addChildNode(node, None); return node


class TexturePassTests(RegionSetup, unittest.TestCase):
    """Strokes on a blended layer clipped to flats: texture that cannot leave its shape."""
    STROKE = {'start': [1, 1], 'segments': [[1, 1, 2, 2, 3, 3]], 'size': 2, 'opacity': 1, 'flow': 1, 'color': '#806040'}

    def test_texture_strokes_go_on_a_clipped_overlay_layer(self):
        flats = run(self.h, 'fill_region', {'name': 'Coat', 'color': '#302018', 'clip_base': True,
                                             'area': [{'shape': 'rectangle', 'bounds': [0, 0, 2, 4]}], 'stage_id': 's'}, 'flats')
        painted_on = []
        self.h.cmd_curve_stroke = lambda stroke, settle=True: painted_on.append(self.h.doc.active) or {'status': 'ok'}
        texture = run(self.h, 'paint_pass', {'name': 'Coat fur', 'preset': 'b) Basic-1', 'strokes': [self.STROKE], 'stage_id': 's',
                                              'blend_mode': 'overlay', 'clip_to': flats['layer_id'], 'layer_opacity': 0.4}, 'fur')
        self.assertEqual(texture['status'], 'ok', texture.get('error'))
        layer = self.h._creative_node(self.h.doc, texture['layer_id'])
        self.assertEqual((layer.blendingMode(), layer.opacity(), layer.inheritAlpha()), ('overlay', round(0.4 * 255), True))
        self.assertEqual(texture['clip']['mode'], 'live', 'a live clip to the flats')
        self.assertEqual(painted_on, [layer], 'the strokes paint on the texture layer')
        self.assertEqual(self.h._creative_session['passes'][-1]['clip']['base_id'], flats['layer_id'])

    def test_texture_pass_refusals(self):
        with self.assertRaisesRegex(ValueError, 'blend mode'):
            run(self.h, 'paint_pass', {'name': 'Bad', 'preset': 'b) Basic-1', 'strokes': [self.STROKE], 'blend_mode': 'sparkle'}, 'bad')
        with self.assertRaisesRegex(ValueError, 'leave out continue_layer_id'):
            run(self.h, 'paint_pass', {'name': 'Bad', 'preset': 'b) Basic-1', 'strokes': [self.STROKE], 'blend_mode': 'overlay',
                                       'continue_layer_id': 'x'}, 'bad-2')
        self.assertEqual(self.h._creative_session['passes'], [])


class RegionTests(RegionSetup, unittest.TestCase):
    # ----- select -------------------------------------------------------------
    def test_select_combines_steps_and_saves_without_a_pass(self):
        result = run(self.h, 'select', {'name': 'Sky', 'steps': [
            {'shape': 'rectangle', 'bounds': [0, 0, 2, 4]},
            {'shape': 'rectangle', 'bounds': [0, 0, 4, 1], 'grow': 2, 'feather': 1},
            {'shape': 'ellipse', 'bounds': [0, 3, 1, 1], 'mode': 'subtract', 'smooth': True}]})
        self.assertEqual((result['bounds'], result['selected_pixels']), ([0, 0, 4, 4], 9))
        saved = self.h._region_load(self.h._creative_session, 'sky')         # names ignore case
        self.assertEqual(saved.pixelData(0, 0, 4, 4), bytes([255] * 4 + [255, 255, 0, 0] * 2 + [0, 255, 0, 0]))
        self.assertEqual(self.h._creative_session['passes'], [], 'a selection is not a pass')
        self.assertEqual(self.h.doc.selection_changes, [], "the artist's selection is never touched")
        self.assertEqual(os.listdir(os.path.join(self.h._creative_session['output'], '.selections'))[0][-4:], '.sel')

    def test_refinements_apply_in_a_fixed_order(self):
        applied = []
        original = region.RegionCraft._region_source
        def source(self_, doc, session, step, kind):
            mask = original(self_, doc, session, step, kind); applied.append(mask); return mask
        region.RegionCraft._region_source = source
        self.addCleanup(setattr, region.RegionCraft, '_region_source', original)
        run(self.h, 'select', {'name': 'Edge', 'steps': [{'shape': 'rectangle', 'bounds': [1, 1, 2, 2], 'feather': 3, 'border': 2,
                                                            'shrink': 1, 'grow': 4, 'smooth': True, 'invert': True}]})
        self.assertEqual(applied[0].ops, [('grow', 4), ('shrink', 1), ('border', 2), ('feather', 3), 'smooth', 'invert'])

    def test_selection_from_layer_alpha_leaves_the_layer_unchanged(self):
        figure = self.artist_layer()
        before = (bytes(figure.pixels), figure.parent, figure.shown, figure.label)
        result = run(self.h, 'select', {'name': 'Figure', 'steps': [{'layer_id': figure.id}]})
        self.assertEqual(result['selected_pixels'], 8, 'every other pixel is opaque')
        self.assertEqual(before, (bytes(figure.pixels), figure.parent, figure.shown, figure.label))

    def test_colour_range_selects_matching_opaque_pixels(self):
        pixels = bytes([10, 20, 30, 255, 12, 22, 33, 255, 10, 20, 30, 0, 90, 20, 30, 255])     # BGRA
        self.assertEqual(region.colour_mask(pixels, (30, 20, 10), 0), bytes([255, 0, 0, 0]))
        self.assertEqual(region.colour_mask(pixels, (30, 20, 10), 3), bytes([255, 255, 0, 0]), 'transparent never matches')
        self.h.doc.root.pixels = bytearray(layer_tests.Node(self.h.doc, 'x', 'paintlayer').pixels)    # the visible image
        result = run(self.h, 'select', {'name': 'Blue', 'steps': [{'color': '#1e140a', 'tolerance': 0, 'bounds': [0, 0, 4, 2]}]})
        self.assertEqual((result['bounds'], result['selected_pixels']), ([0, 0, 3, 2], 4))

    def test_connected_mask_keeps_only_what_touches_the_seed(self):
        # 6x3: a sky across the top that runs down the left edge, a separate patch of the same colour at the right
        # (a lit window), joined to the sky only diagonally, which does not count.
        mask = bytes([255, 255, 255, 255, 0,   0,
                      255, 0,   0,   0,   255, 0,
                      255, 0,   0,   0,   0,   255])
        self.assertEqual(region.connected_mask(mask, 6, 3, 2, 0), bytes([255, 255, 255, 255, 0, 0,
                                                                         255, 0, 0, 0, 0, 0,
                                                                         255, 0, 0, 0, 0, 0]))
        self.assertEqual(region.connected_mask(mask, 6, 3, 1, 1), bytes(18), 'a seed on an unmatched pixel selects nothing')
        self.assertEqual(region.connected_mask(mask, 6, 3, 5, 2), bytes(17) + b'\xff', 'the window alone')

    def test_seed_selects_the_connected_area_of_the_seed_colour(self):
        # The visible image: row 0 sky blue, row 1 sky at the left two pixels; the rest is a building of another colour,
        # except one sky-coloured pixel cut off at the bottom right.
        sky, wall = bytes([60, 20, 10, 255]), bytes([20, 20, 20, 255])
        rows = [sky * 4, sky * 2 + wall * 2, wall * 4, wall * 3 + sky]
        self.h.doc.root.pixels = bytearray(b''.join(rows))
        result = run(self.h, 'select', {'name': 'Sky', 'steps': [{'seed': [3, 0], 'tolerance': 10}]})
        self.assertEqual((result['bounds'], result['selected_pixels']), ([0, 0, 4, 2], 6), 'the cut-off pixel stays out')
        result = run(self.h, 'select', {'name': 'Top', 'steps': [{'seed': [0, 0], 'bounds': [0, 0, 4, 1]}]})
        self.assertEqual((result['bounds'], result['selected_pixels']), ([0, 0, 4, 1], 4), 'bounds limits the search')
        for step, message in (({'seed': [4, 0]}, 'seed'), ({'seed': [0, 2], 'bounds': [0, 0, 4, 1]}, 'inside its bounds'),
                              ({'seed': [0, 0], 'color': '#000000'}, 'one source')):
            with self.assertRaisesRegex(ValueError, message):
                run(self.h, 'select', {'name': 'Bad', 'steps': [step]})

    def test_steps_are_validated_before_anything_is_saved(self):
        figure = self.artist_layer()
        for steps, message in (([{'mode': 'add', 'grow': 2}], 'first step needs a source'),
                               ([{'shape': 'rectangle', 'bounds': [0, 0, 2, 2], 'mode': 'intersect'}], 'cannot intersect'),
                               ([{'shape': 'rectangle', 'bounds': [0, 0, 2, 2], 'layer_id': figure.id}], 'one source'),
                               ([{'shape': 'rectangle', 'bounds': [0, 0, 2, 2], 'tolerance': 3}], 'tolerance belongs'),
                               ([{'shape': 'rectangle', 'bounds': [0, 0, 9, 2]}], 'inside the image'),
                               ([{'shape': 'polygon', 'points': [[0, 0], [9, 0], [0, 3]]}], 'inside the canvas'),
                               ([{'shape': 'rectangle', 'bounds': [0, 0, 2, 2]}, {'grow': 200}], 'Step 2: grow'),
                               ([{'saved': 'Nowhere'}], 'No saved selection "Nowhere". Saved: none')):
            with self.assertRaisesRegex(ValueError, message): run(self.h, 'select', {'name': 'Bad', 'steps': steps})
        with self.assertRaisesRegex(ValueError, 'selection name'):
            run(self.h, 'select', {'name': '../escape', 'steps': [{'shape': 'rectangle', 'bounds': [0, 0, 1, 1]}]})
        with self.assertRaisesRegex(ValueError, 'empty'):
            run(self.h, 'select', {'name': 'None', 'steps': [{'shape': 'rectangle', 'bounds': [0, 0, 2, 2]},
                                                              {'shape': 'rectangle', 'bounds': [0, 0, 2, 2], 'mode': 'subtract'}]})
        self.assertFalse(os.path.exists(os.path.join(self.h._creative_session['output'], '.selections')))

    # ----- fill_region --------------------------------------------------------
    def test_flat_on_a_new_layer_in_one_call(self):
        run(self.h, 'select', {'name': 'Sky', 'steps': [{'shape': 'rectangle', 'bounds': [0, 0, 4, 2]}]})
        result = run(self.h, 'fill_region', {'name': 'Sky flat', 'selection': 'Sky', 'color': '#3a6ea5', 'blend_mode': 'normal'}, 'sky')
        layer = self.h.doc.root.childNodes()[-1]
        self.assertEqual((result['status'], result['filled_bounds'], layer.label), ('ok', [0, 0, 4, 2], 'Sky flat'))
        self.assertEqual(layer.pixelData(0, 0, 1, 1), bytes([0xa5, 0x6e, 0x3a, 255]))
        self.assertEqual(layer.pixelData(0, 2, 4, 2), bytes(layer_tests.Node(self.h.doc, 'x', 'paintlayer').pixels[32:]), 'outside is untouched')
        self.assertIsNone(self.raster.calls[0]['base'], 'a new layer has no pixels under the fill')
        entry, = self.h._creative_session['passes']
        self.assertEqual((entry['kind'], entry['title'], entry['layer_id']), ('fill_region', 'Sky flat', layer.id))

    def test_inline_area_and_a_gradient_reach_the_raster(self):
        gradient = {'start': [0, 0], 'end': [4, 0], 'stops': [{'offset': 0, 'color': '#000000'}, {'offset': 1, 'color': '#ffffff'}]}
        run(self.h, 'fill_region', {'name': 'Glow', 'area': [{'shape': 'ellipse', 'bounds': [1, 1, 2, 2]}], 'gradient': gradient}, 'glow')
        call, = self.raster.calls
        self.assertEqual((call['rect'], call['spec']['kind'], call['spec']['gradient']['type']), ((1, 1, 2, 2), 'gradient', 'linear'))

    def test_filling_an_agent_layer_edits_a_copy_and_reject_restores_it(self):
        run(self.h, 'create_layer', {'name': 'Flats', 'type': 'paint', 'alpha_lock': True}, 'flats')
        flats = self.h.doc.root.childNodes()[-1]
        result = run(self.h, 'fill_region', {'layer_id': flats.id, 'area': [{'shape': 'rectangle', 'bounds': [0, 0, 4, 4]}],
                                             'color': '#ff0000'}, 'recolour')
        copy = self.h.doc.root.childNodes()[-1]
        self.assertEqual((result['layer_id'], result['source_layer_id'], copy.label), (copy.id, flats.id, 'Flats'))
        self.assertFalse(flats.shown)
        self.assertTrue(self.raster.calls[0]['alpha_lock'], 'alpha lock is honoured')
        self.assertEqual(copy.pixelData(0, 0, 2, 1), bytes([0, 0, 255, 255, 10, 20, 30, 0]), 'only opaque pixels change colour')
        run(self.h, 'review_pass', {'pass_id': 'recolour', 'action': 'reject'}, 'reject')
        self.assertEqual((copy.shown, flats.shown), (False, True))

    def test_a_filled_clip_base_stays_a_live_clip_base(self):
        run(self.h, 'create_layer', {'name': 'Flats', 'type': 'paint', 'clip_base': True}, 'flats')
        group = self.h.doc.root.childNodes()[-1]; base = group.childNodes()[0]
        run(self.h, 'create_layer', {'name': 'Shadow', 'type': 'paint', 'blend_mode': 'multiply', 'clip_to': base.id}, 'shadow')
        extended = run(self.h, 'fill_region', {'layer_id': base.id, 'area': [{'shape': 'rectangle', 'bounds': [0, 0, 4, 4]}],
                                               'color': '#3a6ea5'}, 'extend')
        self.assertEqual([n.label for n in group.childNodes()], ['Flats', 'Flats', 'Shadow'], 'the copy sits above the hidden original')
        light = run(self.h, 'create_layer', {'name': 'Light', 'type': 'paint', 'clip_to': extended['layer_id']}, 'light')
        self.assertEqual(light['clip']['mode'], 'live')
        with self.assertRaisesRegex(ValueError, 'clip group'):
            run(self.h, 'set_layer', {'layer_id': extended['layer_id'], 'clip': True}, 'clip-base')

    def test_fill_refusals_change_nothing(self):
        figure = self.artist_layer()
        run(self.h, 'create_layer', {'name': 'Mine', 'type': 'paint'}, 'mine')
        mine = self.h.doc.root.childNodes()[-1]
        area = [{'shape': 'rectangle', 'bounds': [0, 0, 2, 2]}]
        for params, message in (({'layer_id': figure.id, 'area': area, 'color': '#ffffff'}, 'Only layers the agent created'),
                                ({'layer_id': mine.id, 'area': area, 'color': '#ffffff', 'blend_mode': 'multiply'}, 'set up a new layer'),
                                ({'name': 'X', 'area': area, 'color': '#ffffff', 'pattern': 'Paper'}, 'exactly one'),
                                ({'name': 'X', 'color': '#ffffff'}, 'Give the area'),
                                ({'name': 'X', 'area': area, 'pattern': 'Bricks'}, 'Unknown pattern'),
                                ({'name': 'X', 'area': area, 'gradient': {'start': [0, 0], 'end': [1, 0], 'stops': [{'offset': 1, 'color': '#000000'}, {'offset': 0, 'color': '#ffffff'}]}}, 'increasing'),
                                ({'area': area, 'color': '#ffffff'}, 'Name the new layer'),
                                ({'name': 'X', 'area': area, 'color': 'red'}, '#RRGGBB')):
            with self.assertRaisesRegex(ValueError, message): run(self.h, 'fill_region', params, 'bad-' + message[:8])
        empty = run(self.h, 'fill_region', {'name': 'X', 'color': '#ffffff', 'area': area + [dict(area[0], mode='subtract')]}, 'empty')
        self.assertEqual((empty['status'], empty['error_code']), ('rejected', 'validation_rejected'))
        self.assertEqual([n.label for n in self.h.doc.root.childNodes()], ['Figure', 'Mine'])
        self.assertEqual([p['kind'] for p in self.h._creative_session['passes']], ['create_layer'])

    def test_a_pattern_fill_loads_the_installed_pattern(self):
        run(self.h, 'fill_region', {'name': 'Paper', 'area': [{'shape': 'rectangle', 'bounds': [0, 0, 4, 4]}], 'pattern': 'Paper'}, 'paper')
        self.assertEqual(self.raster.calls[0]['spec'], {'kind': 'pattern', 'name': 'Paper', 'image': 'image of Paper'})


if __name__ == '__main__':
    unittest.main()

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


def fake_accel(doc):
    """agent_accel as the plugin sees it: no helper (every builder None) until a test sets `native`, which then answers
    seed and colour steps from the visible image as the C++ helper does: the mask cropped to the selected pixels."""
    accel = types.ModuleType('creative_test_package.agent_accel'); accel.calls = []; accel.native = False
    accel.NATIVE_STROKES, accel.paint_strokes = False, lambda *args, **kwargs: None     # paint_pass: no helper
    def answer(mask, x, y, w, h):
        cells = [(i % w, i // w) for i, v in enumerate(mask) if v]
        if not cells:
            return (0, 0, 0, 0), b''
        left, top = min(c[0] for c in cells), min(c[1] for c in cells)
        right, bottom = max(c[0] for c in cells) + 1, max(c[1] for c in cells) + 1
        return (x + left, y + top, right - left, bottom - top), b''.join(mask[row * w + left:row * w + right] for row in range(top, bottom))
    def similar(path, colour, tolerance, bounds):
        accel.calls.append(('similar', path, colour, tolerance, tuple(bounds)))
        if not accel.native:
            return None
        x, y, w, h = bounds
        return answer(region.colour_mask(doc.root.projectionPixelData(x, y, w, h), bytes.fromhex(colour[1:]), tolerance), x, y, w, h)
    def contiguous(path, seed, tolerance, bounds):
        accel.calls.append(('contiguous', path, tuple(seed), tolerance, tuple(bounds)))
        if not accel.native:
            return None
        x, y, w, h = bounds
        pixel = doc.root.projectionPixelData(seed[0], seed[1], 1, 1)
        mask = region.colour_mask(doc.root.projectionPixelData(x, y, w, h), bytes((pixel[2], pixel[1], pixel[0])), tolerance)
        return answer(region.connected_mask(mask, w, h, seed[0] - x, seed[1] - y), x, y, w, h)
    accel.select_similar, accel.select_contiguous = similar, contiguous
    accel.whole = False                                   # a protocol-4 helper: the whole select in one call
    def build(path, steps):
        if not accel.whole:                               # no protocol-4 helper: no call recorded, as the others
            return None
        accel.calls.append(('build', path, [dict(step) for step in steps]))
        native, accel.native = accel.native, True
        combined = bytearray(SIZE * SIZE)
        try:
            for index, step in enumerate(steps):
                bounds = tuple(step.get('bounds') or (0, 0, SIZE, SIZE))
                (x, y, w, h), mask = (contiguous(path, step['seed'], step.get('tolerance', 24), bounds) if 'seed' in step
                                      else similar(path, step['color'], step.get('tolerance', 24), bounds))
                full = bytearray(SIZE * SIZE)
                for row in range(h):
                    full[(y + row) * SIZE + x:(y + row) * SIZE + x + w] = mask[row * w:(row + 1) * w]
                mode = 'replace' if index == 0 else step.get('mode', 'add')
                combined = full if mode == 'replace' else bytearray(
                    max(a, b) if mode == 'add' else max(0, a - b) if mode == 'subtract' else min(a, b) for a, b in zip(combined, full))
        finally:
            accel.native = native
            del accel.calls[-len(steps):]                 # only the build call is the helper's
        return answer(bytes(combined), 0, 0, SIZE, SIZE)
    accel.build_selection = build
    return accel


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
        self.accel = fake_accel(self.h.doc)
        prior_accel = sys.modules.get(self.accel.__name__)
        sys.modules[self.accel.__name__] = self.accel; native.package.agent_accel = self.accel
        def restore():                                   # `from . import` falls back to the package attribute: remove both
            if prior_accel: sys.modules[self.accel.__name__] = prior_accel; native.package.agent_accel = prior_accel
            else: sys.modules.pop(self.accel.__name__, None); native.package.__dict__.pop('agent_accel', None)
        self.addCleanup(restore)

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

    def _small_edges(self):
        """selection_edges at the 4x4 canvas's scale: edges from 2 px, paint compared 1 px away."""
        import importlib
        edges = importlib.import_module('creative_test_package.selection_edges')
        saved = edges.MIN_PIXELS, edges.PROBE
        edges.MIN_PIXELS, edges.PROBE = 2, 1
        self.addCleanup(lambda: (setattr(edges, 'MIN_PIXELS', saved[0]), setattr(edges, 'PROBE', saved[1])))

    def test_select_reports_a_straight_edge_through_open_paint(self):
        # Run 10-12: a sky selection ending in a straight line in open sky printed it into every fill and stamp.
        self._small_edges()
        cut = run(self.h, 'select', {'name': 'Sky', 'steps': [{'shape': 'rectangle', 'bounds': [0, 0, 4, 2]}]})
        self.assertEqual([(e['edge'], e['at'], e['from'], e['to']) for e in cut['open_edges']], [('horizontal', 2, 0, 4)])
        self.assertIn('straight', cut['note'])
        whole = run(self.h, 'select', {'name': 'All', 'steps': [{'shape': 'rectangle', 'bounds': [0, 0, 4, 4]}]})
        self.assertNotIn('open_edges', whole, 'the canvas border is never an edge')
        filled = run(self.h, 'fill_region', {'name': 'Sky flat', 'selection': 'Sky', 'color': '#3a6ea5', 'blend_mode': 'normal'}, 'sky')
        self.assertEqual(len(filled['open_edges']), 1, 'the fill repeats the warning')

    def test_select_reports_where_its_time_goes(self):
        # Run 13: one select took 22 s though its flood fills take about 1 s; the phases say where the rest goes.
        result = run(self.h, 'select', {'name': 'Sky', 'steps': [{'shape': 'rectangle', 'bounds': [0, 0, 4, 2]}]})
        self.assertEqual(set(result['timings_ms']), {'build', 'bounds', 'save', 'edges'})

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

    def sky_and_building(self):
        # As in test_seed_selects_the_connected_area_of_the_seed_colour: a sky across the top and down the left, one
        # sky-coloured pixel cut off at the bottom right.
        sky, wall = bytes([60, 20, 10, 255]), bytes([20, 20, 20, 255])
        self.h.doc.root.pixels = bytearray(b''.join([sky * 4, sky * 2 + wall * 2, wall * 4, wall * 3 + sky]))

    def test_with_the_helper_seed_and_colour_steps_select_in_krita(self):
        self.sky_and_building(); self.accel.native = True
        seed = run(self.h, 'select', {'name': 'Sky', 'steps': [{'seed': [3, 0], 'tolerance': 10}]})
        self.assertEqual((seed['bounds'], seed['selected_pixels']), ([0, 0, 4, 2], 6), 'the cut-off pixel stays out')
        bounded = run(self.h, 'select', {'name': 'Top', 'steps': [{'seed': [0, 0], 'bounds': [0, 0, 4, 1]}]})
        self.assertEqual((bounded['bounds'], bounded['selected_pixels']), ([0, 0, 4, 1], 4), 'bounds limits the search')
        colour = run(self.h, 'select', {'name': 'All sky', 'steps': [{'color': '#0a143c', 'tolerance': 0}]})
        self.assertEqual((colour['bounds'], colour['selected_pixels']), ([0, 0, 4, 4], 7), 'a colour range is not joined')
        self.assertEqual(self.accel.calls, [('contiguous', '', (3, 0), 10, (0, 0, 4, 4)), ('contiguous', '', (0, 0), 24, (0, 0, 4, 1)),
                                            ('similar', '', '#0a143c', 0, (0, 0, 4, 4))],
                         'the default tolerance (24) and the whole canvas when no bounds are given')
        saved = self.h._region_load(self.h._creative_session, 'sky')
        self.assertEqual(saved.pixelData(0, 0, 4, 4), bytes([255] * 6 + [0] * 10), "the helper's mask lands at its own rect")

    def test_the_helper_and_the_python_path_select_the_same_pixels(self):
        self.sky_and_building()
        steps = [[{'seed': [3, 0], 'tolerance': 10}], [{'seed': [3, 3]}], [{'seed': [2, 2], 'bounds': [1, 1, 3, 3]}],
                 [{'color': '#0a143c', 'bounds': [0, 1, 4, 3]}], [{'seed': [0, 0]}, {'color': '#141414', 'mode': 'subtract'}]]
        masks = {}
        for native in (False, True):
            self.accel.native = native
            for index, step in enumerate(steps):
                built = self.h._region_build(self.h.doc, self.h._creative_session, step)
                masks.setdefault(index, []).append(built.pixelData(0, 0, 4, 4))
        for index, (python, helper) in masks.items():
            self.assertEqual(python, helper, 'steps %d' % index)

    # ----- the whole select in one call (protocol 4) -------------------------------------------------------------------
    def build_both(self, steps):
        """The selection's pixels through the one-call path, then step by step on the Python path, and the calls made."""
        self.accel.whole = True; self.accel.calls.clear()
        whole = self.h._region_build(self.h.doc, self.h._creative_session, steps)
        calls = list(self.accel.calls)
        self.accel.whole = False; self.accel.calls.clear()
        steps_built = self.h._region_build(self.h.doc, self.h._creative_session, steps)
        return (whole.pixelData(0, 0, 4, 4), whole.ops), (steps_built.pixelData(0, 0, 4, 4), steps_built.ops), calls

    def test_one_call_selects_the_same_pixels_as_step_by_step(self):
        self.sky_and_building()
        sky, wall = {'seed': [0, 0], 'tolerance': 10}, {'color': '#141414', 'tolerance': 0}
        cases = [[sky], [dict(sky, bounds=[0, 0, 3, 2])], [{'color': '#0a143c', 'bounds': [0, 1, 4, 3]}],
                 [sky, {'seed': [3, 3], 'tolerance': 0}], [sky, dict(wall, bounds=[1, 1, 2, 2])],
                 [{'color': '#0a143c'}, dict(sky, mode='subtract')], [{'color': '#0a143c'}, dict(sky, mode='subtract', bounds=[0, 0, 2, 4])],
                 [{'color': '#0a143c'}, dict(sky, mode='intersect')], [sky, {'color': '#0a143c', 'mode': 'intersect', 'bounds': [1, 0, 3, 4]}],
                 [sky, wall, {'seed': [3, 3], 'mode': 'replace'}], [sky, {'color': '#0a143c', 'mode': 'add'}, dict(wall, mode='subtract')]]
        for steps in cases:
            whole, by_step, calls = self.build_both(steps)
            self.assertEqual(whole, by_step, steps)
            self.assertEqual([call[0] for call in calls], ['build'], 'one call for %s' % steps)

    def test_one_call_sends_each_step_with_its_mode(self):
        self.sky_and_building(); self.accel.whole = True
        run(self.h, 'select', {'name': 'Sky', 'steps': [{'seed': [0, 0], 'tolerance': 10, 'bounds': [0, 0, 4, 4]},
                                                         {'color': '#141414', 'mode': 'subtract'}, {'seed': [3, 3], 'grow': 2}]})
        self.assertEqual(self.accel.calls, [('build', '', [{'seed': [0, 0], 'tolerance': 10, 'bounds': [0, 0, 4, 4], 'mode': 'replace'},
                                                           {'color': '#141414', 'mode': 'subtract'}, {'seed': [3, 3], 'mode': 'add'}])])

    def test_refinements_after_the_last_source_keep_their_order_in_one_call(self):
        self.sky_and_building()
        sky = {'seed': [0, 0], 'tolerance': 10}
        for steps in ([sky, {'seed': [3, 3], 'grow': 2, 'feather': 1, 'invert': True}],
                      [sky, {'color': '#141414', 'mode': 'subtract'}, {'shrink': 1, 'smooth': True}, {'invert': True}, {'border': 2, 'invert': True}],
                      [dict(sky, grow=3, invert=True)]):
            whole, by_step, calls = self.build_both(steps)
            self.assertEqual(whole, by_step, steps)
            self.assertEqual([call[0] for call in calls], ['build'], 'one call for %s' % steps)
        self.assertEqual(whole[1], [('grow', 3), 'invert'])

    def test_a_refinement_before_a_later_source_builds_step_by_step(self):
        # An invert, grow or smooth between sources changes what the later steps combine with: only the per-step path
        # applies it there, so the whole-select call is not made.
        self.sky_and_building()
        sky = {'seed': [0, 0], 'tolerance': 10}
        for steps in ([dict(sky, invert=True), {'seed': [3, 3], 'tolerance': 0}],
                      [sky, {'invert': True}, {'color': '#0a143c', 'mode': 'intersect'}],
                      [dict(sky, grow=1), {'color': '#141414', 'mode': 'subtract', 'bounds': [0, 0, 2, 2]}]):
            whole, by_step, calls = self.build_both(steps)
            self.assertEqual(whole, by_step, steps)
            self.assertNotIn('build', [call[0] for call in calls], steps)

    def test_other_sources_or_no_helper_build_step_by_step(self):
        self.sky_and_building()
        for steps in ([{'shape': 'rectangle', 'bounds': [0, 0, 2, 2]}, {'seed': [0, 0]}],
                      [{'seed': [0, 0]}, {'shape': 'rectangle', 'bounds': [0, 0, 2, 2], 'mode': 'subtract'}]):
            whole, by_step, calls = self.build_both(steps)
            self.assertEqual(whole, by_step, steps)
            self.assertNotIn('build', [call[0] for call in calls], steps)
        self.accel.calls.clear()                         # a helper without protocol 4 (build answers None): step by step
        built = self.h._region_build(self.h.doc, self.h._creative_session, [{'seed': [3, 0], 'tolerance': 10}])
        self.assertEqual(built.pixelData(0, 0, 4, 4), bytes([255] * 6 + [0] * 10))
        self.assertEqual([call[0] for call in self.accel.calls], ['contiguous'])
        self.accel.calls.clear()
        self.accel.whole = True                          # forced step by step (select_probe native: steps)
        self.h._region_build(self.h.doc, self.h._creative_session, [{'seed': [3, 0], 'tolerance': 10}], whole=False)
        self.assertEqual([call[0] for call in self.accel.calls], ['contiguous'])

    def test_one_call_with_nothing_selected_is_an_empty_selection(self):
        self.sky_and_building(); self.accel.whole = True
        with self.assertRaisesRegex(ValueError, 'empty'):
            run(self.h, 'select', {'name': 'None', 'steps': [{'seed': [0, 0]}, {'seed': [0, 0], 'mode': 'subtract'}]})

    def test_nothing_selected_by_the_helper_is_an_empty_selection(self):
        self.sky_and_building(); self.accel.native = True
        with self.assertRaisesRegex(ValueError, 'empty'):
            run(self.h, 'select', {'name': 'None', 'steps': [{'color': '#ffffff', 'tolerance': 0}]})

    def test_without_the_helper_the_python_path_selects(self):
        self.sky_and_building()                           # native stays off: every builder answers None
        result = run(self.h, 'select', {'name': 'Sky', 'steps': [{'seed': [3, 0], 'tolerance': 10}]})
        self.assertEqual((result['bounds'], result['selected_pixels']), ([0, 0, 4, 2], 6))
        self.assertEqual([call[0] for call in self.accel.calls], ['contiguous'], 'the helper was asked first')

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

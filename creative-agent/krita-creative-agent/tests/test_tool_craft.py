# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Krita's tools as agent operations (krita-fork 5.3): bucket_fill, enclose_and_fill, krita_gradient and smart_patch.
First the pure validation (creative_validation.py: options are checked dicts, nothing NaN, huge or unknown reaches Krita),
then the operations on the fake painting of the protection tests with a fake Node.fill / encloseAndFill / gradient /
smartPatch. Writes only into a temporary study folder."""
import math
import sys
import unittest
import test_native as native

validation = sys.modules['creative_test_package.creative_validation']
INF, NAN = float('inf'), float('nan')


class OptionTests(unittest.TestCase):
    def check(self, kind, options, **kw):
        return validation.tool_options(kind, options, **kw)

    def test_none_or_empty_options_are_empty(self):
        self.assertEqual(self.check('fill', None), {})
        self.assertEqual(self.check('fill', {}), {})

    def test_only_the_documented_keys_per_tool(self):
        self.check('fill', {'mode': 'similar', 'sample': 'all', 'threshold': 12, 'boundaryColor': '#112233'})
        for kind, key in (('fill', 'regions'), ('fill', 'name'), ('enclose', 'mode'), ('gradient', 'sample'), ('patch', 'opacity'),
                          ('patch', 'name'), ('fill', 'lol')):
            with self.assertRaisesRegex(ValueError, 'Unknown options: ' + key):
                self.check(kind, {key: 1})
        with self.assertRaisesRegex(ValueError, 'options must be an object'):
            self.check('fill', [])

    def test_whole_numbers_in_range_and_never_bools_nan_or_inf(self):
        self.assertEqual(self.check('fill', {'threshold': 12.0})['threshold'], 12)
        self.assertIsInstance(self.check('fill', {'threshold': 12.0})['threshold'], int)
        for bad in (0, 101, 1.5, True, '12', None, NAN, INF, -INF, 10 ** 30):
            with self.assertRaisesRegex(ValueError, 'threshold'):
                self.check('fill', {'threshold': bad})
        for key, low, high in (('spread', 0, 100), ('closeGap', 0, 32), ('grow', -400, 400), ('feather', 0, 400)):
            self.check('fill', {key: low}); self.check('fill', {key: high})
            for bad in (low - 1, high + 1):
                with self.assertRaisesRegex(ValueError, key):
                    self.check('fill', {key: bad})

    def test_a_number_too_big_for_a_float_is_a_plain_validation_error(self):
        for key in ('threshold', 'grow'):
            with self.assertRaisesRegex(ValueError, key):
                self.check('fill', {key: 10 ** 400})
        with self.assertRaisesRegex(ValueError, 'opacity'):
            self.check('fill', {'opacity': 10 ** 400})
        with self.assertRaisesRegex(ValueError, 'must be a finite number'):
            validation.numeric(10 ** 400, 'size', 0, 10)
        with self.assertRaisesRegex(ValueError, 'x'):
            validation.canvas_point([10 ** 400, 0], 'start', 4, 4, 4)
        with self.assertRaisesRegex(ValueError, 'x'):
            validation.canvas_pixel(10 ** 400, 0, 'x', 'y', 4, 4)

    def test_opacity_is_a_finite_number_from_0_to_1(self):
        self.assertEqual(self.check('fill', {'opacity': 0.5}), {'opacity': 0.5})
        self.assertEqual(self.check('fill', {'opacity': 1}), {'opacity': 1})
        for bad in (-0.1, 1.1, NAN, INF, True, '1'):
            with self.assertRaisesRegex(ValueError, 'opacity'):
                self.check('gradient', {'opacity': bad, 'colors': ['#000000', '#ffffff']})

    def test_booleans_are_booleans(self):
        self.check('fill', {'antialias': True, 'stopGrowingAtDarkestPixel': False, 'useSelectionAsBoundary': True})
        for bad in (1, 'true', None):
            with self.assertRaisesRegex(ValueError, 'antialias'):
                self.check('fill', {'antialias': bad})

    def test_choices_are_the_documented_words(self):
        for kind, key, good, bad in (('fill', 'mode', 'selection', 'flood'), ('fill', 'sample', 'layer', 'every'),
                                     ('enclose', 'regions', 'surroundedByColorOrTransparent', 'some'),
                                     ('gradient', 'shape', 'spiral', 'zigzag'), ('gradient', 'repeat', 'alternate', 'loop')):
            extra = {'colors': ['#000000', '#ffffff']} if kind == 'gradient' else {}
            if key == 'regions': extra['regionColor'] = '#000000'
            self.check(kind, dict(extra, **{key: good}))
            with self.assertRaisesRegex(ValueError, key):
                self.check(kind, dict(extra, **{key: bad}))

    def test_labels_go_with_sample_labels(self):
        self.assertEqual(self.check('fill', {'sample': 'labels', 'labels': [1, 2.0]})['labels'], [1, 2])
        for options, message in (({'labels': [1]}, 'sample'), ({'sample': 'labels'}, 'labels'), ({'sample': 'labels', 'labels': []}, 'labels'),
                                 ({'sample': 'labels', 'labels': [9]}, 'labels'), ({'sample': 'labels', 'labels': [1.5]}, 'labels'),
                                 ({'sample': 'labels', 'labels': [True]}, 'labels'), ({'sample': 'labels', 'labels': 'all'}, 'labels'),
                                 ({'sample': 'labels', 'labels': list(range(9)) + [1]}, 'labels')):
            with self.assertRaisesRegex(ValueError, message):
                self.check('fill', options)

    def test_colours_are_rrggbb(self):
        self.check('fill', {'boundaryColor': '#A0b1C2'})
        for bad in ('red', '#fff', '#12345g', 5, None):
            with self.assertRaisesRegex(ValueError, 'boundaryColor|Color'):
                self.check('fill', {'boundaryColor': bad})

    def test_a_blending_mode_is_a_known_id(self):
        self.assertEqual(self.check('fill', {'compositeOp': 'multiply'}), {'compositeOp': 'multiply'})
        with self.assertRaisesRegex(ValueError, 'Unknown blend mode'):
            self.check('fill', {'compositeOp': 'sparkle'})

    def test_enclose_regions_that_name_a_colour_need_one(self):
        for regions in ('color', 'colorOrTransparent', 'allExceptColor', 'allExceptColorOrTransparent', 'surroundedByColor', 'surroundedByColorOrTransparent'):
            with self.assertRaisesRegex(ValueError, 'regionColor'):
                self.check('enclose', {'regions': regions})
            self.check('enclose', {'regions': regions, 'regionColor': '#ffffff'})
        for regions in ('all', 'transparent', 'allExceptTransparent', 'surroundedByTransparent'):
            self.check('enclose', {'regions': regions})
        self.check('enclose', {'invert': True, 'includeContourRegions': True, 'includeSurroundingRegions': False, 'sample': 'all', 'grow': 2})
        with self.assertRaisesRegex(ValueError, 'regionColor'):
            self.check('enclose', {'regionColor': 'blue'})

    def test_a_gradient_needs_colours_or_a_named_gradient(self):
        with self.assertRaisesRegex(ValueError, 'options.colors or options.gradient'):
            self.check('gradient', {})
        out = self.check('gradient', {'colors': ['#000000', '#FFFFFF', '#ff0000'], 'shape': 'radial', 'repeat': 'forwards', 'reverse': True,
                                      'dither': 'bayer4', 'antiAliasThreshold': 0.5})
        self.assertEqual(out['colors'], ['#000000', '#FFFFFF', '#ff0000'])
        self.assertEqual(self.check('gradient', {'gradient': 'Sunset'}), {'gradient': 'Sunset'})
        self.assertEqual(self.check('gradient', {'gradient': 'Sunset', 'colors': ['#112233', '#445566']})['colors'], ['#112233', '#445566'])

    def test_gradient_colours_dither_and_threshold_are_checked(self):
        for options in ({'colors': ['#000000']}, {'colors': ['#000000'] * 17}, {'colors': 'black'}, {'colors': ['#000000', 'white']},
                        {'colors': ['#000000', '#ffffff'], 'dither': 'perlin'}, {'colors': ['#000000', '#ffffff'], 'dither': 1},
                        {'colors': ['#000000', '#ffffff'], 'antiAliasThreshold': 1.5}, {'colors': ['#000000', '#ffffff'], 'antiAliasThreshold': NAN},
                        {'gradient': ''}, {'gradient': 'x' * 201}, {'gradient': 5}):
            with self.assertRaises(ValueError, msg=options):
                self.check('gradient', options)
        for dither in (False, True, 'blueNoise', 'bayer2', 'bayer4', 'bayer8'):
            self.check('gradient', {'colors': ['#000000', '#ffffff'], 'dither': dither})

    def test_smart_patch_options(self):
        self.assertEqual(self.check('patch', {'accuracy': 99, 'patchRadius': 8}), {'accuracy': 99, 'patchRadius': 8})
        for options in ({'accuracy': 100}, {'accuracy': -1}, {'patchRadius': 1}, {'patchRadius': 9}, {'accuracy': 5.5}, {'accuracy': NAN}):
            with self.assertRaises(ValueError, msg=options):
                self.check('patch', options)


class PointTests(unittest.TestCase):
    def test_a_point_is_two_finite_numbers_inside_the_canvas_and_its_margin(self):
        self.assertEqual(validation.canvas_point([10, 20.5], 'start', 100, 80, 0), [10, 20.5])
        self.assertEqual(validation.canvas_point([-100, 160], 'start', 100, 80, 100), [-100, 160])
        for bad in ([1], [1, 2, 3], 'xy', None, [1, True], [NAN, 1], [1, INF], [-0.5, 1], [1, 80.5], [10 ** 12, 1]):
            with self.assertRaises(ValueError, msg=bad):
                validation.canvas_point(bad, 'start', 100, 80, 0)

    def test_a_seed_is_a_whole_pixel_inside_the_canvas(self):
        self.assertEqual(validation.canvas_pixel(3.0, 4, 'x', 'y', 10, 10), (3, 4))
        for x, y in ((10, 0), (0, 10), (-1, 0), (1.5, 2), (True, 2), (NAN, 2), (INF, 2), ('1', 2), (None, 2)):
            with self.assertRaises(ValueError, msg=(x, y)):
                validation.canvas_pixel(x, y, 'x', 'y', 10, 10)


class PatchAreaTests(unittest.TestCase):
    def test_the_fork_patches_at_most_512_by_512_pixels_and_the_error_has_the_numbers(self):
        validation.check_patch_area(512, 512)
        validation.check_patch_area(1000, 262)
        with self.assertRaisesRegex(ValueError, r'600 x 500 pixels \(300000\).*262144.*512 x 512'):
            validation.check_patch_area(600, 500)
        with self.assertRaises(ValueError):
            validation.check_patch_area(513, 512)


# ----- the operations, on the 4x4 fake painting of the protection tests ------------------------------------------------------
import types
import test_protection as protection_tests

region_tests = protection_tests.region_tests
tool_module = sys.modules['creative_test_package.tool_craft'] if 'creative_test_package.tool_craft' in sys.modules else None
DISC = [{'shape': 'rectangle', 'bounds': [0, 0, 4, 4]}]
LEFT = [{'shape': 'rectangle', 'bounds': [0, 0, 2, 4]}]


class ToolLayer(protection_tests.Layer):
    """A fork layer: Node.fill, encloseAndFill, gradient and smartPatch. Each records its call on `owner`, returns what
    `owner.answers` says (True by default) and paints what the real tool would, in the colour it was given, where its
    selection reaches."""
    owner = None

    def __init__(self, doc, name, kind):
        super().__init__(doc, name, kind); self.pixels = bytearray(16 * 4)      # a new layer is empty

    def clone(self):
        copy = ToolLayer(self.doc, self.label, self.kind)
        copy.pixels, copy.alpha_locked, copy.blend, copy.inherit, copy.owner = bytearray(self.pixels), self.alpha_locked, self.blend, self.inherit, self.owner
        return copy

    def _hex(self, colour):
        value = str(colour)
        return bytes.fromhex(value[5:7] + value[3:5] + value[1:3]) + bytes([255])

    def _reach(self, selection, area=None):
        limit = selection.pixelData(0, 0, 4, 4)
        inner = area.pixelData(0, 0, 4, 4) if area is not None else limit
        return [i for i in range(16) if limit[i] and inner[i]]

    def bounds(self):
        covered = [i for i in range(16) if self.pixels[i * 4 + 3]]
        if not covered: return types.SimpleNamespace(x=lambda: 0, y=lambda: 0, width=lambda: 0, height=lambda: 0, isEmpty=lambda: True)
        left, top = min(i % 4 for i in covered), min(i // 4 for i in covered)
        return types.SimpleNamespace(x=lambda: left, y=lambda: top, isEmpty=lambda: False, width=lambda: 1 + max(i % 4 for i in covered) - left,
                                     height=lambda: 1 + max(i // 4 for i in covered) - top)

    def _answer(self, name, args):
        owner = self.owner
        owner.calls.append((name,) + args + (self,))
        if owner.on_call:
            owner.on_call(name)
        if owner.raises:
            raise owner.raises
        return owner.answers.get(name, True)

    def _paints(self, name):
        return self.owner.answers.get(name, True) is True      # 'noop': Krita says true but everything was clipped away

    def fill(self, x, y, color, options=None, selection=None):
        if not self._answer('fill', (x, y, color, options, selection)): return False
        for i in (self._reach(selection) if self._paints('fill') else []): self.pixels[i * 4:i * 4 + 4] = self._hex(color)
        return True

    def encloseAndFill(self, area, color, options=None, selection=None):
        if not self._answer('encloseAndFill', (area, color, options, selection)): return False
        for i in (self._reach(selection, area) if self._paints('encloseAndFill') else []): self.pixels[i * 4:i * 4 + 4] = self._hex(color)
        return True

    def gradient(self, start, end, options=None, selection=None):
        if not self._answer('gradient', (start, end, options, selection)): return False
        for i in (self._reach(selection) if self._paints('gradient') else []): self.pixels[i * 4:i * 4 + 4] = self._hex(options['colors'][0] if 'colors' in options else '#808080')
        return True

    def smartPatch(self, area, options=None):
        if not self._answer('smartPatch', (area, options)): return False
        for i in (self._reach(area) if self._paints('smartPatch') else []): self.pixels[i * 4:i * 4 + 4] = bytes([1, 2, 3, 255])           # the patched paint
        return True


class ToolSetup(protection_tests.ProtectionSetup):
    def setUp(self):
        super().setUp()
        global tool_module
        tool_module = sys.modules['creative_test_package.tool_craft']
        self.calls, self.answers, self.raises, self.on_call = [], {}, None, None
        self.background = self.artist_layer('Sky')
        self.background.pixels = bytearray(bytes([150, 90, 40, 255]) * 16)
        doc = self.h.doc
        doc.createNode = lambda name, kind: self._node(doc, name, kind)
        stock = getattr(native.krita, 'Node', None)
        native.krita.Node = ToolLayer
        self.addCleanup(lambda: setattr(native.krita, 'Node', stock) if stock is not None else delattr(native.krita, 'Node'))
        previous = tool_module.Selection
        tool_module.Selection = region_tests.Mask
        self.addCleanup(setattr, tool_module, 'Selection', previous)
        app = types.SimpleNamespace(resources=lambda kind: {'gradient': {'Sunset': 1}}.get(kind, {}))
        prior = tool_module.Krita
        tool_module.Krita = types.SimpleNamespace(instance=lambda: app)
        self.addCleanup(setattr, tool_module, 'Krita', prior)
        self.moves = []
        doc.beginAgentMove = lambda name: self.moves.append(('begin', name)) or setattr(doc, 'is_open', True) or True
        doc.endAgentMove = lambda: self.moves.append(('end',)) or setattr(doc, 'is_open', False) or True
        doc.agentMoveOpen = lambda: getattr(doc, 'is_open', False)
        doc.agentMoveId = lambda: 1

    def _node(self, doc, name, kind):
        node = ToolLayer(doc, name, kind); node.owner = self; return node

    def op(self, operation, identifier='op', **params):
        return region_tests.run(self.h, operation, params, identifier)

    def bucket(self, identifier='bucket', **extra):
        return self.op('bucket_fill', identifier, **dict({'name': 'Wall', 'x': 1, 'y': 1, 'color': '#3a6ea5', 'stage_id': 's'}, **extra))

    def enclose(self, identifier='enclose', **extra):
        return self.op('enclose_and_fill', identifier, **dict({'name': 'Windows', 'enclose_area': LEFT, 'color': '#ffd27f', 'stage_id': 's'}, **extra))

    def gradient(self, identifier='gradient', **extra):
        return self.op('krita_gradient', identifier, **dict({'name': 'Dusk', 'start': [0, 0], 'end': [0, 4], 'stage_id': 's',
                                                             'options': {'colors': ['#112244', '#ffaa66']}}, **extra))

    def patch(self, identifier='patch', **extra):
        return self.op('smart_patch', identifier, **dict({'name': 'Seam repair', 'area': LEFT, 'stage_id': 's'}, **extra))

    def layers(self, name):
        found = []
        def visit(node):
            for child in node.children:
                found.append(child) if child.label == name and child.kind == 'paintlayer' else None
                visit(child)
        visit(self.h.doc.root)
        return found

    def painted(self, result):
        return self.h._creative_node(self.h.doc, result['layer_id'])

    def alpha(self, node):
        return [node.pixels[i * 4 + 3] for i in range(16)]


class BucketFillTests(ToolSetup, unittest.TestCase):
    def test_a_fill_is_one_node_fill_call_on_one_new_layer_with_a_short_description(self):
        result = self.bucket()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(len(self.calls), 1)
        name, x, y, colour, options, selection, node = self.calls[0]
        self.assertEqual((name, x, y, str(colour)), ('fill', 1, 1, '#3a6ea5'))
        self.assertIs(node, self.painted(result))
        self.assertEqual(len(self.layers('Wall')), 1)
        self.assertEqual(options['sample'], 'all', 'the new layer is empty: regions are found on the painting as shown')
        self.assertNotIn('mode', options)
        self.assertEqual(selection.pixelData(0, 0, 4, 4), bytes([255]) * 16, 'no area: the whole canvas, never the artist\'s selection')
        self.assertEqual(result['tool_call']['call'], 'Node.fill')
        self.assertIs(result['tool_call']['returned'], True)
        self.assertIn('(1, 1)', result['tool_call']['did']); self.assertIn('#3a6ea5', result['tool_call']['did'])
        self.assertEqual(self.alpha(node), [255] * 16)
        entry = self.h._creative_session['passes'][0]
        self.assertEqual((entry['kind'], entry['layer_id'], entry['title']), ('bucket_fill', result['layer_id'], 'Wall'))

    def test_the_options_reach_krita_as_given_and_a_sample_the_painter_chose_stays(self):
        result = self.bucket(options={'mode': 'similar', 'sample': 'layer', 'threshold': 20, 'grow': 2, 'opacity': 0.5, 'compositeOp': 'multiply'})
        self.assertEqual(result['status'], 'ok', result.get('error'))
        options = self.calls[0][4]
        self.assertEqual({k: v for k, v in options.items() if k != 'name'},
                         {'mode': 'similar', 'sample': 'layer', 'threshold': 20, 'grow': 2, 'opacity': 0.5, 'compositeOp': 'multiply'})
        self.assertEqual(options['name'], 'Bucket fill: Wall')

    def test_the_new_layer_takes_its_settings_like_fill_region(self):
        result = self.bucket(blend_mode='multiply', opacity=0.5)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        node = self.painted(result)
        self.assertEqual((node.blend, node.alpha), ('multiply', 128))

    def test_the_area_and_the_stage_region_limit_the_fill(self):
        result = self.bucket(area=LEFT, region=[0, 0, 4, 2])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        selection = self.calls[0][5]
        data = selection.pixelData(0, 0, 4, 4)
        inside = [i for i in range(16) if data[i]]
        self.assertTrue(inside and all(i % 4 < 2 and i // 4 < 2 for i in inside), 'left half and top half only: %s' % inside)
        self.assertEqual(data[0], 255, 'full strength inside both')
        fresh = self.alpha(ToolLayer(self.h.doc, 'fresh', 'paintlayer'))
        self.assertEqual(self.alpha(self.painted(result)), [255 if i in inside else fresh[i] for i in range(16)])

    def test_a_saved_selection_limits_the_fill(self):
        region_tests.run(self.h, 'select', {'name': 'Left', 'steps': LEFT}, None)
        result = self.bucket(selection='Left')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual([i for i in range(16) if self.calls[0][5].pixelData(0, 0, 4, 4)[i]], [0, 1, 4, 5, 8, 9, 12, 13])

    def test_the_artists_selection_layer_and_brush_are_left_alone(self):
        self.h.doc.selected = 'the artist\'s selection'; self.h.doc.active = self.background
        brushes = []
        self.h.cmd_set_brush = lambda params: brushes.append(params) or {'status': 'ok'}
        self.assertEqual(self.bucket()['status'], 'ok')
        self.assertEqual((self.h.doc.selected, self.h.doc.active, brushes), ('the artist\'s selection', self.background, []))
        self.assertEqual(self.h.doc.selection_changes, [], 'never swapped, not even and restored')

    def test_the_layer_and_the_fill_are_one_undo_step(self):
        self.assertEqual(self.bucket()['status'], 'ok')
        self.assertEqual([m[0] for m in self.moves], ['begin', 'end'])
        self.assertEqual(self.moves[0][1], 'Bucket fill: Wall')

    def test_a_refused_fill_is_a_rejected_pass_with_no_layer_left(self):
        self.answers['fill'] = False
        result = self.bucket()
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertIn('Krita refused', result['error']); self.assertIn('nothing was changed', result['error'])
        self.assertIs(result['tool_call']['returned'], False)
        self.assertEqual(self.layers('Wall'), [])
        self.assertNotIn('layer_id', result)
        self.assertEqual(self.h._creative_session['passes'], [])
        self.assertTrue(result['reconciled'])
        self.assertTrue(self.bucket().get('replayed'), 'the same operation is never run twice')
        self.assertEqual(len(self.calls), 1)

    def test_an_error_from_krita_removes_the_layer_and_rejects_the_pass(self):
        self.raises = TypeError('arguments did not match any overloaded call')
        result = self.bucket()
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertIn('arguments did not match', result['error'])
        self.assertEqual(self.layers('Wall'), [])
        self.assertEqual(self.h._creative_session['passes'], [])
        self.assertEqual([m[0] for m in self.moves], ['begin', 'end'], 'the move still ends')

    def test_the_artist_pressing_undo_during_the_call_is_waited_out_and_nothing_is_recorded(self):
        doc = self.h.doc; doc.idx, doc.redo = 5, 0
        doc.undoIndex = lambda: doc.idx
        doc.undoCount = lambda: doc.idx + doc.redo
        def undo(_name): doc.idx -= 1; doc.redo += 1
        self.on_call = undo
        result = self.bucket()
        self.assertEqual((result['status'], result['error_code']), ('partial', 'partial_change'))
        self.assertIn('pressed Undo', result['error'])
        self.assertTrue(result['contribution_removed'])
        self.assertEqual(self.layers('Wall'), [])
        self.assertEqual(self.h._creative_session['passes'], [])
        self.assertEqual([m[0] for m in self.moves], ['begin', 'end'])

    def test_protection_keeps_the_fill_out_of_a_kept_area(self):
        self.keep('Moon', (0, 0, 2, 2)); before = self.inside()
        result = self.bucket()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['protected'][0]['name'], 'Moon')
        self.assertEqual(self.inside(), before)

    def test_refusals_change_nothing_and_run_nothing(self):
        layers = len(self.h.doc.root.children)
        cases = (({'x': 4}, 'x'), ({'y': -1}, 'y'), ({'x': float('nan')}, 'x'), ({'x': 1.5}, 'x'), ({'color': 'red'}, 'Color'),
                 ({'color': '#12345'}, 'Color'), ({'options': {'threshold': 0}}, 'threshold'), ({'options': {'regions': 'all'}}, 'Unknown options'),
                 ({'options': {'name': 'x'}}, 'Unknown options'), ({'options': []}, 'options'), ({'area': LEFT, 'selection': 'X'}, 'at most one'),
                 ({'bogus': 1}, 'Unknown parameters'), ({'name': ''}, 'name'), ({'selection': 'Nowhere'}, 'Nowhere'),
                 ({'blend_mode': 'sparkle'}, 'blend mode'), ({'region': [0, 0, 9, 9]}, 'Region'), ({'region': [0, 0, 2]}, 'Region'),
                 ({'area': [{'shape': 'blob'}]}, 'shape'), ({'x': None}, 'x'), ({'clip_to': 'nope'}, 'no longer in this painting'))
        for extra, message in cases:
            with self.assertRaisesRegex(ValueError, message, msg=extra):
                self.bucket('bad-%s' % list(extra)[0] + str(len(self.calls)), **extra)
        with self.assertRaisesRegex(ValueError, 'Missing parameters: y'):
            self.op('bucket_fill', 'missing', name='Wall', x=1, color='#112233')
        self.assertEqual((len(self.h.doc.root.children), self.calls, self.h._creative_session['passes']), (layers, [], []))
        self.assertEqual(self.moves, [])
        self.assertEqual(self.h._creative_session['operations'], {}, 'nothing was journalled for a refused call')

    def test_without_the_fork_there_is_no_bucket_fill(self):
        del native.krita.Node
        self.addCleanup(setattr, native.krita, 'Node', ToolLayer)
        with self.assertRaisesRegex(ValueError, 'our Krita'):
            self.bucket()
        self.assertEqual(self.layers('Wall'), [])


class EncloseAndFillTests(ToolSetup, unittest.TestCase):
    def test_the_regions_inside_the_enclosing_area_are_filled_on_a_new_layer(self):
        result = self.enclose(options={'regions': 'transparent', 'invert': False, 'includeContourRegions': True})
        self.assertEqual(result['status'], 'ok', result.get('error'))
        name, area, colour, options, selection, node = self.calls[0]
        self.assertEqual((name, str(colour)), ('encloseAndFill', '#ffd27f'))
        self.assertEqual([i for i in range(16) if area.pixelData(0, 0, 4, 4)[i]], [0, 1, 4, 5, 8, 9, 12, 13], 'the enclosing steps, built')
        self.assertEqual({k: v for k, v in options.items() if k != 'name'}, {'regions': 'transparent', 'invert': False, 'includeContourRegions': True, 'sample': 'all'})
        self.assertEqual(options['name'], 'Enclose and fill: Windows')
        self.assertEqual(selection.pixelData(0, 0, 4, 4), bytes([255]) * 16)
        self.assertEqual(result['tool_call']['call'], 'Node.encloseAndFill')
        self.assertIn('#ffd27f', result['tool_call']['did'])
        self.assertEqual(self.h._creative_session['passes'][0]['kind'], 'enclose_and_fill')
        self.assertEqual([m[0] for m in self.moves], ['begin', 'end'])

    def test_a_saved_selection_can_be_the_enclosing_area_and_another_limits_the_call(self):
        region_tests.run(self.h, 'select', {'name': 'Ring', 'steps': DISC}, None)
        result = self.op('enclose_and_fill', 'saved', name='Windows', enclose_selection='Ring', color='#ffd27f', area=LEFT)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual([i for i in range(16) if self.calls[0][4].pixelData(0, 0, 4, 4)[i]], [0, 1, 4, 5, 8, 9, 12, 13])

    def test_an_empty_enclosing_area_is_rejected_before_any_layer(self):
        self.h._region_bounds = lambda doc, selection: None
        layers = len(self.h.doc.root.children)
        result = self.enclose()
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertEqual((len(self.h.doc.root.children), self.calls), (layers, []))

    def test_a_refused_call_removes_its_layer(self):
        self.answers['encloseAndFill'] = False
        result = self.enclose()
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertEqual(self.layers('Windows'), []); self.assertEqual(self.h._creative_session['passes'], [])
        self.assertIn('Node.encloseAndFill', result['error'])

    def test_refusals(self):
        cases = (({'enclose_area': None}, 'enclosing area'), ({'enclose_selection': 'Nope'}, 'enclose_selection|Nope|Give the enclosing'),
                 ({'color': 'blue'}, 'Color'), ({'options': {'regions': 'color'}}, 'regionColor'), ({'options': {'regions': 'some'}}, 'regions'),
                 ({'options': {'mode': 'similar'}}, 'Unknown options'), ({'options': {'grow': 401}}, 'grow'), ({'start': [0, 0]}, 'Unknown parameters'))
        for extra, message in cases:
            params = dict({'name': 'Windows', 'enclose_area': LEFT, 'color': '#ffd27f'}, **extra)
            params = {k: v for k, v in params.items() if v is not None}
            if 'enclose_selection' in extra: params.pop('enclose_area')
            with self.assertRaisesRegex(ValueError, message, msg=extra):
                self.op('enclose_and_fill', 'bad%d' % len(self.calls) + str(sorted(extra)), **params)
        with self.assertRaisesRegex(ValueError, 'enclosing area'):
            self.op('enclose_and_fill', 'both', name='W', color='#112233', enclose_area=LEFT, enclose_selection='X')
        self.assertEqual((self.calls, self.moves, self.h._creative_session['passes']), ([], [], []))


class GradientTests(ToolSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        stock = getattr(native.qt, 'QPointF', None)
        native.qt.QPointF = lambda x, y: ('point', x, y)
        self.addCleanup(lambda: setattr(native.qt, 'QPointF', stock) if stock else delattr(native.qt, 'QPointF'))

    def test_a_gradient_is_one_node_gradient_call_between_two_points_on_a_new_layer(self):
        result = self.gradient(options={'colors': ['#112244', '#ffaa66', '#ffffff'], 'shape': 'radial', 'repeat': 'alternate', 'dither': 'bayer4', 'opacity': 0.8})
        self.assertEqual(result['status'], 'ok', result.get('error'))
        name, start, end, options, selection, node = self.calls[0]
        self.assertEqual((name, start, end), ('gradient', ('point', 0.0, 0.0), ('point', 0.0, 4.0)))
        self.assertEqual({k: v for k, v in options.items() if k != 'name'},
                         {'colors': ['#112244', '#ffaa66', '#ffffff'], 'shape': 'radial', 'repeat': 'alternate', 'dither': 'bayer4', 'opacity': 0.8})
        self.assertEqual(selection.pixelData(0, 0, 4, 4), bytes([255]) * 16, 'no area: the whole layer')
        self.assertIs(node, self.painted(result))
        self.assertEqual(result['tool_call']['call'], 'Node.gradient')
        self.assertIn('radial', result['tool_call']['did']); self.assertIn('3 colours', result['tool_call']['did'])
        self.assertEqual(self.h._creative_session['passes'][0]['kind'], 'krita_gradient')

    def test_a_named_gradient_must_be_installed(self):
        self.assertEqual(self.gradient(options={'gradient': 'Sunset', 'colors': ['#000000', '#ffffff']})['status'], 'ok')
        with self.assertRaisesRegex(ValueError, 'Unknown gradient "Dawn"'):
            self.gradient('b', options={'gradient': 'Dawn'})

    def test_the_stage_region_limits_a_gradient(self):
        result = self.gradient(region=[0, 0, 4, 2])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        data = self.calls[0][4].pixelData(0, 0, 4, 4)
        self.assertTrue(all(data[i] == 0 for i in range(8, 16)) and data[0] > 0)

    def test_points_may_leave_the_canvas_by_a_canvas_length_and_no_more(self):
        self.assertEqual(self.gradient('far', start=[-4, -4], end=[8, 8])['status'], 'ok')
        for extra, message in (({'start': [-5, 0]}, 'start x'), ({'end': [0, 9]}, 'end y'), ({'start': [float('nan'), 0]}, 'start x'),
                               ({'end': [float('inf'), 0]}, 'end x'), ({'end': [0, 0]}, 'different'), ({'start': [1]}, 'start'),
                               ({'start': 'a'}, 'start'), ({'end': [True, 0]}, 'end x'), ({'start': [10 ** 12, 0]}, 'start x')):
            with self.assertRaisesRegex(ValueError, message, msg=extra):
                self.gradient('bad' + str(sorted(extra.items())), **extra)

    def test_options_are_required_and_checked(self):
        with self.assertRaisesRegex(ValueError, 'Missing parameters: options'):
            self.op('krita_gradient', 'x', name='Dusk', start=[0, 0], end=[0, 4])
        for options, message in (({}, 'colors or options.gradient'), ({'colors': ['#000000']}, 'colors'), ({'colors': ['#000000', '#ffffff'], 'shape': 'zig'}, 'shape'),
                                 ({'colors': ['#000000', '#ffffff'], 'name': 'x'}, 'Unknown options')):
            with self.assertRaisesRegex(ValueError, message):
                self.gradient('bad' + message, options=options)
        self.assertEqual((self.calls, self.moves), ([], []))

    def test_a_refused_gradient_leaves_no_layer(self):
        self.answers['gradient'] = False
        result = self.gradient()
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertEqual(self.layers('Dusk'), [])


class SmartPatchTests(ToolSetup, unittest.TestCase):
    def test_a_patch_repairs_the_area_on_a_new_layer_that_holds_the_repair_and_nothing_else(self):
        result = self.patch(options={'accuracy': 80, 'patchRadius': 6}, context=8)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        name, area, options, node = self.calls[0]
        self.assertEqual(name, 'smartPatch')
        self.assertEqual({k: v for k, v in options.items() if k != 'name'}, {'accuracy': 80, 'patchRadius': 6})
        self.assertEqual([i for i in range(16) if area.pixelData(0, 0, 4, 4)[i]], [0, 1, 4, 5, 8, 9, 12, 13])
        layer = self.painted(result)
        self.assertIs(node, layer)
        left = [i for i in range(16) if i % 4 < 2]
        self.assertTrue(all(bytes(layer.pixels[i * 4:i * 4 + 4]) == bytes([1, 2, 3, 255]) for i in left), 'the patched paint inside the area')
        self.assertTrue(all(bytes(layer.pixels[i * 4:i * 4 + 4]) == bytes(4) for i in range(16) if i % 4 >= 2),
                        'the copied context is cleared: nothing outside the area stays on the layer')
        self.assertEqual((result['patched_bounds'], result['patched_pixels']), ([0, 0, 2, 4], 8))
        self.assertEqual(result['tool_call']['call'], 'Node.smartPatch'); self.assertIs(result['tool_call']['returned'], True)
        self.assertIn('8 pixels', result['tool_call']['did'])
        self.assertEqual(self.h._creative_session['passes'][0]['kind'], 'smart_patch')

    def test_pixels_inside_the_areas_bounds_but_outside_the_selection_stay_clear(self):
        ring = [{'shape': 'rectangle', 'bounds': [0, 0, 4, 4]}, {'shape': 'rectangle', 'bounds': [1, 1, 2, 2], 'mode': 'subtract'}]
        result = self.patch(area=ring, context=8)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        layer = self.painted(result)
        hole = [5, 6, 9, 10]
        self.assertTrue(all(bytes(layer.pixels[i * 4:i * 4 + 4]) == bytes(4) for i in hole), 'the hole keeps none of the copied painting')
        self.assertTrue(all(bytes(layer.pixels[i * 4:i * 4 + 4]) == bytes([1, 2, 3, 255]) for i in range(16) if i not in hole))
        self.assertEqual(result['patched_pixels'], 12)

    def test_the_patch_layer_is_first_given_the_paint_around_the_area_to_search(self):
        written = []
        real = ToolLayer.setPixelData
        ToolLayer.setPixelData = lambda node, data, x, y, w, h: written.append((x, y, w, h, bytes(data[:4]))) or real(node, data, x, y, w, h)
        self.addCleanup(setattr, ToolLayer, 'setPixelData', real)
        self.assertEqual(self.patch(context=8)['status'], 'ok')
        self.assertEqual(written[0][:4], (0, 0, 4, 4), 'the area grown by the context, cut to the canvas: the painting around it')
        self.assertEqual(written[0][4], bytes([150, 90, 40, 255]), "the painting's pixels")
        self.assertEqual(written[1][:4], (0, 0, 4, 4), 'then the whole window cleared')
        self.assertEqual(written[2][:4], (0, 0, 2, 4), 'then the repair alone')

    def test_the_stage_region_cuts_the_area_to_patch(self):
        result = self.patch(region=[0, 0, 4, 2])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['patched_bounds'], [0, 0, 2, 2])
        self.assertEqual([i for i in range(16) if self.calls[0][1].pixelData(0, 0, 4, 4)[i]], [0, 1, 4, 5])

    def test_an_area_over_the_forks_cap_is_a_clear_error_with_numbers_and_nothing_is_made(self):
        original = validation.PATCH_AREA_LIMIT
        validation.PATCH_AREA_LIMIT = 7
        self.addCleanup(setattr, validation, 'PATCH_AREA_LIMIT', original)
        layers = len(self.h.doc.root.children)
        result = self.patch()
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertIn('2 x 4 pixels (8)', result['error']); self.assertIn('limit', result['error'])
        self.assertEqual((len(self.h.doc.root.children), self.calls, self.moves), (layers, [], []))

    def test_a_patch_of_an_agent_layer_edits_a_copy_and_hides_the_original(self):
        made = self.bucket('first')
        original = self.painted(made)
        result = self.patch(layer_id=made['layer_id'])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        copy = self.calls[-1][-1]
        self.assertIsNot(copy, original)
        self.assertEqual((result['source_layer_id'], result['layer_id']), (made['layer_id'], result['layer_id']))
        self.assertNotEqual(result['layer_id'], made['layer_id'])
        self.assertFalse(original.shown, 'rejecting the pass shows the original again')
        self.assertTrue(copy.shown)
        self.assertEqual(self.alpha(copy), [255] * 16, 'nothing cleared: the copy is the layer with the area patched')

    def test_a_refused_patch_of_an_agent_layer_leaves_the_original_visible_and_no_copy(self):
        made = self.bucket('first'); original = self.painted(made)
        self.answers['smartPatch'] = False
        layers = len(original.parent.children)
        result = self.patch(layer_id=made['layer_id'])
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertTrue(original.shown)
        self.assertEqual(len(original.parent.children), layers, 'the copy is gone again')
        self.assertNotIn('source_layer_id', result)

    def test_a_refused_patch_leaves_no_layer(self):
        self.answers['smartPatch'] = False
        result = self.patch()
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertEqual(self.layers('Seam repair'), [])
        self.assertIn('Node.smartPatch', result['error'])

    def test_the_artist_s_own_layer_cannot_be_patched_in_place(self):
        with self.assertRaisesRegex(ValueError, 'Only layers the agent created'):
            self.patch(layer_id=self.background.id)

    def test_refusals(self):
        cases = (({'area': None}, 'Give the area to patch'), ({'selection': 'Nope'}, 'Nope|Give the area'), ({'options': {'accuracy': 100}}, 'accuracy'),
                 ({'options': {'patchRadius': 1}}, 'patchRadius'), ({'options': {'opacity': 1}}, 'Unknown options'), ({'context': 4}, 'context'),
                 ({'context': 1000}, 'context'), ({'context': float('nan')}, 'context'), ({'layer_id': 'nope'}, 'no longer in this painting'),
                 ({'color': '#000000'}, 'Unknown parameters'), ({'blend_mode': 'multiply'}, 'Unknown parameters'))
        for extra, message in cases:
            params = {k: v for k, v in dict({'name': 'Seam repair', 'area': LEFT}, **extra).items() if v is not None}
            if extra.get('selection'): params.pop('area')
            with self.assertRaisesRegex(ValueError, message, msg=extra):
                self.op('smart_patch', 'bad' + str(sorted(extra)), **params)
        with self.assertRaisesRegex(ValueError, 'Give the area to patch'):
            self.op('smart_patch', 'both', name='x', area=LEFT, selection='X')
        self.assertEqual((self.calls, self.moves, self.h._creative_session['passes']), ([], [], []))

    def test_protection_keeps_the_patch_out_of_a_kept_area(self):
        self.keep('Moon', (0, 0, 2, 2)); before = self.inside()
        result = self.patch()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['protected'][0]['name'], 'Moon')
        self.assertEqual(self.inside(), before)


class HealthTests(ToolSetup, unittest.TestCase):
    def health(self):
        previous = native.module.Krita
        native.module.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(version=lambda: '5.3.3'))
        try:
            self.h._creative_adapter_capabilities = lambda: {}       # needs real Qt; not what this test is about
            self.h._native_actions = lambda version: []
            return self.h.cmd_creative({'operation': 'health', 'params': {}})
        finally:
            native.module.Krita = previous

    def test_health_says_whether_this_krita_has_the_tool_functions(self):
        self.assertIs(self.health()['fork_tools'], True)
        del native.krita.Node
        self.addCleanup(setattr, native.krita, 'Node', ToolLayer)
        self.assertIs(self.health()['fork_tools'], False, 'stock Krita: the companion then does not offer the four tools')


class FixRoundTests(ToolSetup, unittest.TestCase):
    """The review's fixes: clip groups, a call that changed nothing, kept-out features, a cleanup that fails, a closed document."""
    def setUp(self):
        super().setUp()
        stock = getattr(native.qt, 'QPointF', None)
        native.qt.QPointF = lambda x, y: ('point', x, y)
        self.addCleanup(lambda: setattr(native.qt, 'QPointF', stock) if stock else delattr(native.qt, 'QPointF'))

    def groups(self):
        found = []
        def visit(node):
            for child in node.children:
                found.append(child) if child.kind == 'grouplayer' and child.label.startswith('Creative Agent') and child.label != 'Creative Agent · s' else None    # not the stage group
                visit(child)
        visit(self.h.doc.root)
        return found

    CLIP_CASES = (('bucket_fill', 'fill', {}), ('enclose_and_fill', 'encloseAndFill', {}), ('krita_gradient', 'gradient', {}))

    def run_op(self, operation, identifier, **extra):
        return {'bucket_fill': self.bucket, 'enclose_and_fill': self.enclose, 'krita_gradient': self.gradient, 'smart_patch': self.patch}[operation](identifier, **extra)

    def test_a_failed_call_with_clip_base_leaves_no_empty_group(self):
        doc = self.h.doc; doc.idx, doc.redo = 5, 0
        doc.undoIndex = lambda: doc.idx
        doc.undoCount = lambda: doc.idx + doc.redo
        for operation, method, _ in self.CLIP_CASES:
            for scenario in ('refused', 'raises', 'undo'):
                self.answers, self.raises, self.on_call = {}, None, None
                if scenario == 'refused': self.answers[method] = False
                elif scenario == 'raises': self.raises = TypeError('boom')
                else: self.on_call = lambda _n: (setattr(doc, 'idx', doc.idx - 1), setattr(doc, 'redo', doc.redo + 1))
                doc.idx, doc.redo = 5, 0
                label = '%s %s' % (operation, scenario)
                try:
                    self.run_op(operation, label, clip_base=True)
                except Exception:
                    pass
                self.assertEqual(self.groups(), [], label)
                self.assertEqual(self.h._creative_session.get('clip_groups', set()), set(), label)
                self.assertEqual([n for n in self.h._creative_session['layers']], [], label)

    def test_a_call_that_changed_nothing_is_a_rejected_pass_with_no_layer(self):
        for operation, method, _ in self.CLIP_CASES + (('smart_patch', 'smartPatch', {}),):
            self.answers = {method: 'noop'}
            result = self.run_op(operation, 'noop-' + operation)
            self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'), operation)
            self.assertIn('changed nothing', result['error'], operation)
            self.assertIs(result['tool_call']['returned'], True)
            self.assertNotIn('layer_id', result)
        self.assertEqual((self.layers('Wall'), self.layers('Windows'), self.layers('Dusk'), self.layers('Seam repair')), ([], [], [], []))
        self.assertEqual(self.h._creative_session['passes'], [])

    def test_the_rejection_names_the_protected_features_krita_kept_the_call_out_of(self):
        self.h.doc.lastKeptOut = lambda: ['Moon', 'Figure']
        self.answers = {'fill': 'noop'}
        result = self.bucket()
        self.assertIn('Moon', result['error']); self.assertIn('Figure', result['error'])
        self.assertEqual(result['kept_out'], ['Moon', 'Figure'])

    def test_a_painted_call_reports_what_krita_kept_it_out_of(self):
        self.h.doc.lastKeptOut = lambda: ['Moon']
        self.assertEqual(self.bucket()['kept_out'], ['Moon'])
        result = self.patch('p')
        self.assertEqual(result['kept_out'], ['Moon'])
        self.assertIn('hole', result['kept_out_note'])           # the copied context has the feature as a hole to search around

    def test_without_last_kept_out_nothing_is_reported(self):
        self.assertNotIn('kept_out', self.bucket())

    def test_a_cleanup_that_fails_removes_the_layer_and_rejects_the_pass(self):
        real = ToolLayer.setPixelData
        count = []
        def failing(node, data, x, y, w, h):
            count.append(1)
            return False if len(count) == 3 else real(node, data, x, y, w, h)       # the window, the clearing, then the repair
        ToolLayer.setPixelData = failing
        self.addCleanup(setattr, ToolLayer, 'setPixelData', real)
        result = self.patch(context=8)
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertIn('patched pixels', result['error'])
        self.assertEqual(self.layers('Seam repair'), [])
        self.assertEqual(self.h._creative_session['passes'], [])

    def test_a_document_closed_during_the_call_is_named_as_such(self):
        doc = self.h.doc
        doc.undoIndex = lambda: 5
        doc.undoCount = lambda: 5
        closed = RuntimeError('wrapped C/C++ object of type Document has been deleted')
        def close(_name):
            doc.undoIndex = doc.undoCount = doc.width = lambda *a: (_ for _ in ()).throw(closed)
        self.on_call = close
        result = self.bucket()
        self.assertEqual((result['status'], result['error_code']), ('partial', 'partial_change'))
        self.assertIn('document was closed', result['error'])


if __name__ == '__main__':
    unittest.main()

"""make_material and stamp, the native operations (material_stamp.py), on the 4x4 fake painting of the protection
tests with the real material_raster. Materials go to a temporary study folder that is removed."""
import base64
import json
import os
import sys
import unittest
import test_protection as protection_tests
import test_material_raster as raster_tests

region_tests = protection_tests.region_tests
native = protection_tests.native
qt = raster_tests.qt_compat
DISC = [{'shape': 'rectangle', 'bounds': [0, 0, 4, 4]}]


def disc_png(size=64):
    """A white disc on transparency, as an asset cut-out would be."""
    image = qt.QImage(size, size, qt.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(qt.Qt.GlobalColor.transparent)
    painter = qt.QPainter(image)
    painter.setBrush(qt.QColor(255, 255, 255)); painter.setPen(qt.QColor(255, 255, 255))
    painter.drawEllipse(4, 4, size - 8, size - 8); painter.end()
    buffer = qt.QtCore.QBuffer(); buffer.open(qt.QtCore.QIODevice.OpenModeFlag.WriteOnly); image.save(buffer, 'PNG')
    return base64.b64encode(bytes(buffer.data())).decode()


class MaterialSetup(protection_tests.ProtectionSetup):
    def setUp(self):
        super().setUp()
        name = 'creative_test_package.material_raster'
        prior = sys.modules.get(name)
        sys.modules[name] = raster_tests.raster; native.package.material_raster = raster_tests.raster
        self.addCleanup(lambda: sys.modules.__setitem__(name, prior) if prior else sys.modules.pop(name, None))
        self.background = self.artist_layer('Sky')
        self.background.pixels = bytearray(bytes([150, 90, 40, 255]) * 16)    # opaque blue sky, BGRA

    def make(self, **extra):
        params = dict({'name': 'Disc', 'kind': 'shape', 'size': 64, 'source': {'image_base64': disc_png()}}, **extra)
        return region_tests.run(self.h, 'make_material', params)

    def dab(self, **extra):
        return dict({'x': 1.5, 'y': 1.5, 'scale': 0.08, 'stretch': 1, 'rotation': 0, 'opacity': 1, 'tip': 0}, **extra)

    def stamp(self, identifier='stamp', **extra):
        params = dict({'name': 'Clouds', 'material': 'Disc', 'area': DISC, 'dabs': [self.dab()], 'stage_id': 's'}, **extra)
        return region_tests.run(self.h, 'stamp', params, identifier)

    def stamped(self, result):
        return self.h._creative_node(self.h.doc, result['layer_id'])


class MakeMaterialTests(MaterialSetup, unittest.TestCase):
    def test_a_material_is_saved_with_the_chat_and_changes_nothing_on_the_canvas(self):
        before = (self.h.doc.pixelData(0, 0, 4, 4), len(self.h.doc.root.children))
        result = self.make()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual((result['material'], result['kind'], result['tips'], result['size']), ('Disc', 'shape', 1, 64))
        folder = os.path.dirname(result['sheet_path'])
        self.assertTrue(os.path.isfile(result['sheet_path']))
        self.assertEqual(json.load(open(os.path.join(folder, 'material.json')))['tips'], 1)
        self.assertNotIn('image_path', result, 'the sheet is not the canvas view')
        self.assertEqual((self.h.doc.pixelData(0, 0, 4, 4), len(self.h.doc.root.children)), before)
        self.assertEqual(self.h._creative_session['passes'], [], 'not a pass')

    def test_light_tips_from_the_painting_avoid_protected_areas(self):
        self.keep('Moon', (2, 0, 2, 2))
        seen = {}
        real = raster_tests.raster.light_tips
        def spy(*args, **kw):
            seen.update(kw); return real(*args, **kw)
        raster_tests.raster.light_tips = spy
        self.addCleanup(setattr, raster_tests.raster, 'light_tips', real)
        self.background.pixels[0:4] = bytes([255, 255, 255, 255])                       # one bright pixel of light
        try:
            self.make(name='Sky light', kind='light', source={'area': DISC})
        except ValueError as refused:                                                   # 4x4 may hold too little light
            self.assertIn('No light', str(refused))
        self.assertEqual(seen['avoid'], [(2, 0, 2, 2)], 'the protected Moon, in source coordinates')

    def test_any_readable_name_up_to_40_characters(self):
        # Run 7: the painter named it "Cloud tips — cut from the painting" and the ASCII-only rule refused it.
        self.assertEqual(self.make(name='Cloud tips — cut from the painting')['material'], 'Cloud tips — cut from the painting')
        for bad in ('', 'x' * 41, 'tab\there'):
            with self.assertRaisesRegex(ValueError, 'name'):
                self.make(name=bad)

    def test_refusals(self):
        for params, message in (({'kind': 'glitter'}, 'kind'), ({'count': 9}, 'count'), ({'size': 8}, 'size'),
                                ({'source': {}}, 'source'), ({'name': ' '}, 'name')):
            with self.assertRaisesRegex(ValueError, message):
                self.make(**params)
        with self.assertRaisesRegex(ValueError, 'No light'):
            self.make(name='Flat', kind='light', source={'area': DISC})                  # a flat sky has no light to cut


class StampTests(MaterialSetup, unittest.TestCase):
    def setUp(self):
        super().setUp(); self.make()

    def test_a_stamp_is_one_pass_on_one_new_layer_inside_its_area(self):
        result = self.stamp(area=[{'shape': 'rectangle', 'bounds': [0, 0, 2, 4]}], dabs=[self.dab(x=1, y=2, scale=0.1)])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['dabs_placed'], 1)
        layer, fresh = self.stamped(result), region_tests.Layer(self.h.doc, 'fresh', 'paintlayer').pixels
        outside = lambda pixels: [bytes(pixels[(y * 4 + x) * 4:(y * 4 + x) * 4 + 4]) for y in range(4) for x in range(2, 4)]
        self.assertTrue(any(layer.pixels[(y * 4 + x) * 4 + 3] for y in range(4) for x in range(2)))
        self.assertEqual(outside(layer.pixels), outside(fresh), 'nothing written outside the area')
        self.assertEqual([p['layer_id'] for p in self.h._creative_session['passes']], [result['layer_id']])

    def test_a_heavy_stamp_is_thinned_to_the_coverage_cap_and_says_so(self):
        # 1400 dabs at 0.22-0.42 laid a pale veil over the whole sky (Luna: texture over forms, flat block).
        heavy = self.stamp(dabs=[self.dab(x=x + 0.5, y=y + 0.5) for x in range(4) for y in range(4)])
        self.assertEqual(heavy['status'], 'ok', heavy.get('error'))
        self.assertLess(heavy['opacity_scaled'], 1)
        self.assertAlmostEqual(heavy['coverage'], native.package.material_stamp.MAX_COVERAGE, places=2)
        light = self.stamp('light', dabs=[self.dab(opacity=0.01, scale=0.02)])
        self.assertNotIn('opacity_scaled', light)
        self.assertLess(light['coverage'], native.package.material_stamp.MAX_COVERAGE)

    def test_dabs_that_all_miss_the_area_make_no_layer(self):
        layers = len(self.h.doc.root.children)
        result = self.stamp(area=[{'shape': 'rectangle', 'bounds': [0, 0, 1, 1]}], dabs=[self.dab(x=3.5, y=3.5)])
        self.assertEqual(result['error_code'], 'validation_rejected')
        self.assertEqual(len(self.h.doc.root.children), layers)

    def test_protection_erases_the_stamp_inside_a_kept_area(self):
        self.keep('Moon', (0, 0, 2, 2)); before = self.inside()
        result = self.stamp(dabs=[self.dab(x=x + 0.5, y=y + 0.5) for x in range(4) for y in range(4)])
        self.assertEqual(result['protected'][0]['name'], 'Moon')
        self.assertEqual(self.inside(), before)

    def test_refusals(self):
        for extra, message in (({'material': 'Nope'}, 'No material'), ({'dabs': []}, 'dabs'),
                               ({'dabs': [self.dab()] * 2001}, '2000'), ({'dabs': [self.dab(tip=3)]}, 'tip'),
                               ({'dabs': [self.dab(opacity=2)]}, 'opacity'), ({'tint': {'color': '#ffffff', 'amount': 2}}, 'amount'),
                               ({'area': None}, 'area')):
            params = dict({'name': 'Clouds', 'material': 'Disc', 'area': DISC, 'dabs': [self.dab()], 'stage_id': 's'}, **extra)
            if params['area'] is None: params.pop('area')
            with self.assertRaisesRegex(ValueError, message):
                region_tests.run(self.h, 'stamp', params, 'bad-' + message)
        self.assertEqual(self.h._creative_session['passes'], [])


# ----- the Krita-brush stamp (krita-fork 5.1) ------------------------------------------------------------------------------
stamp_module = sys.modules['creative_test_package.material_stamp']


class FakeResource:
    def __init__(self, kind, name, image=None, application=None, base=None, tip=None):
        self.kind, self.label, self.image, self.application, self.base, self.tip = kind, name, image, application, base, tip
    def name(self): return self.label
    def type(self): return self.kind


class StampKrita:
    """Application.createBrushTip / createPreset as the fork documents them: a name that is another resource's gets
    "name (2)"; resources(kind) lists what exists."""
    def __init__(self, artist=(), refuse_tip=False, refuse_preset=False):
        self.tips, self.presets = {}, {'b) Basic-1': FakeResource('preset', 'b) Basic-1'),
                                       'b) Basic-3 Flow': FakeResource('preset', 'b) Basic-3 Flow'),
                                       'c) Pencil': FakeResource('preset', 'c) Pencil')}
        self.artist, self.refuse_tip, self.refuse_preset, self.calls = set(artist), refuse_tip, refuse_preset, []
        self.settings = {}
    def readSetting(self, group, key, default=''): return self.settings.get((group, key), default)
    def writeSetting(self, group, key, value): self.settings[(group, key)] = value
    def _free(self, name, own):
        if name in self.artist or (name in own and not own[name].agent):
            number = 2
            while '%s (%d)' % (name, number) in self.artist or '%s (%d)' % (name, number) in own: number += 1
            return '%s (%d)' % (name, number)
        return name
    def createBrushTip(self, image, name, application='alpha'):
        self.calls.append(('tip', name, image.width(), application))
        if self.refuse_tip: return None
        tip = FakeResource('brush', self._free(name, self.tips), image, application); tip.agent = True
        self.tips[tip.label] = tip; return tip
    def createPreset(self, base, tip, name):
        self.calls.append(('preset', name, base.name(), tip.name()))
        if self.refuse_preset: return None
        preset = FakeResource('preset', self._free(name, self.presets), base=base, tip=tip); preset.agent = True
        self.presets[preset.label] = preset; return preset
    def resources(self, kind): return dict(self.presets if kind == 'preset' else self.tips if kind == 'brush' else {})


class StampJob:
    """A finished StrokeJob. It paints what its strokes say onto the layer: each one-point stroke is one pixel in its
    colour and opacity, where the job's selection lets it."""
    def __init__(self, layer, strokes, selection, error=''):
        self.error, self.n = error, len(strokes)
        if not error:
            for stroke in strokes:
                x, y = int(stroke['points'][0][0]), int(stroke['points'][0][1])
                if selection is not None and not selection.pixelData(x, y, 1, 1)[0]: continue
                i = (y * 4 + x) * 4
                layer.pixels[i:i + 4] = bytes.fromhex(stroke['color'][5:7] + stroke['color'][3:5] + stroke['color'][1:3]) + bytes([round(stroke['opacity'] * 255)])
    def state(self): return 'failed' if self.error else 'done'
    def strokesDone(self): return 0 if self.error else self.n
    def strokesTotal(self): return self.n
    def changedRect(self): return types.SimpleNamespace(x=lambda: 0, y=lambda: 0, width=lambda: 4, height=lambda: 4)
    def errorString(self): return self.error
    def elapsedMs(self): return 3
    def wait(self, ms=-1): return True
    def cancel(self): return False


class StoppableJob(StampJob):
    """A job that is still running until it is cancelled (the artist's Stop), then ends cancelled."""
    def __init__(self, layer, strokes, selection):
        super().__init__(layer, strokes, selection); self.cancelled = False
    def state(self): return 'cancelled' if self.cancelled else 'running'
    def strokesDone(self): return 0
    def wait(self, ms=-1): return self.cancelled
    def cancel(self): self.cancelled = True; return True
    def cancelReason(self): return 'script'


class StampLayer(protection_tests.Layer):
    """A fork layer: Node.paintStrokes. `owner` holds the calls and decides which job (by call number) is refused."""
    owner = None
    def paintStrokes(self, strokes, options=None, selection=None):
        owner = self.owner
        owner.calls.append((strokes, options, selection, self))
        if owner.stoppable:
            return StoppableJob(self, strokes, selection)
        return StampJob(self, strokes, selection, owner.refuse.get(len(owner.calls), ''))


import types


class BrushStampSetup(MaterialSetup):
    def setUp(self):
        super().setUp()
        self.make()
        self.calls, self.refuse, self.stoppable = [], {}, False
        self.krita = StampKrita()
        self.use(self.krita)
        doc = self.h.doc
        owner = self
        doc.createNode = lambda name, kind: self._node(doc, name, kind)
        self.raster_calls = []
        real = raster_tests.raster.stamp
        raster_tests.raster.stamp = lambda *a, **k: self.raster_calls.append(1) or real(*a, **k)
        self.addCleanup(setattr, raster_tests.raster, 'stamp', real)
        previous = stamp_module.Selection
        stamp_module.Selection = region_tests.Mask
        self.addCleanup(setattr, stamp_module, 'Selection', previous)

    def _node(self, doc, name, kind):
        node = StampLayer(doc, name, kind); node.owner = self; return node

    def use(self, krita):
        prior = stamp_module.Krita
        stamp_module.Krita = types.SimpleNamespace(instance=lambda: krita)
        self.addCleanup(setattr, stamp_module, 'Krita', prior)
        self._krita_in_use = krita

    def group_layers(self):
        """How many 'Clouds' paint layers are in the painting, whatever group holds them."""
        found = []
        def visit(node):
            for child in node.children:
                found.append(child) if child.label == 'Clouds' and child.kind == 'paintlayer' else None
                visit(child)
        visit(self.h.doc.root)
        return len(found)


class StockBrushNoteTests(MaterialSetup, unittest.TestCase):
    def test_brush_means_nothing_on_stock_and_the_result_says_so(self):
        self.make()
        result = self.stamp(brush='b) Basic-1')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertIn('only in our Krita', result['brush_note'])
        self.assertNotIn('brush_note', self.stamp('plain'))


class KritaBrushStampTests(BrushStampSetup, unittest.TestCase):
    def test_the_dabs_are_one_paint_strokes_call_on_one_new_layer_by_the_krita_brush(self):
        result = self.stamp(dabs=[self.dab(x=1.5, y=1.5, opacity=0.4, scale=0.03), self.dab(x=2.5, y=0.5, opacity=0.3, scale=0.03)])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(self.raster_calls, [], 'no QPainter dabs on the fork')
        self.assertEqual(len(self.calls), 1, 'one variant: one job')
        strokes, options, selection, node = self.calls[0]
        self.assertIs(node, self.stamped(result))
        self.assertEqual(self.group_layers(), 1)
        self.assertEqual(len(strokes), 2)
        self.assertEqual([stroke['points'] for stroke in strokes], [[[1.5, 1.5]], [[2.5, 0.5]]])
        self.assertEqual([stroke['opacity'] for stroke in strokes], [0.4, 0.3])
        self.assertTrue(all(stroke['flow'] == 1 and stroke['color'].startswith('#') and len(stroke['color']) == 7 for stroke in strokes))
        self.assertAlmostEqual(strokes[0]['size'], 64 * 0.03, places=3, msg='the tip size times the dab scale')
        self.assertEqual(options['name'], 'Clouds')
        self.assertIn(options['preset'], self.krita.presets)
        self.assertEqual((result['engine'], result['dabs_placed'], result['material']), ('krita_brush', 2, 'Disc'))
        self.assertEqual(result['stroke_job']['strokes'], 2)
        self.assertEqual([p['layer_id'] for p in self.h._creative_session['passes']], [result['layer_id']])
        self.assertEqual(self.h._creative_session['passes'][0]['kind'], 'stamp')

    def test_the_tip_is_an_alpha_tip_and_the_preset_comes_from_a_base_preset(self):
        result = self.stamp()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        tip_call = next(c for c in self.krita.calls if c[0] == 'tip')
        preset_call = next(c for c in self.krita.calls if c[0] == 'preset')
        self.assertEqual((tip_call[2], tip_call[3]), (64, 'alpha'), 'the material tip at its own size, as a coverage tip')
        self.assertEqual(preset_call[2], 'b) Basic-1', 'the default base preset')
        self.assertEqual(preset_call[3], tip_call[1], 'the preset takes the tip just made')
        self.assertEqual(result['brush'], {'base': 'b) Basic-1', 'application': 'alpha', 'presets': 1, 'created': 1, 'reused': 0, 'variants': 'fine'})
        # The base can be chosen from the plugin's brush list.
        again = self.stamp('b', brush='b) Basic-3 Flow')
        self.assertEqual(again['brush']['base'], 'b) Basic-3 Flow')
        self.assertEqual([c for c in self.krita.calls if c[0] == 'preset'][-1][2], 'b) Basic-3 Flow')

    def test_resources_are_made_once_and_reused_by_the_next_stamp(self):
        first = self.stamp('a'); second = self.stamp('b')
        self.assertEqual((first['brush']['created'], first['brush']['reused']), (1, 0))
        self.assertEqual((second['brush']['created'], second['brush']['reused']), (0, 1))
        self.assertEqual(len([c for c in self.krita.calls if c[0] == 'tip']), 1)
        self.assertEqual(len([c for c in self.krita.calls if c[0] == 'preset']), 1)
        self.assertEqual(self.calls[0][1]['preset'], self.calls[1][1]['preset'])

    def test_a_remade_material_or_a_deleted_preset_replaces_the_agents_own_resource(self):
        self.stamp('a')
        name = [c for c in self.krita.calls if c[0] == 'tip'][0][1]
        self.make(kind='shape', source={'image_base64': disc_png(48)}, size=48)       # same name, other pixels
        self.stamp('b')
        tips = [c for c in self.krita.calls if c[0] == 'tip']
        self.assertEqual([c[1] for c in tips], [name, name], 'the same deterministic name: Krita replaces the agent tip')
        self.assertEqual(tips[1][2], 48)
        del self.krita.presets[next(n for n in self.krita.presets if n.startswith('Agent stamp'))]     # the artist deleted it
        third = self.stamp('c')
        self.assertEqual(third['brush']['created'], 1)

    def test_resource_names_are_deterministic_per_material(self):
        self.stamp('a')
        names = [c[1] for c in self.krita.calls if c[0] in ('tip', 'preset')]
        self.assertTrue(all(n.startswith('Agent stamp') and 'Disc' in n for n in names), names)

    def test_a_new_chat_reuses_what_an_earlier_one_made_and_lost_records_replace_rather_than_pile_up(self):
        first = self.stamp('a')
        names = [c[1] for c in self.krita.calls if c[0] in ('tip', 'preset')]
        self.krita.calls.clear()
        self.h._creative_session.pop('stamp_resources', None)             # the next chat: nothing remembered in the session
        second = self.stamp('b')
        self.assertEqual((second['brush']['created'], second['brush']['reused']), (0, 1))
        self.assertEqual(self.krita.calls, [], 'no new resource version for the same tip and base')
        self.krita.settings.clear()                                       # Krita's record is gone: the agent's own are replaced
        third = self.stamp('c')
        self.assertEqual(third['brush']['created'], 1)
        self.assertEqual([c[1] for c in self.krita.calls if c[0] in ('tip', 'preset')], names)
        self.assertEqual(len([n for n in self.krita.presets if n.startswith('Agent stamp')]), 1)

    def test_a_same_name_resource_of_the_artist_is_left_alone_and_the_renamed_preset_is_painted_with(self):
        self.stamp('probe')                                                     # learn the deterministic name
        agent = [c[1] for c in self.krita.calls if c[0] == 'preset'][0]
        self.krita.settings.clear()
        self.krita.artist.add(agent); self.krita.presets.pop(agent)
        self.krita.calls.clear(); self.calls.clear()
        result = self.stamp('b')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(self.calls[0][1]['preset'], agent + ' (2)', 'the job paints with the name Krita gave')
        self.assertEqual(result['brush']['renamed'], [agent + ' (2)'])
        self.krita.calls.clear(); self.calls.clear()
        again = self.stamp('c')
        self.assertEqual((again['brush']['created'], again['brush']['reused'], self.krita.calls), (0, 1, []), 'the renamed preset is the one reused')
        self.assertEqual(self.calls[0][1]['preset'], agent + ' (2)')

    def test_a_dabs_rotation_and_stretch_are_folded_into_tip_variants_one_job_each_in_one_undo_step(self):
        doc = self.h.doc; moves = []
        doc.beginAgentMove = lambda name: moves.append(('begin', name)) or setattr(doc, 'is_open', True) or True
        doc.endAgentMove = lambda: moves.append(('end',)) or setattr(doc, 'is_open', False) or True
        doc.agentMoveOpen = lambda: getattr(doc, 'is_open', False)
        doc.agentMoveId = lambda: 1
        dabs = [self.dab(x=0.5, y=0.5), self.dab(x=1.5, y=0.5, rotation=30, stretch=1.5), self.dab(x=2.5, y=0.5, rotation=31, stretch=1.4),
                self.dab(x=3.5, y=0.5, rotation=90, stretch=1.5)]
        result = self.stamp(dabs=dabs)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['brush']['presets'], 3, 'plain, 30 degrees wide, 90 degrees wide')
        self.assertEqual(len(self.calls), 3, 'one job per variant (a preset has one tip)')
        self.assertEqual(sorted(len(c[0]) for c in self.calls), [1, 1, 2])
        self.assertEqual(sorted(s[2] for s in [c for c in self.krita.calls if c[0] == 'tip']), [64, 91, 91], 'turned tips sit in a larger square')
        self.assertEqual([m[0] for m in moves], ['begin', 'end'], 'all the jobs are one undo step')
        self.assertIn('Clouds', moves[0][1])
        wide = next(c[0][0] for c in self.calls if len(c[0]) == 2)
        self.assertAlmostEqual(wide['size'], 91 * 0.08 * 1.5, places=2, msg='the long axis: size x scale x stretch, in the larger square')

    def test_too_many_variants_fall_back_to_plain_tips_and_say_so(self):
        original = stamp_module.MAX_VARIANTS
        stamp_module.MAX_VARIANTS = 1
        self.addCleanup(setattr, stamp_module, 'MAX_VARIANTS', original)
        result = self.stamp(dabs=[self.dab(x=0.5, y=0.5, rotation=60, stretch=2), self.dab(x=1.5, y=0.5, rotation=200, stretch=0.5)])
        self.assertEqual((result['status'], result['brush']['variants'], result['brush']['presets']), ('ok', 'plain', 1))
        self.assertIn('rotation', result['brush']['dropped'])

    def test_a_heavy_stamp_is_thinned_and_each_stroke_carries_the_thinned_opacity(self):
        heavy = self.stamp(dabs=[self.dab(x=x + 0.5, y=y + 0.5) for x in range(4) for y in range(4)])
        self.assertEqual(heavy['status'], 'ok', heavy.get('error'))
        self.assertLess(heavy['opacity_scaled'], 1)
        strokes = self.calls[0][0]
        self.assertAlmostEqual(strokes[0]['opacity'], max(0.01, heavy['opacity_scaled']), places=3)
        self.assertAlmostEqual(heavy['coverage'], stamp_module.MAX_COVERAGE, places=2)

    def test_the_job_is_clipped_by_the_area_with_a_faded_edge_and_by_the_stage_region(self):
        result = self.stamp(area=[{'shape': 'rectangle', 'bounds': [0, 0, 2, 4]}], dabs=[self.dab(x=1, y=2, scale=0.1)], region=[0, 0, 4, 2])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        selection = self.calls[0][2]
        clip = lambda x, y: selection.pixelData(x, y, 1, 1)[0]
        self.assertEqual((clip(3, 0), clip(0, 3)), (0, 0), 'nothing past the area, nothing past the stage region')
        self.assertGreater(clip(0, 0), 0)

    def test_dabs_that_all_miss_the_area_make_no_layer_and_no_resource(self):
        layers = len(self.h.doc.root.children)
        result = self.stamp(area=[{'shape': 'rectangle', 'bounds': [0, 0, 1, 1]}], dabs=[self.dab(x=3.5, y=3.5)])
        self.assertEqual(result['error_code'], 'validation_rejected')
        self.assertEqual((len(self.h.doc.root.children), self.krita.calls, self.calls), (layers, [], []))

    def test_a_refused_job_is_a_rejected_pass_with_no_layer_left(self):
        self.refuse = {1: 'The layer is locked.'}
        result = self.stamp()
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertIn('The layer is locked.', result['error'])
        self.assertNotIn('layer_id', result)
        self.assertEqual(self.h._creative_session['passes'], [])
        self.assertEqual(self.group_layers(), 0, 'the new layer was removed')

    def test_a_job_refused_after_others_painted_removes_the_whole_layer(self):
        self.refuse = {2: 'Krita refused it.'}
        result = self.stamp(dabs=[self.dab(x=0.5, y=0.5), self.dab(x=1.5, y=0.5, rotation=90, stretch=2)])
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertEqual(self.group_layers(), 0)
        self.assertEqual(self.h._creative_session['passes'], [])

    def test_krita_refusing_the_tip_or_the_preset_is_a_rejected_pass_before_any_layer(self):
        for kwargs in ({'refuse_tip': True}, {'refuse_preset': True}):
            krita = StampKrita(**kwargs); self.use(krita)
            result = self.stamp('r%d' % len(kwargs) + str(sorted(kwargs)))
            self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'), kwargs)
            self.assertIn('brush', result['error'].lower())
            self.assertEqual(self.group_layers(), 0)

    def test_protection_erases_the_stamp_inside_a_kept_area(self):
        self.keep('Moon', (0, 0, 2, 2)); before = self.inside()
        result = self.stamp(dabs=[self.dab(x=x + 0.5, y=y + 0.5) for x in range(4) for y in range(4)])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['protected'][0]['name'], 'Moon')
        self.assertEqual(self.inside(), before)

    def test_the_base_preset_must_exist(self):
        with self.assertRaisesRegex(ValueError, 'brush'):
            self.stamp('x', brush='No such preset')
        self.krita.presets.clear()
        with self.assertRaisesRegex(ValueError, 'brush'):
            self.stamp('y')

    def test_stop_ends_the_pass_after_the_running_job_and_no_further_job_starts(self):
        creative = native.module
        self.stoppable = True
        creative.stop_requested.clear()
        self.addCleanup(creative.stop_requested.clear)
        real = StampLayer.paintStrokes
        StampLayer.paintStrokes = lambda node, *a, **k: creative.stop_requested.set() or real(node, *a, **k)
        self.addCleanup(setattr, StampLayer, 'paintStrokes', real)
        result = self.stamp(dabs=[self.dab(x=0.5, y=0.5), self.dab(x=1.5, y=0.5, rotation=90, stretch=2)])
        self.assertEqual(len(self.calls), 1, 'the second variant never starts')
        self.assertEqual(result['status'], 'ok', 'a definite, shorter pass')
        self.assertEqual((result['stopped'], result['stopped_after_strokes'], result['strokes_total']), ('Stopped by the artist.', 0, 2))
        self.assertEqual(self.group_layers(), 1, 'the layer stays: it is the pass, recorded as shorter')

    def test_an_eraser_or_destructive_base_brush_is_refused(self):
        self.krita.presets['a) Eraser Soft'] = FakeResource('preset', 'a) Eraser Soft')
        self.krita.presets['x) Dark'] = FakeResource('preset', 'x) Dark'); self.krita.presets['x) Dark'].xml = '<Preset><param name="CompositeOp" type="string">multiply</param></Preset>'
        self.krita.presets['x) Fine'] = FakeResource('preset', 'x) Fine'); self.krita.presets['x) Fine'].xml = '<Preset><param name="CompositeOp" type="string">normal</param></Preset>'
        stock = getattr(native.krita, 'Preset', None)
        native.krita.Preset = lambda resource: types.SimpleNamespace(toXML=lambda: getattr(resource, 'xml', ''))
        self.addCleanup(lambda: setattr(native.krita, 'Preset', stock) if stock else delattr(native.krita, 'Preset'))
        for brush in ('a) Eraser Soft', 'x) Dark'):
            with self.assertRaisesRegex(ValueError, 'paints normally'):
                self.stamp(brush, brush=brush)
        self.assertEqual(self.stamp('ok', brush='x) Fine')['status'], 'ok')
        self.assertEqual(self.krita.calls and [c for c in self.krita.calls if c[0] == 'preset'][-1][2], 'x) Fine')

    def test_the_artists_view_state_is_not_touched(self):
        self.h.doc.active = self.background
        brushes = []
        self.h.cmd_set_brush = lambda params: brushes.append(params) or {'status': 'ok'}
        self.stamp()
        self.assertEqual(brushes, [], 'the job takes its preset by name')
        self.assertIs(self.h.doc.active, self.background)


if __name__ == '__main__':
    unittest.main()

"""Capability manifest and native layer craft, on a fake layer tree. Writes no files."""
import json
import types
import unittest
import test_native as native

import sys
# The same modules creative_tools imported, so the harness and the code share one manifest cache.
capabilities = sys.modules['creative_test_package.capabilities']
craft = sys.modules['creative_test_package.layer_craft']


class Node:
    counter = 0
    def __init__(self, doc, name, kind):
        Node.counter += 1
        self.doc, self.label, self.kind, self.id = doc, name, kind, 'node-%d' % Node.counter
        self.children, self.parent = [], None
        self.alpha, self.shown, self.is_locked = 255, True, False
        self.blend, self.alpha_locked, self.inherit = 'normal', False, False
        self.pixels = bytes([10, 20, 30, 255, 10, 20, 30, 0]) * 8   # 4x4 BGRA, alternating opaque
        self.selection = None
        self.config = None
    def uniqueId(self): return self
    def toString(self): return self.id
    def name(self): return self.label
    def setName(self, value): self.label = value
    def type(self): return self.kind
    def childNodes(self): return list(self.children)
    def parentNode(self): return self.parent
    def addChildNode(self, node, above):
        # As in Krita: directly above `above`, or at the top when it is None.
        index = self.children.index(above) + 1 if above in self.children else len(self.children)
        self.children.insert(index, node); node.parent = self; return True
    def pixelData(self, x, y, w, h): return self.pixels
    def projectionPixelData(self, x, y, w, h): return self.pixels[y * 16:(y + h) * 16]
    def opacity(self): return self.alpha
    def setOpacity(self, value): self.alpha = value
    def visible(self): return self.shown
    def setVisible(self, value): self.shown = value
    def locked(self): return self.is_locked
    def blendingMode(self): return self.blend
    def setBlendingMode(self, value): self.blend = value
    def alphaLocked(self): return self.alpha_locked
    def setAlphaLocked(self, value): self.alpha_locked = value
    def inheritAlpha(self): return self.inherit
    def setInheritAlpha(self, value): self.inherit = value
    def setSelection(self, value): self.selection = value
    def filterConfig(self): return self.config
    def layerStyleToAsl(self): return getattr(self, 'style', '')
    def setLayerStyleFromAsl(self, value): self.style = value; return True


class Area:
    def __init__(self): self.rect, self.rows = None, {}
    def select(self, x, y, w, h, value): self.rect = (x, y, w, h, value)
    def setPixelData(self, data, x, y, w, h): self.rows[y] = bytes(data)


class TreeDocument(native.Document):
    def __init__(self):
        super().__init__(); self.root = Node(self, 'root', 'grouplayer'); self.fills = []
    def rootNode(self): return self.root
    def width(self): return 4
    def height(self): return 4
    def colorModel(self): return 'RGBA'
    def colorDepth(self): return 'U8'
    def createNode(self, name, kind): return Node(self, name, kind)
    def createFillLayer(self, name, generator, config, selection):
        if generator not in ('color', 'gradient'): return None
        node = Node(self, name, 'filllayer'); node.config = config; self.fills.append((generator, selection)); return node
    def createTransparencyMask(self, name): return Node(self, name, 'transparencymask')
    def childNodes(self): return self.root.childNodes()


def fake_app(settings=None):
    settings = {} if settings is None else settings
    filters = {'colorbalance': {'cyan_red_midtones': 0, 'preserve_luminosity': True},
               'gaussian blur': {'horizRadius': 5, 'vertRadius': 5, 'lockAspect': True}}
    def configuration(name):
        info = native.InfoObject()
        for key, value in filters[name].items(): info.setProperty(key, value)
        return info
    return types.SimpleNamespace(
        version=lambda: '5.3.3', filters=lambda: list(filters),
        filter=lambda name: types.SimpleNamespace(configuration=lambda: configuration(name)),
        resources=lambda kind: {'preset': {'b) Basic-1': 1}, 'pattern': {'Paper': 1}, 'gradient': {'Sunset': 1}}[kind],
        readSetting=lambda group, key, default: settings.get((group, key), default),
        writeSetting=lambda group, key, value: settings.__setitem__((group, key), value))


class Harness(native.Harness):
    def __init__(self):
        super().__init__(); self.doc = TreeDocument()
        self._creative_session.update(document_id=native.module.document_id(self.doc), width=4, height=4, passes=[])
        self.app = fake_app()
        self._craft_manifest_cache = capabilities.manifest(self.app, self.doc)
    def _creative_progress(self, *args): pass
    def _craft_lower(self, doc, node):
        """Krita's Move Layer Down, on the fake tree."""
        siblings = node.parent.children; index = siblings.index(node)
        if index: siblings[index - 1], siblings[index] = siblings[index], siblings[index - 1]


def run(h, operation, params, identifier):
    return h.cmd_creative({'operation': operation, 'session_id': 'session', 'operation_id': identifier, 'params': params})


class ManifestTests(unittest.TestCase):
    def test_manifest_reads_krita_and_caches_per_version(self):
        settings = {}; app = fake_app(settings); doc = TreeDocument()
        full = capabilities.manifest(app, doc)
        self.assertEqual(full['filters']['gaussian blur']['horizRadius'], {'type': 'int', 'default': 5})
        self.assertEqual(sorted(full['generators']), ['color', 'gradient'], 'only generators Krita creates')
        self.assertEqual(full['presets'], ['b) Basic-1'])
        self.assertTrue(settings, 'a complete manifest is cached')
        app.filters = lambda: []                       # a cached manifest is not re-read
        self.assertIn('colorbalance', capabilities.manifest(app, doc)['filters'])
        self.assertNotIn('colorbalance', capabilities.manifest(app, doc, refresh=True)['filters'])

    def test_without_a_document_generators_are_missing_and_nothing_is_cached(self):
        settings = {}
        self.assertEqual(capabilities.manifest(fake_app(settings), None)['generators'], {})
        self.assertEqual(settings, {})

    def test_compact_manifest_is_small_and_names_common_filters(self):
        compact = capabilities.compact(capabilities.manifest(fake_app(), TreeDocument()))
        self.assertEqual(compact['common_filters']['colorbalance']['preserve_luminosity'], True)
        self.assertIn('multiply', compact['blend_modes']['darken'])
        self.assertLess(len(json.dumps(compact)), 4000)

    def test_validation_refuses_unknown_names_keys_and_types(self):
        full = capabilities.manifest(fake_app(), TreeDocument())
        capabilities.validate_filter('gaussian blur', {'horizRadius': 3.0}, full)          # integral float is an int
        capabilities.validate_filter('colorbalance', {'cyan_red_midtones': 12}, full)
        for name, config, message in (('sharpen', {}, 'Unknown filter'),
                                      ('gaussian blur', {'radius': 3}, 'no setting'),
                                      ('gaussian blur', {'horizRadius': 'big'}, 'must be int'),
                                      ('gaussian blur', {'horizRadius': 2.5}, 'must be int'),
                                      ('colorbalance', {'preserve_luminosity': 1}, 'must be bool')):
            with self.assertRaisesRegex(ValueError, message): capabilities.validate_filter(name, config, full)
        with self.assertRaisesRegex(ValueError, 'Unknown blend mode'): capabilities.validate_blend_mode('darker')
        with self.assertRaisesRegex(ValueError, 'Unknown generator'): capabilities.validate_generator('noise', None, full)


class GeneratorAndSizeTests(unittest.TestCase):
    def test_generators_offer_their_known_settings_and_take_hex_colours(self):
        full = capabilities.manifest(fake_app(), TreeDocument(), refresh=True)
        self.assertEqual(full['generators']['color']['color'], {'type': 'color', 'default': '#000000'})
        capabilities.validate_generator('color', {'color': '#3a6ea5'}, full)
        for value in ('blue', '#3a6ea', 255, None):
            with self.assertRaisesRegex(ValueError, 'must be a colour'):
                capabilities.validate_generator('color', {'color': value}, full)

    def test_a_gradient_fill_takes_shape_positions_and_two_colours(self):
        full = {'generators': {'gradient': dict(capabilities.GENERATOR_SETTINGS['gradient'])}}
        config = {'shape': 'radial', 'start_position_x': 30, 'end_position_x': 70.5, 'start_color': '#3a6ea5', 'end_color': '#ffffff'}
        capabilities.validate_generator('gradient', config, full)
        for bad, message in (({'shape': 'star'}, 'must be one of: linear'), ({'repeat': 'twice'}, 'must be one of: none'),
                             ({'start_color': 'blue'}, 'must be a colour'), ({'start_position_x_units': 'inches'}, 'must be one of: pixels')):
            with self.assertRaisesRegex(ValueError, message):
                capabilities.validate_generator('gradient', bad, full)
        info = capabilities.info_object(full['generators']['gradient'], config).properties()
        self.assertNotIn('start_color', info, 'the colours become the gradient stops')
        self.assertEqual((info['shape'], info['start_position_x'], info['end_position_x'], info['repeat']), ('radial', 30, 70.5, 'none'))
        self.assertEqual(info['gradient'], '<gradient name="Creative Agent" type="stop">'
                         '<stop offset="0" bitdepth="U8" alpha="1" type="0"><RGB r="0.227451" g="0.431373" b="0.647059"/></stop>'
                         '<stop offset="1" bitdepth="U8" alpha="1" type="0"><RGB r="1.000000" g="1.000000" b="1.000000"/></stop></gradient>')
        self.assertIn('<RGB r="0.000000"', capabilities.info_object(full['generators']['gradient'], {}).properties()['gradient'], 'black to white by default')

    def test_settings_of_other_types_are_recorded_not_offered(self):
        class QColor:
            def name(self): return '#112233'
        app = fake_app()
        def configuration(name):
            info = native.InfoObject(); info.setProperty('radius', 3); info.setProperty('curve', object()); info.setProperty('tint', QColor())
            return info
        app.filters = lambda: ['custom']; app.filter = lambda name: types.SimpleNamespace(configuration=lambda: configuration(name))
        full = capabilities.collect(app, TreeDocument())
        self.assertEqual(full['filters']['custom'], {'radius': {'type': 'int', 'default': 3}, 'tint': {'type': 'color', 'default': '#112233'}})
        self.assertEqual(full['unsupported_settings'], {'filter:custom': {'curve': 'object'}})

    def test_compact_manifest_fits_a_full_krita(self):
        names = list(capabilities.COMMON_FILTERS) + ['filter number %d' % i for i in range(38)]
        full = {'krita_version': '5.3.3 (git 858d352)', 'blend_modes': capabilities.BLEND_MODES,
                'filters': {n: {'setting_name_%02d' % k: {'type': 'float', 'default': 0.123456} for k in range(10)} for n in names},
                'generators': {g: dict(capabilities.GENERATOR_SETTINGS.get(g, {})) for g in ('color', 'gradient', 'pattern', 'screentone', 'multigrid')},
                'presets': ['preset %d' % i for i in range(154)], 'patterns': ['Pattern name %03d.pat' % i for i in range(120)],
                'gradients': ['Gradient name %03d' % i for i in range(80)]}
        self.assertLess(len(json.dumps(capabilities.compact(full))), 4000)


class LayerCraftTests(unittest.TestCase):
    def setUp(self):
        self.previous = native.module.Selection, craft.Selection
        native.module.Selection = craft.Selection = Area
    def tearDown(self): native.module.Selection, craft.Selection = self.previous

    def test_shadow_layer_in_one_call_is_one_owned_pass(self):
        h = Harness()
        result = run(h, 'create_layer', {'name': 'Shadow', 'type': 'paint', 'blend_mode': 'multiply', 'opacity': 0.6, 'alpha_lock': True}, 'shadow')
        self.assertEqual(result['status'], 'ok')
        layer = h.doc.root.childNodes()[-1]
        self.assertEqual((layer.label, layer.blend, layer.alpha, layer.alpha_locked), ('Shadow', 'multiply', 153, True))
        self.assertIn(layer.id, h._creative_session['layers'])
        self.assertEqual([p['kind'] for p in h._creative_session['passes']], ['create_layer'])

    def test_fill_layer_uses_a_validated_generator_and_region(self):
        h = Harness()
        run(h, 'create_layer', {'name': 'Sky', 'type': 'fill', 'generator': 'color', 'generator_config': {'color': '#3a6ea5'}, 'region': [0, 0, 4, 2]}, 'sky')
        generator, area = h.doc.fills[-1]          # earlier entries are the manifest probes
        self.assertEqual((generator, area.rect), ('color', (0, 0, 4, 2, 255)))
        self.assertEqual(h.doc.root.childNodes()[-1].config.properties(), {'color': '#3a6ea5'}, 'the colour reaches Krita')
        for params, message in (({'name': 'F', 'type': 'fill', 'generator': 'plasma'}, 'Unknown generator'),
                                ({'name': 'F', 'type': 'fill', 'generator': 'color', 'alpha_lock': True}, 'Alpha lock'),
                                ({'name': 'P', 'type': 'paint', 'region': [0, 0, 2, 2]}, 'region limits'),
                                ({'name': 'P', 'type': 'paint', 'blend_mode': 'darker'}, 'Unknown blend mode')):
            with self.assertRaisesRegex(ValueError, message): run(h, 'create_layer', params, 'bad-' + params['name'])
        self.assertEqual(len(h.doc.root.childNodes()), 1, 'refused calls change nothing')

    def test_clip_to_a_clip_base_is_live(self):
        h = Harness()
        run(h, 'create_layer', {'name': 'Flats', 'type': 'paint', 'clip_base': True}, 'flats')
        group = h.doc.root.childNodes()[-1]; base = group.childNodes()[0]
        result = run(h, 'create_layer', {'name': 'Shadow', 'type': 'paint', 'blend_mode': 'multiply', 'clip_to': base.id}, 'shadow')
        shadow = group.childNodes()[-1]
        self.assertEqual(result['clip']['mode'], 'live')
        self.assertEqual([n.label for n in group.childNodes()], ['Flats', 'Shadow'])
        self.assertTrue(shadow.inherit and not base.inherit)
        self.assertEqual(h._creative_session['passes'][0]['clip_group_id'], group.id)

    def test_clip_to_an_artist_layer_uses_a_mask_and_leaves_it_in_place(self):
        h = Harness()
        figure = Node(h.doc, 'Figure', 'paintlayer'); h.doc.root.addChildNode(figure, None)
        before = (figure.parent, h.doc.root.childNodes().index(figure), figure.pixels, figure.blend, figure.label)
        result = run(h, 'create_layer', {'name': 'Light', 'type': 'paint', 'blend_mode': 'screen', 'clip_to': figure.id}, 'light')
        light = h.doc.root.childNodes()[-1]; mask = light.childNodes()[0]
        self.assertEqual(result['clip']['mode'], 'mask')
        self.assertEqual(mask.kind, 'transparencymask')
        self.assertEqual(mask.selection.rows[0], bytes([255, 0]) * 8, "the mask is the base's alpha")
        self.assertEqual(before, (figure.parent, h.doc.root.childNodes().index(figure), figure.pixels, figure.blend, figure.label))

    def test_stage_layers_share_the_stage_group(self):
        h = Harness()
        run(h, 'create_layer', {'name': 'Flats', 'type': 'paint', 'stage_id': 'stage-1-0'}, 'one')
        run(h, 'create_layer', {'name': 'Shadow', 'type': 'paint', 'stage_id': 'stage-1-0'}, 'two')
        self.assertEqual(len(h.doc.root.childNodes()), 1)
        self.assertEqual([n.label for n in h.doc.root.childNodes()[0].childNodes()], ['Flats', 'Shadow'])
        self.assertEqual(len({p['group_id'] for p in h._creative_session['passes']}), 1)

    def test_set_layer_reject_restores_every_setting(self):
        h = Harness()
        run(h, 'create_layer', {'name': 'Glow', 'type': 'paint'}, 'glow')
        glow = h.doc.root.childNodes()[-1]
        run(h, 'set_layer', {'layer_id': glow.id, 'blend_mode': 'overlay', 'opacity': 0.5, 'alpha_lock': True, 'name': 'Warm glow'}, 'adjust')
        self.assertEqual((glow.blend, glow.alpha, glow.alpha_locked, glow.label), ('overlay', 128, True, 'Warm glow'))
        run(h, 'review_pass', {'pass_id': 'adjust', 'action': 'reject'}, 'reject')
        self.assertEqual((glow.blend, glow.alpha, glow.alpha_locked, glow.label, glow.shown), ('normal', 255, False, 'Glow', True))

    def test_a_layer_style_adds_a_shadow_without_strokes_and_reject_removes_it(self):
        layer_style = sys.modules['creative_test_package.layer_style']
        h = Harness()
        run(h, 'create_layer', {'name': 'Moon', 'type': 'paint'}, 'moon')
        moon = h.doc.root.childNodes()[-1]
        style = {'drop_shadow': {'color': '#102040', 'distance': 6, 'size': 12}, 'outer_glow': {'color': '#fff2b0', 'opacity': 0.8}}
        run(h, 'set_layer', {'layer_id': moon.id, 'style': style}, 'glow')
        self.assertEqual(moon.style, layer_style.asl(style))
        for fragment in ('classId="DrSh"', 'key="Dstn" unit="#Pxl" value="6"', 'key="blur" unit="#Pxl" value="12"', 'key="Rd  " value="16"',
                         'classId="OrGl"', 'key="Opct" unit="#Prc" value="80.0"', 'key="masterFXSwitch" value="1"'):
            self.assertIn(fragment, moon.style)
        run(h, 'set_layer', {'layer_id': moon.id, 'style': {'outline': {'size': 2, 'position': 'inside'}}}, 'outline')
        run(h, 'review_pass', {'pass_id': 'outline', 'action': 'reject'}, 'reject-outline')
        self.assertEqual(moon.style, layer_style.asl(style), 'reject restores the previous style')
        run(h, 'review_pass', {'pass_id': 'glow', 'action': 'reject'}, 'reject-glow')
        self.assertEqual(moon.style, layer_style.cleared(), 'a layer with no style before shows none again')
        self.assertIn('key="masterFXSwitch" value="0"', moon.style)
        figure = Node(h.doc, 'Figure', 'paintlayer'); h.doc.root.addChildNode(figure, None)
        for params, message in (({'layer_id': figure.id, 'style': style}, 'Only layers the agent created'),
                                ({'layer_id': moon.id, 'style': {}}, 'at least one effect'),
                                ({'layer_id': moon.id, 'style': {'bevel': {}}}, 'Unknown parameters'),
                                ({'layer_id': moon.id, 'style': {'drop_shadow': {'opacity': 3}}}, 'drop_shadow: opacity must be between'),
                                ({'layer_id': moon.id, 'style': {'outline': {'position': 'around'}}}, 'outline: position')):
            with self.assertRaisesRegex(ValueError, message):
                run(h, 'set_layer', params, 'bad')
        self.assertFalse(hasattr(figure, 'style'))

    def test_set_layer_on_an_artist_layer_allows_only_opacity_and_visibility(self):
        h = Harness()
        figure = Node(h.doc, 'Figure', 'paintlayer'); h.doc.root.addChildNode(figure, None)
        with self.assertRaisesRegex(ValueError, 'Only layers the agent created'):
            run(h, 'set_layer', {'layer_id': figure.id, 'blend_mode': 'multiply'}, 'blend')
        self.assertEqual(figure.blend, 'normal')
        self.assertEqual(run(h, 'set_layer', {'layer_id': figure.id, 'opacity': 0.5}, 'fade')['status'], 'ok')
        self.assertEqual(figure.alpha, 128)

    def test_live_clip_setting_needs_a_clip_group(self):
        h = Harness()
        run(h, 'create_layer', {'name': 'Loose', 'type': 'paint'}, 'loose')
        loose = h.doc.root.childNodes()[-1]
        with self.assertRaisesRegex(ValueError, 'clip group'):
            run(h, 'set_layer', {'layer_id': loose.id, 'clip': True}, 'clip')

    def test_capabilities_operation_returns_the_compact_manifest(self):
        h = Harness()
        result = h.cmd_creative({'operation': 'capabilities', 'session_id': 'session', 'params': {}})
        self.assertIn('common_filters', result['capabilities'])
        full = h.cmd_creative({'operation': 'capabilities', 'session_id': 'session', 'params': {'full': True}})
        self.assertIn('gaussian blur', full['capabilities']['filters'])


if __name__ == '__main__':
    unittest.main()

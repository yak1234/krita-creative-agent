"""Krita's own features driven from the creative journal: vetted menu actions, on a fake 4x4 layer tree.
Saved selections and the action list go to a temporary folder that is removed."""
import json
import os
import sys
import tempfile
import types
import unittest
import test_region_craft as region_tests
import test_transform as transform_tests

native = region_tests.native
native_craft = sys.modules['creative_test_package.native_craft']
run = region_tests.run
SIZE = region_tests.SIZE

ACTIONS = {'5.3.3': [
    {'id': 'mirrorNodeX', 'label': 'Mirror layer horizontally', 'kind': 'pixels', 'needs': ['target']},
    {'id': 'selectopaque', 'label': 'Select opaque', 'kind': 'selection', 'needs': ['target']},
    {'id': 'clear', 'label': 'Clear inside the selection', 'kind': 'pixels', 'needs': ['target', 'selection']}]}


class FakeKrita:
    """Krita.instance(): actions that act on the document's active node, as Krita's menu commands do."""
    def __init__(self, doc, version='5.3.3'):
        self.doc, self.release, self.triggered, self.viewed = doc, version, [], doc
    def version(self): return self.release
    def activeDocument(self): return self.viewed
    def action(self, identifier):
        known = {'mirrorNodeX': self._mirror, 'selectopaque': self._opaque, 'clear': self._clear, 'invert_selection': self._invert}
        if identifier not in known:
            return None
        return types.SimpleNamespace(trigger=lambda: self.triggered.append((identifier, self.doc.activeNode().id)) or known[identifier]())
    def _mirror(self):
        node = self.doc.activeNode()
        rows = [node.pixels[row * SIZE * 4:(row + 1) * SIZE * 4] for row in range(SIZE)]
        node.pixels = bytearray(b''.join(b''.join(bytes(r[i * 4:i * 4 + 4]) for i in reversed(range(SIZE))) for r in rows))
    def _opaque(self):
        node, mask = self.doc.activeNode(), region_tests.Mask()
        mask.m = bytearray(255 if node.pixels[i * 4 + 3] else 0 for i in range(SIZE * SIZE))
        self.doc.setSelection(mask)
    def _invert(self):
        mask = region_tests.Mask(); mask.m = bytearray(255 - v for v in self.doc.selection().m); self.doc.setSelection(mask)
    def _clear(self):
        node, area = self.doc.activeNode(), self.doc.selection()
        for i in range(SIZE * SIZE):
            if area.m[i]: node.pixels[i * 4:i * 4 + 4] = bytes(4)


class NativeActionTests(region_tests.RegionSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, 'krita_actions.json')
        with open(path, 'w') as stream: json.dump(ACTIONS, stream)
        previous = native_craft.ACTIONS_PATH, native_craft.Krita, native_craft.Selection
        native_craft.ACTIONS_PATH = path
        self.krita = FakeKrita(self.h.doc)
        native_craft.Krita = types.SimpleNamespace(instance=lambda: self.krita)
        native_craft.Selection = region_tests.Mask
        self.addCleanup(lambda: (setattr(native_craft, 'ACTIONS_PATH', previous[0]), setattr(native_craft, 'Krita', previous[1]),
                                 setattr(native_craft, 'Selection', previous[2])))

    def agent_layer(self, name='Car'):
        run(self.h, 'create_layer', {'name': name, 'type': 'paint'}, 'make-' + name)
        layer = self.h.doc.root.childNodes()[-1]
        layer.pixels = bytearray(b''.join(bytes([i, i, i, 255 if i % 4 else 0]) for i in range(SIZE * SIZE)))
        return layer

    def test_an_action_not_on_the_list_is_refused_with_the_list(self):
        layer = self.agent_layer()
        with self.assertRaisesRegex(ValueError, 'mirrorNodeX.*selectopaque|selectopaque.*mirrorNodeX'):
            run(self.h, 'krita_action', {'action': 'resizeimage', 'target': layer.id}, 'resize')
        self.assertEqual(self.krita.triggered, [])

    def test_no_actions_on_an_unaudited_krita_version(self):
        layer = self.agent_layer()
        self.krita.release = '6.0.0'
        with self.assertRaisesRegex(ValueError, 'has not been audited'):
            run(self.h, 'krita_action', {'action': 'mirrorNodeX', 'target': layer.id}, 'mirror')
        self.assertEqual(self.krita.triggered, [])
        self.assertEqual(self.h._native_actions('6.0.0'), [])

    def test_a_pixel_action_edits_a_copy_of_an_agent_layer_and_reject_restores_it(self):
        layer = self.agent_layer()
        before = bytes(layer.pixels)
        result = run(self.h, 'krita_action', {'action': 'mirrorNodeX', 'target': layer.id}, 'mirror')
        copy = self.h.doc.root.childNodes()[-1]
        self.assertEqual((result['status'], result['layer_id'], result['source_layer_id']), ('ok', copy.id, layer.id))
        self.assertEqual(self.krita.triggered, [('mirrorNodeX', copy.id)], 'the copy was the active layer')
        self.assertEqual(bytes(layer.pixels), before, 'the original keeps its pixels')
        self.assertEqual(bytes(copy.pixels[0:4]), before[12:16], 'the copy is mirrored')
        self.assertEqual((copy.shown, layer.shown), (True, False))
        entry = self.h._creative_session['passes'][-1]
        self.assertEqual((entry['kind'], entry['title']), ('krita_action', 'Mirror layer horizontally'))
        run(self.h, 'review_pass', {'pass_id': 'mirror', 'action': 'reject'}, 'reject')
        self.assertEqual((copy.shown, layer.shown), (False, True))

    def test_a_pixel_action_refuses_the_artists_layer(self):
        figure = self.artist_layer()
        with self.assertRaisesRegex(ValueError, "artist's layers"):
            run(self.h, 'krita_action', {'action': 'mirrorNodeX', 'target': figure.id}, 'mirror')
        self.assertEqual(self.krita.triggered, [])

    def test_a_pixel_action_inside_a_saved_selection(self):
        layer = self.agent_layer()
        run(self.h, 'select', {'name': 'Left', 'steps': [{'shape': 'rectangle', 'bounds': [0, 0, 2, 4]}]})
        run(self.h, 'krita_action', {'action': 'clear', 'target': layer.id, 'selection': 'Left'}, 'clear-left')
        copy = self.h.doc.root.childNodes()[-1]
        self.assertEqual(bytes(copy.pixels[0:8]), bytes(8), 'cleared inside the selection')
        self.assertNotEqual(bytes(copy.pixels[8:16]), bytes(8), 'kept outside it')
        self.assertIsNone(self.h.doc.selection(), "the artist's (empty) selection is back")
        with self.assertRaisesRegex(ValueError, 'needs a saved selection'):
            run(self.h, 'krita_action', {'action': 'clear', 'target': layer.id}, 'clear-all')

    def test_a_selection_action_restores_the_artists_selection(self):
        figure = self.artist_layer()
        figure.pixels = bytearray(b''.join(bytes([9, 9, 9, 255 if i < 8 else 0]) for i in range(SIZE * SIZE)))
        artist = region_tests.Mask(); artist.select(3, 3, 1, 1, 255)
        self.h.doc.setSelection(artist)
        result = run(self.h, 'krita_action', {'action': 'selectopaque', 'target': figure.id, 'save_as': 'Figure'}, 'opaque')
        self.assertEqual((result['status'], result['name'], result['bounds']), ('ok', 'Figure', [0, 0, 4, 2]))
        saved = self.h._region_load(self.h._creative_session, 'figure')
        self.assertEqual(saved.pixelData(0, 0, 4, 4), bytes([255] * 8 + [0] * 8))
        self.assertIs(self.h.doc.selection(), artist, "the artist's selection is exactly restored")
        self.assertEqual(self.h._creative_session['passes'], [], 'a selection is not a pass')
        self.assertEqual(figure.pixels[3], 255, "the artist's layer is only read")
        with self.assertRaisesRegex(ValueError, 'save_as'):
            run(self.h, 'krita_action', {'action': 'selectopaque', 'target': figure.id}, 'unnamed')

    REFUSED = 'Protection is made from the objects themselves'

    def with_invert(self):
        entries = ACTIONS['5.3.3'] + [{'id': 'invert_selection', 'label': 'Invert selection', 'kind': 'selection', 'needs': ['target', 'selection']}]
        self.h._native_actions = lambda version: entries

    def test_a_seeded_selection_inverted_by_a_krita_action_cannot_become_protection(self):
        # element-scoped-painting review C1: the seed's provenance survives krita_action invert_selection save_as.
        self.with_invert(); figure = self.artist_layer()
        run(self.h, 'select', {'name': 'SkyAll', 'steps': [{'seed': [0, 0], 'tolerance': 40}]})
        run(self.h, 'krita_action', {'action': 'invert_selection', 'target': figure.id, 'selection': 'SkyAll', 'save_as': 'Towers'}, 'inv')
        self.assertTrue(self.h._region_colour_based(self.h._creative_session, [{'saved': 'Towers'}]))
        with self.assertRaisesRegex(ValueError, self.REFUSED):
            run(self.h, 'propose_protection', {'name': 'Towers', 'area': [{'saved': 'Towers'}]}, 'p1')
        run(self.h, 'select', {'name': 'Box', 'steps': [{'shape': 'rectangle', 'bounds': [0, 0, 2, 2]}]})
        run(self.h, 'krita_action', {'action': 'invert_selection', 'target': figure.id, 'selection': 'Box', 'save_as': 'Not box'}, 'inv2')
        self.assertFalse(self.h._region_colour_based(self.h._creative_session, [{'saved': 'Not box'}]), 'a box inverted stays a shape')

    def test_the_opaque_pixels_of_an_agent_layer_are_not_an_object(self):
        # Review I1: an agent layer may be a split_by_color region or a fill over a seeded selection.
        figure = self.artist_layer(); figure.pixels = bytearray(b''.join(bytes([9, 9, 9, 255 if i < 8 else 0]) for i in range(SIZE * SIZE)))
        car = self.agent_layer()
        run(self.h, 'krita_action', {'action': 'selectopaque', 'target': figure.id, 'save_as': 'Figure'}, 'o1')
        run(self.h, 'krita_action', {'action': 'selectopaque', 'target': car.id, 'save_as': 'Car'}, 'o2')
        self.assertFalse(self.h._region_colour_based(self.h._creative_session, [{'saved': 'Figure'}]), "the artist's layer alpha")
        self.assertTrue(self.h._region_colour_based(self.h._creative_session, [{'saved': 'Car'}]))

    def test_a_replayed_action_runs_once(self):
        layer = self.agent_layer()
        first = run(self.h, 'krita_action', {'action': 'mirrorNodeX', 'target': layer.id}, 'mirror')
        second = run(self.h, 'krita_action', {'action': 'mirrorNodeX', 'target': layer.id}, 'mirror')
        self.assertEqual(len(self.krita.triggered), 1)
        self.assertEqual((second.get('replayed'), second['layer_id']), (True, first['layer_id']))

    def test_the_actions_are_listed_in_the_capabilities(self):
        self.assertEqual([a['id'] for a in self.h._native_actions('5.3.3')], ['mirrorNodeX', 'selectopaque', 'clear'])
        listed = native_craft.compact_actions(self.h._native_actions('5.3.3'))
        self.assertEqual(listed[0], {'id': 'mirrorNodeX', 'label': 'Mirror layer horizontally', 'kind': 'pixels', 'needs': ['target']})

    def test_an_action_refuses_when_another_document_is_in_view(self):
        layer = self.agent_layer()
        self.krita.viewed = region_tests.Document()           # the artist switched to another painting
        with self.assertRaisesRegex(ValueError, 'another document'):
            run(self.h, 'krita_action', {'action': 'mirrorNodeX', 'target': layer.id}, 'mirror')
        self.assertEqual(self.krita.triggered, [])

    def test_an_action_refuses_when_krita_did_not_activate_the_layer(self):
        layer = self.agent_layer()
        self.h.doc.active = self.artist_layer()                # the artist's layer is active in Krita
        self.h.doc.setActiveNode = lambda node: None           # Krita ignores it when the view shows another document
        with self.assertRaisesRegex(ValueError, 'could not make'):
            run(self.h, 'krita_action', {'action': 'mirrorNodeX', 'target': layer.id}, 'mirror')
        self.assertEqual(self.krita.triggered, [])

    def test_a_selection_action_restores_the_active_layer(self):
        figure = self.artist_layer()
        figure.pixels = bytearray(b''.join(bytes([9, 9, 9, 255]) for _ in range(SIZE * SIZE)))
        chosen = self.artist_layer('Background'); self.h.doc.active = chosen
        run(self.h, 'krita_action', {'action': 'selectopaque', 'target': figure.id, 'save_as': 'Figure'}, 'opaque')
        self.assertIs(self.h.doc.activeNode(), chosen, "the artist's active layer is back")

    def test_the_audit_refuses_while_a_painting_is_open(self):
        self.h._creative_session = None
        previous = native_craft.open_documents
        native_craft.open_documents = lambda: [self.h.doc]
        self.addCleanup(setattr, native_craft, 'open_documents', previous)
        with self.assertRaisesRegex(ValueError, 'Close every painting'):
            self.h.cmd_creative({'operation': 'krita_actions_audit', 'params': {'candidates': ['mirrorNodeX']}})

    def test_health_reports_how_many_actions_are_vetted(self):
        previous = native.module.Krita; native.module.Krita = native_craft.Krita
        self.addCleanup(setattr, native.module, 'Krita', previous)
        self.h._creative_adapter_capabilities = lambda: {}       # needs real Qt; not what this test is about
        self.assertEqual(self.h.cmd_creative({'operation': 'health', 'params': {}})['krita_actions'], 3)
        self.krita.release = '6.0.0'
        self.assertEqual(self.h.cmd_creative({'operation': 'health', 'params': {}})['krita_actions'], 0)

    def test_the_fork_is_listed_by_its_settings_folder_and_version_without_the_commit(self):
        # The fork is rebuilt at every commit, so its exact version (with "(git <commit>)") would lose its audit at each
        # build; it is listed under its settings folder and release, re-audited at each upstream merge (AGENT-FORK.md).
        self.assertEqual(native_craft.actions_key('6.1.0-prealpha (git 6ad1cf6)', 'KritaAgent'), 'KritaAgent 6.1.0-prealpha')
        self.assertEqual(native_craft.actions_key('6.1.0-prealpha', 'KritaAgent'), 'KritaAgent 6.1.0-prealpha')
        self.assertEqual(native_craft.actions_key('5.3.3 (git 858d352)', ''), '5.3.3 (git 858d352)', 'stock: the exact build')

    def test_the_fork_offers_its_audited_actions_at_any_commit(self):
        with open(native_craft.ACTIONS_PATH, 'w') as stream:
            json.dump(dict(ACTIONS, **{'KritaAgent 6.1.0-prealpha': ACTIONS['5.3.3'][:1]}), stream)
        previous = native_craft.organization
        self.addCleanup(setattr, native_craft, 'organization', previous)
        native_craft.organization = lambda: 'KritaAgent'
        self.assertEqual([a['id'] for a in self.h._native_actions('6.1.0-prealpha (git 1234567)')], ['mirrorNodeX'])
        self.krita.release = '6.1.0-prealpha (git 89abcde)'
        layer = self.agent_layer()
        run(self.h, 'krita_action', {'action': 'mirrorNodeX', 'target': layer.id}, 'mirror')
        self.assertEqual(len(self.krita.triggered), 1)
        native_craft.organization = lambda: ''                 # stock Krita of the same version string was never audited
        self.assertEqual(self.h._native_actions('6.1.0-prealpha (git 1234567)'), [])

    def test_the_audit_answers_the_key_it_is_listed_under(self):
        self.h._creative_session = None
        previous = native_craft.organization, native_craft.open_documents
        self.addCleanup(lambda: (setattr(native_craft, 'organization', previous[0]), setattr(native_craft, 'open_documents', previous[1])))
        native_craft.organization = lambda: 'KritaAgent'
        native_craft.open_documents = lambda: []
        qt = sys.modules['creative_test_package.qt_compat']     # the fake Qt: the audit imports its timers, unused here
        for name in ('QCoreApplication', 'QElapsedTimer', 'QTimer'):
            if not hasattr(qt, name):
                setattr(qt, name, object()); self.addCleanup(delattr, qt, name)
        if 'creative_test_package.audit_dialogs' not in sys.modules:      # needs real Qt widgets; never reached here
            sys.modules['creative_test_package.audit_dialogs'] = types.ModuleType('creative_test_package.audit_dialogs')
            self.addCleanup(sys.modules.pop, 'creative_test_package.audit_dialogs', None)
            self.addCleanup(lambda: hasattr(sys.modules['creative_test_package'], 'audit_dialogs') and
                            delattr(sys.modules['creative_test_package'], 'audit_dialogs'))
        self.krita.release = '6.1.0-prealpha (git 89abcde)'
        closed = []
        audit = types.SimpleNamespace(rootNode=lambda: types.SimpleNamespace(childNodes=lambda: []), setModified=lambda flag: None,
                                      close=lambda: closed.append(True))
        self.krita.createDocument = lambda *args: audit
        self.krita.activeWindow = lambda: None
        answer = self.h._native_audit({'candidates': ['nosuchaction']})
        self.assertEqual((answer['version'], answer['krita_version']), ('KritaAgent 6.1.0-prealpha', '6.1.0-prealpha (git 89abcde)'))
        self.assertEqual(answer['results'][0]['status'], 'missing')
        self.assertEqual(closed, [True])

    def test_the_audit_refuses_during_a_session(self):
        with self.assertRaisesRegex(ValueError, 'no painting session'):
            self.h.cmd_creative({'operation': 'krita_actions_audit', 'params': {'candidates': ['mirrorNodeX']}})



class CloneLayer(region_tests.Layer):
    """Krita's clone layer: it shows its source's pixels and follows later edits to them."""
    def __init__(self, doc, name, source):
        super().__init__(doc, name, 'clonelayer'); self.source = source
    def pixelData(self, x, y, w, h): return self.source.pixelData(x, y, w, h)


class CloneDocument(transform_tests.Document):
    def createCloneLayer(self, name, source): return CloneLayer(self, name, source)


class CloneTests(region_tests.RegionSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.h.doc = CloneDocument()
        self.h._creative_session.update(document_id=native.module.document_id(self.h.doc))

    def test_a_clone_of_the_artists_layer_leaves_it_unchanged(self):
        figure = self.artist_layer()
        state = (bytes(figure.pixels), figure.label, figure.parent, figure.shown, figure.alpha)
        result = run(self.h, 'clone_layer', {'source': figure.id, 'name': 'Figure echo', 'opacity': 0.5, 'blend_mode': 'multiply'}, 'echo')
        clone = self.h._creative_node(self.h.doc, result['layer_id'])
        self.assertEqual((result['status'], result['layer_type'], result['clone_of']), ('ok', 'clonelayer', figure.id))
        self.assertNotIn('source_layer_id', result, 'not a copy edit: reject must not touch the source')
        self.assertEqual((clone.kind, clone.source, clone.alpha, clone.blend), ('clonelayer', figure, 128, 'multiply'))
        self.assertEqual((bytes(figure.pixels), figure.label, figure.parent, figure.shown, figure.alpha), state)
        run(self.h, 'review_pass', {'pass_id': 'echo', 'action': 'reject'}, 'reject')
        self.assertEqual((clone.shown, figure.shown, figure.alpha), (False, True, state[4]))

    def test_a_clone_offset_moves_it(self):
        run(self.h, 'create_layer', {'name': 'Lamp post', 'type': 'paint'}, 'lamp')
        lamp = self.h.doc.root.childNodes()[-1]
        result = run(self.h, 'clone_layer', {'source': lamp.id, 'name': 'Lamp post 2', 'offset': [400, 0]}, 'lamp-2')
        clone = self.h._creative_node(self.h.doc, result['layer_id'])
        mask, = clone.childNodes()
        moved = transform_tests.values(mask.xml)
        self.assertEqual((mask.kind, moved['transformed'][0] - moved['original'][0], moved['transformed'][1] - moved['original'][1]),
                         ('transformmask', 400.0, 0.0))

    def test_a_clone_never_goes_inside_the_group_it_copies(self):
        run(self.h, 'create_layer', {'name': 'Street', 'type': 'group'}, 'street')
        group = self.h.doc.root.childNodes()[-1]
        before = [n.kind for n in self.h.doc.root.childNodes()]
        with self.assertRaisesRegex(ValueError, 'inside the group it copies'):
            run(self.h, 'clone_layer', {'source': group.id, 'name': 'Street echo'}, 'echo')
        self.assertEqual([n.kind for n in self.h.doc.root.childNodes()], before)
        artist = region_tests.Layer(self.h.doc, 'Artist group', 'grouplayer'); self.h.doc.root.addChildNode(artist, None)
        result = run(self.h, 'clone_layer', {'source': artist.id, 'name': 'Artist echo'}, 'artist-echo')
        self.assertEqual(result['status'], 'ok', "an artist's group holds no agent layer: it can be cloned")

    def test_clone_refusals_change_nothing(self):
        figure = self.artist_layer()
        for params, message in (({'source': 'missing', 'name': 'X'}, 'layer'),
                                ({'source': figure.id, 'name': 'X', 'offset': [1]}, 'offset'),
                                ({'source': figure.id, 'name': 'X', 'opacity': 2}, 'opacity')):
            with self.assertRaisesRegex(ValueError, message):
                run(self.h, 'clone_layer', params, 'bad-' + message)
        self.assertEqual([n.kind for n in self.h.doc.root.childNodes()], ['paintlayer'])



def fake_color_split():
    """color_split without Qt: the real byte helpers, a palette of the distinct opaque colours, exact assignment."""
    module = types.ModuleType('creative_test_package.color_split')
    gui = sys.modules['PyQt5.QtGui']; saved = (getattr(gui, 'QImage', None), getattr(gui, 'qRgb', None))
    gui.QImage, gui.qRgb = object(), lambda *a: a
    try:
        with open(os.path.join(os.path.dirname(native.SOURCE / 'x'), 'color_split.py')) as stream:
            exec(compile(stream.read(), 'color_split.py', 'exec'), module.__dict__)
    finally:
        gui.QImage, gui.qRgb = saved
    def palette(bgra, w, h, count):
        found = []
        for i in range(w * h):
            b, g, r, a = bgra[i * 4:i * 4 + 4]
            if a >= 128 and (r, g, b) not in found: found.append((r, g, b))
        return found[:count]
    def assign(bgra, w, h, colours):
        out = bytearray()
        for i in range(w * h):
            b, g, r, a = bgra[i * 4:i * 4 + 4]
            out.append(255 if a < 128 else min(range(len(colours)), key=lambda k: sum((x - y) ** 2 for x, y in zip(colours[k], (r, g, b)))))
        return bytes(out)
    module.palette, module.assign = palette, assign
    return module


class SplitTests(region_tests.RegionSetup, unittest.TestCase):
    """A 4x4 painting: a blue sky on the top two rows, a grey road on the next one and a single red pixel."""
    def setUp(self):
        super().setUp()
        self.split = fake_color_split()
        previous = native_craft.Selection; native_craft.Selection = region_tests.Mask
        self.addCleanup(setattr, native_craft, 'Selection', previous)
        prior = sys.modules.get(self.split.__name__)
        sys.modules[self.split.__name__] = self.split; native.package.color_split = self.split
        self.addCleanup(lambda: sys.modules.__setitem__(self.split.__name__, prior) if prior else sys.modules.pop(self.split.__name__, None))
        painting = self.artist_layer('Painting')
        sky, road, red = bytes([200, 100, 20, 255]), bytes([90, 90, 90, 255]), bytes([0, 0, 220, 255])
        painting.pixels = bytearray(sky * 8 + road * 4 + red + bytes(4) * 3)
        self.painting = painting
        self.h.doc.root.pixels = bytearray(painting.pixels)          # the visible image is the painting
        self.writes = []
        create = self.h.doc.createNode
        def logged(name, kind):
            node = create(name, kind)
            if kind == 'paintlayer':
                write = node.setPixelData
                node.setPixelData = lambda data, x, y, w, h: self.writes.append((name, (x, y, w, h))) or write(data, x, y, w, h)
            return node
        self.h.doc.createNode = logged

    def test_split_saves_named_selections_without_a_pass(self):
        result = run(self.h, 'split_by_color', {'source': 'visible', 'colors': 8, 'min_area': 2})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([(s['name'], s['color'], s['share'], s['bounds']) for s in result['selections']],
                         [('Split 1 1464c8', '#1464c8', 0.5, [0, 0, 4, 2]), ('Split 2 5a5a5a', '#5a5a5a', 0.25, [0, 2, 4, 1])],
                         'largest first; the single red pixel is under min_area')
        sky = self.h._region_load(self.h._creative_session, 'Split 1 1464c8')
        self.assertEqual(sky.pixelData(0, 0, 4, 4), bytes([255] * 8 + [0] * 8))
        self.assertLessEqual(sum(s['share'] for s in result['selections']), 1)
        self.assertEqual(self.h._creative_session['passes'], [], 'selections are not a pass')
        self.assertEqual(self.h.doc.selection_changes, [], "the artist's selection is never touched")

    def test_split_regions_are_colour_selections_and_never_protection(self):
        # Review C1: split_by_color regions are colour picks; inverting one does not make it an object.
        run(self.h, 'split_by_color', {'source': 'visible', 'colors': 8, 'min_area': 2})
        steps = [{'saved': 'Split 1 1464c8'}, {'invert': True}]
        self.assertTrue(self.h._region_colour_based(self.h._creative_session, steps))
        with self.assertRaisesRegex(ValueError, 'Protection is made from the objects themselves'):
            run(self.h, 'propose_protection', {'name': 'Buildings', 'area': steps}, 'p')

    def test_split_layers_are_not_an_object_either(self):
        result = run(self.h, 'split_by_color', {'source': 'visible', 'as_layers': True, 'min_area': 2}, 'layers')
        owned = [n for n in self.h.doc.root.childNodes() if n.type() == 'grouplayer']
        layer = next(c for g in owned for c in g.childNodes())
        self.assertEqual(result['status'], 'ok')
        with self.assertRaisesRegex(ValueError, 'Protection is made from the objects themselves'):
            run(self.h, 'propose_protection', {'name': 'Sky', 'area': [{'layer_id': layer.id}]}, 'p2')

    def test_split_of_a_region_and_a_prefix(self):
        result = run(self.h, 'split_by_color', {'source': self.painting.id, 'region': [0, 1, 4, 2], 'min_area': 1, 'name_prefix': 'Street'})
        self.assertEqual([(s['name'], s['bounds']) for s in result['selections']],
                         [('Street 1 1464c8', [0, 1, 4, 1]), ('Street 2 5a5a5a', [0, 2, 4, 1])])

    def test_split_as_layers_is_one_pass_reject_removes_the_group(self):
        result = run(self.h, 'split_by_color', {'source': 'visible', 'as_layers': True, 'min_area': 2}, 'layers')
        group = self.h._creative_node(self.h.doc, result['layer_id'])
        self.assertEqual((result['status'], group.kind, [c.label for c in group.childNodes()]),
                         ('ok', 'grouplayer', ['Split 1 1464c8', 'Split 2 5a5a5a']))
        sky, road = group.childNodes()
        self.assertEqual(bytes(sky.pixels[:32]), bytes(self.painting.pixels[:32]), 'the sky pixels, written over its bounds only')
        self.assertEqual(bytes(road.pixels[32:48]), bytes(self.painting.pixels[32:48]))
        self.assertEqual(self.writes, [('Split 1 1464c8', (0, 0, 4, 2)), ('Split 2 5a5a5a', (0, 2, 4, 1))],
                         'each layer is written over its own bounds, not the whole canvas')
        self.assertEqual(len(result['selections']), 2, 'the selections are saved too')
        self.assertEqual(self.h._creative_session['passes'][-1]['kind'], 'split_by_color')
        run(self.h, 'review_pass', {'pass_id': 'layers', 'action': 'reject'}, 'reject')
        self.assertFalse(group.shown)

    def test_split_refuses_a_non_rgba_painting(self):
        self.h.doc.colorDepth = lambda: 'U16'
        with self.assertRaisesRegex(ValueError, '8-bit RGBA'):
            run(self.h, 'split_by_color', {'source': 'visible'})
        self.assertFalse(os.path.isdir(os.path.join(self.h._creative_session['output'], '.selections')))

    def test_split_refuses_a_layer_that_is_not_8_bit_rgba(self):
        self.painting.colorModel, self.painting.colorDepth = (lambda: 'GRAYA'), (lambda: 'U8')
        with self.assertRaisesRegex(ValueError, '8-bit RGBA'):
            run(self.h, 'split_by_color', {'source': self.painting.id})

    def test_the_default_speck_size_follows_the_area_split(self):
        self.h.doc.width = self.h.doc.height = lambda: 1000      # a large canvas; the split reads only a small region
        self.h._creative_session.update(width=1000, height=1000)
        result = run(self.h, 'split_by_color', {'source': 'visible', 'region': [0, 0, 4, 4]})
        self.assertEqual(len(result['selections']), 3, 'nothing in a 16-pixel region is a speck of a 1000x1000 canvas')

    def test_split_refusals(self):
        for params, message in (({'source': 'visible', 'colors': 1}, 'colors'),
                                ({'source': 'visible', 'colors': 25}, 'colors'),
                                ({'source': 'missing'}, 'layer'),
                                ({'source': 'visible', 'name_prefix': 'Sky · 1'}, 'name_prefix'),
                                ({'source': 'visible', 'min_area': -1}, 'min_area')):
            with self.assertRaisesRegex(ValueError, message):
                run(self.h, 'split_by_color', params)



class BenchmarkCopyTests(unittest.TestCase):
    """The tool-choice benchmark closes the painting copy it opened, unsaved, when no chat is painting."""
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.run_dir = os.path.join(folder.name, 'benchmark-runs', '202610181200-tool-choice', 'moscow-sky-1')
        os.makedirs(self.run_dir)
        self.copy = os.path.join(self.run_dir, 'new_moscow.kra'); open(self.copy, 'w').close()
        self.closed = []
        test = self
        class Doc:
            def __init__(self, path): self.path, self.modified = path, True
            def fileName(self): return self.path
            def setModified(self, value): self.modified = value
            def close(self): test.closed.append((self.path, self.modified)); return True
        self.docs = [Doc(self.copy), Doc(os.path.join(folder.name, 'new_moscow.kra'))]
        previous = native.module.open_documents
        native.module.open_documents = lambda: list(self.docs)
        self.addCleanup(setattr, native.module, 'open_documents', previous)
        self.h = native.Harness(); self.h._creative_session = None

    def close(self, path):
        return self.h.cmd_creative({'operation': 'close_benchmark_copy', 'params': {'path': path}})

    def test_the_copy_closes_unsaved(self):
        self.assertEqual(self.close(self.copy), {'status': 'ok', 'closed': True})
        self.assertEqual(self.closed, [(self.copy, False)], 'unsaved: the copy is thrown away')

    def test_a_copy_a_session_saved_deeper_in_the_run_folder_closes_too(self):
        deeper = os.path.join(self.run_dir, '8118a08d-268e-44a6-9bcb-33965df47e26', 'painting.kra')
        os.makedirs(os.path.dirname(deeper)); open(deeper, 'w').close()
        self.docs[0].path = deeper
        self.assertEqual(self.close(deeper), {'status': 'ok', 'closed': True})

    def test_an_image_copy_closes_too(self):
        image = os.path.join(self.run_dir, 'new_moscow_flat.png'); open(image, 'w').close()
        self.docs[0].path = image
        self.assertEqual(self.close(image), {'status': 'ok', 'closed': True})

    def test_only_a_copy_in_a_tool_choice_run_and_never_during_a_chat(self):
        with self.assertRaisesRegex(ValueError, 'tool-choice'):
            self.close(self.docs[1].path)
        lookalike = os.path.join(os.path.dirname(self.docs[1].path), 'my-tool-choice', 'notes', 'painting.kra')
        with self.assertRaisesRegex(ValueError, 'tool-choice'):
            self.close(lookalike)
        self.h._creative_session = {'id': 'painting'}
        with self.assertRaisesRegex(ValueError, 'painting session'):
            self.close(self.copy)
        self.assertEqual(self.closed, [])


class CloseDocumentTests(unittest.TestCase):
    """Closing a saved painting (to free Krita's undo history, then reopen it): never one with unsaved changes, never during a chat."""
    def setUp(self):
        self.closed = []
        test = self
        class Doc:
            def __init__(self, path, changed): self.path, self.changed = path, changed
            def fileName(self): return self.path
            def modified(self): return self.changed
            def setModified(self, value): self.changed = value
            def close(self): test.closed.append(self.path); return True
        self.saved, self.unsaved = Doc('/art/new_moscow.kra', False), Doc('/art/sketch.kra', True)
        previous = native.module.open_documents
        native.module.open_documents = lambda: [self.saved, self.unsaved]
        self.addCleanup(setattr, native.module, 'open_documents', previous)
        self.h = native.Harness(); self.h._creative_session = None

    def close(self, path):
        return self.h.cmd_creative({'operation': 'close_document', 'params': {'path': path}})

    def test_a_saved_painting_closes(self):
        self.assertEqual(self.close('/art/new_moscow.kra'), {'status': 'ok', 'closed': True})
        self.assertEqual(self.closed, ['/art/new_moscow.kra'])

    def test_unsaved_changes_a_chat_or_an_unknown_path_close_nothing(self):
        with self.assertRaisesRegex(ValueError, 'unsaved'):
            self.close('/art/sketch.kra')
        self.assertEqual(self.close('/art/elsewhere.kra'), {'status': 'ok', 'closed': False})
        self.h._creative_session = {'id': 'painting'}
        with self.assertRaisesRegex(ValueError, 'painting session'):
            self.close('/art/new_moscow.kra')
        self.assertEqual(self.closed, [])
        self.assertTrue(self.unsaved.changed, 'its changes are never discarded')



class TestKeepProtectionTests(unittest.TestCase):
    """A test chat keeps a proposed protected area, as the artist's panel click would, on benchmark copies only."""
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.copy = os.path.join(folder.name, 'benchmark-runs', '202610181200-tool-choice', 'moscow-finish-clouds-1', 'new_moscow_finished.kra')
        self.original = os.path.join(folder.name, 'new_moscow_finished.kra')
        self.h = native.Harness()
        self.path = self.copy
        self.h.doc.fileName = lambda: self.path
        self.areas = [{'id': 'a1', 'name': 'Moon', 'state': 'pending', 'by': 'agent'}, {'id': 'a2', 'name': 'Moon', 'state': 'pending', 'by': 'agent'},
                      {'id': 'a3', 'name': 'Rim', 'state': 'active', 'by': 'artist'}]
        self.h._protect_list = lambda doc: [dict(a) for a in self.areas]
        self.changed = []
        def set_state(doc, area_id, state):
            self.changed.append((area_id, state))
            next(a for a in self.areas if a['id'] == area_id)['state'] = state
        self.h._protect_set_state = set_state

    def keep(self, name):
        return self.h.cmd_creative({'operation': 'test_keep_protection', 'params': {'name': name}})

    def test_a_proposed_area_on_a_test_copy_is_kept(self):
        self.assertEqual(self.keep('Moon'), {'status': 'ok', 'kept': 2})
        self.assertEqual(self.changed, [('a1', 'active'), ('a2', 'active')])

    def test_only_test_copies(self):
        self.path = self.original
        with self.assertRaisesRegex(ValueError, 'Only test copies in benchmark-runs/ can be kept from a test.'):
            self.keep('Moon')
        self.assertEqual(self.changed, [])

    def test_an_unknown_or_already_kept_name_is_refused(self):
        for name in ('Sun', 'Rim'):
            with self.assertRaisesRegex(ValueError, "No proposed area named '%s'." % name):
                self.keep(name)


class MergeAgentWorkTests(unittest.TestCase):
    """Merging the agent's kept work: each of its groups becomes one layer showing exactly what the group showed, empty
    groups go, neighbouring merged layers become one; the artist's layers and the protected areas are untouched."""
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.h = native.Harness(); self.h._creative_session = None
        doc = region_tests.Document(); self.h.doc = doc
        self.h.get_active_document = lambda: doc
        self.merged_down = []
        test = self
        def node(name, kind='paintlayer', shown=True, parent=None, fill=None, opacity=255):
            n = region_tests.Layer(doc, name, kind); n.shown = shown; n.alpha = opacity
            if fill is not None: n.pixels = bytearray(bytes(fill) * (len(n.pixels) // 4))
            n.remove = lambda n=n: n.parent.children.remove(n) or True
            def merge_down(n=n):
                below = n.parent.children[n.parent.children.index(n) - 1]
                test.merged_down.append((n.label, below.label)); n.remove(); return below
            n.mergeDown = merge_down
            n.bounds = lambda: types.SimpleNamespace(x=lambda: 0, y=lambda: 0, width=lambda: 4, height=lambda: 4)
            (parent or doc.root).addChildNode(n, None); return n
        self.node = node
        doc.createNode = self._fresh
        self.background = node('Background', fill=(10, 10, 10, 255))
        move1 = node('Creative Agent · move-1', 'grouplayer', opacity=200)
        move1.projectionPixelData = lambda x, y, w, h: bytes((1, 2, 3, 255)) * (w * h)
        node('Sky', parent=move1, fill=(1, 2, 3, 255))
        node('Creative Agent · move-2', 'grouplayer')                                  # left empty by a tidy
        move3 = node('Creative Agent · move-3', 'grouplayer')
        move3.projectionPixelData = lambda x, y, w, h: bytes((7, 8, 9, 255)) * (w * h)
        node('Clouds', parent=move3, fill=(7, 8, 9, 255))
        self.artist = node('Car finish', fill=(50, 50, 50, 255))
        move4 = node('Creative Agent · move-4', 'grouplayer')
        move4.projectionPixelData = lambda x, y, w, h: bytes((4, 4, 4, 255)) * (w * h)
        node('Moon glow', parent=move4, fill=(4, 4, 4, 255))
        node('Protected areas · Creative Agent', 'grouplayer', shown=False)
        painting = os.path.join(folder.name, 'painting.kra'); open(painting, 'w').write('kra')
        doc.fileName = lambda: painting
        self.painting = painting
        self.h._native_merge_signature = lambda doc: 'same'

    def _fresh(self, name, kind):
        n = region_tests.Layer(self.h.doc, name, kind)
        n.remove = lambda n=n: n.parent.children.remove(n) or True
        test = self
        def merge_down(n=n):
            below = n.parent.children[n.parent.children.index(n) - 1]
            test.merged_down.append((n.label, below.label)); n.remove(); return below
        n.mergeDown = merge_down
        return n

    def merge(self, **params):
        return self.h.cmd_creative({'operation': 'merge_agent_work', 'params': params})

    def top(self):
        return [(c.label, c.kind) for c in self.h.doc.root.children]

    def test_a_dry_run_lists_what_would_merge_and_changes_nothing(self):
        before = self.top()
        result = self.merge()
        self.assertEqual((result['dry_run'], result['groups'], result['empty_groups'], result['layers_after']), (True, 3, 1, 2))
        self.assertEqual(self.top(), before)

    def test_groups_become_one_layer_each_run_merges_down_and_the_artist_is_untouched(self):
        result = self.merge(dry_run=False)
        names = [n for n, _ in self.top()]
        self.assertEqual(names, ['Background', 'Creative Agent · merged 1', 'Car finish', 'Creative Agent · merged 2', 'Protected areas · Creative Agent'])
        self.assertEqual(self.h.doc.root.children[1].kind, 'paintlayer')
        self.assertEqual(self.merged_down, [('Creative Agent · move-3', 'Creative Agent · move-1')], 'the run of two merges into one')
        self.assertEqual(bytes(self.artist.pixels[:4]), bytes((50, 50, 50, 255)))
        self.assertEqual((result['groups'], result['empty_groups'], result['layers_after'], result['unchanged']), (3, 1, 2, True))
        self.assertTrue(result['backup'].endswith('painting.before-merge.kra'))
        self.assertIn('not saved', result['note'])

    def test_a_group_keeps_its_opacity_on_the_layer_that_replaces_it(self):
        self.h.doc.root.children[3].label = 'Artist divider'      # move-1 and move-3 no longer neighbours
        self.h.doc.root.children[3].kind = 'paintlayer'
        self.merge(dry_run=False)
        layer = next(c for c in self.h.doc.root.children if c.label == 'Creative Agent · merged 1')
        self.assertEqual((layer.alpha, bytes(layer.pixels[:4])), (200, bytes((1, 2, 3, 255))))

    def test_merging_refuses_during_a_painting_session(self):
        self.h._creative_session = {'id': 'chat'}
        with self.assertRaisesRegex(ValueError, 'painting session'):
            self.merge(dry_run=False)


class MergeAgentWorkForkTests(MergeAgentWorkTests):
    """On the fork (krita-fork 5.2): each run of agent groups is one Document.mergeGroups call, all inside one agent move,
    so the whole merge is one undo step and nothing is copied through Python."""
    def setUp(self):
        super().setUp()
        doc, test = self.h.doc, self
        self.calls, self.moves = [], []
        def merge_groups(nodes):
            test.calls.append([n.label for n in nodes])
            if test.refuse:
                return None
            parent = nodes[-1].parent
            merged = test._fresh('merged', 'paintlayer')
            parent.children.insert(parent.children.index(nodes[-1]) + 1, merged); merged.parent = parent
            for n in nodes:
                n.remove()
            return merged
        self.refuse = False
        doc.mergeGroups = merge_groups
        class Move:
            def __init__(self, name): test.moves.append([name, 'open'])
            def __enter__(self): return self
            def __exit__(self, *exc): test.moves[-1][1] = 'closed'; return False
        doc.agentMove = Move

    def test_each_run_is_one_merge_groups_call_inside_one_agent_move(self):
        result = self.merge(dry_run=False)
        self.assertEqual(self.calls, [['Creative Agent · move-1', 'Creative Agent · move-3'], ['Creative Agent · move-4']])
        self.assertEqual(self.moves, [['Merge agent work', 'closed']])
        self.assertEqual(self.merged_down, [], 'no layer-by-layer merge down on the fork')
        names = [n for n, _ in self.top()]
        self.assertEqual(names, ['Background', 'Creative Agent · merged 1', 'Car finish', 'Creative Agent · merged 2', 'Protected areas · Creative Agent'])
        self.assertEqual((result['built_with'], result['unchanged']), ('mergeGroups', True))

    def test_a_refused_run_stops_the_merge_and_says_which(self):
        self.refuse = True
        with self.assertRaisesRegex(RuntimeError, "Krita refused to merge 'Creative Agent · move-1', 'Creative Agent · move-3'"):
            self.merge(dry_run=False)
        self.assertEqual(self.moves, [['Merge agent work', 'closed']], 'the move closes even when a run is refused')

    def test_a_group_keeps_its_opacity_on_the_layer_that_replaces_it(self):
        pass                                                  # Krita's merge renders the group's opacity itself

    def test_groups_become_one_layer_each_run_merges_down_and_the_artist_is_untouched(self):
        pass                                                  # the stock path's merge down; the fork's is tested above


class TidyTests(unittest.TestCase):
    """Tidying a painting: the agent's hidden leftovers go; everything of the artist's stays."""
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder = folder.name
        self.h = native.Harness(); self.h._creative_session = None
        doc = region_tests.Document(); self.h.doc = doc
        self.h.get_active_document = lambda: doc
        def node(name, kind='paintlayer', shown=True, parent=None):
            n = region_tests.Layer(doc, name, kind); n.shown = shown
            n.remove = lambda n=n: n.parent.children.remove(n) or True
            (parent or doc.root).addChildNode(n, None); return n
        self.node = node
        self.artist_hidden = node('Old sketch', shown=False)
        self.protection = node('Protected areas · Creative Agent', 'grouplayer', shown=False)
        stage = node('Creative Agent · move-5', 'grouplayer')
        self.kept = node('Clouds', parent=stage)
        self.original = node('Clouds', shown=False, parent=stage)          # a copy edit's hidden original
        self.rejected = node('Sky wash', shown=False, parent=stage)
        emptied = node('Creative Agent · move-2', 'grouplayer')
        node('Rejected pass', shown=False, parent=emptied)
        painting = os.path.join(self.folder, 'painting.kra'); open(painting, 'w').write('kra')
        doc.fileName = lambda: painting
        self.painting = painting

    def tidy(self, **params):
        return self.h.cmd_creative({'operation': 'tidy_painting', 'params': params})

    def names(self):
        out = []
        def walk(n):
            for c in n.childNodes(): out.append(c.label); walk(c)
        walk(self.h.doc.root); return out

    def test_a_dry_run_lists_the_agents_hidden_layers_and_changes_nothing(self):
        before = self.names()
        result = self.tidy()
        self.assertEqual((result['dry_run'], result['layers']), (True, 3))
        self.assertEqual(sorted(r['name'] for r in result['removed']), ['Clouds', 'Rejected pass', 'Sky wash'])
        self.assertEqual(result['empty_groups'], 1)
        self.assertEqual(self.names(), before)

    def test_tidying_removes_only_hidden_agent_layers_backs_up_and_does_not_save(self):
        result = self.tidy(dry_run=False)
        self.assertEqual(result['layers'], 3)
        names = self.names()
        self.assertIn('Old sketch', names, "the artist's hidden layer stays")
        self.assertIn('Protected areas · Creative Agent', names, 'the protected areas stay')
        self.assertEqual(names.count('Clouds'), 1, 'the kept copy stays, its hidden original goes')
        self.assertNotIn('Creative Agent · move-2', names, 'a group left empty goes')
        self.assertEqual(open(self.painting.replace('.kra', '.before-tidy.kra')).read(), 'kra', 'a backup of the saved file')
        self.assertTrue(result['backup'].endswith('painting.before-tidy.kra'))
        self.assertIn('not saved', result['note'])

    def test_tidying_refuses_during_a_painting_session(self):
        self.h._creative_session = {'id': 'chat'}
        with self.assertRaisesRegex(ValueError, 'painting session'):
            self.tidy(dry_run=False)



class TidyKeptTests(region_tests.RegionSetup, unittest.TestCase):
    """On Keep the stage's hidden leftovers go: rejected passes and the originals its copy edits replaced."""
    def setUp(self):
        super().setUp()
        self.h.doc.root.remove = lambda: True
        original_create = self.h.doc.createNode
        def create(name, kind):
            node = original_create(name, kind)
            node.remove = lambda n=node: n.parent.children.remove(n) or True
            return node
        self.h.doc.createNode = create
        previous = region_tests.Layer.clone
        def clone(layer):
            copy = previous(layer); copy.remove = lambda n=copy: n.parent.children.remove(n) or True; return copy
        region_tests.Layer.clone = clone
        self.addCleanup(setattr, region_tests.Layer, 'clone', previous)

    def test_keep_removes_the_stages_hidden_leftovers_and_marks_their_history(self):
        run(self.h, 'create_layer', {'name': 'Clouds', 'type': 'paint', 'stage_id': 'move-1'}, 'clouds')
        clouds = self.h._creative_session['passes'][-1]['layer_id']
        run(self.h, 'fill_region', {'layer_id': clouds, 'color': '#336699', 'stage_id': 'move-1',
                                   'area': [{'shape': 'rectangle', 'bounds': [0, 0, 2, 2]}]}, 'veil')   # a copy edit: Clouds hidden
        copy = self.h._creative_session['passes'][-1]['layer_id']
        run(self.h, 'create_layer', {'name': 'Wash', 'type': 'paint', 'stage_id': 'move-1'}, 'wash')
        wash = self.h._creative_session['passes'][-1]['layer_id']
        run(self.h, 'review_pass', {'pass_id': 'wash', 'action': 'reject'}, 'reject-wash')
        result = self.h.cmd_creative({'operation': 'tidy_kept', 'session_id': 'session', 'params': {'stage_id': 'move-1'}})
        self.assertEqual(result['removed_layers'], 2)
        for gone in (clouds, wash):
            with self.assertRaises(ValueError):
                self.h._creative_node(self.h.doc, gone)
            self.assertNotIn(gone, self.h._creative_session['layers'])
        self.assertTrue(self.h._creative_node(self.h.doc, copy).visible(), 'the kept copy stays')
        tidied = {e['id'] for e in self.h._creative_session['passes'] if e.get('tidied')}
        self.assertEqual(tidied, {'clouds', 'wash'})
        again = self.h.cmd_creative({'operation': 'tidy_kept', 'session_id': 'session', 'params': {'stage_id': 'move-1'}})
        self.assertEqual(again['removed_layers'], 0, 'nothing twice')

    def test_another_stage_and_the_artists_layers_are_left_alone(self):
        figure = self.artist_layer(); figure.shown = False
        run(self.h, 'create_layer', {'name': 'Other', 'type': 'paint', 'stage_id': 'move-2'}, 'other')
        run(self.h, 'review_pass', {'pass_id': 'other', 'action': 'reject'}, 'reject-other')
        result = self.h.cmd_creative({'operation': 'tidy_kept', 'session_id': 'session', 'params': {'stage_id': 'move-1'}})
        self.assertEqual(result['removed_layers'], 0)
        self.assertIn(figure, self.h.doc.root.childNodes())


if __name__ == '__main__':
    unittest.main()


class PaintingWeightTests(unittest.TestCase):
    """Observations say how heavy the painting is, from layer metadata (painting_weight.py)."""
    def test_the_weight_of_the_active_painting_from_its_layers(self):
        import test_painting_weight as tw
        h = native.Harness()
        doc = tw.Doc([tw.Node('paintlayer', 'Background', bounds=(0, 0, 100, 100))])
        doc.width = lambda: 100; doc.height = lambda: 100
        weight = h._creative_weight(doc)
        self.assertEqual((weight['nodes'], weight['level']), (1, 'ok'))

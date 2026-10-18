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
        known = {'mirrorNodeX': self._mirror, 'selectopaque': self._opaque, 'clear': self._clear}
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


if __name__ == '__main__':
    unittest.main()

"""Exercise native dispatch policies without launching or modifying Krita."""
import importlib.util
import os
import pathlib
import sys
import types
import unittest
import tempfile
import uuid

SOURCE = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
package = types.ModuleType('creative_test_package')
package.__path__ = [str(SOURCE)]
sys.modules[package.__name__] = package
krita = types.ModuleType('krita')
krita.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(resources=lambda _kind: {'b) Basic-1': 1}))
class Selection:
    def select(self, *bounds): self.bounds = bounds
    def setPixelData(self, data, *bounds): self.data, self.bounds = bytes(data), bounds
krita.Selection = Selection
class InfoObject:
    def __init__(self): self.values = {}
    def setProperty(self, key, value): self.values[key] = value
    def properties(self): return dict(self.values)
krita.InfoObject = InfoObject
krita.ManagedColor = types.SimpleNamespace(fromQColor=lambda colour: colour)
sys.modules['krita'] = krita
qt = types.ModuleType('PyQt5.QtCore'); qt.Qt = object()
qt.QCoreApplication = types.SimpleNamespace(processEvents=lambda: None)
class QElapsedTimer:
    def start(self): pass
    def elapsed(self): return 0
qt.QElapsedTimer = QElapsedTimer
gui = types.ModuleType('PyQt5.QtGui'); gui.QColor = lambda name: name
sys.modules['PyQt5'] = types.ModuleType('PyQt5')
sys.modules['PyQt5.QtCore'] = qt
sys.modules['PyQt5.QtGui'] = gui
# Plugin modules import Qt from qt_compat: here it serves the stubs above, read at import time, so a test that patches
# a stub (gui.QImage) reaches the code. Names no stub has are missing, as an import error says.
compat = types.ModuleType('creative_test_package.qt_compat')
def _stub(name):
    for stub in (qt, gui):
        if name in stub.__dict__:
            return stub.__dict__[name]
    raise AttributeError(name)
compat.__getattr__ = _stub
compat.QT6 = False
sys.modules[compat.__name__] = compat; package.qt_compat = compat
spec = importlib.util.spec_from_file_location('creative_test_package.creative_tools', SOURCE / 'creative_tools.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class Document:
    identity = 'study-document'
    def __init__(self): self.nodes = []; self.selected = None; self.active = None; self.selection_changes = []
    def rootNode(self): return self
    def uniqueId(self): return self
    def toString(self): return self.identity
    def width(self): return 768
    def height(self): return 1024
    def name(self): return 'Unsaved painting'
    def fileName(self): return ''
    def modified(self): return True
    def childNodes(self): return self.nodes
    def activeNode(self): return self.active
    def setActiveNode(self, value): self.active = value
    def selection(self): return self.selected
    def setSelection(self, value): self.selected = value; self.selection_changes.append(value)
    def refreshProjection(self): pass
    def waitForDone(self): pass

class Layer:
    def __init__(self, identity): self.identity=identity; self.alpha=255; self.shown=True; self.pixels=b'paint'; self.is_locked=False
    def uniqueId(self): return self
    def toString(self): return self.identity
    def childNodes(self): return []
    def name(self): return self.identity
    def type(self): return 'paintlayer'
    def pixelData(self, *args): return self.pixels
    def opacity(self): return self.alpha
    def visible(self): return self.shown
    def locked(self): return self.is_locked
    def setOpacity(self, value): self.alpha=value
    def setVisible(self, value): self.shown=value

class Harness(module.CreativeTools):
    def __init__(self):
        self.doc = Document(); self.paints = 0; self.created_layers = 0; self.fail = False
        self._creative_session = {'id': 'session', 'document_id': module.document_id(self.doc),
                                  'width': 768, 'height': 1024, 'operations': {}, 'layers': set()}
    def get_active_document(self): return self.doc
    def cmd_set_brush(self, params): return {'status': 'ok'}
    def _creative_new_layer(self, doc, session, params):
        # General dispatch tests use a flat tree; test_stage_groups exercises
        # actual container creation and reuse with a hierarchical document.
        return self.cmd_new_layer(params)
    def cmd_new_layer(self, params):
        self.created_layers += 1
        node = Layer('layer-' + str(self.created_layers)); self.doc.nodes.append(node); self.doc.active=node
        return {'id': node.identity}
    def cmd_select_layer(self, params): self.doc.active=self._creative_node(self.doc, params['id']); return {'status':'ok'}
    def cmd_layer_settings(self, params):
        if 'opacity' in params: self.doc.active.setOpacity(round(params['opacity']*255))
        if 'visible' in params: self.doc.active.setVisible(params['visible'])
        return {'status':'ok'}
    def cmd_curve_stroke(self, params, settle=True):
        self.settled = getattr(self, 'settled', []) + [settle]
        self.paints += 1
        if self.fail: raise RuntimeError('Brush failed after partial work')
        return {'status': 'ok'}
    def _creative_checkpoint(self, doc, session, changed=True): return {'status': 'ok', 'checkpoint': 'saved.kra'}
    def _creative_observe(self, doc, session, region=None): return {'status':'ok', 'document_id':module.document_id(doc), 'image_path':'/tmp/before.png'}
    def _creative_revision(self, doc, projection=None): return 'current-revision'


def request():
    return {'operation': 'paint_pass', 'session_id': 'session', 'operation_id': 'op-1', 'params': {
        'name': 'Field', 'preset': 'b) Basic-1', 'strokes': [{'start': [10,20],
        'segments': [[20,20,30,20,40,20]], 'size': 20, 'opacity': 1, 'flow': 1, 'color': '#112233'}]}}


class NativePolicyTests(unittest.TestCase):
    def test_a_pass_tells_a_sleeping_screen_apart_from_switching_documents(self):
        harness = Harness(); doc = harness.doc
        self.assertIsNone(harness._creative_let_krita_respond(doc, None), 'same document: the pass continues')
        harness.get_active_document = lambda: None
        stopped = harness._creative_let_krita_respond(doc, None)
        self.assertIn('lost its active window', stopped); self.assertIn('Keep the screen awake while painting', stopped)
        self.assertNotIn('switched', stopped)
        other = Document(); harness.get_active_document = lambda: other
        self.assertIn('switched to another document', harness._creative_let_krita_respond(doc, None))

    def test_live_document_id_survives_wrappers_save_as_and_cloned_layer_ids(self):
        class Wrapper(Document):
            def __init__(self, native): super().__init__(); self.native = native
            def __eq__(self, other): return isinstance(other, Wrapper) and self.native is other.native
        source = Wrapper(object()); clone = Wrapper(object())
        source_wrapper = Wrapper(source.native)
        original_instance = krita.Krita.instance
        krita.Krita.instance = lambda: types.SimpleNamespace(documents=lambda:[source, clone], activeDocument=lambda:clone)
        try:
            first = module.document_id(source)
            self.assertEqual(first, module.document_id(source_wrapper))
            self.assertEqual(source.rootNode().uniqueId().toString(), clone.rootNode().uniqueId().toString())
            self.assertNotEqual(first, module.document_id(clone))
            source_wrapper.fileName = lambda:'/new-location/renamed.kra'
            self.assertEqual(first, module.document_id(source_wrapper))
            h=Harness(); h.doc=clone
            self.assertIs(h._creative_document(first), source)
        finally: krita.Krita.instance = original_instance

    def test_open_document_inventory_includes_clone_views(self):
        source, clone = Document(), Document()
        original_instance = krita.Krita.instance
        krita.Krita.instance = lambda: types.SimpleNamespace(documents=lambda:[source], activeDocument=lambda:source,
            windows=lambda:[types.SimpleNamespace(views=lambda:[types.SimpleNamespace(document=lambda:clone)])])
        try:
            self.assertEqual(module.open_documents(), [source, clone])
        finally: krita.Krita.instance = original_instance

    def test_colour_sampling_is_read_only_and_uses_projection_pixels(self):
        h = Harness(); owner = h._creative_session
        class Colour:
            def red(self): return 192
            def green(self): return 66
            def blue(self): return 42
            def alpha(self): return 255
        h.doc.projection = lambda *args: types.SimpleNamespace(isNull=lambda:False,pixelColor=lambda x,y:Colour())
        result = h.cmd_creative({'operation':'sample_colors','params':{'points':[[120,180],[200,320]]}})
        self.assertEqual(result['samples'][0]['hex'], '#c0422a')
        self.assertEqual(result['samples'][1]['position'], [200,320])
        self.assertIs(h._creative_session, owner); self.assertEqual(h.paints, 0); self.assertEqual(h.created_layers, 0)
        for points in ([], [[-1, 0]], [[768,0]], [[1.5,2]], [[True,0]], [[0,0]]*17):
            with self.assertRaises(ValueError): h.cmd_creative({'operation':'sample_colors','params':{'points':points}})

    def test_ask_peek_never_takes_ownership_or_saves(self):
        h = Harness(); original = h._creative_session
        h._creative_observe = lambda doc, session, region=None: {'status': 'ok', 'document_id': session['document_id']}
        with tempfile.TemporaryDirectory() as root:
            identifier = str(uuid.uuid4()); destination = pathlib.Path(root) / identifier; destination.mkdir()
            result = h.cmd_creative({'operation': 'peek', 'session_id': identifier, 'params': {'output_dir': str(destination)}})
            self.assertEqual(result['document_id'], module.document_id(h.doc))
            self.assertIs(h._creative_session, original)
            self.assertEqual(h.created_layers, 0); self.assertEqual(h.paints, 0)
            h.doc = None
            result = h.cmd_creative({'operation': 'peek', 'session_id': identifier, 'params': {'output_dir': str(destination)}})
            self.assertEqual(result['message'], 'No canvas is open.')

    def test_peek_close_up_can_skip_the_recomposite(self):
        h = Harness(); sessions = []
        h._creative_observe = lambda doc, session, region=None: sessions.append((session, region)) or {'status': 'ok'}
        with tempfile.TemporaryDirectory() as root:
            identifier = str(uuid.uuid4()); destination = pathlib.Path(root) / identifier; destination.mkdir()
            peek = lambda **extra: h.cmd_creative({'operation': 'peek', 'session_id': identifier, 'params': {'output_dir': str(destination), **extra}})
            peek(); peek(region=[0, 0, 64, 64], refresh=False)
            self.assertEqual([s['projection_fresh'] for s, _ in sessions], [False, True])
            self.assertEqual(sessions[1][1], [0, 0, 64, 64])
            with self.assertRaises(ValueError): peek(refresh='no')

    def test_peek_close_ups_can_be_saved_as_jpeg(self):
        # eyes-and-history review b: the painter's close-ups are JPEG (a region view is PNG otherwise: multi-MB files).
        h = Harness(); sessions = []
        h._creative_observe = lambda doc, session, region=None: sessions.append(session) or {'status': 'ok'}
        with tempfile.TemporaryDirectory() as root:
            identifier = str(uuid.uuid4()); destination = pathlib.Path(root) / identifier; destination.mkdir()
            peek = lambda **extra: h.cmd_creative({'operation': 'peek', 'session_id': identifier, 'params': {'output_dir': str(destination), **extra}})
            peek(region=[0, 0, 64, 64], refresh=False, jpeg=True); peek(region=[0, 0, 64, 64])
            self.assertEqual([s.get('jpeg_views', False) for s in sessions], [True, False])
            with self.assertRaises(ValueError): peek(jpeg='yes')
        saved = []
        class Image:
            def hasAlphaChannel(self): return False
            def save(self, filename, kind, quality): saved.append((os.path.splitext(filename)[1], kind, quality)); return True
        module.CreativeTools._creative_save_view(h, '/previews', Image(), [0, 0, 64, 64], jpeg=True)
        module.CreativeTools._creative_save_view(h, '/previews', Image(), [0, 0, 64, 64])
        self.assertEqual(saved, [('.jpg', 'JPEG', module.VIEW_JPEG_QUALITY), ('.png', 'PNG', -1)])

    def test_successive_saves_use_one_working_file(self):
        h = Harness(); paths = []
        h.cmd_save_native = lambda p: paths.append(p['path']) or {'status': 'ok'}
        h._creative_observe = lambda doc, session: {'status': 'ok'}
        with tempfile.TemporaryDirectory() as folder:
            session = {'output': folder, 'checkpoint': 0}
            h.cmd_save_native = lambda p: paths.append(p['path']) or pathlib.Path(p['path']).touch() or {'status': 'ok'}
            first = module.CreativeTools._creative_checkpoint(h, h.doc, session)
            second = module.CreativeTools._creative_checkpoint(h, h.doc, session)
            self.assertEqual(paths, [str(pathlib.Path(folder) / 'painting.kra')] * 2)
        self.assertEqual(second['save_number'], 2)
        self.assertEqual(first['checkpoint'], second['checkpoint'])

    def test_a_checkpoint_skips_the_save_when_the_file_already_holds_the_painting(self):
        h = Harness(); paths = []
        h.cmd_save_native = lambda p: paths.append(p['path']) or {'status': 'ok'}
        h._creative_observe = lambda doc, session: {'status': 'ok'}
        with tempfile.TemporaryDirectory() as folder:
            saved = pathlib.Path(folder) / 'painting.kra'; saved.touch()
            h.doc.fileName = lambda: str(saved); h.doc.modified = lambda: False
            session = {'output': folder, 'painting_path': str(saved), 'checkpoint': 0}
            result = module.CreativeTools._creative_checkpoint(h, h.doc, session, changed=False)
            self.assertEqual(paths, [], 'an unmodified document already on disk is not written again')
            self.assertEqual((result['checkpoint'], result['save_skipped']), (str(saved.resolve()), True))
            self.assertTrue(session['saved_once']); self.assertEqual(session['unsaved_operations'], 0)
            module.CreativeTools._creative_checkpoint(h, h.doc, session)
            self.assertEqual(len(paths), 1, 'after an agent change it always saves, whatever Krita’s modified flag says')
            h.doc.modified = lambda: True
            module.CreativeTools._creative_checkpoint(h, h.doc, session, changed=False)
            self.assertEqual(len(paths), 2, 'the artist changed it: save')

    def test_a_checkpoint_waits_out_a_save_krita_is_already_making(self):
        h = Harness(); attempts = []
        busy = iter([True, True, False])                       # Krita's autosave holds the file for two tries
        h.cmd_save_native = lambda p: attempts.append(p['path']) or ({'error': 'saveAs failed: ' + p['path']} if next(busy) else {'status': 'ok'})
        h._creative_observe = lambda doc, session: {'status': 'ok'}
        waited = []
        previous = module.SAVE_RETRY_SECONDS, module.wait_for_krita
        module.SAVE_RETRY_SECONDS, module.wait_for_krita = (0, 0, 0), waited.append
        self.addCleanup(lambda: (setattr(module, 'SAVE_RETRY_SECONDS', previous[0]), setattr(module, 'wait_for_krita', previous[1])))
        with tempfile.TemporaryDirectory() as folder:
            session = {'output': folder, 'painting_path': os.path.join(folder, 'painting.kra'), 'checkpoint': 0}
            pathlib.Path(session['painting_path']).touch()        # the fake save writes nothing
            result = module.CreativeTools._creative_checkpoint(h, h.doc, session)
            self.assertEqual(len(attempts), 3, 'two refusals while Krita saves, then the save')
            self.assertEqual(waited, [0, 0], 'Krita runs its own events between tries, so its save can finish')
            self.assertEqual(result['checkpoint'], session['painting_path'])
            busy = iter([True] * 10)
            with self.assertRaisesRegex(RuntimeError, 'saveAs failed'):
                module.CreativeTools._creative_checkpoint(h, h.doc, session)

    def test_a_pass_waits_and_redraws_once_not_after_every_stroke(self):
        h = Harness(); events = []
        h.doc.waitForDone = lambda: events.append('wait')
        h.doc.refreshProjection = lambda: events.append('refresh')
        h.doc.setSelection = lambda value: events.append('selection')
        h._creative_checkpoint = lambda doc, session: {'status': 'ok'}
        params = request()['params']; params['strokes'] = params['strokes'] * 5
        h._creative_session['passes'] = []
        h.cmd_creative(dict(request(), params=params))
        self.assertEqual(h.settled, [False] * 5, 'strokes leave the wait and redraw to the pass')
        first, last = events.index('selection'), len(events) - 1 - events[::-1].index('selection')
        self.assertEqual(events[last - 1], 'wait', 'every stroke finishes before the artist\'s selection comes back')
        self.assertEqual(events[last + 1], 'refresh')
        self.assertEqual(events[first:last + 2].count('refresh'), 1, 'one redraw for the whole pass')

    def test_with_the_native_helper_a_pass_paints_in_one_call_and_still_waits_and_redraws_once(self):
        h = Harness(); events = []; sent = []
        h.doc.waitForDone = lambda: events.append('wait')
        h.doc.refreshProjection = lambda: events.append('refresh')
        h._creative_checkpoint = lambda doc, session: {'status': 'ok'}
        h._creative_session['passes'] = []
        accel = types.ModuleType('creative_test_package.agent_accel'); accel.NATIVE_STROKES = True
        accel.paint_strokes = lambda path, layer_id, strokes, defaults, stop=None: sent.append((layer_id, len(strokes), defaults)) or \
            {'strokes': len(strokes), 'jobs': 1, 'groups': 1, 'ms': 4}
        prior = sys.modules.get(accel.__name__); sys.modules[accel.__name__] = accel; package.agent_accel = accel
        def restore():                                   # `from . import` falls back to the package attribute: remove both
            if prior: sys.modules[accel.__name__] = prior; package.agent_accel = prior
            else: sys.modules.pop(accel.__name__, None); package.__dict__.pop('agent_accel', None)
        self.addCleanup(restore)
        params = request()['params']; params['strokes'] = params['strokes'] * 5
        result = h.cmd_creative(dict(request(), params=params))
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(getattr(h, 'settled', []), [], 'no stroke went through the Python API')
        self.assertEqual([(n, set(d)) for _id, n, d in sent], [(5, {'size', 'opacity'})])
        self.assertEqual(result['native_strokes']['strokes'], 5)
        self.assertEqual(events.count('refresh'), 1, 'one redraw for the whole pass')
        self.assertLess(events.index('wait'), events.index('refresh'), 'Krita finishes the queued strokes before the redraw')

    def _pumping(self, h, on_pump):
        """Run every stroke's event pump through on_pump(count) instead of waiting 0.2 s."""
        calls = []
        saved = module.RESPONSIVE_SECONDS, module.QCoreApplication.processEvents
        module.RESPONSIVE_SECONDS = 0
        module.QCoreApplication.processEvents = lambda: calls.append(1) or on_pump(len(calls))
        self.addCleanup(lambda: (setattr(module, 'RESPONSIVE_SECONDS', saved[0]), setattr(module.QCoreApplication, 'processEvents', saved[1]),
                                 module.stop_requested.clear()))
        h._creative_checkpoint = lambda doc, session: {'status': 'ok'}
        h._creative_session['passes'] = []
        params = request()['params']; params['strokes'] = params['strokes'] * 6
        return dict(request(), params=params)

    def test_stop_in_krita_refuses_the_next_action_before_anything_is_recorded(self):
        h = Harness(); self.addCleanup(module.stop_requested.clear)
        module.stop_requested.set()
        result = h.cmd_creative(request())
        self.assertEqual(result['error_code'], 'stopped_by_artist')
        self.assertEqual(h.paints, 0); self.assertEqual(h.created_layers, 0)
        self.assertEqual(h._creative_session['operations'], {}, 'no intent: the action never started, so nothing is uncertain')
        module.stop_requested.clear()
        self.assertEqual(h.cmd_creative(request())['status'], 'ok', 'the same action runs once the stop is over')

    def test_stop_during_a_stroke_pass_ends_it_after_the_current_stroke_as_a_definite_pass(self):
        h = Harness(); events = []
        h.doc.waitForDone = lambda: events.append('wait')
        call = self._pumping(h, lambda count: count == 2 and module.stop_requested.set())   # the click lands during stroke 2
        result = h.cmd_creative(call)
        self.assertEqual(h.paints, 2)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual((result['stopped_after_strokes'], result['strokes_total']), (2, 6))
        self.assertIn('wait', events, 'painted strokes finish before the selection comes back')
        self.assertEqual(h._creative_session['operations']['op-1'][1]['status'], 'ok', 'recorded as done, never repainted')

    def test_a_click_on_another_layer_mid_pass_does_not_redirect_strokes(self):
        h = Harness()
        other = Layer('artist-layer')
        call = self._pumping(h, lambda count: setattr(h.doc, 'active', other))
        result = h.cmd_creative(call)
        self.assertEqual(h.paints, 6); self.assertNotIn('stopped', result)
        self.assertEqual(h.doc.active.identity, 'layer-1', 'the painting layer is active again after every pump')

    def test_switching_documents_mid_pass_ends_the_pass(self):
        h = Harness()
        elsewhere = Document(); elsewhere.identity = 'another-document'
        # The artist brings another document to the front during stroke 3; the pass keeps its own.
        call = self._pumping(h, lambda count: count == 3 and setattr(h, 'doc', elsewhere))
        result = h.cmd_creative(call)
        self.assertEqual(h.paints, 3)
        self.assertIn('another document', result['stopped'])

    def test_painting_actions_save_by_time_not_by_count(self):
        # Runs 5-8 on merged New Moscow: 12 saves of 5-6.5 s each, every 8 reference chunks, were 26% of all time.
        h = Harness(); paths = []; clock = [1000.0]
        h.cmd_save_native = lambda p: paths.append(p['path']) or pathlib.Path(p['path']).touch() or {'status': 'ok'}
        h._creative_observe = lambda doc, session: {'status': 'ok', 'image_path': 'view.png'}
        h._creative_checkpoint = lambda doc, session: module.CreativeTools._creative_checkpoint(h, doc, session)
        previous = module.time.monotonic; module.time.monotonic = lambda: clock[0]
        self.addCleanup(setattr, module.time, 'monotonic', previous)
        with tempfile.TemporaryDirectory() as folder:
            session = {'output': folder, 'checkpoint': 0}
            views = [module.CreativeTools._creative_commit_view(h, h.doc, session) for _ in range(40)]
            self.assertEqual(len(paths), 1, 'the first action saves; forty quick actions after it do not')
            self.assertTrue(views[-1]['checkpoint_deferred']); self.assertEqual(views[-1]['unsaved_operations'], 39)
            clock[0] += module.CHECKPOINT_SECONDS
            self.assertIn('checkpoint', module.CreativeTools._creative_commit_view(h, h.doc, session))
        self.assertEqual(len(paths), 2, 'then one save once CHECKPOINT_SECONDS have passed')
        self.assertEqual(session['unsaved_operations'], 0)
        self.assertLessEqual(module.CHECKPOINT_SECONDS, 300, 'a crash loses at most a few minutes of the agent’s painting')
        self.assertFalse(hasattr(module, 'CHECKPOINT_EVERY'))

    def test_saves_follow_the_user_file_and_save_as(self):
        h = Harness(); paths = []
        h.cmd_save_native = lambda p: paths.append(p['path']) or {'status': 'ok'}
        h._creative_observe = lambda doc, session: {'status': 'ok'}
        with tempfile.TemporaryDirectory() as folder:
            original = pathlib.Path(folder)/'painting.kra'; moved = pathlib.Path(folder)/'new-location.kra'; moved.touch()
            h.doc.fileName = lambda: str(moved)
            session = {'output': folder, 'painting_path': str(original), 'checkpoint': 0}
            module.CreativeTools._creative_checkpoint(h, h.doc, session)
            module.CreativeTools._creative_checkpoint(h, h.doc, session)
            self.assertEqual(paths, [str(original), str(moved.resolve())])

    def test_context_is_read_only_for_unsaved_canvas(self):
        h = Harness(); owner = h._creative_session
        result = h.cmd_creative({'operation':'context','params':{}})
        self.assertTrue(result['modified']); self.assertEqual(result['filename'], '')
        self.assertEqual(result['document_id'], module.document_id(h.doc))
        self.assertIs(owner, h._creative_session); self.assertEqual(h.created_layers, 0)

    def test_resume_binds_without_native_save(self):
        h = Harness(); h._creative_session = None; saves=[]
        h._creative_checkpoint = lambda *args: saves.append(True)
        with tempfile.TemporaryDirectory() as folder:
            identifier=str(uuid.uuid4()); destination=pathlib.Path(folder)/identifier; destination.mkdir()
            painting=pathlib.Path(folder)/'painting.kra'; painting.touch()
            h.doc.fileName=lambda: str(painting)
            result=h.cmd_creative({'operation':'begin','session_id':identifier,'params':{
                'mode':'resume','name':'Existing','output_dir':str(destination),'painting_path':str(painting)}})
            self.assertEqual(result['session_id'],identifier); self.assertEqual(saves,[])

    def test_current_mode_uses_same_saved_or_unsaved_document(self):
        for saved in (False, True):
            h=Harness(); h._creative_session=None; original=h.doc
            with tempfile.TemporaryDirectory() as folder:
                identifier=str(uuid.uuid4()); destination=pathlib.Path(folder)/identifier; destination.mkdir()
                painting=pathlib.Path(folder)/'painting.kra'
                if saved:
                    painting.touch(); h.doc.fileName=lambda: str(painting)
                result=h.cmd_creative({'operation':'begin','session_id':identifier,'params':{
                    'mode':'current','name':'Current','output_dir':str(destination),'painting_path':str(painting),
                    'source_document_id':module.document_id(h.doc)}})
                self.assertEqual(result['status'],'ok'); self.assertIs(h.doc,original)
                self.assertEqual(h.created_layers,0)
                self.assertEqual(h._creative_session['painting_path'],str(painting.resolve()))

    def test_a_session_pauses_krita_autosave_on_its_painting_and_restores_it(self):
        for before in (True, False):
            h=Harness(); h._creative_session=None; states=[]
            h.doc.autosave=lambda: before
            h.doc.setAutosave=states.append
            h._creative_document=lambda identifier=None: h.doc
            with tempfile.TemporaryDirectory() as folder:
                identifier=str(uuid.uuid4()); destination=pathlib.Path(folder)/identifier; destination.mkdir()
                painting=pathlib.Path(folder)/'painting.kra'; painting.touch(); h.doc.fileName=lambda: str(painting)
                h.cmd_creative({'operation':'begin','session_id':identifier,'params':{
                    'mode':'current','name':'Current','output_dir':str(destination),'painting_path':str(painting),
                    'source_document_id':module.document_id(h.doc)}})
                self.assertEqual(states,[False],'the agent checkpoints every operation; Krita\u2019s autosave would stall it')
                h.cmd_creative({'operation':'end','session_id':identifier,'params':{}})
                self.assertEqual(states,[False,before],'the artist\u2019s own state comes back')

    def test_manual_change_rejected_before_mutation(self):
        h=Harness(); p=request(); p['params']['expected_revision']='stale'
        result=h.cmd_creative(p)
        self.assertEqual(result['error_code'],'canvas_changed'); self.assertEqual(h.paints,0)

    def test_disappeared_file_never_recreated_or_painted(self):
        h=Harness(); h._creative_session.update(saved_once=True,painting_path='/nonexistent/old/painting.kra')
        with self.assertRaisesRegex(ValueError,'will not be recreated'): h.cmd_creative(request())
        self.assertEqual(h.paints,0)

    def test_region_clips_brush_and_restores_selection(self):
        h=Harness(); original=Selection(); h.doc.selected=original
        p=request(); p['params']['region']=[100,150,580,330]
        h.cmd_creative(p)
        stage=h.doc.selection_changes[0]
        self.assertEqual(stage.bounds,(100,150,580,330))
        self.assertEqual(len(stage.data),580*330)
        self.assertEqual(stage.data[165*580+290],255)
        self.assertLess(stage.data[290],16,'the inner edge fades in: a hard 255 rectangle printed a straight band (fork chat, 19 October)')
        self.assertIs(h.doc.selected,original)

    def test_review_preserves_other_artist_layers(self):
        h=Harness(); h.cmd_creative(request()); artist=Layer('artist'); artist.pixels=b'later artwork'; h.doc.nodes.append(artist)
        result=h.cmd_creative({'operation':'review_pass','session_id':'session','operation_id':'review-1',
            'params':{'pass_id':'op-1','action':'reject'}})
        self.assertFalse(h.doc.nodes[0].visible()); self.assertTrue(artist.visible()); self.assertEqual(artist.pixels,b'later artwork')
        replay=h.cmd_creative({'operation':'review_pass','session_id':'session','operation_id':'review-1',
            'params':{'pass_id':'op-1','action':'reject'}})
        self.assertTrue(replay['replayed'])

    def test_review_refuses_to_hide_later_paint_on_same_layer(self):
        h=Harness(); h.cmd_creative(request()); h.doc.nodes[0].pixels=b'artist added details'
        with self.assertRaisesRegex(ValueError,'newer artist changes'):
            h.cmd_creative({'operation':'review_pass','session_id':'session','operation_id':'review-1',
                'params':{'pass_id':'op-1','action':'reject'}})
        self.assertTrue(h.doc.nodes[0].visible())

    def test_adjust_layer_cannot_escape_stage_region(self):
        h=Harness(); p=request(); p['params']['region']=[100,600,580,250]; h.cmd_creative(p)
        with self.assertRaisesRegex(ValueError,'beyond the current stage'):
            h.cmd_creative({'operation':'adjust_layer','session_id':'session','operation_id':'adjust',
                'params':{'layer_id':'layer-1','opacity':0.1,'region':[100,150,580,330]}})
        self.assertEqual(h.doc.nodes[0].opacity(),255)

    def test_adjustment_captures_fresh_manual_baseline_and_reject_restores_it(self):
        h=Harness(); h.cmd_creative(request()); h.doc.nodes[0].pixels=b'later artist work'
        h.cmd_creative({'operation':'adjust_layer','session_id':'session','operation_id':'adjust',
            'params':{'layer_id':'layer-1','visible':False,'expected_revision':'current-revision'}})
        h.cmd_creative({'operation':'review_pass','session_id':'session','operation_id':'reject-adjust',
            'params':{'pass_id':'adjust','action':'reject'}})
        self.assertTrue(h.doc.nodes[0].visible())
        self.assertEqual(h.doc.nodes[0].pixels,b'later artist work')

    def test_recorded_layer_adjustment_is_reversible(self):
        h=Harness(); h.cmd_creative(request())
        h.cmd_creative({'operation':'adjust_layer','session_id':'session','operation_id':'adjust',
            'params':{'layer_id':'layer-1','opacity':0.2}})
        self.assertEqual(h.doc.nodes[0].opacity(),51)
        h.cmd_creative({'operation':'review_pass','session_id':'session','operation_id':'reject-adjust',
            'params':{'pass_id':'adjust','action':'reject'}})
        self.assertEqual(h.doc.nodes[0].opacity(),255)

    def test_uncertain_result_blocks_new_ids_until_explicit_reconciliation(self):
        h=Harness(); h.fail=True; h.cmd_creative(request()); second=request(); second['operation_id']='op-2'
        result=h.cmd_creative(second)
        self.assertEqual(result['error_code'],'outcome_unknown'); self.assertEqual(h.paints,1)
        with self.assertRaises(ValueError):
            h.cmd_creative({'operation':'reconcile','session_id':'session','params':{}})
        stale=h.cmd_creative({'operation':'reconcile','session_id':'session','params':{'expected_revision':'stale'}})
        self.assertEqual(stale['error_code'],'canvas_changed')
        ready=h.cmd_creative({'operation':'reconcile','session_id':'session','params':{'expected_revision':'current-revision'}})
        self.assertEqual(ready['unresolved_operations'],[]); self.assertEqual(h.paints,1)
        h.fail=False; h.cmd_creative(second); self.assertEqual(h.paints,2)

    def test_resume_restores_uncertain_operation_guard(self):
        h=Harness(); h.fail=True
        with tempfile.TemporaryDirectory() as folder:
            identifier=str(uuid.uuid4()); destination=pathlib.Path(folder)/identifier; destination.mkdir()
            painting=pathlib.Path(folder)/'painting.kra'; painting.touch(); h.doc.fileName=lambda:str(painting)
            h._creative_session.update(id=identifier,output=str(destination))
            p=request(); p['session_id']=identifier; h.cmd_creative(p)
            h._creative_session=None
            result=h.cmd_creative({'operation':'begin','session_id':identifier,'params':{
                'mode':'resume','name':'Existing','output_dir':str(destination),'painting_path':str(painting)}})
            self.assertEqual(result['unresolved_operations'],['op-1'])
            p['operation_id']='new-attempt'; refused=h.cmd_creative(p)
            self.assertEqual(refused['error_code'],'outcome_unknown'); self.assertEqual(h.paints,1)

    def test_replay_uses_logical_arguments_not_freshness_precondition(self):
        h=Harness(); p=request(); p['params']['expected_revision']='current-revision'; h.cmd_creative(p)
        p['params']['expected_revision']='different-snapshot'
        replay=h.cmd_creative(p)
        self.assertTrue(replay['replayed']); self.assertEqual(h.paints,1)

    def test_duplicate_call_does_not_repaint(self):
        h = Harness(); first = h.cmd_creative(request()); second = h.cmd_creative(request())
        self.assertEqual(h.paints, 1); self.assertEqual(h.created_layers, 1)
        self.assertTrue(second['replayed']); self.assertEqual(first['checkpoint'], second['checkpoint'])

    def test_reused_id_with_different_arguments_rejected(self):
        h = Harness(); h.cmd_creative(request()); other = request(); other['params']['name'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'different'): h.cmd_creative(other)
        self.assertEqual(h.paints, 1)

    def test_wrong_document_rejected_before_any_mutation(self):
        h = Harness(); h.doc = Document()  # Clones can retain all layer UUIDs.
        result = h.cmd_creative(request())
        self.assertEqual(result['error_code'], 'document_changed')
        self.assertEqual(h.created_layers, 0)

    def test_unknown_parameter_is_not_silently_ignored(self):
        h = Harness(); other = request(); other['params']['brush'] = 'Wrong'
        with self.assertRaisesRegex(ValueError, 'Unknown parameters'): h.cmd_creative(other)
        self.assertEqual(h.created_layers, 0)

    def test_entire_batch_validated_before_first_stroke(self):
        h = Harness(); other = request(); other['params']['strokes'].append({
            **other['params']['strokes'][0], 'start': [9999, 20]})
        with self.assertRaises(ValueError): h.cmd_creative(other)
        self.assertEqual(h.paints, 0); self.assertEqual(h.created_layers, 0)

    def test_strokes_may_start_up_to_one_brush_size_off_the_canvas(self):
        validation = sys.modules['creative_test_package.creative_validation']
        stroke = {'start': [-150, -60], 'segments': [[2000, -60, 4000, 0, 6150, 70]], 'size': 560, 'opacity': 1, 'flow': 1, 'color': '#0a1026'}
        params = {'name': 'Sky', 'preset': 'b) Basic-1', 'strokes': [stroke]}
        self.assertIs(validation.validate_pass(params, 6000, 4500, ['b) Basic-1']), params, 'edge-to-edge strokes start off the canvas')
        for start in ([-561, 0], [0, 4500 + 561]):
            with self.assertRaisesRegex(ValueError, 'coordinate'):
                validation.validate_pass({**params, 'strokes': [{**stroke, 'start': start}]}, 6000, 4500, ['b) Basic-1'])

    def test_pressure_has_one_value_per_point_between_0_and_1(self):
        validation = sys.modules['creative_test_package.creative_validation']
        stroke = {'start': [10, 20], 'segments': [[20, 20, 30, 20, 40, 20], [50, 20, 60, 20, 70, 20]], 'size': 20, 'opacity': 1, 'flow': 1,
                  'color': '#112233', 'pressure': [0.1, 1, 0.3]}
        params = {'name': 'Taper', 'preset': 'b) Basic-1', 'strokes': [stroke]}
        self.assertIs(validation.validate_pass(params, 600, 450, ['b) Basic-1']), params)
        for pressure in ([0.1], [0.1, 1, 0.3, 0.5], [0.1, 1.2, 0.3], [0.1, True, 0.3], 0.5):
            with self.assertRaisesRegex(ValueError, 'pressure'):
                validation.validate_pass({**params, 'strokes': [{**stroke, 'pressure': pressure}]}, 600, 450, ['b) Basic-1'])

    def test_pen_lists_take_one_value_per_segment_too_resampled_by_repeating_the_first(self):
        # A traced painter sent one pressure per segment four times and each batch failed (after-the-underpainting goal 5).
        validation = sys.modules['creative_test_package.creative_validation']
        stroke = {'start': [10, 20], 'segments': [[20, 20, 30, 20, 40, 20], [50, 20, 60, 20, 70, 20], [80, 20, 90, 20, 99, 20]],
                  'size': 20, 'opacity': 1, 'flow': 1, 'color': '#112233', 'pressure': [0.4, 1, 0.2], 'tilt': [[10, 0], [20, 0], [30, 0]],
                  'rotation': [5, 6, 7], 'speed': [0.1, 0.2, 0.3], 'time_ms': [40, 80, 120]}
        params = {'name': 'Per segment', 'preset': 'b) Basic-1', 'strokes': [stroke]}
        validation.validate_pass(params, 600, 450, ['b) Basic-1'])
        painted = params['strokes'][0]
        self.assertEqual(painted['pressure'], [0.4, 0.4, 1, 0.2], 'the start takes the first segment\'s value')
        self.assertEqual(painted['tilt'], [[10, 0], [10, 0], [20, 0], [30, 0]])
        self.assertEqual((painted['rotation'], painted['speed'], painted['time_ms']), ([5, 5, 6, 7], [0.1, 0.1, 0.2, 0.3], [0, 40, 80, 120]),
                         'time starts at 0: the stroke begins at its start')
        one = {**stroke, 'segments': stroke['segments'][:1], 'pressure': [0.6]}
        for name in ('tilt', 'rotation', 'speed', 'time_ms'):
            one.pop(name)
        validation.validate_pass({**params, 'strokes': [one]}, 600, 450, ['b) Basic-1'])
        self.assertEqual(one['pressure'], [0.6, 0.6], 'one segment, one value')
        for wrong in ([0.5, 0.5], [0.5] * 5):
            with self.assertRaisesRegex(ValueError, r'pressure needs 4 values \(the start and each of the 3 segment ends\) or 3 \(one per segment\); this stroke has %d' % len(wrong)):
                validation.validate_pass({**params, 'strokes': [{**stroke, 'pressure': wrong}]}, 600, 450, ['b) Basic-1'])

    def test_tilt_rotation_speed_and_time_have_one_value_per_point_in_krita_s_ranges(self):
        validation = sys.modules['creative_test_package.creative_validation']
        stroke = {'start': [10, 20], 'segments': [[20, 20, 30, 20, 40, 20], [50, 20, 60, 20, 70, 20]], 'size': 20, 'opacity': 1, 'flow': 1,
                  'color': '#112233', 'tilt': [[0, 0], [30, -60], [60, 10.5]], 'rotation': [-180, 0, 180], 'speed': [0, 0.5, 1],
                  'time_ms': [0, 120, 120]}
        params = {'name': 'Pen', 'preset': 'b) Basic-1', 'strokes': [stroke]}
        self.assertIs(validation.validate_pass(params, 600, 450, ['b) Basic-1']), params)
        wrong = {'tilt': ([[0, 0]], [[0, 0], [61, 0], [0, 0]], [[0, 0], [0], [0, 0]], [0, 0, 0], [[0, 0], [True, 0], [0, 0]]),
                 'rotation': ([0], [0, 181, 0], [0, 'a', 0]),
                 'speed': ([0, 1, 1, 1], [0, 1.5, 0], [-0.1, 0, 0]),
                 'time_ms': ([0], [0, -1, 2], [0, 200, 100], [0, 10, 3600001])}
        for name, values in wrong.items():
            for value in values:
                with self.assertRaisesRegex(ValueError, name, msg='%s %r' % (name, value)):
                    validation.validate_pass({**params, 'strokes': [{**stroke, name: value}]}, 600, 450, ['b) Basic-1'])

    def test_a_pass_with_any_pen_input_paints_through_the_helper_and_reports_each(self):
        sent = self._helper()
        h = Harness(); h._creative_checkpoint = lambda doc, session: {'status': 'ok'}; h._creative_session['passes'] = []
        params = request()['params']; params['strokes'] = [dict(params['strokes'][0], tilt=[[0, 0], [40, 0]], speed=[0, 1])]
        result = h.cmd_creative(dict(request(), params=params))
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual((len(sent), h.paints), (1, 0), 'tilt alone is reason enough to paint natively')
        self.assertEqual((result['tilt'], result['speed']), ('applied', 'applied'))
        self.assertFalse({'pressure', 'rotation', 'time_ms'} & set(result), 'only the inputs the pass gave are reported')

    def test_without_the_helper_pen_inputs_are_reported_ignored_and_the_pass_still_paints(self):
        self._helper(paints=False)
        h = Harness(); h._creative_checkpoint = lambda doc, session: {'status': 'ok'}; h._creative_session['passes'] = []
        params = request()['params']; params['strokes'] = [dict(params['strokes'][0], rotation=[0, 90], time_ms=[0, 300])]
        result = h.cmd_creative(dict(request(), params=params))
        self.assertEqual((result['status'], h.paints), ('ok', 1))
        self.assertIn('ignored', result['rotation']); self.assertIn('ignored', result['time_ms'])

    def test_without_the_helper_the_python_path_gets_strokes_without_pen_inputs(self):
        # precision_tools.cmd_curve_stroke refuses a stroke with pressure: the pass hands it the curve alone.
        self._helper(paints=False)
        h = Harness(); h._creative_checkpoint = lambda doc, session: {'status': 'ok'}; h._creative_session['passes'] = []
        given, real = [], h.cmd_curve_stroke
        h.cmd_curve_stroke = lambda params, settle=True: given.append(params) or real(params, settle)
        params = request()['params']
        params['strokes'] = [dict(params['strokes'][0], pressure=[0.2, 0.8], tilt=[[0, 0], [40, 0]], rotation=[0, 9], speed=[0, 1], time_ms=[0, 9])]
        result = h.cmd_creative(dict(request(), params=params))
        self.assertEqual((result['status'], h.paints), ('ok', 1), result.get('error'))
        self.assertEqual(set(given[0]), {'start', 'segments', 'size', 'opacity', 'flow', 'color'})

    def test_an_older_helper_applies_pressure_and_reports_the_rest_ignored(self):
        sent = self._helper()
        stub = package.agent_accel
        stub.paint_strokes = lambda path, layer_id, strokes, defaults, stop=None: (sent.append(strokes) or
            {'strokes': len(strokes), 'jobs': 1, 'groups': 1, 'ms': 4, 'ignored': ['tilt']})
        h = Harness(); h._creative_checkpoint = lambda doc, session: {'status': 'ok'}; h._creative_session['passes'] = []
        params = request()['params']; params['strokes'] = [dict(params['strokes'][0], pressure=[0.2, 0.8], tilt=[[0, 0], [40, 0]])]
        result = h.cmd_creative(dict(request(), params=params))
        self.assertEqual(result['pressure'], 'applied')
        self.assertIn('ignored', result['tilt']); self.assertIn('protocol 5', result['tilt'])

    def test_the_pen_probe_measures_one_input_and_refuses_others(self):
        calls = []
        self._helper()
        package.agent_accel.pen_compare = lambda doc, plugin, field, preset=None, size=60, image=None: (
            calls.append((field, preset, size, image)) or {'helper': True, 'input': field})
        h = Harness(); h._creative_session = None
        result = h.cmd_creative({'operation': 'pen_probe', 'params': {'input': 'tilt', 'size': 40}})
        self.assertEqual((result['status'], calls), ('ok', [('tilt', None, 40.0, None)]))
        for params in ({'input': 'colour'}, {}, {'input': 'speed', 'wobble': 1}):
            with self.assertRaises(ValueError):
                h.cmd_creative({'operation': 'pen_probe', 'params': params})
        h._creative_session = {'id': 'chat'}
        with self.assertRaisesRegex(ValueError, 'session'):
            h.cmd_creative({'operation': 'pen_probe', 'params': {'input': 'speed'}})

    def _helper(self, paints=True):
        """A stand-in native helper with the stroke path off, as shipped; paints=False is Krita without it."""
        sent = []
        accel = types.ModuleType('creative_test_package.agent_accel'); accel.NATIVE_STROKES = False
        accel.paint_strokes = lambda path, layer_id, strokes, defaults, stop=None: (sent.append(strokes) or
            {'strokes': len(strokes), 'jobs': 1, 'groups': 1, 'ms': 4}) if paints else None
        prior = sys.modules.get(accel.__name__); sys.modules[accel.__name__] = accel; package.agent_accel = accel
        def restore():
            if prior: sys.modules[accel.__name__] = prior; package.agent_accel = prior
            else: sys.modules.pop(accel.__name__, None); package.__dict__.pop('agent_accel', None)
        self.addCleanup(restore)
        return sent

    def _pressure_pass(self):
        h = Harness(); h._creative_checkpoint = lambda doc, session: {'status': 'ok'}; h._creative_session['passes'] = []
        params = request()['params']; params['strokes'] = [dict(params['strokes'][0], pressure=[0.2, 0.8])]
        return h, h.cmd_creative(dict(request(), params=params))

    def test_a_pass_with_pressure_paints_through_the_helper_even_with_its_stroke_path_off(self):
        sent = self._helper()
        h, result = self._pressure_pass()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(len(sent), 1); self.assertEqual(h.paints, 0, 'no stroke went through the Python API')
        self.assertEqual(result['pressure'], 'applied')

    def test_without_the_helper_pressure_is_reported_ignored_and_the_pass_still_paints(self):
        self._helper(paints=False)
        h, result = self._pressure_pass()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(h.paints, 1)
        self.assertIn('ignored', result['pressure'])

    def test_a_pass_without_pressure_stays_on_the_python_path(self):
        sent = self._helper()
        h = Harness(); h._creative_checkpoint = lambda doc, session: {'status': 'ok'}; h._creative_session['passes'] = []
        result = h.cmd_creative(request())
        self.assertEqual((sent, h.paints), ([], 1)); self.assertNotIn('pressure', result)

    def test_baked_in_seam_candidates_are_found_once_and_carried_by_every_look(self):
        h = Harness(); calls = []
        h._creative_seam_candidates = lambda doc, session: calls.append(1) or [{'axis': 'h', 'at': 900, 'from': 0, 'to': 2400, 'crop': '/s/.seams/0.jpg'}]
        observe = lambda **params: h.cmd_creative({'operation': 'observe', 'session_id': 'session', 'params': params})
        self.assertEqual(observe()['seam_candidates'][0]['at'], 900)
        self.assertEqual(observe()['seam_candidates'][0]['at'], 900, 'every whole look carries them: the studio looks before the painter does')
        self.assertEqual(observe(region=[0, 0, 2, 2])['seam_candidates'][0]['at'], 900, 'region looks too: run 15 looked only at regions')
        self.assertEqual(len(calls), 1, 'found once a chat')

    def test_partial_failure_is_checkpointed_and_never_retried(self):
        h = Harness(); h.fail = True; first = h.cmd_creative(request()); second = h.cmd_creative(request())
        self.assertEqual(first['status'], 'partial'); self.assertEqual(first['error_code'], 'partial_change')
        self.assertEqual(first['checkpoint'], 'saved.kra'); self.assertEqual(h.paints, 1)
        self.assertTrue(second['replayed'])

    def test_another_session_cannot_take_over(self):
        h = Harness(); other = request(); other['session_id'] = 'other'
        with self.assertRaisesRegex(ValueError, 'does not own'): h.cmd_creative(other)
        self.assertEqual(h.paints, 0)

    def test_unknown_layers_cannot_be_modified(self):
        h = Harness()
        with self.assertRaisesRegex(ValueError, 'no longer'):
            h.cmd_creative({'operation': 'adjust_layer', 'session_id': 'session', 'operation_id': 'other',
                            'params': {'layer_id': 'original', 'opacity': .1}})

    def test_existing_layer_adjustment_and_reversal(self):
        h=Harness(); h.doc.nodes.append(Layer('original'))
        h.cmd_creative({'operation':'adjust_layer','session_id':'session','operation_id':'adjust',
            'params':{'layer_id':'original','opacity':.3}})
        self.assertEqual(h.doc.nodes[0].opacity(),76)
        h.cmd_creative({'operation':'review_pass','session_id':'session','operation_id':'reject',
            'params':{'pass_id':'adjust','action':'reject'}})
        self.assertEqual(h.doc.nodes[0].opacity(),255)

    def test_broad_brush_and_larger_pass(self):
        h=Harness(); p=request(); p['params']['strokes'][0]['size']=1200
        p['params']['strokes'] *= 24
        h.cmd_creative(p)
        self.assertEqual(h.paints,24)

    def test_unknown_toolbox_command_rejected_before_creating_layer(self):
        h=Harness()
        with self.assertRaisesRegex(ValueError,'Unknown painting tool'):
            h.cmd_creative({'operation':'painting_toolbox','session_id':'session','operation_id':'tool',
                'params':{'name':'test','commands':[{'tool':'open_file','parameters_json':'{}'}]}})
        self.assertEqual(h.created_layers,0)
        self.assertFalse(h._creative_session['operations'])


class FakeRect:
    def __init__(self, x, y, w, h): self.box = (x, y, w, h)
    def x(self): return self.box[0]
    def y(self): return self.box[1]
    def width(self): return self.box[2]
    def height(self): return self.box[3]


class FakeJob:
    """libkis StrokeJob under the real constraint: Krita's feeder paints one window of strokes only when the event loop
    runs (ForkHarness.pump, called from the patched processEvents); wait() never paints anything by itself.
    krita_stops_after: Krita ends the job itself once that many strokes are painted (the artist's Undo, the document
    closing). stuck: the job never advances."""
    def __init__(self, owner, layer, total, error='', krita_stops_after=None, window=2, stuck=False):
        self.owner, self.layer, self.total, self.error, self.window, self.stuck = owner, layer, total, error, window, stuck
        self.done, self.cancels, self.waits, self.krita_stops_after = 0, 0, [], krita_stops_after
        self.final = 'failed' if error else None
    def pump(self):
        if self.final: return
        if self.stuck and not self.cancels: return
        limit = self.total if self.krita_stops_after is None else self.krita_stops_after
        if self.cancels:
            self.final = 'cancelled'
        else:
            self.done = min(limit, self.done + self.window)
            if self.done >= limit:
                self.final = 'done' if limit == self.total else 'cancelled'
        if self.final:
            if self.done: self.owner.doc.land('Agent: ' + self.layer.name())      # the held step lands with the last stroke
            if self.final == 'cancelled' and not self.cancels and self.owner.undo_lands: self.owner.undo_next = True
    def state(self): return self.final or ('running' if self.done else 'queued')
    def strokesDone(self): return self.done
    def strokesTotal(self): return self.total
    def changedRect(self): return FakeRect(30, 40, 50, 60) if self.done else FakeRect(0, 0, 0, 0)
    def errorString(self): return self.error
    def elapsedMs(self): return 7
    def wait(self, timeout_ms=-1):
        self.waits.append(timeout_ms)
        return self.final is not None
    def cancel(self):
        self.cancels += 1
        return self.final is None


class FakeReasonJob(FakeJob):
    """The fork's later cancel reason."""
    reason = 'undo'
    def cancelReason(self): return 'script' if self.cancels else self.reason


class JobLayer(Layer):
    """A fork layer: it has Node.paintStrokes and remove()."""
    def __init__(self, identity, owner):
        super().__init__(identity); self.owner = owner
    def paintStrokes(self, strokes, options=None, selection=None):
        owner = self.owner
        owner.events.append('paintStrokes')
        owner.job_calls.append((strokes, options, selection, self))
        cls = FakeReasonJob if owner.job_reason else FakeJob
        owner.job = cls(owner, self, len(strokes), owner.job_error, owner.krita_stops_after, stuck=owner.job_stuck)
        if owner.job_reason: owner.job.reason = owner.job_reason
        return owner.job
    def remove(self):
        self.owner.doc.nodes.remove(self); return True


class NoStrokesLayer(Layer):
    pass


class ForkDocument(Document):
    """Undo history as libkis exposes it: steps, and the number applied."""
    def __init__(self): super().__init__(); self.steps = ['Earlier'] * 5; self.index = 5
    def undoIndex(self): return self.index
    def undoCount(self): return len(self.steps)
    def undoText(self, i): return self.steps[i]
    def land(self, name): del self.steps[self.index:]; self.steps.append(name); self.index += 1


class ForkHarness(Harness):
    def __init__(self):
        super().__init__(); self.doc = ForkDocument(); self._creative_session['document_id'] = module.document_id(self.doc)
        self.job_calls, self.job, self.job_error, self.krita_stops_after, self.brushes = [], None, '', None, 0
        self.job_stuck, self.job_reason, self.undo_lands, self.undo_next, self.events = False, None, True, False, []
        self.layer_class = JobLayer
        self._creative_checkpoint = lambda doc, session: self.events.append('checkpoint@%d' % doc.index) or {'status': 'ok'}
        self._creative_session['passes'] = []
        self._craft_validate_create = lambda doc, session, params: None
    def pump(self):
        """One turn of Krita's event loop: a deferred Undo is carried out, then each job's feeder paints a window."""
        if self.undo_next:
            self.undo_next = False
            self.doc.index -= 1
            if self.job.done: self.job.layer.pixels = b''            # the job's step undone
            else: self.doc.nodes.remove(self.job.layer)              # nothing painted: the step below, the layer's creation
        if self.job: self.job.pump()
    def cmd_set_brush(self, params): self.brushes += 1; self.events.append('set_brush'); return {'status': 'ok'}
    def _new(self):
        self.created_layers += 1
        node = self.layer_class('layer-' + str(self.created_layers), self) if self.layer_class is not JobLayer else JobLayer('layer-' + str(self.created_layers), self)
        self.doc.nodes.append(node); self.doc.active = node; self.doc.land('Add layer')
        return node
    def cmd_new_layer(self, params): return {'id': self._new().identity}
    def _craft_create(self, doc, session, params): return {'layer_id': self._new().identity, 'clip': 'clipped'}


class ForkStrokeJobTests(unittest.TestCase):
    """On the fork a pass paints as one Node.paintStrokes job (krita-fork task 2.4): clipped by the stage mask given as
    its selection, pen input as given, Stop as job.cancel(), and a refresh of the job's changed rect only. The fake
    paints only while Krita's event loop runs, so a loop that stops running events cannot pass these tests."""

    def setUp(self):
        self.refreshed, self.harnesses = [], []
        saved = module.canvas_projection.refresh
        module.canvas_projection.refresh = lambda doc, rect=None: self.refreshed.append(rect) or 'fork'
        pump = module.QCoreApplication.processEvents
        module.QCoreApplication.processEvents = lambda: [h.pump() for h in self.harnesses] and None
        constants = (module.JOB_DEADLINE_SECONDS, module.UNDO_WAIT_SECONDS, module._FORK, module.CANCEL_GRACE_SECONDS)
        module.JOB_DEADLINE_SECONDS, module.UNDO_WAIT_SECONDS, module._FORK = 1, 0.2, True
        def restore():
            module.canvas_projection.refresh = saved
            module.QCoreApplication.processEvents = pump
            module.JOB_DEADLINE_SECONDS, module.UNDO_WAIT_SECONDS, module._FORK, module.CANCEL_GRACE_SECONDS = constants
            module.stop_requested.clear()
        self.addCleanup(restore)

    def harness(self):
        h = ForkHarness(); self.harnesses.append(h); return h

    def _pass(self, h, strokes=3, operation_id='op-1', **extra):
        params = request()['params']; params['strokes'] = params['strokes'] * strokes; params.update(extra)
        return h.cmd_creative(dict(request(), params=params, operation_id=operation_id))

    def test_a_pass_paints_with_one_paint_strokes_call_clipped_by_the_stage_mask(self):
        h = self.harness(); events = []
        h.doc.waitForDone = lambda: events.append('wait')
        h.doc.setSelection = lambda value: events.append('selection')
        result = self._pass(h, 3, region=[100, 150, 580, 330])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(len(h.job_calls), 1, 'the whole pass is one job')
        strokes, options, selection, node = h.job_calls[0]
        self.assertEqual(len(strokes), 3)
        self.assertEqual((options['preset'], options['name']), ('b) Basic-1', 'Field'))
        self.assertEqual(selection.bounds, (100, 150, 580, 330))
        self.assertEqual(len(selection.data), 580 * 330)
        self.assertEqual(selection.data[165 * 580 + 290], 255)
        self.assertLess(selection.data[290], 16, 'the stage mask fades in at inner edges, as on stock')
        self.assertEqual(h.paints, 0, 'no stroke through the Python API')
        self.assertNotIn('selection', events, "the artist's selection is never swapped")
        self.assertNotIn('wait', events, "no Document.waitForDone: it ends the artist's open strokes")
        self.assertEqual(h.brushes, 0, "the job takes its preset by name: the artist's brush is left alone")
        self.assertTrue(h.job.waits and all(0 < ms <= 50 for ms in h.job.waits), 'every wait on the GUI thread is short and bounded')
        self.assertEqual(result['stroke_job']['state'], 'done')
        self.assertEqual((result['stroke_job']['strokes'], result['stroke_job']['total']), (3, 3))

    def test_without_a_region_the_job_gets_no_selection(self):
        h = self.harness()
        self.assertEqual(self._pass(h)['status'], 'ok')
        self.assertIsNone(h.job_calls[0][2], 'none paints everywhere, whatever the document selects')

    def test_the_fork_path_wins_over_the_native_helper(self):
        sent = []
        accel = types.ModuleType('creative_test_package.agent_accel'); accel.NATIVE_STROKES = True
        accel.paint_strokes = lambda *args, **kwargs: sent.append(args) or {'strokes': 1, 'jobs': 1, 'groups': 1, 'ms': 1}
        prior = sys.modules.get(accel.__name__); sys.modules[accel.__name__] = accel; package.agent_accel = accel
        def restore():
            if prior: sys.modules[accel.__name__] = prior; package.agent_accel = prior
            else: sys.modules.pop(accel.__name__, None); package.__dict__.pop('agent_accel', None)
        self.addCleanup(restore)
        h = self.harness(); result = self._pass(h)
        self.assertEqual((sent, len(h.job_calls)), ([], 1))
        self.assertNotIn('native_strokes', result)

    def test_the_fork_is_detected_once_from_the_node_class_not_per_pass(self):
        module._FORK = None
        saved = module.krita_module
        calls = []
        class Node:
            def __getattribute__(self, name): return object.__getattribute__(self, name)
        class Fork:
            def paintStrokes(self, *args): pass
        module.krita_module = types.SimpleNamespace(Node=Fork)
        self.addCleanup(lambda: setattr(module, 'krita_module', saved))
        self.assertTrue(module.on_fork())
        module.krita_module = types.SimpleNamespace(Node=object)     # cached: not asked again
        self.assertTrue(module.on_fork())
        module._FORK = None
        self.assertFalse(module.on_fork(), 'stock Krita: the Node class has no paintStrokes')

    def test_the_loop_runs_krita_s_events_or_nothing_paints(self):
        h = self.harness(); module.QCoreApplication.processEvents = lambda: None
        module.JOB_DEADLINE_SECONDS = module.CANCEL_GRACE_SECONDS = 0.05
        result = self._pass(h, 4)
        self.assertEqual(h.job.strokesDone(), 0)
        self.assertEqual(h.job.cancels, 1, 'a loop that runs no events can only reach the deadline, and even a cancel needs the loop')
        self.assertEqual(result['status'], 'partial'); self.assertIn('did not end after it was cancelled', result['error'])

    def test_stop_cancels_the_job_and_reports_the_painted_prefix(self):
        h = self.harness(); pumps = []
        real = module.QCoreApplication.processEvents
        def pump():
            pumps.append(1); real()
            if len(pumps) == 2: module.stop_requested.set()
        module.QCoreApplication.processEvents = pump
        result = self._pass(h, 8)
        self.assertEqual(h.job.cancels, 1, 'Stop cancels the job once')
        self.assertEqual(result['status'], 'ok', 'a definite, shorter pass')
        self.assertEqual(result['stopped'], 'Stopped by the artist.')
        self.assertEqual((result['stopped_after_strokes'], result['strokes_total']), (h.job.strokesDone(), 8))
        self.assertTrue(0 < result['stopped_after_strokes'] < 8)
        self.assertEqual(h._creative_session['operations']['op-1'][1]['status'], 'ok', 'recorded as done, never repainted')

    def test_a_stuck_job_is_cancelled_at_the_deadline_with_a_definite_result(self):
        h = self.harness(); h.job_stuck = True; module.JOB_DEADLINE_SECONDS = 0.05
        result = self._pass(h, 3)
        self.assertEqual(h.job.cancels, 1)
        self.assertEqual(result['status'], 'ok')
        self.assertIn('too long', result['stopped'])
        self.assertEqual((result['stopped_after_strokes'], result['strokes_total']), (0, 3))

    def test_the_artist_s_undo_mid_pass_is_not_recorded_as_a_painted_pass(self):
        h = self.harness(); h.krita_stops_after = 4
        result = self._pass(h, 8)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['error_code'], 'partial_change')
        self.assertIn('pressed Undo', result['error']); self.assertIn('Inspect the painting', result['error'])
        self.assertEqual(h.doc.index, 6, "the undo landed (the job's step is gone, the layer's creation stays) before anything observed or saved")
        self.assertEqual(h.events[-1], 'checkpoint@6', 'the checkpoint ran after the undo landed')
        self.assertEqual(h._creative_session['passes'], [], 'no pass entry with an after_path')
        self.assertNotIn('layer_id', result)
        self.assertTrue(result['contribution_removed'])
        self.assertEqual([n.identity for n in h.doc.nodes], [], 'the empty pass layer is removed as a rejected pass is')
        self.assertEqual(h._creative_session['layers'], set())

    def test_the_artist_s_undo_before_any_stroke_does_not_undo_the_step_below_unnoticed(self):
        h = self.harness(); h.krita_stops_after = 0
        result = self._pass(h, 4)
        self.assertEqual((result['status'], result['error_code']), ('partial', 'partial_change'))
        self.assertIn('pressed Undo', result['error'])
        self.assertEqual(h.doc.index, 5, "the undo took the layer's creation (the step below the job), which the result says")
        self.assertEqual(h.doc.nodes, [])
        self.assertTrue(result['contribution_removed']); self.assertEqual(h._creative_session['passes'], [])

    def test_an_undo_that_never_lands_is_reported_as_not_landed(self):
        h = self.harness(); h.krita_stops_after = 2; h.undo_lands = False
        result = self._pass(h, 6)
        self.assertEqual((result['status'], result['error_code']), ('partial', 'partial_change'))
        self.assertIn('no undo was seen to land', result['error'])
        self.assertEqual(len(h.doc.nodes), 1, 'the layer stays: its strokes may still be there')

    def test_an_undo_in_a_continuation_leaves_the_earlier_passes_layer_and_records_nothing(self):
        h = self.harness()
        self.assertEqual(self._pass(h, 2)['status'], 'ok')
        recorded = len(h._creative_session['passes'])
        h.krita_stops_after = 2
        result = self._pass(h, 6, operation_id='op-2', continue_layer_id='layer-1')
        self.assertEqual(result['status'], 'partial'); self.assertIn('pressed Undo', result['error'])
        self.assertEqual(len(h.doc.nodes), 1, 'the layer holds the first pass')
        self.assertEqual(len(h._creative_session['passes']), recorded)

    def test_the_jobs_cancel_reason_tells_a_closed_document_from_an_undo(self):
        h = self.harness(); h.krita_stops_after = 2; h.job_reason = 'document_closed'
        result = self._pass(h, 6)
        self.assertEqual(result['status'], 'partial')
        self.assertIn('document was closed', result['error']); self.assertNotIn('pressed Undo', result['error'])
        h = self.harness(); h.krita_stops_after = 2; h.job_reason = 'undo'
        self.assertIn('pressed Undo', self._pass(h, 6, operation_id='op-2')['error'])

    def test_a_failed_job_is_a_rejected_pass_with_its_layer_removed(self):
        h = self.harness(); h.job_error = 'The layer is locked.'
        result = self._pass(h, 3)
        self.assertEqual((result['status'], result['error_code']), ('rejected', 'validation_rejected'))
        self.assertIn('The layer is locked.', result['error'])
        self.assertTrue(result['reconciled'])
        self.assertEqual(h.doc.nodes, [], 'a refused job painted nothing: the new layer is removed')
        self.assertEqual(h._creative_session['passes'], []); self.assertEqual(self.refreshed, [])
        self.assertNotIn('layer_id', result)
        self.assertTrue(self._pass(h, 3).get('replayed'), 'the same operation is never painted twice')

    def test_the_refresh_covers_only_the_job_s_changed_rect(self):
        h = self.harness()
        result = self._pass(h, 2)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(self.refreshed, [[30, 40, 50, 60]], "Krita's own record of what the strokes changed")

    def test_pen_inputs_reach_the_job_unchanged_and_are_reported(self):
        import json
        h = self.harness()
        params = request()['params']
        pen = dict(pressure=[0.2, 0.8], tilt=[[0, 0], [40, -10]], rotation=[0, 90], speed=[0, 1], time_ms=[0, 300])
        params['strokes'] = [dict(params['strokes'][0], **pen)]
        given = json.loads(json.dumps(params['strokes']))
        result = h.cmd_creative(dict(request(), params=params))
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(h.job_calls[0][0], given)
        for name in ('pressure', 'tilt', 'rotation', 'speed'):
            self.assertEqual(result[name], 'applied')
        self.assertEqual(result['time_ms'], 'applied (not yet confirmed visually)')

    def test_the_artist_s_layer_is_active_again_as_soon_as_the_job_is_started(self):
        h = self.harness(); artist = Layer('artist'); h.doc.nodes.append(artist); h.doc.active = artist; seen = []
        real = module.QCoreApplication.processEvents
        module.QCoreApplication.processEvents = lambda: seen.append(h.doc.active.identity) or real()
        self.assertEqual(self._pass(h, 6)['status'], 'ok')
        self.assertTrue(seen and set(seen) == {'artist'}, 'strokes the artist paints during the pass land on their own layer: %s' % seen)
        self.assertEqual(h.job_calls[0][3].identity, 'layer-1', 'the job targets the pass layer by id')

    def test_smudge_overlay_goes_to_the_job_as_preset_properties_and_never_touches_the_view_s_brush(self):
        h = self.harness(); h._creative_validate_smudge_overlay = lambda preset, rate=False: None
        for name in ('cmd_set_brush', 'cmd_configure_brush', 'cmd_restore_brush'):
            setattr(h, name, lambda params, name=name: h.events.append(name) or {'status': 'ok', 'preset': 'b) Smudge'})
        result = self._pass(h, 2, smudge_overlay=True)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual([e for e in h.events if not str(e).startswith('checkpoint')], ['paintStrokes'],
                         "the view's brush is not selected, configured or restored")
        options = h.job_calls[0][1]
        self.assertTrue(options['preset'])
        self.assertEqual(options['presetProperties'], {'MergedPaint': True})
        self.assertNotIn('useViewTweaks', options)
        self.assertNotIn('brush_restore', result)

    def test_smudge_rate_goes_with_the_overlay_properties(self):
        h = self.harness(); h._creative_validate_smudge_overlay = lambda preset, rate=False: None
        result = self._pass(h, 2, smudge_overlay=True, smudge_rate=0.5)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(h.job_calls[0][1]['presetProperties'], {'MergedPaint': True, 'SmudgeRateValue': 0.5})

    def test_a_pass_without_overlay_has_no_preset_properties(self):
        h = self.harness()
        self.assertEqual(self._pass(h, 2)['status'], 'ok')
        self.assertNotIn('presetProperties', h.job_calls[0][1])

    def test_a_continuation_paints_the_earlier_layer_without_activating_it(self):
        h = self.harness()
        self.assertEqual(self._pass(h, 2)['status'], 'ok')
        artist = Layer('artist'); h.doc.nodes.append(artist); h.doc.active = artist
        result = self._pass(h, 2, operation_id='op-2', continue_layer_id='layer-1')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual((len(h.job_calls), h.created_layers), (2, 1))
        self.assertEqual(h.job_calls[1][3].identity, 'layer-1')
        self.assertEqual(h.doc.active.identity, 'artist')

    def test_a_blended_or_clipped_pass_paints_its_craft_layer_as_a_job(self):
        h = self.harness()
        result = self._pass(h, 2, blend_mode='multiply')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['clip'], 'clipped')
        self.assertEqual((len(h.job_calls), h.brushes, h.paints), (1, 0, 0))
        self.assertEqual(h.job_calls[0][3].identity, result['layer_id'])

    def test_a_node_without_paint_strokes_is_an_error_not_a_fall_back_to_the_stock_block(self):
        h = self.harness(); h.layer_class = NoStrokesLayer
        h._new = lambda: (setattr(h, 'created_layers', h.created_layers + 1), h.doc.nodes.append(NoStrokesLayer('layer-1')),
                          setattr(h.doc, 'active', h.doc.nodes[-1]), h.doc.nodes[-1])[-1]
        result = self._pass(h, 2)
        self.assertEqual((result['status'], result['error_code']), ('partial', 'partial_change'))
        self.assertIn('paintStrokes', result['error'])
        self.assertEqual((h.paints, h.brushes, h.job_calls), (0, 0, []))


class BackgroundCheckpointTests(unittest.TestCase):
    """With a protocol-6 native helper a checkpoint saves in the background (agent_accel.save_in_background): its result
    reports the job and claims no save; the next checkpoint, a save_status call or the end confirms it. Without the
    helper, or before the painting is its own file, it saves as before."""
    class Saver:
        """A stand-in helper: jobs 1, 2, ... answer `first` (running, or failed for a refused start) until the
        next wait or status call after `finish` says how they end."""
        def __init__(self, first='running', end='done'):
            self.first, self.end, self.started, self.waited, self.jobs = first, end, [], [], {}
        def save_in_background(self, path):
            self.started.append(path); job = len(self.started); self.jobs[job] = self.first; return job
        def save_status(self, job):
            return {'job': job, 'state': self.jobs[job], 'error': 'disk full' if self.jobs[job] == 'failed' else '', 'ms': 40, 'startMs': 3}
        def wait_for_save(self, job, timeout=600):
            self.waited.append(job)
            if self.jobs[job] == 'running': self.jobs[job] = self.end
            return self.save_status(job)
        def done(self):
            for job, state in self.jobs.items():
                if state == 'running': self.jobs[job] = self.end

    def _install(self, saver):
        stub = types.ModuleType('creative_test_package.agent_accel')
        for name in ('save_in_background', 'save_status', 'wait_for_save'):
            setattr(stub, name, getattr(saver, name))
        prior = sys.modules.get(stub.__name__); sys.modules[stub.__name__] = stub; package.agent_accel = stub
        def restore():
            if prior: sys.modules[stub.__name__] = prior; package.agent_accel = prior
            else: sys.modules.pop(stub.__name__, None); package.__dict__.pop('agent_accel', None)
        self.addCleanup(restore)
        return saver

    def _painting(self, saver=None, modified=True):
        """A harness whose document is its own saved file in a temporary folder, removed after the test."""
        h = Harness(); folder = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(__import__('shutil').rmtree, folder, True)
        painting = pathlib.Path(folder) / 'painting.kra'; painting.touch()
        h.doc.fileName = lambda: str(painting); h.doc.modified = lambda: h.modified
        h.modified = modified; h.saves = []
        h.cmd_save_native = lambda p: h.saves.append(p['path']) or {'status': 'ok'}
        h._creative_observe = lambda doc, session, region=None: {'status': 'ok', 'image_path': 'view.png'}
        h._creative_checkpoint = lambda *args, **kwargs: module.CreativeTools._creative_checkpoint(h, *args, **kwargs)
        session = {'output': folder, 'painting_path': str(painting), 'checkpoint': 0, 'saved_once': True}
        if saver: self._install(saver)
        return h, session, str(painting)

    def test_a_checkpoint_saves_in_the_background_and_claims_nothing_until_done(self):
        saver = self.Saver()
        h, session, painting = self._painting(saver)
        started = module.CreativeTools._creative_checkpoint(h, h.doc, session)
        self.assertEqual((h.saves, saver.started), ([], [painting]), 'no synchronous save: the helper saves')
        self.assertNotIn('checkpoint', started, 'nothing is claimed saved while the job runs')
        self.assertEqual(started['save_job'], {'job': 1, 'state': 'running'})
        self.assertTrue(started['checkpoint_deferred']); self.assertEqual(started['unsaved_operations'], 1)
        self.assertEqual(session['unsaved_operations'], 1)
        h.modified = False                                     # Krita marked it unmodified when the job ended
        confirmed = module.CreativeTools._creative_checkpoint(h, h.doc, session, changed=None)
        self.assertEqual(saver.waited, [1], 'the next checkpoint waits for the job and confirms it')
        self.assertEqual(confirmed['checkpoint'], painting); self.assertTrue(confirmed['save_skipped'])
        self.assertEqual(confirmed['save_job'], {'job': 1, 'state': 'done', 'ms': 40})
        self.assertEqual(session['unsaved_operations'], 0); self.assertNotIn('save_job', session)
        self.assertEqual(len(saver.started), 1, 'nothing changed since: no second save')

    def test_actions_after_the_copy_stay_unsaved_when_the_job_is_confirmed(self):
        saver = self.Saver(); clock = [1000.0]
        h, session, painting = self._painting(saver)
        previous = module.time.monotonic; module.time.monotonic = lambda: clock[0]
        self.addCleanup(setattr, module.time, 'monotonic', previous)
        session['last_saved_at'] = clock[0] - module.CHECKPOINT_SECONDS
        first = module.CreativeTools._creative_commit_view(h, h.doc, session)
        self.assertEqual((first['save_job']['state'], first['unsaved_operations']), ('running', 1))
        later = [module.CreativeTools._creative_commit_view(h, h.doc, session) for _ in range(3)]
        self.assertEqual(len(saver.started), 1, 'the save in progress counts as the timed save')
        self.assertEqual(later[-1]['unsaved_operations'], 4)
        saver.done()
        after = module.CreativeTools._creative_commit_view(h, h.doc, session)
        self.assertEqual(after['save_job'], {'job': 1, 'state': 'done', 'ms': 40}, 'a later result confirms the job')
        self.assertEqual(after['unsaved_operations'], 4, 'the three actions after the copy and this one are still unsaved')
        self.assertNotIn('checkpoint', after)

    def test_a_failed_background_save_stays_unsaved_and_the_next_checkpoint_saves_again(self):
        saver = self.Saver(end='failed')
        h, session, painting = self._painting(saver)
        module.CreativeTools._creative_checkpoint(h, h.doc, session)
        again = module.CreativeTools._creative_checkpoint(h, h.doc, session, changed=None)
        self.assertEqual(again['previous_save'], {'job': 1, 'state': 'failed', 'error': 'disk full'})
        self.assertEqual(len(saver.started), 2, 'the unsaved work is saved again')
        self.assertEqual(again['save_job'], {'job': 2, 'state': 'running'}); self.assertNotIn('checkpoint', again)
        self.assertEqual(session['unsaved_operations'], 1, 'the failed job confirmed nothing')

    def test_a_refused_background_save_falls_back_to_the_synchronous_save(self):
        saver = self.Saver(first='failed')                     # Krita was already saving the document
        h, session, painting = self._painting(saver)
        result = module.CreativeTools._creative_checkpoint(h, h.doc, session)
        self.assertEqual((h.saves, result['checkpoint']), ([painting], painting))
        self.assertEqual(session['unsaved_operations'], 0)

    def test_without_the_helper_or_before_the_first_save_the_checkpoint_saves_as_before(self):
        h, session, painting = self._painting()
        result = module.CreativeTools._creative_checkpoint(h, h.doc, session)
        self.assertEqual((h.saves, result['checkpoint']), ([painting], painting))
        saver = self.Saver()
        h, session, painting = self._painting(saver)
        h.doc.fileName = lambda: ''                           # a new canvas: its first save names the file
        module.CreativeTools._creative_checkpoint(h, h.doc, session)
        self.assertEqual((h.saves, saver.started), ([painting], []))

    def test_end_waits_for_the_background_save_and_saves_what_is_left(self):
        saver = self.Saver()
        h, session, painting = self._painting(saver)
        session.update(id='session', document_id=module.document_id(h.doc), width=768, height=1024, operations={}, layers=set())
        h._creative_session = session
        module.CreativeTools._creative_checkpoint(h, h.doc, session)
        result = h.cmd_creative({'operation': 'end', 'session_id': 'session', 'params': {}})
        self.assertEqual(saver.waited, [1])
        self.assertEqual(h.saves, [painting], 'changed since the copy: the end saves synchronously before releasing it')
        self.assertEqual(result['checkpoint'], painting)

    def test_the_save_status_operation_confirms_a_finished_job(self):
        saver = self.Saver()
        h, session, painting = self._painting(saver)
        session.update(id='session', document_id=module.document_id(h.doc), width=768, height=1024, operations={}, layers=set())
        h._creative_session = session
        module.CreativeTools._creative_checkpoint(h, h.doc, session)
        status = lambda: h.cmd_creative({'operation': 'save_status', 'session_id': 'session', 'params': {}})
        self.assertEqual(status(), {'status': 'ok', 'saved': False, 'unsaved_operations': 1, 'save_job': {'job': 1, 'state': 'running'}})
        saver.done()
        self.assertEqual(status(), {'status': 'ok', 'saved': True, 'unsaved_operations': 0, 'save_job': {'job': 1, 'state': 'done', 'ms': 40}})
        self.assertEqual(saver.waited, [], 'a status call never waits')

    def test_an_action_says_saved_only_when_it_was(self):
        for checkpoint, said in (({'checkpoint': 'p.kra'}, 'Painting saved'),
                                 ({'checkpoint_deferred': True, 'unsaved_operations': 1, 'save_job': {'job': 1, 'state': 'running'}}, 'Painting updated; saving in the background'),
                                 ({'checkpoint_deferred': True, 'unsaved_operations': 2}, 'Painting updated')):
            h = Harness(); h._creative_session['passes'] = []; messages = []
            h._creative_commit_view = lambda doc, session, c=checkpoint: dict(c, status='ok')
            h._creative_progress = lambda session, phase, message: messages.append(message)
            h.cmd_creative(request())
            self.assertEqual(messages[-1], said)

    def test_the_save_probe_runs_outside_a_chat_on_a_saved_painting(self):
        calls = []
        stub = types.ModuleType('creative_test_package.agent_accel')
        stub.save_compare = lambda doc, plugin, rounds=1, tick_ms=10: calls.append((rounds, tick_ms)) or {'helper': True}
        prior = sys.modules.get(stub.__name__); sys.modules[stub.__name__] = stub; package.agent_accel = stub
        self.addCleanup(lambda: (sys.modules.__setitem__(stub.__name__, prior), setattr(package, 'agent_accel', prior)) if prior
                        else (sys.modules.pop(stub.__name__, None), package.__dict__.pop('agent_accel', None)))
        h = Harness(); h._creative_session = None
        result = h.cmd_creative({'operation': 'save_probe', 'params': {'rounds': 2, 'tick_ms': 5}})
        self.assertEqual((result['status'], calls), ('ok', [(2, 5)]))
        for params in ({'rounds': 0}, {'rounds': 9}, {'tick_ms': 0}, {'wobble': 1}):
            with self.assertRaises(ValueError):
                h.cmd_creative({'operation': 'save_probe', 'params': params})
        h._creative_session = {'id': 'chat'}
        with self.assertRaisesRegex(ValueError, 'session'):
            h.cmd_creative({'operation': 'save_probe', 'params': {}})


class PaintedShareTests(unittest.TestCase):
    def test_blank_canvases_score_zero_whatever_their_colour(self):
        from importlib import util
        spec = util.spec_from_file_location('creative_validation_share', SOURCE / 'creative_validation.py')
        module = util.module_from_spec(spec); spec.loader.exec_module(module)
        white, red, grey = bytes([255, 255, 255, 255]), bytes([200, 20, 20, 255]), bytes([250, 250, 250, 255])
        self.assertEqual(module.painted_share(white * 100), 0.0)
        self.assertEqual(module.painted_share(red * 100), 0.0, 'a coloured ground is still blank')
        self.assertEqual(module.painted_share(white * 90 + grey * 10), 0.0, 'JPEG-level noise is within tolerance')
        self.assertEqual(module.painted_share(white * 75 + red * 25), 0.25)
        self.assertEqual(module.painted_share(b''), 0.0)

    def test_guide_lines_are_not_paint(self):
        """A live New Moscow chat drew its block-in guides on a blank canvas, measured 10% painted, was taken for an
        existing painting and lost its whole-picture underpainting. Pixels under a guide never count."""
        from importlib import util
        spec = util.spec_from_file_location('creative_validation_share', SOURCE / 'creative_validation.py')
        module = util.module_from_spec(spec); spec.loader.exec_module(module)
        white, blue, red = bytes([255, 255, 255, 255]), bytes([79, 179, 255, 255]), bytes([200, 20, 20, 255])
        under_guides = bytes([0] * 80 + [1] * 20)
        self.assertEqual(module.painted_share(white * 80 + blue * 20, ignore=under_guides), 0.0)
        self.assertEqual(module.painted_share(white * 70 + red * 10 + blue * 20, ignore=under_guides), 0.1, 'paint beside the guides still counts')
        self.assertEqual(module.painted_share(blue * 60 + white * 40, ignore=bytes([1] * 60 + [0] * 40)), 0.0, 'guides never decide the ground colour')


if __name__ == '__main__': unittest.main()

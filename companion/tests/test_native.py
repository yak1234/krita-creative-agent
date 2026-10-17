"""Exercise native dispatch policies without launching or modifying Krita."""
import importlib.util
import pathlib
import sys
import types
import unittest
import tempfile
import uuid

SOURCE = pathlib.Path(__file__).resolve().parents[2] / 'plugin/kritamcp'
package = types.ModuleType('creative_test_package')
package.__path__ = [str(SOURCE)]
sys.modules[package.__name__] = package
krita = types.ModuleType('krita')
krita.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(resources=lambda _kind: {'b) Basic-1': 1}))
class Selection:
    def select(self, *bounds): self.bounds = bounds
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
    def _creative_checkpoint(self, doc, session): return {'status': 'ok', 'checkpoint': 'saved.kra'}
    def _creative_observe(self, doc, session, region=None): return {'status':'ok', 'document_id':module.document_id(doc), 'image_path':'/tmp/before.png'}
    def _creative_revision(self, doc, projection=None): return 'current-revision'


def request():
    return {'operation': 'paint_pass', 'session_id': 'session', 'operation_id': 'op-1', 'params': {
        'name': 'Field', 'preset': 'b) Basic-1', 'strokes': [{'start': [10,20],
        'segments': [[20,20,30,20,40,20]], 'size': 20, 'opacity': 1, 'flow': 1, 'color': '#112233'}]}}


class NativePolicyTests(unittest.TestCase):
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

    def test_painting_actions_save_every_few_actions_not_every_action(self):
        h = Harness(); paths = []
        h.cmd_save_native = lambda p: paths.append(p['path']) or pathlib.Path(p['path']).touch() or {'status': 'ok'}
        h._creative_observe = lambda doc, session: {'status': 'ok', 'image_path': 'view.png'}
        h._creative_checkpoint = lambda doc, session: module.CreativeTools._creative_checkpoint(h, doc, session)
        with tempfile.TemporaryDirectory() as folder:
            session = {'output': folder, 'checkpoint': 0}
            views = [module.CreativeTools._creative_commit_view(h, h.doc, session) for _ in range(1 + module.CHECKPOINT_EVERY)]
        # The first action saves; then one save per CHECKPOINT_EVERY actions.
        self.assertEqual(len(paths), 2)
        self.assertTrue(views[1]['checkpoint_deferred']); self.assertEqual(views[1]['unsaved_operations'], 1)
        self.assertIn('checkpoint', views[-1]); self.assertEqual(session['unsaved_operations'], 0)

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
        self.assertEqual(h.doc.selection_changes[0].bounds,(100,150,580,330,255))
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


if __name__ == '__main__': unittest.main()

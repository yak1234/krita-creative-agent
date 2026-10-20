"""The plugin uses the fork's features and protection (krita-fork 6.6): fake Document with features, no Krita."""
import copy
import sys
import types
import unittest
import test_region_craft as region_tests
import test_filters as filter_tests
import test_merge as merge_tests

native = region_tests.native
run = region_tests.run
Mask = region_tests.Mask
guard = sys.modules.get('creative_test_package.feature_guard') or __import__('creative_test_package.feature_guard', fromlist=['x'])
SIZE = region_tests.SIZE


class Rect:
    def __init__(self, x, y, w, h): self.r = (x, y, w, h)
    def isEmpty(self): return self.r[2] <= 0 or self.r[3] <= 0
    def x(self): return self.r[0]
    def y(self): return self.r[1]
    def width(self): return self.r[2]
    def height(self): return self.r[3]
    def intersects(self, other):
        a, b = self.r, other.r
        return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def merge(a, b): return list(a) + [n for n in b if n not in a]


class Feature:
    def __init__(self, name, rect, kind='region', protected=False, author='artist', state='kept'):
        self.n, self.rect, self.k, self.prot, self.a, self.s = name, Rect(*rect), kind, protected, author, state
    def name(self): return self.n
    def kind(self): return self.k
    def author(self): return self.a
    def state(self): return self.s
    def isProtected(self): return self.prot
    def bounds(self): return self.rect
    def setProtected(self, value): self.prot = value; return True


class Protected(Mask):
    """What Document.protectedSelection() returns: it remembers whether it was inverted."""
    def __init__(self, inverted=False):
        super().__init__(); self.inverted = inverted
        self.select(0, 0, 2, 4, 255)                      # the stub's protected feature: the two left columns
        if inverted: self.invert()


class Layer(merge_tests.Layer):
    def bounds(self): return Rect(0, 0, SIZE, SIZE)
    def paintStrokes(self, *args): return None
    def mergeDown(self):
        if getattr(self.doc, 'refuse_merge', False): self.doc.keep_out('Buildings'); return None      # Krita refuses, naming the feature
        return super().mergeDown()


class FeatureDocument(merge_tests.Document):
    """A fork document: features, protection, selection(expression), setAgentActive and the kept-out record."""
    def __init__(self, features=()):
        super().__init__(); self.feature_list = list(features); self.agent_calls, self.expressions = [], []
        self.kept, self.move_kept = [], []
    def createNode(self, name, kind): return Layer(self, name, kind)
    def features(self): return list(self.feature_list)
    def feature(self, name): return next((f for f in self.feature_list if f.name() == name), None)
    def featuresAt(self, x, y): return []
    def featuresOverlapping(self, area):
        if isinstance(area, Mask): area = Rect(*area._box())
        return [f for f in self.feature_list if f.bounds().intersects(area)]
    # agent moves: the record of what was kept out starts again with each move, as in the fork
    def beginAgentMove(self, name):
        if getattr(self, 'move_held', False): return False        # someone else's move stays open
        self.move_open, self.move_ids = True, getattr(self, 'move_ids', 0) + 1
        self.kept, self.move_kept = [], []; return True
    def endAgentMove(self):
        if getattr(self, 'move_held', False): return False
        self.move_open = False; self.kept, self.move_kept = [], []; return True
    def agentMoveOpen(self): return getattr(self, 'move_open', False)
    def agentMoveId(self): return getattr(self, 'move_ids', 0)
    def keep_out(self, *names):
        """A write Krita kept out of features."""
        self.kept = list(names); self.move_kept = merge(self.move_kept, names)
    def setAgentActive(self, value): self.agent_calls.append(value)
    def protectionActive(self): return any(f.isProtected() for f in self.feature_list)
    def protectedSelection(self, inverted=False): return Protected(inverted)
    def lastKeptOut(self): return list(self.kept)
    def agentMoveKeptOut(self): return list(self.move_kept)
    def selection(self, expression=None):
        if expression is None: return self.selected
        self.expressions.append(expression)
        if expression in ('Sky - Moon', 'Sky'):
            mask = Mask(); mask.select(0, 0, SIZE, 2, 255); return mask
        return None                                       # Krita warns and answers None for an unknown name


class FeatureHarness(merge_tests.Harness):
    def __init__(self, folder, features=()):
        super().__init__(folder); self.doc = FeatureDocument(features)
        self._creative_session.update(document_id=native.module.document_id(self.doc))


class Setup(region_tests.RegionSetup):
    FEATURES = (Feature('Sky', (0, 0, 4, 2)), Feature('Moon', (3, 0, 1, 1)))
    def setUp(self):
        super().setUp(); self.h = FeatureHarness(self.h._creative_session['output'], [copy.copy(f) for f in self.FEATURES])
        self.doc = self.h.doc


FILL = {'name': 'Sky wash', 'color': '#203040', 'selection': 'Sky - Moon'}


class PrivilegedOptionTests(Setup, unittest.TestCase):
    def test_a_model_cannot_send_what_only_the_artist_confirms(self):
        for key in ('allowProtected', 'allow_protected', 'setProtectionSuspended', 'setProtected', 'removeFeature', 'protectionSuspended'):
            with self.assertRaisesRegex(ValueError, 'artist'):
                run(self.h, 'bucket_fill', {'name': 'x', 'x': 0, 'y': 0, 'color': '#000000', 'options': {key: True}}, 'op-' + key)

    def test_nested_in_lists_and_objects_too(self):
        with self.assertRaisesRegex(ValueError, "'allowProtected'.*artist"):
            run(self.h, 'painting_toolbox', {'name': 'x', 'commands': [{'tool': 'stroke', 'parameters_json': '{}', 'extra': [{'a': {'allowProtected': 1}}]}]}, 'nested')

    def test_the_rejection_names_the_key_and_runs_before_anything_changes(self):
        with self.assertRaises(ValueError):
            run(self.h, 'fill_region', dict(FILL, allowProtected=True), 'priv')
        self.assertEqual((self.doc.agent_calls, self.h._creative_session['operations']), ([], {}))

    def test_panel_only_feature_operations_are_refused(self):
        for operation in ('feature_set_protected', 'feature_remove', 'feature_undo'):
            with self.assertRaisesRegex(ValueError, 'artist'):
                run(self.h, operation, {'name': 'Moon', 'value': False}, None)

    def test_innocent_text_is_not_rejected(self):
        self.assertEqual(guard.privileged_key({'name': 'allowProtected area', 'note': ['setProtected']}), None)


class AgentActiveTests(Setup, unittest.TestCase):
    def test_a_writing_call_is_wrapped_in_set_agent_active(self):
        done = run(self.h, 'fill_region', dict(FILL, selection='Sky'), 'fill')
        self.assertEqual(done['status'], 'ok', done.get('error'))
        self.assertEqual(self.doc.agent_calls, [True, False])

    def test_it_is_switched_off_when_the_call_fails(self):
        self.h._region_fill = lambda *args: (_ for _ in ()).throw(RuntimeError('boom'))
        done = run(self.h, 'fill_region', dict(FILL, selection='Sky'), 'fail')
        self.assertEqual(done['status'], 'partial')
        self.assertEqual(self.doc.agent_calls, [True, False])

    def test_a_document_without_it_is_left_alone(self):
        class Stock: pass
        with guard.agent_writing(Stock()):
            pass
        calls = []
        doc = types.SimpleNamespace(setAgentActive=calls.append)
        with self.assertRaises(KeyError):
            with guard.agent_writing(doc):
                raise KeyError()
        self.assertEqual(calls, [True, False])

    def test_a_selection_is_not_a_write(self):
        run(self.h, 'select', {'name': 'Top', 'steps': [{'feature': 'Sky'}]})
        self.assertEqual(self.doc.agent_calls, [])


class FeatureRegionTests(Setup, unittest.TestCase):
    def test_select_takes_a_feature_expression_step(self):
        result = run(self.h, 'select', {'name': 'Sky no moon', 'steps': [{'feature': 'Sky - Moon'}, {'shape': 'rectangle', 'bounds': [0, 0, 1, 4], 'mode': 'subtract'}]})
        self.assertEqual(set(self.doc.expressions), {'Sky - Moon'}, 'checked when validated, again when built')
        self.assertEqual(result['bounds'], [1, 0, 3, 2])

    def test_an_unknown_feature_names_itself_and_nothing_is_saved(self):
        with self.assertRaisesRegex(ValueError, "Ghost"):
            run(self.h, 'select', {'name': 'Nope', 'steps': [{'feature': 'Ghost'}]})

    def test_features_need_the_fork(self):
        stock = region_tests.Document()
        self.h.doc = stock; self.h._creative_session['document_id'] = native.module.document_id(stock)
        with self.assertRaisesRegex(ValueError, 'our Krita'):
            run(self.h, 'select', {'name': 'x', 'steps': [{'feature': 'Sky'}]})

    def test_fill_region_selection_may_be_an_expression(self):
        done = run(self.h, 'fill_region', dict(FILL), 'fill-expr')
        self.assertEqual(done['status'], 'ok', done.get('error'))
        self.assertEqual(done['filled_bounds'], [0, 0, 4, 2])

    def test_a_saved_selection_wins_over_a_feature_of_the_same_name(self):
        run(self.h, 'select', {'name': 'Sky', 'steps': [{'shape': 'rectangle', 'bounds': [0, 3, 4, 1]}]})
        done = run(self.h, 'fill_region', dict(FILL, selection='Sky'), 'fill-saved')
        self.assertEqual(done['filled_bounds'], [0, 3, 4, 1])
        self.assertEqual(self.doc.expressions, [])

    def test_a_typo_in_an_expression_is_refused_before_anything_is_made(self):
        with self.assertRaisesRegex(ValueError, 'Features: Sky, Moon'):
            run(self.h, 'fill_region', dict(FILL, selection='Sky - Mon'), 'typo')
        self.assertEqual((self.h._creative_session['operations'], self.doc.root.childNodes()), ({}, []))
        with self.assertRaisesRegex(ValueError, 'Features: Sky, Moon'):
            run(self.h, 'select', {'name': 'x', 'steps': [{'feature': 'Sky - Mon'}]})

    def test_a_missing_name_says_both_places(self):
        with self.assertRaisesRegex(ValueError, 'saved selection or feature'):
            run(self.h, 'fill_region', dict(FILL, selection='Ghost'), 'ghost')

    def test_a_pass_may_be_limited_to_a_feature(self):
        seen = []
        def new_layer(doc, session, params):
            node = doc.createNode(params['name'], 'paintlayer'); doc.root.addChildNode(node, None); return {'id': node.id}
        self.h._creative_new_layer = new_layer
        self.h._creative_stroke_job = lambda doc, session, params, node, result, new_layer=True, started=None, selection=None: seen.append(selection) or {}
        native.module._FORK = True
        self.addCleanup(setattr, native.module, '_FORK', None)
        stroke = {'start': [1, 1], 'segments': [[1, 1, 2, 2, 3, 3]], 'size': 2, 'opacity': 1, 'flow': 1, 'color': '#806040'}
        done = run(self.h, 'paint_pass', {'name': 'Sky strokes', 'preset': 'b) Basic-1', 'strokes': [stroke], 'selection': 'Sky - Moon'}, 'pass')
        self.assertEqual(done['status'], 'ok', done.get('error'))
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].pixelData(0, 0, SIZE, SIZE), Mask().pixelData(0, 0, SIZE, SIZE)[:0] + bytes([255] * 8 + [0] * 8))

    def test_a_pass_takes_a_region_or_a_selection_not_both(self):
        native.module._FORK = True
        self.addCleanup(setattr, native.module, '_FORK', None)
        stroke = {'start': [1, 1], 'segments': [[1, 1, 2, 2, 3, 3]], 'size': 2, 'opacity': 1, 'flow': 1, 'color': '#806040'}
        with self.assertRaisesRegex(ValueError, 'region or a selection'):
            run(self.h, 'paint_pass', {'name': 'x', 'preset': 'b) Basic-1', 'strokes': [stroke], 'selection': 'Sky', 'region': [0, 0, 2, 2]}, 'both')


class KeptOutTests(Setup, unittest.TestCase):
    def test_what_krita_kept_out_is_in_the_result(self):
        fill = self.h._region_fill
        self.h._region_fill = lambda *args: self.doc.keep_out('Moon') or self.doc.keep_out('Moon', 'Tower') or fill(*args)
        done = run(self.h, 'fill_region', dict(FILL, selection='Sky'), 'kept')
        self.assertEqual(done['kept_out'], ['Moon', 'Tower'])
        self.assertIn('protected', done['kept_out_note'])

    def test_nothing_kept_out_adds_no_field(self):
        done = run(self.h, 'fill_region', dict(FILL, selection='Sky'), 'clean')
        self.assertNotIn('kept_out', done)

    def test_a_stroke_job_reports_its_names(self):
        job = types.SimpleNamespace(keptOut=lambda: ['Moon', 'Moon', 'Tower'])
        self.assertEqual(guard.merge_names(['Tower'], job.keptOut()), ['Tower', 'Moon'])


class NodeOperationTests(Setup, unittest.TestCase):
    FEATURES = (Feature('Buildings', (0, 0, 2, 4), protected=True), Feature('Moon', (3, 0, 1, 1)))

    def test_a_layer_reaching_a_protected_feature_is_named(self):
        node = Layer(self.doc, 'Layer', 'paintlayer')
        with self.assertRaisesRegex(ValueError, "protected feature 'Buildings'"):
            self.h._feature_check_node(self.doc, node, 'rotate')

    def test_unprotected_features_do_not_block(self):
        self.doc.feature_list[0].prot = False
        self.h._feature_check_node(self.doc, Layer(self.doc, 'Layer', 'paintlayer'), 'rotate')

    def test_no_features_no_check(self):
        self.h._feature_check_node(region_tests.Document(), Layer(self.doc, 'Layer', 'paintlayer'), 'rotate')

    def test_merge_passes_reports_a_refused_merge_to_the_model(self):
        STROKE = merge_tests.STROKE
        for name in ('Walls', 'Towers'):
            run(self.h, 'paint_pass', {'name': name, 'preset': 'b) Basic-1', 'strokes': [STROKE], 'stage_id': 'move-1'}, name)
        self.doc.refuse_merge = True
        done = run(self.h, 'merge_passes', {'stage_id': 'move-1', 'name': 'Merged'}, 'merge')
        self.assertIn(done['status'], ('rejected', 'partial'))
        self.assertIn('Buildings', done['error'])
        self.assertTrue(self.doc.agent_calls[-1] is False)

    def test_a_transform_krita_refuses_is_reported_with_the_names(self):
        self.doc.feature_list[0].prot = False             # the pre-check passes; Krita still answers False
        self.doc.keep_out('Buildings')
        node = Layer(self.doc, 'Layer', 'paintlayer')
        with self.assertRaisesRegex(RuntimeError, "'Buildings'"):
            self.h._feature_transform(self.doc, node, 'rotate', lambda: False)
        self.h._feature_transform(self.doc, node, 'rotate', lambda: None)       # stock: void, no refusal

    def test_a_transform_is_not_called_when_the_pre_check_refuses(self):
        called = []
        with self.assertRaises(ValueError):
            self.h._feature_transform(self.doc, Layer(self.doc, 'Layer', 'paintlayer'), 'scale', lambda: called.append(1))
        self.assertEqual(called, [])

    def test_a_merge_down_krita_refuses_is_an_error_not_a_crash(self):
        node = Layer(self.doc, 'Layer', 'paintlayer'); node.mergeDown = lambda: None
        self.doc.keep_out('Buildings')
        with self.assertRaisesRegex(RuntimeError, 'Buildings'):
            self.h._feature_merge_down(self.doc, node)


class SelectionLimitTests(Setup, unittest.TestCase):
    FEATURES = (Feature('Buildings', (0, 0, 2, 4), protected=True),)

    def test_a_filter_mask_is_limited_to_what_is_not_protected(self):
        area = Mask(); area.select(0, 0, SIZE, SIZE, 255)
        limited = self.h._feature_limit_area(self.doc, area)
        self.assertEqual(limited.pixelData(0, 0, SIZE, 1), bytes([0, 0, 255, 255]))

    def test_no_protection_leaves_the_area_alone(self):
        self.doc.feature_list[0].prot = False
        area = Mask()
        self.assertIs(self.h._feature_limit_area(self.doc, area), area)

    def test_whole_canvas_becomes_everything_outside_the_protected(self):
        limited = self.h._feature_limit_area(self.doc, None)
        self.assertTrue(limited.inverted)
        self.assertEqual(limited.pixelData(0, 0, SIZE, 1), bytes([0, 0, 255, 255]))

    def test_a_stock_document_is_left_alone(self):
        area = Mask()
        self.assertIs(self.h._feature_limit_area(region_tests.Document(), area), area)

    def test_a_region_filter_mask_gets_the_limited_area(self):
        filters = sys.modules['creative_test_package.filters']
        class Fdoc(filter_tests.Document, FeatureDocument): pass
        doc = Fdoc(); doc.feature_list = list(self.doc.feature_list)
        h = filter_tests.Harness(self.h._creative_session['output']); h.doc = doc
        h._creative_session['document_id'] = native.module.document_id(doc)
        saved = filters.Selection, filters.Krita
        filters.Selection = Mask
        filters.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(filter=lambda name: filter_tests.Filter(name, [])))
        self.addCleanup(lambda: setattr(filters, 'Selection', saved[0]) or setattr(filters, 'Krita', saved[1]))
        run(h, 'create_layer', {'name': 'Walls', 'type': 'paint'}, 'make')
        target = doc.root.childNodes()[-1]
        done = run(h, 'apply_filter', {'target': target.id, 'filter': 'gaussian blur', 'mode': 'mask',
                                       'area': [{'shape': 'rectangle', 'bounds': [0, 0, 4, 4]}]}, 'blur')
        self.assertEqual(done['status'], 'ok', done.get('error'))
        mask = next(n for n in target.childNodes() if n.kind == 'filtermask')
        self.assertEqual(mask.area.pixelData(0, 0, SIZE, 1), bytes([0, 0, 255, 255]), 'the protected columns are out of the mask')


class ActionTests(Setup, unittest.TestCase):
    FEATURES = (Feature('Buildings', (0, 0, 2, 4), protected=True),)

    def test_a_pixel_action_is_refused_while_a_feature_is_protected(self):
        with self.assertRaisesRegex(ValueError, 'protected'):
            self.h._feature_refuse_action(self.doc, {'kind': 'pixels', 'id': 'filter_apply_again'})

    def test_a_selection_action_is_not_a_write(self):
        self.h._feature_refuse_action(self.doc, {'kind': 'selection', 'id': 'select_all'})

    def test_with_nothing_protected_an_action_runs(self):
        self.doc.feature_list[0].prot = False
        self.h._feature_refuse_action(self.doc, {'kind': 'pixels', 'id': 'x'})


class ListingTests(Setup, unittest.TestCase):
    FEATURES = (Feature('Sky', (0, 0, 4, 2), kind='sky'), Feature('Buildings', (0, 2, 4, 2), protected=True, author='agent', state='proposed'))

    def test_the_list_has_name_kind_protected_author_and_state(self):
        listed = self.h._feature_list(self.doc)
        self.assertEqual(listed[1], {'name': 'Buildings', 'kind': 'region', 'protected': True, 'author': 'agent', 'state': 'proposed'})
        self.assertEqual([f['name'] for f in listed], ['Sky', 'Buildings'])

    def test_the_model_may_list_features(self):
        done = run(self.h, 'features_list', {})
        self.assertEqual(done['status'], 'ok')
        self.assertEqual([f['name'] for f in done['features']], ['Sky', 'Buildings'])

    def test_a_stock_document_has_none(self):
        self.assertEqual(self.h._feature_list(region_tests.Document()), [])

    def test_observe_carries_the_features(self):
        listed = []
        done = self.h._feature_observation(self.doc, {'status': 'ok'})
        self.assertEqual([f['name'] for f in done['features']], ['Buildings', 'Sky'], 'protected first')

    def test_the_artist_sets_protection_from_the_panel(self):
        self.assertTrue(self.h._feature_set_protected(self.doc, 'Sky', True))
        self.assertTrue(self.doc.feature('Sky').isProtected())
        self.assertTrue(self.h._feature_set_protected(self.doc, 'Buildings', False))
        self.assertFalse(self.doc.feature('Buildings').isProtected())

    def test_an_unknown_feature_is_an_error(self):
        with self.assertRaisesRegex(ValueError, 'Ghost'):
            self.h._feature_set_protected(self.doc, 'Ghost', True)


if not hasattr(Mask, 'duplicate'):
    def _duplicate(self):
        copy = Mask(); copy.m = bytearray(self.m); return copy
    Mask.duplicate = _duplicate


class KeptOutFreshTests(Setup, unittest.TestCase):
    """A move someone else holds open: its record is cumulative, so a call must not read it."""
    FEATURES = (Feature('Sky', (0, 0, 4, 2)), Feature('Buildings', (0, 2, 4, 2), protected=True))

    def setUp(self):
        super().setUp()
        self.doc.move_held = self.doc.move_open = True
        self.doc.keep_out('Buildings')                          # left by an earlier whole-canvas pass

    def test_a_tiny_pass_far_from_the_feature_reports_nothing(self):
        def new_layer(doc, session, params):
            node = doc.createNode(params['name'], 'paintlayer'); doc.root.addChildNode(node, None); return {'id': node.id}
        self.h._creative_new_layer = new_layer
        self.h._creative_stroke_job = lambda *args, **kwargs: {'stroke_job': {'state': 'done'}}      # the job kept out of nothing
        native.module._FORK = True
        self.addCleanup(setattr, native.module, '_FORK', None)
        stroke = {'start': [1, 1], 'segments': [[1, 1, 2, 2, 3, 3]], 'size': 2, 'opacity': 1, 'flow': 1, 'color': '#806040'}
        done = run(self.h, 'paint_pass', {'name': 'Dab', 'preset': 'b) Basic-1', 'strokes': [stroke]}, 'dab')
        self.assertEqual(done['status'], 'ok', done.get('error'))
        self.assertNotIn('kept_out', done)

    def test_a_pass_reports_its_own_jobs_names(self):
        def new_layer(doc, session, params):
            node = doc.createNode(params['name'], 'paintlayer'); doc.root.addChildNode(node, None); return {'id': node.id}
        self.h._creative_new_layer = new_layer
        self.h._creative_stroke_job = lambda *args, **kwargs: {'stroke_job': {'state': 'done'}, 'kept_out': ['Buildings']}
        native.module._FORK = True
        self.addCleanup(setattr, native.module, '_FORK', None)
        stroke = {'start': [1, 1], 'segments': [[1, 1, 2, 2, 3, 3]], 'size': 2, 'opacity': 1, 'flow': 1, 'color': '#806040'}
        done = run(self.h, 'paint_pass', {'name': 'Wide', 'preset': 'b) Basic-1', 'strokes': [stroke]}, 'wide')
        self.assertEqual(done['kept_out'], ['Buildings'])

    def test_a_toolbox_call_that_writes_nothing_reports_nothing(self):
        self.h._creative_toolbox = lambda doc, session, params: {'layer_id': None}
        done = run(self.h, 'painting_toolbox', {'name': 'Colour', 'commands': [{'tool': 'set_color', 'parameters_json': '{"color": "#112233"}'}]}, 'colour')
        self.assertNotIn('kept_out', done)

    def test_a_write_replaces_the_last_record_so_its_own_result_is_reported(self):
        fill = self.h._region_fill
        self.h._region_fill = lambda *args: setattr(self.doc, 'kept', []) or fill(*args)      # a write that kept out of nothing
        self.assertNotIn('kept_out', run(self.h, 'fill_region', dict(FILL, selection='Sky'), 'clear'))
        self.h._region_fill = lambda *args: setattr(self.doc, 'kept', ['Buildings']) or fill(*args)
        self.assertEqual(run(self.h, 'fill_region', dict(FILL, name='B', selection='Sky'), 'hit')['kept_out'], ['Buildings'])

    def test_the_report_does_not_read_the_document_again(self):
        self.assertEqual(self.h._feature_report(self.doc, {'status': 'ok'}), {'status': 'ok'})


class ErrorAndEmptyFillTests(Setup, unittest.TestCase):
    FEATURES = (Feature('Sky', (0, 0, 4, 2)), Feature('Buildings', (0, 2, 4, 2), protected=True))

    def test_a_validation_error_carries_validation_rejected(self):
        from creative_test_package.creative_validation import command_error
        self.assertEqual(command_error(ValueError("'allowProtected' lifts protection")),
                         {'error': "ValueError: 'allowProtected' lifts protection", 'error_code': 'validation_rejected'})
        self.assertEqual(command_error(RuntimeError('boom')), {'error': 'RuntimeError: boom', 'error_code': 'internal'})

    def test_a_fill_wholly_inside_a_protected_feature_is_rejected_and_leaves_no_layer(self):
        self.doc.protectedSelection = lambda inverted=False: _Columns(0, 2, SIZE, 2, inverted)
        before = len(self.doc.root.childNodes())
        done = run(self.h, 'fill_region', dict(FILL, selection='Sky - Moon'), 'ok-first')
        self.assertEqual(done['status'], 'ok')
        done = run(self.h, 'fill_region', {'name': 'Walls', 'color': '#203040', 'area': [{'shape': 'rectangle', 'bounds': [0, 2, 4, 2]}]}, 'all-protected')
        self.assertEqual((done['status'], done['error_code']), ('rejected', 'validation_rejected'))
        self.assertIn("'Buildings'", done['error'])
        self.assertEqual(len(self.doc.root.childNodes()), before + 1, 'only the first fill made a layer')


class _Columns(Mask):
    def __init__(self, x, y, w, h, inverted=False):
        super().__init__(); self.select(x, y, w, h, 255)
        if inverted: self.invert()


class ReviewFixTests(Setup, unittest.TestCase):
    FEATURES = (Feature('Sky', (0, 0, 4, 2)), Feature('Buildings', (0, 2, 4, 2), protected=True))

    # C1: the toolbox's strokes and shapes are not clipped by Krita
    def test_toolbox_painting_commands_are_refused_while_a_feature_is_protected(self):
        for tool in ('stroke', 'curve_stroke', 'draw_shape', 'gradient', 'smart_patch', 'clear', 'fill', 'flood_fill'):
            with self.assertRaisesRegex(ValueError, "'Buildings'.*paint_pass.*fill_region"):
                run(self.h, 'painting_toolbox', {'name': 'x', 'commands': [{'tool': tool, 'parameters_json': '{}'}]}, 'tb-' + tool)

    def test_toolbox_commands_that_write_nothing_stay_allowed(self):
        self.h._creative_validate_toolbox(self.doc, {'name': 'x', 'commands': [{'tool': 'blend_mode', 'parameters_json': '{"mode": "normal"}'}]})

    def test_toolbox_painting_is_allowed_when_nothing_is_protected(self):
        self.doc.feature_list[1].prot = False
        try:                                             # it may fail later for other reasons in the stub, but not on protection
            self.h._creative_validate_toolbox(self.doc, {'name': 'x', 'commands': [{'tool': 'stroke', 'parameters_json': '{}'}]})
        except Exception as error:
            self.assertNotIn('protected', str(error))

    # I1: kept_out is fresh for each call
    def test_each_writing_call_is_one_agent_move_and_kept_out_does_not_repeat(self):
        fill = self.h._region_fill
        self.h._region_fill = lambda *args: self.doc.keep_out('Buildings') or fill(*args)
        first = run(self.h, 'fill_region', dict(FILL, selection='Sky'), 'one')
        self.assertEqual(first['kept_out'], ['Buildings'])
        self.h._region_fill = fill
        second = run(self.h, 'fill_region', dict(FILL, name='Again', selection='Sky'), 'two')
        self.assertNotIn('kept_out', second)
        self.assertEqual((self.doc.move_ids, self.doc.agentMoveOpen()), (2, False))

    def test_the_names_are_read_before_the_move_ends(self):
        fill = self.h._region_fill
        self.h._region_fill = lambda *args: self.doc.keep_out('Buildings') or fill(*args)
        self.assertEqual(run(self.h, 'fill_region', dict(FILL, selection='Sky'), 'in')['kept_out'], ['Buildings'])

    # I2: limited areas say so
    def test_a_limited_filter_area_names_what_it_left_out(self):
        area = Mask(); area.select(0, 0, SIZE, SIZE, 255)
        self.h._feature_clipped = []
        limited = self.h._feature_limit_area(self.doc, area)
        self.assertEqual(self.h._feature_clipped, ['Buildings'])
        self.assertIsNotNone(limited)

    def test_an_area_wholly_inside_a_protected_feature_is_an_error(self):
        area = Mask(); area.select(0, 2, SIZE, 2, 255)
        class Everything(Protected):
            def __init__(self, inverted=False): Mask.__init__(self); self.inverted = inverted; self.select(0, 2, SIZE, 2, 255)
        self.doc.protectedSelection = lambda inverted=False: Everything(inverted)
        with self.assertRaisesRegex(ValueError, "entirely inside.*'Buildings'"):
            self.h._feature_limit_area(self.doc, area)

    def test_the_result_of_a_limited_call_carries_kept_out_and_a_note(self):
        self.h._feature_clipped = ['Buildings']
        done = self.h._feature_report(self.doc, {'status': 'ok'})
        self.assertEqual(done['kept_out'], ['Buildings'])
        self.assertIn('protected', done['kept_out_note'])

    # I4: observe stays small
    def test_thirty_features_are_compact_protected_first_and_capped(self):
        many = [Feature('F%02d' % n, (0, 0, 1, 1), protected=(n % 10 == 9)) for n in range(30)]
        self.doc.feature_list = many
        rows = self.h._feature_observation(self.doc, {'status': 'ok'})
        listed = rows['features']
        self.assertLessEqual(len(listed), 24)
        self.assertEqual([r['name'] for r in listed[:3]], ['F09', 'F19', 'F29'])
        self.assertEqual(set(listed[0]), {'name', 'protected'})
        self.assertEqual(rows['features_more'], 30 - len(listed))
        self.assertEqual(len(self.h._feature_list(self.doc)), 30, 'features_list still gives all of them')

    # I6: one vocabulary
    def test_a_name_protected_both_ways_is_reported_once(self):
        self.h._feature_clipped = ['Buildings']
        done = self.h._feature_report(self.doc, {'status': 'ok', 'protected': ['Buildings', 'Car']})
        self.assertEqual(done['kept_out'], ['Buildings'])
        self.assertEqual(done['protected'], ['Car'])
        again = self.h._feature_report(self.doc, {'status': 'ok', 'protected': ['Buildings']})
        self.assertNotIn('protected', again)

    # M1
    def test_the_privileged_keys_are_found_in_parameters_json_and_odd_spellings(self):
        self.assertEqual(guard.privileged_key({'parameters_json': '{"a": {"allowProtected": true}}'}), 'allowProtected')
        self.assertEqual(guard.privileged_key({'x': '[{"set_protected": 1}]'}), 'set_protected')
        for key in ('allow.protected', 'ALLOW PROTECTED', 'allow\u2011protected', 'Remove_Feature', 'allow\u200bProtected'):
            self.assertIsNotNone(guard.privileged_key({key: 1}), key)
        self.assertIsNone(guard.privileged_key({'parameters_json': 'not json {', 'n': '{"fine": 1}'}))

    # M4
    def test_a_setprotected_krita_refuses_is_not_reported_as_success(self):
        self.doc.feature('Sky').setProtected = lambda value: False
        self.assertFalse(self.h._feature_set_protected(self.doc, 'Sky', True))

    def test_the_panel_survives_a_closed_document(self):
        def closed(value): raise RuntimeError('Object has been deleted')
        self.doc.feature('Sky').setProtected = closed
        self.assertFalse(self.h._feature_set_protected(self.doc, 'Sky', True))

    # demo: the artist's selection becomes a protected feature
    def test_the_artists_selection_becomes_a_protected_feature(self):
        added = []
        self.doc.addFeature = lambda *args: added.append(args) or Feature(args[0], (0, 0, 1, 1))
        selection = Mask()
        self.assertTrue(self.h._feature_add_protected(self.doc, ' Buildings 2 ', selection))
        name, kind, mask, author, state, protect = added[0]
        self.assertEqual((name, author, state, protect, mask is selection), ('Buildings 2', 'artist', 'kept', True, True))

    def test_a_name_already_used_is_an_error_not_a_second_feature(self):
        self.doc.addFeature = lambda *args: None
        with self.assertRaisesRegex(ValueError, 'name'):
            self.h._feature_add_protected(self.doc, 'Sky', Mask())


if __name__ == '__main__':
    unittest.main()

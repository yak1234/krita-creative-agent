"""agent_accel.py: finding and calling the native helper (krita-native/agent-accel) with real Qt, under PyQt5 or PyQt6.
A Python QObject stands in for the C++ service, with the same name and invokable slots. Writes no files."""
import importlib
import pathlib
import sys
import types
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'


def load_with_real_qt():
    """test_native.py replaces PyQt5 with stubs in this process: load under a package of our own with the real binding."""
    stubs = {name: sys.modules.pop(name) for name in list(sys.modules) if name == 'PyQt5' or name.startswith('PyQt5.')}
    try:
        package = types.ModuleType('accel_test_package'); package.__path__ = [str(PLUGIN)]
        sys.modules['accel_test_package'] = package
        return (importlib.import_module('accel_test_package.qt_compat'), importlib.import_module('accel_test_package.agent_accel'))
    finally:
        sys.modules.update(stubs)


qt, accel = load_with_real_qt()
app = qt.QCoreApplication.instance() or qt.QCoreApplication([])


class FakeService(qt.QObject):
    def __init__(self, version=3):
        super().__init__(app)
        self.setObjectName('creative-agent-accel')
        self.calls, self.protocol = [], version

    @qt.pyqtSlot(result=int)
    def version(self):
        return self.protocol

    @qt.pyqtSlot(str, str, str, result=str)
    def paintStrokes(self, path, layer_id, strokes_json):
        import json
        strokes = json.loads(strokes_json)['strokes']
        self.calls.append(('paint', path, layer_id, strokes))
        return json.dumps({'status': 'ok', 'strokes': len(strokes), 'jobs': 1, 'ms': 3})

    @qt.pyqtSlot(str, int, int, int, int, result=int)
    def refreshRect(self, path, x, y, w, h):
        self.calls.append((path, x, y, w, h))
        return -1 if path == '/missing.kra' else 7

    # Protocol 7: the region refresh answers the rect it recomposited, here grown by an 8-pixel blur as a filter mask
    # would grow it, cut to a 6000x4500 canvas.
    @qt.pyqtSlot(str, int, int, int, int, result=str)
    def refreshRegion(self, path, x, y, w, h):
        import json
        self.calls.append(('region', path, x, y, w, h))
        if path == '/missing.kra':
            return json.dumps({'error': 'No such document.'})
        left, top = max(0, x - 8), max(0, y - 8)
        right, bottom = min(6000, x + w + 8), min(4500, y + h + 8)
        return json.dumps({'ms': 9, 'rect': [left, top, right - left, bottom - top], 'requested': [x, y, w, h]})

    # The selection builders answer a 16-byte header (x, y, w, h as little-endian int32: the selected pixels' bounding
    # rect) and then w*h mask bytes; an empty answer is a failure (no such document, not 8-bit RGBA).
    MASK = (2, 3, 3, 2, bytes([255, 255, 0, 0, 255, 255]))

    def _answer(self, path):
        import struct
        if path == '/missing.kra':
            return qt.QByteArray()
        x, y, w, h, mask = self.MASK
        return qt.QByteArray(struct.pack('<4i', x, y, w, h) + mask)

    @qt.pyqtSlot(str, int, int, int, int, int, int, int, result=qt.QByteArray)
    def selectContiguous(self, path, x, y, tolerance, bx, by, bw, bh):
        self.calls.append(('contiguous', path, x, y, tolerance, bx, by, bw, bh))
        return self._answer(path)

    @qt.pyqtSlot(str, str, int, int, int, int, int, result=qt.QByteArray)
    def selectSimilar(self, path, colour, tolerance, bx, by, bw, bh):
        self.calls.append(('similar', path, colour, tolerance, bx, by, bw, bh))
        return self._answer(path)

    @qt.pyqtSlot(qt.QByteArray, result=str)
    def selectionOutline(self, header_and_mask):
        import json
        import struct
        data = bytes(header_and_mask)
        self.calls.append(('outline', struct.unpack('<4i', data[:16]), data[16:]))
        return json.dumps({'polygons': [[[2, 3], [5, 3], [5, 5], [2, 5]]]})

    # Protocol 4: a whole select's seed and colour steps in one call, the same answer format; the phases after.
    @qt.pyqtSlot(str, str, result=qt.QByteArray)
    def buildSelection(self, path, steps_json):
        import json
        self.calls.append(('build', path, json.loads(steps_json)))
        return self._answer(path)

    @qt.pyqtSlot(result=str)
    def buildTimings(self):
        return '{"steps": 2, "read": 90, "fill": 100, "combine": 5, "pack": 20, "total": 230}'

    # Protocol 6: a background save of a document to its own file, a job id (-1: no such document), then its status.
    # `running` is how many status calls a job answers "running" before it is done (or fails, for /fails.kra).
    running = 2

    @qt.pyqtSlot(str, result=int)
    def saveInBackground(self, path):
        self.calls.append(('save', path))
        if path == '/missing.kra':
            return -1
        self.jobs = getattr(self, 'jobs', {})
        self.jobs[len(self.jobs) + 1] = {'path': path, 'left': 0 if path == '/busy.kra' else self.running}
        return len(self.jobs)

    @qt.pyqtSlot(int, result=str)
    def saveStatus(self, job):
        import json
        self.calls.append(('status', job))
        found = getattr(self, 'jobs', {}).get(job)
        if found is None:
            return json.dumps({'job': job, 'state': 'failed', 'error': 'No such save job.', 'ms': 0, 'startMs': 0, 'file': '', 'clean': False})
        if found['path'] == '/busy.kra':
            return json.dumps({'job': job, 'state': 'failed', 'error': 'Krita is already saving this document.', 'ms': 0, 'startMs': 0, 'file': found['path'], 'clean': False})
        if found['left'] > 0:
            found['left'] -= 1
            return json.dumps({'job': job, 'state': 'running', 'error': '', 'ms': 10, 'startMs': 4, 'file': found['path'], 'clean': False})
        failed = found['path'] == '/fails.kra'
        return json.dumps({'job': job, 'state': 'failed' if failed else 'done', 'error': 'disk full' if failed else '',
                           'ms': 50, 'startMs': 4, 'file': found['path'], 'clean': not failed})


class AgentAccelTests(unittest.TestCase):
    def tearDown(self):
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def test_without_the_helper_nothing_is_called(self):
        self.assertIsNone(accel.service(app))
        self.assertIsNone(accel.refresh_rect('/art/x.kra', (0, 0, 10, 10), app))

    def test_a_region_refresh_reaches_the_helper_and_returns_its_time(self):
        fake = FakeService()
        self.assertIs(accel.service(app), fake)
        self.assertEqual(accel.refresh_rect('/art/new_moscow.kra', (10, 20, 300, 400), app), 7)
        self.assertEqual(fake.calls, [('/art/new_moscow.kra', 10, 20, 300, 400)])

    def test_no_document_or_an_unknown_protocol_is_none(self):
        FakeService()
        self.assertIsNone(accel.refresh_rect('/missing.kra', (0, 0, 1, 1), app))
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None)
        FakeService(version=99)
        self.assertIsNone(accel.service(app), 'a helper from another protocol is not used')


class PaintStrokesTests(unittest.TestCase):
    STROKE = {'start': [1, 2], 'segments': [[3, 4, 5, 6, 7, 8]], 'color': '#806040'}

    def tearDown(self):
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def test_strokes_go_in_groups_with_the_plugin_defaults_filled_in(self):
        fake = FakeService()
        result = accel.paint_strokes('/art/x.kra', '{layer}', [dict(self.STROKE)] * 150, {'size': 12, 'opacity': 0.5}, group=64, app=app)
        groups = [call[3] for call in fake.calls]
        self.assertEqual([len(g) for g in groups], [64, 64, 22], 'Stop is checked between groups')
        self.assertEqual(groups[0][0], {'start': [1, 2], 'segments': [[3, 4, 5, 6, 7, 8]], 'color': '#806040', 'size': 12, 'opacity': 0.5, 'flow': 1},
                         'the same defaults as cmd_curve_stroke')
        self.assertEqual((result['strokes'], result['jobs'], result['groups']), (150, 3, 3))

    def test_pressure_per_point_travels_inline_as_the_helper_reads_it(self):
        fake = FakeService()
        stroke = {'start': [1, 2], 'segments': [[3, 4, 5, 6, 7, 8], [9, 10, 11, 12, 13, 14]], 'color': '#806040', 'pressure': [0.2, 0.9, 0.4]}
        accel.paint_strokes('/art/x.kra', '{layer}', [stroke], {}, app=app)
        sent = fake.calls[0][3][0]
        self.assertEqual(sent['start'], [1, 2, 0.2])
        self.assertEqual(sent['segments'], [[3, 4, 5, 6, 7, 8, 0.9], [9, 10, 11, 12, 13, 14, 0.4]])
        self.assertNotIn('pressure', sent)
        self.assertEqual(stroke['start'], [1, 2], 'the caller\'s stroke is left as it was')

    # Protocol 5: the pen beyond pressure, as Krita's tablet input gives it (stroke_points.h): after pressure on each
    # point come x tilt, y tilt, rotation, speed and time; values a stroke does not set take a mouse's (1, 0, 0, 0, 0, 0).
    def test_tilt_rotation_speed_and_time_travel_inline_after_pressure(self):
        fake = FakeService(version=5)
        stroke = {'start': [1, 2], 'segments': [[3, 4, 5, 6, 7, 8], [9, 10, 11, 12, 13, 14]], 'color': '#806040',
                  'tilt': [[0, 0], [30, -10], [60, 5]], 'rotation': [0, 90, -45], 'speed': [0, 0.5, 1], 'time_ms': [0, 120, 300]}
        result = accel.paint_strokes('/art/x.kra', '{layer}', [stroke], {}, app=app)
        sent = fake.calls[0][3][0]
        self.assertEqual(sent['start'], [1, 2, 1, 0, 0, 0, 0, 0])
        self.assertEqual(sent['segments'], [[3, 4, 5, 6, 7, 8, 1, 30, -10, 90, 0.5, 120], [9, 10, 11, 12, 13, 14, 1, 60, 5, -45, 1, 300]])
        self.assertFalse({'tilt', 'rotation', 'speed', 'time_ms'} & set(sent))
        self.assertNotIn('ignored', result)
        self.assertEqual(stroke['start'], [1, 2], 'the caller\'s stroke is left as it was')

    def test_one_pen_input_alone_leaves_the_others_at_a_mouse_s_values(self):
        fake = FakeService(version=5)
        stroke = {'start': [1, 2], 'segments': [[3, 4, 5, 6, 7, 8]], 'color': '#806040', 'pressure': [0.2, 0.9], 'speed': [0.1, 0.7]}
        accel.paint_strokes('/art/x.kra', '{layer}', [stroke], {}, app=app)
        sent = fake.calls[0][3][0]
        self.assertEqual((sent['start'], sent['segments'][0][6:]), ([1, 2, 0.2, 0, 0, 0, 0.1, 0], [0.9, 0, 0, 0, 0.7, 0]))

    def test_a_pressure_only_stroke_keeps_the_protocol_4_format(self):
        fake = FakeService(version=5)
        accel.paint_strokes('/art/x.kra', '{layer}', [dict(self.STROKE, pressure=[0.3, 0.6])], {}, app=app)
        sent = fake.calls[0][3][0]
        self.assertEqual((sent['start'], sent['segments']), ([1, 2, 0.3], [[3, 4, 5, 6, 7, 8, 0.6]]))

    def test_an_older_helper_paints_pressure_and_says_which_inputs_it_ignored(self):
        fake = FakeService(version=4)
        stroke = dict(self.STROKE, pressure=[0.3, 0.6], tilt=[[0, 0], [40, 0]], time_ms=[0, 100])
        result = accel.paint_strokes('/art/x.kra', '{layer}', [stroke], {}, app=app)
        sent = fake.calls[0][3][0]
        self.assertEqual((sent['start'], sent['segments']), ([1, 2, 0.3], [[3, 4, 5, 6, 7, 8, 0.6]]), 'a protocol-4 helper reads pressure only')
        self.assertEqual(result['ignored'], ['tilt', 'time_ms'])

    def test_a_protocol_5_helper_is_known(self):
        fake = FakeService(version=5)
        self.assertIs(accel.service(app, 5), fake)
        self.assertEqual(accel.refresh_rect('/art/x.kra', (0, 0, 1, 1), app), 7)

    def test_stop_between_groups_and_no_helper(self):
        fake = FakeService()
        result = accel.paint_strokes('/art/x.kra', '{layer}', [self.STROKE] * 150, {}, group=64, app=app, stop=lambda: len(fake.calls) == 1)
        self.assertEqual((result['strokes'], result['stopped_after_strokes']), (64, 64))
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None)
        self.assertIsNone(accel.paint_strokes('/art/x.kra', '{layer}', [self.STROKE], {}, app=app))


class SelectionTests(unittest.TestCase):
    """The magic wand and the colour range in the helper: the mask comes back for its bounding rect only."""
    def tearDown(self):
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def test_a_seed_selection_comes_back_as_its_rect_and_mask(self):
        fake = FakeService()
        found = accel.select_contiguous('/art/x.kra', (3, 4), 24, (0, 0, 6000, 4500), app)
        self.assertEqual(fake.calls, [('contiguous', '/art/x.kra', 3, 4, 24, 0, 0, 6000, 4500)])
        self.assertEqual(found, ((2, 3, 3, 2), bytes([255, 255, 0, 0, 255, 255])))

    def test_a_colour_range_sends_the_colour_and_bounds(self):
        fake = FakeService()
        found = accel.select_similar('', '#1e140a', 0, (10, 20, 30, 40), app)
        self.assertEqual(fake.calls, [('similar', '', '#1e140a', 0, 10, 20, 30, 40)])
        self.assertEqual(found[0], (2, 3, 3, 2))

    def test_nothing_selected_is_an_empty_rect_not_a_failure(self):
        fake = FakeService(); fake.MASK = (0, 0, 0, 0, b'')
        self.assertEqual(accel.select_contiguous('/art/x.kra', (0, 0), 24, (0, 0, 4, 4), app), ((0, 0, 0, 0), b''))

    def test_a_failure_or_no_helper_is_none_so_the_python_path_runs(self):
        self.assertIsNone(accel.select_contiguous('/art/x.kra', (0, 0), 24, (0, 0, 4, 4), app), 'no helper')
        self.assertIsNone(accel.select_similar('/art/x.kra', '#000000', 24, (0, 0, 4, 4), app))
        self.assertIsNone(accel.selection_outline((0, 0, 1, 1), b'\xff', app))
        FakeService()
        self.assertIsNone(accel.select_contiguous('/missing.kra', (0, 0), 24, (0, 0, 4, 4), app), 'no such document')
        self.assertIsNone(accel.select_similar('/missing.kra', '#000000', 24, (0, 0, 4, 4), app))
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None)
        FakeService(version=2)
        self.assertIsNone(accel.select_contiguous('/art/x.kra', (0, 0), 24, (0, 0, 4, 4), app), 'a protocol-2 helper has no builders')

    def test_a_mask_of_the_wrong_size_is_refused(self):
        fake = FakeService(); fake.MASK = (0, 0, 4, 4, bytes(3))
        self.assertIsNone(accel.select_similar('/art/x.kra', '#000000', 24, (0, 0, 4, 4), app))

    def test_an_outline_is_polygons_in_canvas_pixels(self):
        fake = FakeService()
        polygons = accel.selection_outline((2, 3, 3, 2), bytes([255] * 6), app)
        self.assertEqual(polygons, [[[2, 3], [5, 3], [5, 5], [2, 5]]])
        self.assertEqual(fake.calls, [('outline', (2, 3, 3, 2), bytes([255] * 6))])
        self.assertEqual(accel.selection_outline((0, 0, 0, 0), b'', app), [], 'nothing selected has no outline')


class BuildSelectionTests(unittest.TestCase):
    """Protocol 4: every seed and colour step of a select in one call, one mask back."""
    STEPS = [{'seed': [3, 4], 'tolerance': 10, 'grow': 2}, {'color': '#1e140a', 'bounds': [0, 0, 8, 8], 'mode': 'subtract', 'invert': True}]

    def tearDown(self):
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def test_the_steps_go_in_one_call_without_their_refinements(self):
        fake = FakeService(version=4)
        found = accel.build_selection('/art/x.kra', self.STEPS, app)
        self.assertEqual(fake.calls, [('build', '/art/x.kra', [{'seed': [3, 4], 'tolerance': 10},
                                                               {'color': '#1e140a', 'bounds': [0, 0, 8, 8], 'mode': 'subtract'}])])
        self.assertEqual(found, ((2, 3, 3, 2), bytes([255, 255, 0, 0, 255, 255])))
        self.assertEqual(accel.build_timings(app)['total'], 230)
        self.assertEqual(self.STEPS[0]['grow'], 2, "the caller's steps are left as they were")

    def test_a_protocol_4_helper_still_answers_the_protocol_3_calls(self):
        fake = FakeService(version=4)
        self.assertEqual(accel.select_contiguous('/art/x.kra', (3, 4), 24, (0, 0, 6, 6), app)[0], (2, 3, 3, 2))
        self.assertEqual(accel.refresh_rect('/art/x.kra', (0, 0, 1, 1), app), 7)
        self.assertEqual(len(fake.calls), 2)

    def test_without_a_protocol_4_helper_or_the_document_it_is_none(self):
        self.assertIsNone(accel.build_selection('/art/x.kra', self.STEPS, app), 'no helper')
        self.assertIsNone(accel.build_timings(app))
        fake = FakeService(version=3)
        self.assertIsNone(accel.build_selection('/art/x.kra', self.STEPS, app), 'a protocol-3 helper builds step by step')
        self.assertEqual(fake.calls, [])
        self.assertIsNotNone(accel.select_similar('/art/x.kra', '#000000', 24, (0, 0, 4, 4), app), 'and still has its builders')
        fake.setParent(None)
        FakeService(version=4)
        self.assertIsNone(accel.build_selection('/missing.kra', self.STEPS, app), 'no such document')


class ProbeTests(unittest.TestCase):
    """The proof: the same document, the full refresh the plugin uses today against the helper's area refresh."""
    class Doc:
        def __init__(self): self.refreshed = 0
        def fileName(self): return '/art/new_moscow.kra'
        def width(self): return 6000
        def height(self): return 4500
        def refreshProjection(self): self.refreshed += 1
        def waitForDone(self): pass

    def tearDown(self):
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def test_both_refreshes_are_timed_on_the_same_area(self):
        fake, doc = FakeService(), self.Doc()
        result = accel.probe(doc, (100, 200, 512, 512), app)
        self.assertEqual(doc.refreshed, 1, 'one full refresh, as observe does today')
        self.assertEqual(fake.calls, [('/art/new_moscow.kra', 100, 200, 512, 512)])
        self.assertEqual((result['helper'], result['region_ms'], result['rect']), (True, 7, [100, 200, 512, 512]))
        self.assertIsInstance(result['full_ms'], int)

    def test_without_the_helper_the_probe_says_so(self):
        result = accel.probe(self.Doc(), (0, 0, 10, 10), app)
        self.assertEqual((result['helper'], result['region_ms']), (False, None))


class StrokeProbeTests(unittest.TestCase):
    """Where a chunk of strokes spends its time, with the calls a real pass makes, on a layer that is removed after."""
    def test_each_phase_is_timed_and_the_layer_is_removed(self):
        events = []
        class Layer:
            def paintPath(self, path, stroke, fill): events.append('paint')
            def remove(self): events.append('remove')
        class Doc:
            def __init__(self): self.layer = Layer()
            def width(self): return 6000
            def height(self): return 4500
            def createNode(self, name, kind): events.append(('create', kind)); return self.layer
            def rootNode(self): return type('Root', (), {'addChildNode': lambda _s, node, above: events.append('add')})()
            def setActiveNode(self, node): events.append('active')
            def waitForDone(self): events.append('wait')
            def refreshProjection(self): events.append('refresh')
        plugin = type('Plugin', (), {'_apply_brush_state': lambda _s, view, **kw: events.append('brush')})()
        result = accel.stroke_probe(Doc(), None, plugin, count=5)
        self.assertEqual(events.count('brush'), 5); self.assertEqual(events.count('paint'), 5)
        self.assertEqual(events[-1], 'remove', 'the probe layer is gone afterwards')
        self.assertEqual(set(result['ms']), {'brush', 'queue', 'paint_wait', 'full_refresh'})
        self.assertEqual(result['strokes'], 5)


class SelectCompareTests(unittest.TestCase):
    """The same seed and colour steps through the Python path and the helper (region_craft._region_colour, native off
    and on): the time of each and how many pixels differ."""
    class Selection:
        def __init__(self, mask): self.mask = mask
        def pixelData(self, x, y, w, h): return self.mask[:w * h]

    class Plugin:
        def __init__(self, test):
            self.test, self.calls = test, []
        def _region_colour(self, doc, step, source, native=True):
            self.calls.append((source, native, step))
            mask = bytearray([255] * 8 + [0] * 8)
            if native and source == 'color':
                mask[15] = 255                            # one pixel the helper disagrees on
            return SelectCompareTests.Selection(bytes(mask))

    class Doc:
        def width(self): return 4
        def height(self): return 4

    def tearDown(self):
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def test_each_step_is_timed_both_ways_and_compared(self):
        FakeService()
        plugin = self.Plugin(self)
        steps = [{'seed': [1, 1], 'tolerance': 10}, {'color': '#ffffff', 'bounds': [0, 0, 4, 4]}]
        result = accel.select_compare(self.Doc(), plugin, steps, app=app)
        self.assertEqual([(source, native) for source, native, _step in plugin.calls],
                         [('seed', False), ('seed', True), ('color', False), ('color', True)])
        self.assertTrue(result['helper'])
        self.assertEqual([row['differing_pixels'] for row in result['steps']], [0, 1])
        self.assertEqual([row['selected_pixels'] for row in result['steps']], [8, 8])
        self.assertEqual(set(result['steps'][0]['ms']), {'python', 'native'})
        self.assertEqual(set(result['ms']), {'python', 'native'})
        self.assertIn('speedup', result)

    def test_seeded_steps_by_default(self):
        FakeService()
        plugin = self.Plugin(self)
        result = accel.select_compare(self.Doc(), plugin, None, count=3, tolerance=12, app=app)
        steps = [step for _s, native, step in plugin.calls if native]
        self.assertEqual(len(steps), 3)
        self.assertTrue(all(step['tolerance'] == 12 and 0 <= step['seed'][0] < 4 and 0 <= step['seed'][1] < 4 for step in steps))
        self.assertEqual(steps, [row['step'] for row in result['steps']])

    def test_without_the_helper_nothing_runs(self):
        plugin = self.Plugin(self)
        self.assertEqual(accel.select_compare(self.Doc(), plugin, None, app=app), {'helper': False})
        self.assertEqual(plugin.calls, [])


class PenCompareTests(unittest.TestCase):
    """pen_probe: one stroke without the pen input and one with it changing along the stroke, through the helper, each
    on a temporary layer, measured for thickness at five points; the layers are removed and the selection restored."""
    class Layer:
        def __init__(self, events, name): self.events, self.name = events, name
        def uniqueId(self): return type('Id', (), {'toString': lambda _s: '{%s}' % self.name})()
        def pixelData(self, x, y, w, h):
            # A band whose painted rows grow from left to right, so the five points read differently.
            return bytes(v for row in range(h) for col in range(w) for v in (0, 0, 0, 255 if row < 1 + col * h // w else 0))
        def remove(self): self.events.append(('remove', self.name))

    class Doc:
        def __init__(self, events): self.events, self.chosen = events, 'artist selection'
        def width(self): return 400
        def height(self): return 200
        def fileName(self): return '/art/probe.kra'
        def selection(self): return self.chosen
        def setSelection(self, selection): self.chosen = selection; self.events.append(('selection', selection))
        def createNode(self, name, kind): return PenCompareTests.Layer(self.events, name)
        def rootNode(self): return type('Root', (), {'addChildNode': lambda _s, node, above: self.events.append(('add', node.name))})()
        def waitForDone(self): pass

    def tearDown(self):
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def _plugin(self, events):
        return type('Plugin', (), {'cmd_set_brush': lambda _s, params: events.append(('brush', params['preset']))})()

    def test_tilt_changes_along_one_stroke_and_not_the_other(self):
        fake, events = FakeService(version=5), []
        doc = self.Doc(events)
        result = accel.pen_compare(doc, self._plugin(events), 'tilt', size=20)
        plain, varied = [call[3][0] for call in fake.calls]
        self.assertEqual(len(plain['start']), 2, 'the plain stroke carries no pen input')
        self.assertEqual([plain['start'][2:]] + [s[6:] for s in plain['segments']], [[], [], []])
        self.assertEqual([varied['start'][3:5]] + [s[7:9] for s in varied['segments']], accel.PEN_RAMPS['tilt'])
        self.assertEqual(events[0], ('brush', accel.PEN_PRESETS['tilt']), 'a tilt-sensitive preset by default')
        self.assertEqual((result['helper'], result['input'], result['values']), (True, 'tilt', accel.PEN_RAMPS['tilt']))
        self.assertEqual(len(result['thickness']['plain']), 5); self.assertEqual(len(result['thickness']['varied']), 5)
        self.assertEqual([e for e in events if e[0] == 'remove'], [('remove', 'Creative Agent · pen plain'), ('remove', 'Creative Agent · pen tilt')])
        self.assertEqual(doc.chosen, 'artist selection', 'the selection is put back')

    def test_speed_time_and_rotation_each_have_a_ramp_and_a_preset(self):
        for name in ('rotation', 'speed', 'time_ms'):
            fake = FakeService(version=5)
            result = accel.pen_compare(self.Doc([]), self._plugin([]), name, preset='b) Basic-5 Size')
            self.assertEqual((result['input'], result['preset']), (name, 'b) Basic-5 Size'))
            self.assertEqual(len(accel.PEN_RAMPS[name]), 3, 'one value per point: the start and two segment ends')
            self.assertIn(name, accel.PEN_PRESETS)
            self.assertEqual(len(fake.calls), 2)
            fake.setParent(None)

    def test_an_older_helper_says_so_and_unknown_inputs_are_refused(self):
        FakeService(version=4)
        result = accel.pen_compare(self.Doc([]), self._plugin([]), 'speed')
        self.assertEqual(result['ignored'], ['speed'], 'a protocol-4 helper paints both strokes the same')
        with self.assertRaises(ValueError):
            accel.pen_compare(self.Doc([]), self._plugin([]), 'colour')

    def test_without_the_helper_nothing_is_measured(self):
        events = []
        self.assertEqual(accel.pen_compare(self.Doc(events), self._plugin(events), 'tilt'), {'helper': False})
        self.assertIn(('remove', 'Creative Agent · pen plain'), events, 'the probe layer is gone afterwards')

    def test_pressure_compare_keeps_its_answer(self):
        FakeService(version=5)
        result = accel.pressure_compare(self.Doc([]), self._plugin([]), size=20)
        self.assertEqual((result['pressure'], set(result['thickness'])), (accel.TAPER, {'full', 'taper'}))


class RegionRefreshTests(unittest.TestCase):
    """Protocol 7: refresh_region recomposites the rect grown by every effect that spreads a change outside it, and
    says which rect that was. An older helper recomposited exactly the rect (a stale halo), so it is never asked."""
    def tearDown(self):
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def test_a_region_refresh_answers_the_rect_it_recomposited(self):
        fake = FakeService(version=7)
        answer = accel.refresh_region('/art/new_moscow.kra', (10, 20, 300, 400), app=app)
        self.assertEqual(answer, {'ms': 9, 'rect': (2, 12, 316, 416), 'requested': (10, 20, 300, 400)})
        self.assertEqual(fake.calls, [('region', '/art/new_moscow.kra', 10, 20, 300, 400)])

    def test_the_grown_rect_is_cut_to_the_canvas(self):
        FakeService(version=7)
        self.assertEqual(accel.refresh_region('/art/x.kra', (0, 0, 10, 10), app=app)['rect'], (0, 0, 18, 18))

    def test_an_older_helper_is_never_asked_for_a_region(self):
        fake = FakeService(version=6)
        self.assertIsNone(accel.refresh_region('/art/x.kra', (0, 0, 10, 10), app=app), 'it would leave the halo stale')
        self.assertEqual(fake.calls, [])
        self.assertEqual(accel.refresh_rect('/art/x.kra', (0, 0, 10, 10), app), 7, 'refresh_rect still works on it')

    def test_no_document_or_no_helper_is_none(self):
        self.assertIsNone(accel.refresh_region('/art/x.kra', (0, 0, 10, 10), app=app))
        FakeService(version=7)
        self.assertIsNone(accel.refresh_region('/missing.kra', (0, 0, 10, 10), app=app))

    def test_a_protocol_7_helper_still_answers_the_older_calls(self):
        fake = FakeService(version=7)
        self.assertIs(accel.service(app), fake)
        self.assertEqual(accel.refresh_rect('/art/x.kra', (0, 0, 1, 1), app), 7)
        self.assertIsNotNone(accel.save_in_background('/art/x.kra', app=app))
        self.assertEqual((accel.PROTOCOL, accel.KNOWN[-1]), (7, 7))


class BackgroundSaveTests(unittest.TestCase):
    """Protocol 6: save_in_background starts Krita's background save of a document to its own file and answers a job;
    save_status reports it; wait_for_save lets Krita run until the job ends. None without a protocol-6 helper."""
    def tearDown(self):
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def test_a_save_starts_and_reports_its_job_until_done(self):
        fake = FakeService(version=6)
        job = accel.save_in_background('/art/painting.kra', app=app)
        self.assertEqual(job, 1)
        self.assertEqual(accel.save_status(job, app=app)['state'], 'running')
        done = accel.wait_for_save(job, timeout=5, app=app, pause=0)
        self.assertEqual((done['state'], done['file'], done['clean']), ('done', '/art/painting.kra', True))
        self.assertEqual(fake.calls[0], ('save', '/art/painting.kra'))

    def test_a_failed_save_is_failed_with_its_reason_and_never_done(self):
        FakeService(version=6)
        failed = accel.wait_for_save(accel.save_in_background('/fails.kra', app=app), timeout=5, app=app, pause=0)
        self.assertEqual((failed['state'], failed['error']), ('failed', 'disk full'))
        self.assertEqual(accel.save_status(99, app=app)['state'], 'failed', 'an unknown job is never reported saved')

    def test_waiting_gives_up_at_the_timeout_with_the_job_still_running(self):
        fake = FakeService(version=6); fake.running = 10 ** 6
        status = accel.wait_for_save(accel.save_in_background('/art/painting.kra', app=app), timeout=0.05, app=app, pause=0)
        self.assertEqual(status['state'], 'running')

    def test_no_document_or_no_protocol_6_helper_is_none(self):
        FakeService(version=6)
        self.assertIsNone(accel.save_in_background('/missing.kra', app=app))
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None)
        FakeService(version=5)
        self.assertIsNone(accel.save_in_background('/art/painting.kra', app=app), 'a protocol-5 helper cannot save')
        self.assertIsNone(accel.save_status(1, app=app))
        self.assertIsNone(accel.wait_for_save(1, app=app))
        self.assertIn(6, accel.KNOWN)


class SaveCompareTests(unittest.TestCase):
    """save_probe: the plugin's synchronous save and the helper's background save of the open painting, each timed,
    with a timer on the main thread measuring how long Krita's main thread could not run it."""
    class Doc:
        def __init__(self, path='/art/painting.kra'): self.path = path
        def fileName(self): return self.path
        def width(self): return 6000
        def height(self): return 4500
        def waitForDone(self): pass

    def tearDown(self):
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def _plugin(self, saves, block=0.0):
        import time
        def save(params):
            saves.append(params['path']); time.sleep(block)
            return {'status': 'ok', 'path': params['path']}
        return type('Plugin', (), {'cmd_save_native': lambda _s, params: save(params)})()

    def test_both_saves_are_timed_and_the_blocking_one_shows_its_block(self):
        fake, saves = FakeService(version=6), []
        result = accel.save_compare(self.Doc(), self._plugin(saves, block=0.12), rounds=2, tick_ms=5, app=app)
        self.assertTrue(result['helper'])
        self.assertEqual(saves, ['/art/painting.kra'] * 2, 'the synchronous save is the checkpoint\'s own')
        self.assertEqual([c for c in fake.calls if c[0] == 'save'], [('save', '/art/painting.kra')] * 2)
        self.assertEqual(len(result['rounds']), 2)
        for row in result['rounds']:
            self.assertGreaterEqual(row['sync']['max_gap_ms'], 100, 'the synchronous save held the main thread')
            self.assertEqual(row['background']['state'], 'done')
            self.assertLess(row['background']['max_gap_ms'], 100, 'the background save let the timer run')
            self.assertIn('start_ms', row['background']); self.assertIn('helper_ms', row['background'])
            self.assertIn('ticks', row['sync']); self.assertIn('late_ticks', row['background'])
        self.assertEqual((result['file'], result['canvas'], result['tick_ms']), ('/art/painting.kra', [6000, 4500], 5))

    def test_without_the_helper_only_the_synchronous_save_runs(self):
        saves = []
        result = accel.save_compare(self.Doc(), self._plugin(saves), rounds=1, tick_ms=5, app=app)
        self.assertFalse(result['helper'])
        self.assertEqual(len(saves), 1); self.assertNotIn('background', result['rounds'][0])

    def test_an_unsaved_painting_is_refused(self):
        with self.assertRaises(ValueError):
            accel.save_compare(self.Doc(''), self._plugin([]), app=app)


class ThicknessTests(unittest.TestCase):
    def test_thickness_counts_covered_rows_in_a_column(self):
        w, h = 4, 6
        alpha = [0, 0, 0, 0,  0, 255, 0, 0,  0, 255, 30, 0,  0, 255, 30, 0,  0, 10, 0, 0,  0, 255, 0, 0]
        data = bytes(v for a in alpha for v in (0, 0, 0, a))
        self.assertEqual([accel.thickness(data, w, h, x) for x in range(4)], [0, 4, 2, 0])


if __name__ == '__main__':
    unittest.main()

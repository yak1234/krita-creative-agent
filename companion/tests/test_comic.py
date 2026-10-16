"""Comic pages, panel-scoped painting and lettering on a fake layer tree. Files go to a temporary folder that is removed."""
import sys
import tempfile
import unittest
import test_layer_craft as layer_tests

native = layer_tests.native
craft = layer_tests.craft
comic = sys.modules.get('creative_test_package.comic') or __import__('creative_test_package.comic', fromlist=['x'])
comic_layout = sys.modules['creative_test_package.comic_layout']
lettering = sys.modules['creative_test_package.lettering']
measure = lambda line: len(line) * 10          # every character 10 pixels wide


class VectorLayer(layer_tests.Node):
    def __init__(self, doc, name):
        super().__init__(doc, name, 'vectorlayer'); self.svg = []
    def addShapesFromSvg(self, svg): self.svg.append(svg); return []
    def setLocked(self, value): self.is_locked = value


class Page(layer_tests.TreeDocument):
    def width(self): return 1200
    def height(self): return 1800
    def createVectorLayer(self, name): return VectorLayer(self, name)


class Harness(layer_tests.Harness):
    _creative_new_layer = native.module.CreativeTools._creative_new_layer
    def __init__(self, folder):
        super().__init__(); self.doc = Page()
        self._creative_session.update(document_id=native.module.document_id(self.doc), output=folder, width=1200, height=1800)
        self._craft_manifest_cache = layer_tests.capabilities.manifest(self.app, self.doc)
    def _comic_fonts(self): return {'Comic Neue', 'sans-serif'}
    def _comic_measure(self, font, size): return measure


def run(h, operation, params, identifier):
    return h.cmd_creative({'operation': operation, 'session_id': 'session', 'operation_id': identifier, 'params': params})


def children(node): return [child.name() for child in node.childNodes()]


class LayoutTests(unittest.TestCase):
    def test_four_rows_of_two_are_equal_with_gutters_and_margins(self):
        panels = comic_layout.panels({'preset': 'grid-2x4', 'margin': 40, 'gutter': 20}, 1200, 1800)
        self.assertEqual([p['id'] for p in panels], ['P%d' % i for i in range(1, 9)])
        self.assertEqual(panels[0]['bounds'], [40, 40, 550, 415])
        self.assertEqual(panels[1]['bounds'][0] - (panels[0]['bounds'][0] + panels[0]['bounds'][2]), 20, 'gutter between columns')
        self.assertEqual(panels[2]['bounds'][1] - (panels[0]['bounds'][1] + panels[0]['bounds'][3]), 20, 'gutter between rows')
        last = panels[-1]['bounds']
        self.assertEqual((last[0] + last[2], last[1] + last[3]), (1160, 1760), 'margin to the page edge')
        self.assertEqual(len({tuple(p['bounds'][2:]) for p in panels}), 1, 'all the same size')

    def test_manga_reading_order_starts_top_right(self):
        panels = comic_layout.panels({'preset': 'grid-2x2', 'reading': 'rtl'}, 1200, 1800)
        self.assertGreater(panels[0]['bounds'][0], panels[1]['bounds'][0])
        self.assertEqual(panels[0]['row'], 1)

    def test_rows_with_their_own_columns(self):
        panels = comic_layout.panels({'rows': [2, 1], 'cols': [[1], [1, 1, 1]], 'margin': 0, 'gutter': 0}, 900, 900)
        self.assertEqual([p['bounds'] for p in panels], [[0, 0, 900, 600], [0, 600, 300, 300], [300, 600, 300, 300], [600, 600, 300, 300]])

    def test_invalid_layouts_are_refused(self):
        for layout, message in (({'rows': [1], 'cols': [[1] * 20], 'gutter': 40}, 'smaller than'), ({'rows': [1] * 5, 'cols': [[1] * 5] * 5}, 'at most 24'),
                                ({'preset': 'grid-2x2', 'rows': [1]}, 'not both'), ({'preset': 'nope'}, 'preset must be'),
                                ({'rows': [1, 1], 'cols': [[1]]}, 'one list'), ({'preset': 'single', 'reading': 'up'}, 'reading'),
                                ({'preset': 'single', 'colour': '#fff'}, 'Unknown')):
            with self.subTest(layout=layout), self.assertRaisesRegex(ValueError, message):
                comic_layout.panels(layout, 1200, 1800)


class LetteringTests(unittest.TestCase):
    def test_wrap_keeps_lines_within_the_width(self):
        self.assertEqual(lettering.wrap('one two three four', 100, measure), ['one two', 'three four'])
        self.assertEqual(lettering.wrap('extraordinarily', 50, measure), ['extraordinarily'], 'a long word stays whole')

    def test_caption_is_a_box_with_one_tspan_per_line(self):
        markup, bounds, lines = lettering.balloon('caption', 'The forest recedes & <dries>', [100, 50], 200, measure, size=20)
        self.assertIn('<rect x="100.0" y="50.0" width="200.0"', markup)
        self.assertEqual(markup.count('<tspan'), len(lines))
        self.assertIn('&amp; &lt;dries&gt;', markup, 'text is escaped')
        self.assertTrue(all(measure(line) <= 200 - 2 * 20 * 0.6 for line in lines))
        self.assertEqual(bounds[:3], [100, 50, 200])

    def test_speech_balloon_and_tail_are_one_outline(self):
        markup, bounds, _ = lettering.balloon('speech', 'Run!', [100, 100], 200, measure, tail_to=[180, 400])
        self.assertEqual(markup.count('<path'), 1)
        self.assertEqual(markup.count('<ellipse'), 0, 'no separate ellipse whose stroke would cross the tail')
        self.assertIn('180.0 400.0', markup)
        self.assertEqual(bounds[1] + bounds[3], 400, 'bounds reach the tail tip')

    def test_thought_and_shout_shapes(self):
        thought, _, _ = lettering.balloon('thought', 'Hmm', [0, 0], 200, measure, tail_to=[50, 300])
        self.assertEqual((thought.count('<ellipse'), thought.count('<circle')), (1, 3))
        shout, _, _ = lettering.balloon('shout', 'NOW', [0, 0], 200, measure)
        self.assertIn('<polygon', shout)

    def test_document_is_the_painting_size(self):
        self.assertTrue(lettering.document('<rect/>', 1200, 1800).startswith('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1800">'))


class ComicPageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        previous = comic.Selection
        comic.Selection = layer_tests.Area
        self.addCleanup(setattr, comic, 'Selection', previous)
        self.h = Harness(folder.name)

    def page(self, layout=None):
        return run(self.h, 'comic_page', dict(layout or {'preset': 'grid-2x2'}, stage_id='comic-page'), 'page')

    def test_page_structure_in_one_pass(self):
        artist = layer_tests.Node(self.h.doc, 'Sketch', 'paintlayer'); self.h.doc.root.addChildNode(artist, None)
        result = self.page()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        page = self.h.doc.root.childNodes()[-1]
        self.assertEqual(page.name(), 'Comic page')
        self.assertEqual(children(page), ['Page', 'Panel 1', 'Panel 2', 'Panel 3', 'Panel 4', 'Panel borders', 'Lettering'])
        self.assertEqual(len(self.h._creative_session['passes']), 1)
        model = result['comic']
        self.assertEqual([p['id'] for p in model['panels']], ['P1', 'P2', 'P3', 'P4'])
        for panel, group in zip(model['panels'], page.childNodes()[1:5]):
            self.assertEqual(panel['group_id'], group.id)
            mask = group.childNodes()[0]
            self.assertEqual((mask.type(), mask.name()), ('transparencymask', 'Panel shape'))
            self.assertEqual(mask.selection.rect, tuple(panel['bounds']) + (255,), 'the mask is the panel rectangle')
        borders = page.childNodes()[5]
        self.assertTrue(borders.locked(), 'borders are out of reach of panel art')
        self.assertEqual(borders.svg[0].count('<rect'), 4)
        self.assertIn('fill="none"', borders.svg[0])
        owned = self.h._creative_session['layers']
        self.assertTrue(all(node.id in owned for node in [page] + page.childNodes()))
        self.assertNotIn(artist.id, owned)
        self.assertEqual((artist.parent, self.h.doc.root.childNodes()[0]), (self.h.doc.root, artist), "the artist's layer stays put")

    def test_one_page_per_chat_and_resume_rebuilds_the_model(self):
        model = self.page()['comic']
        with self.assertRaisesRegex(ValueError, 'already has a comic page'):
            run(self.h, 'comic_page', {'preset': 'single'}, 'page-2')
        resumed = {'passes': [dict(entry) for entry in self.h._creative_session['passes']]}
        self.assertEqual(self.h._comic_model(resumed), model, 'the model comes back from the saved pass')

    def test_invalid_layout_changes_nothing(self):
        with self.assertRaisesRegex(ValueError, 'at most 24'):
            run(self.h, 'comic_page', {'rows': [1], 'cols': [[1] * 60]}, 'page')
        self.assertEqual((self.h.doc.root.childNodes(), self.h._creative_session['passes']), ([], []))

    def test_panel_scoped_layer_goes_into_the_panel_stage_group(self):
        model = self.page()['comic']
        result = run(self.h, 'create_layer', {'name': 'Sky', 'type': 'paint', 'panel': 'P2', 'stage_id': 'move-1'}, 'sky')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        layer = self.h._creative_node(self.h.doc, result['layer_id'])
        stage = layer.parentNode()
        self.assertEqual(stage.parentNode().id, model['panels'][1]['group_id'], 'inside P2, clipped by its mask')
        self.assertTrue(stage.name().startswith('Creative Agent'))
        self.assertEqual(self.h._creative_session['passes'][-1]['panel'], 'P2')
        again = run(self.h, 'create_layer', {'name': 'Ground', 'type': 'paint', 'panel': 'P2', 'stage_id': 'move-1'}, 'ground')
        self.assertIs(self.h._creative_node(self.h.doc, again['layer_id']).parentNode(), stage, 'the move reuses its group in the panel')

    def test_panel_scoped_paint_pass(self):
        model = self.page()['comic']
        result = run(self.h, 'paint_pass', {'name': 'Figure', 'preset': 'b) Basic-1', 'panel': 'P3', 'stage_id': 'stage-1-0',
                                            'strokes': [{'start': [300, 1000], 'segments': [[320, 1020, 360, 1060, 400, 1100]], 'size': 10, 'opacity': 1, 'flow': 1, 'color': '#336699'}]}, 'figure')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        layer = self.h._creative_node(self.h.doc, result['layer_id'])
        self.assertEqual(layer.parentNode().parentNode().id, model['panels'][2]['group_id'])

    def test_panel_refusals_change_nothing(self):
        with self.assertRaisesRegex(ValueError, 'no comic page'):
            run(self.h, 'create_layer', {'name': 'Early', 'type': 'paint', 'panel': 'P1'}, 'early')
        self.page()
        passes = len(self.h._creative_session['passes'])
        with self.assertRaisesRegex(ValueError, 'Unknown panel P9'):
            run(self.h, 'create_layer', {'name': 'Lost', 'type': 'paint', 'panel': 'P9'}, 'lost')
        outside = run(self.h, 'create_layer', {'name': 'Base', 'type': 'paint', 'panel': 'P1', 'clip_base': True}, 'base')
        with self.assertRaisesRegex(ValueError, 'not inside panel P2'):
            run(self.h, 'create_layer', {'name': 'Shade', 'type': 'paint', 'panel': 'P2', 'clip_to': outside['layer_id']}, 'shade')
        self.assertEqual(len(self.h._creative_session['passes']), passes + 1, 'only the valid layer was recorded')

    def test_letter_adds_one_text_layer_in_lettering(self):
        model = self.page()['comic']
        x, y = model['panels'][0]['bounds'][:2]
        result = run(self.h, 'letter', {'panel': 'P1', 'kind': 'caption', 'text': 'The once-continuous forest begins to recede.',
                                        'at': [x + 20, y + 20], 'width': 300, 'font': 'Missing Font'}, 'caption')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        layer = self.h._creative_node(self.h.doc, result['layer_id'])
        self.assertEqual((layer.name(), layer.parentNode().id), ('text · caption P1', model['lettering_id']))
        self.assertIn('<tspan', layer.svg[0])
        self.assertIn('font-family="sans-serif"', layer.svg[0])
        self.assertIn('not installed', result['note'])
        self.assertEqual(self.h._creative_session['passes'][-1]['kind'], 'letter')

    def test_letter_refusals(self):
        model = self.page()['comic']
        x, y, w, h = model['panels'][0]['bounds']
        for params, message in (({'kind': 'caption', 'text': 'x', 'at': [x + w + 50, y]}, 'at x'),
                                ({'kind': 'caption', 'text': 'x', 'at': [x, y], 'tail_to': [x, y + 10]}, 'speech and thought'),
                                ({'kind': 'whisper', 'text': 'x', 'at': [x, y]}, 'kind must be'),
                                ({'kind': 'speech', 'text': ' ', 'at': [x, y]}, 'nonempty'),
                                ({'kind': 'speech', 'text': 'x' * 401, 'at': [x, y]}, 'nonempty')):
            with self.subTest(params=params), self.assertRaisesRegex(ValueError, message):
                run(self.h, 'letter', dict(params, panel='P1'), 'bad-%d' % len(str(params)))
        self.assertEqual(len(self.h._creative_session['passes']), 1)

    def test_page_reject_waits_for_panel_work(self):
        self.page()
        run(self.h, 'create_layer', {'name': 'Sky', 'type': 'paint', 'panel': 'P1', 'stage_id': 'move-1'}, 'sky')
        with self.assertRaisesRegex(ValueError, 'kept panel work'):
            run(self.h, 'review_pass', {'pass_id': 'page', 'action': 'reject'}, 'reject-page')
        page = self.h._creative_node(self.h.doc, self.h._creative_session['passes'][0]['layer_id'])
        self.assertTrue(page.visible())
        self.assertEqual(run(self.h, 'review_pass', {'pass_id': 'sky', 'action': 'reject'}, 'reject-sky')['status'], 'ok')
        self.assertEqual(run(self.h, 'review_pass', {'pass_id': 'page', 'action': 'reject'}, 'reject-page-2')['status'], 'ok')
        self.assertFalse(page.visible())
        self.assertIsNone(self.h._comic_model(self.h._creative_session), 'a rejected page has no panels')


if __name__ == '__main__':
    unittest.main()

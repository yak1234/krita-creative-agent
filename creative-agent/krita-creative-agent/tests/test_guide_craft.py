# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Guide layers (guided trace): draw_guide and finish_guide on a fake layer tree of our Krita (Node.paintStrokes).
The study folder is a temporary folder that is removed."""
import contextlib
import sys
import types
import unittest
import test_region_craft as region_tests

native = region_tests.native
run = region_tests.run
module = native.module
guide = sys.modules['creative_test_package.guide_craft']
STROKE = {'start': [1, 1], 'segments': [[1, 1, 2, 2, 3, 3]], 'size': 2, 'opacity': 1, 'flow': 1, 'color': '#806040'}
LINE = {'start': [0, 2], 'segments': [[1, 2, 3, 2, 4, 2]]}


class Job:
    """A stroke job that has painted everything by the time it is asked."""
    def __init__(self, n): self.n = n
    def state(self): return 'done'
    def wait(self, ms=-1): return True
    def strokesDone(self): return self.n
    def strokesTotal(self): return self.n
    def errorString(self): return ''
    def elapsedMs(self): return 1
    def changedRect(self): return types.SimpleNamespace(x=lambda: 0, y=lambda: 0, width=lambda: 0, height=lambda: 0)


class Layer(region_tests.Layer):
    """A fork layer: paintStrokes marks its first pixel, and each line's colour where it starts; mergeDown and remove as
    Krita."""
    def paintStrokes(self, strokes, options=None, selection=None):
        self.doc.jobs.append((self, [dict(s) for s in strokes], dict(options or {}), selection))
        self.pixels[0:4] = bytes([255, 179, 79, 255])
        for stroke in strokes:
            x, y = (min(3, max(0, int(v))) for v in stroke['start'])
            colour = bytes.fromhex(stroke['color'][1:])
            self.pixels[(y * 4 + x) * 4:(y * 4 + x) * 4 + 4] = bytes([colour[2], colour[1], colour[0], 255])
        return Job(len(strokes))
    def mergeDown(self):
        parent = self.parent; index = parent.children.index(self); below = parent.children[index - 1]
        merged = Layer(self.doc, below.label, 'paintlayer')
        merged.pixels = bytearray(max(a, b) for a, b in zip(below.pixels, self.pixels))
        parent.children[index - 1:index + 1] = [merged]; merged.parent = parent
        return merged
    def remove(self):
        self.parent.children.remove(self); self.parent = None; return True


class Document(region_tests.Document):
    def __init__(self):
        super().__init__(); self.root = Layer(self, 'root', 'grouplayer'); self.jobs = []
        background = Layer(self, 'Background', 'paintlayer'); self.root.addChildNode(background, None)
        self.annotations = {}
    def createNode(self, name, kind): return Layer(self, name, kind)
    def setAnnotation(self, kind, description, data): self.annotations[kind] = bytes(data)
    def annotation(self, kind): return self.annotations.get(kind, b'')


class Harness(region_tests.Harness):
    _creative_new_layer = module.CreativeTools._creative_new_layer
    def __init__(self, folder):
        super().__init__(folder); self.doc = Document()
        self._creative_session['document_id'] = module.document_id(self.doc)
        self.observed = []
    def _creative_observe(self, doc, session, region=None, guides=True):
        self.observed.append(guides)
        return {'status': 'ok', 'document_id': module.document_id(doc), 'image_path': '/tmp/view.png', 'revision': 'current-revision'}


class GuideSetup(region_tests.RegionSetup):
    def setUp(self):
        super().setUp()
        self.h = Harness(self.h._creative_session['output'])
        prior = module._FORK
        module._FORK = True                                      # our Krita: Node.paintStrokes
        self.addCleanup(setattr, module, '_FORK', prior)

    def guide(self, element='Towers', strokes=None, identifier=None, stage='move-1'):
        return run(self.h, 'draw_guide', {'element': element, 'strokes': strokes or [LINE], 'stage_id': stage}, identifier or 'guide-' + element)

    def stroke(self, name, stage='move-1'):
        return run(self.h, 'paint_pass', {'name': name, 'preset': 'b) Basic-1', 'strokes': [STROKE], 'stage_id': stage}, name)

    def node(self, identifier):
        return self.h._creative_node(self.h.doc, identifier)

    def guides_group(self):
        return next(c for c in self.h.doc.root.children if c.name() == 'Guides · Creative Agent')


class DrawGuideTests(GuideSetup, unittest.TestCase):
    def test_draw_guide_creates_its_layer_in_the_guides_group(self):
        painted = self.stroke('Walls')
        result = self.guide()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        layer = self.node(result['layer_id'])
        self.assertEqual(layer.name(), 'Guide · Towers')
        group = layer.parentNode()
        self.assertEqual((group.name(), group.type()), ('Guides · Creative Agent', 'grouplayer'))
        self.assertIs(group.parentNode(), self.h.doc.root, 'outside every stage group')
        self.assertIs(self.h.doc.root.children[-1], group, 'at the top of the painting')
        self.assertNotEqual(self.node(painted['layer_id']).parentNode(), group)
        self.assertEqual(layer.opacity(), round(0.7 * 255))
        self.assertFalse(layer.locked(), 'never locked: the agent paints and finishes its own guides')
        _node, strokes, options, selection = self.h.doc.jobs[-1]
        self.assertEqual(options['preset'], 'b) Basic-1')
        self.assertIsNone(selection)
        self.assertEqual([(s['color'], s['opacity'], s['flow']) for s in strokes], [('#4fb3ff', 1, 1)], 'the guide brush is forced')
        self.assertEqual([s['size'] for s in strokes], [3], 'a contour line by default, its width from the canvas size')
        entry = next(p for p in self.h._creative_session['passes'] if p['id'] == 'guide-Towers')
        self.assertEqual((entry['kind'], entry['stage_id'], entry['layer_id'], entry['element']), ('guide', 'move-1', result['layer_id'], 'Towers'))
        self.assertIn(result['layer_id'], self.h._creative_session['layers'])

    def test_a_second_guide_in_the_same_move_extends_its_layer(self):
        first = self.guide(identifier='g1')
        second = self.guide(element='  towers ', strokes=[dict(LINE, weight='contour')], identifier='g2')
        other = self.guide(element='Sky', identifier='g3')
        self.assertEqual(first['layer_id'], second['layer_id'], 'names match case-insensitively: one element, one layer per move')
        self.assertNotEqual(first['layer_id'], other['layer_id'])
        self.assertEqual(len(self.guides_group().children), 2)
        self.assertEqual(self.h.doc.jobs[1][1][0]['size'], 3, 'a guide line takes its weight\'s width')
        self.assertEqual(len([c for c in self.h.doc.root.children if c.name() == 'Guides · Creative Agent']), 1)
        later = self.guide(stage='move-2', identifier='g4')
        self.assertNotEqual(later['layer_id'], first['layer_id'], 'a later move draws on a layer of its own')

    def test_rejecting_a_later_move_keeps_the_earlier_guide(self):
        first = self.guide(identifier='g1')
        later = self.guide(stage='move-2', identifier='g2')
        run(self.h, 'review_pass', {'pass_id': 'stage:move-2', 'action': 'reject'}, 'undo-move-2')
        self.assertTrue(self.node(first['layer_id']).visible(), 'the accepted lines of move 1 stay')
        self.assertFalse(self.node(later['layer_id']).visible())
        tidied = run(self.h, 'tidy_kept', {'stage_id': 'move-2'})
        self.assertEqual(tidied['removed_layers'], 0, 'tidy never deletes a guide layer')
        self.assertIn(self.node(later['layer_id']), self.guides_group().children)

    def test_guides_group_is_found_by_its_id_after_a_rename(self):
        first = self.guide(identifier='g1')
        group = self.guides_group(); group.setName('My guides')
        second = self.guide(element='Sky', identifier='g2')
        self.assertIs(self.node(second['layer_id']).parentNode(), group, 'the renamed group is still the guides group')
        self.assertEqual(len([c for c in self.h.doc.root.children if c.type() == 'grouplayer' and c.name() in ('My guides', 'Guides · Creative Agent')]), 1)
        self.assertTrue(self.h._guide_in_group(self.node(first['layer_id'])))
        # Moved into a stage group, it keeps that group out of merge_agent_work, so its guides are never flattened.
        painted = self.stroke('Walls')
        stage = self.node(painted['layer_id']).parentNode()
        self.h.doc.root.children.remove(group); stage.addChildNode(group, None)
        runs = []
        self.h.doc.mergeGroups = lambda groups: runs.append([g.name() for g in groups]) or groups[0]
        self.h.doc.agentMove = lambda name: contextlib.nullcontext()
        self.h._native_merge_signature = lambda doc: b'same'
        self.h._creative_session = None
        result = self.h._native_merge_agent(self.h.doc, {'dry_run': False})
        self.assertEqual((result['groups'], runs), (0, []), 'a stage group holding the guides group is not merged')

    def test_guide_layers_are_refused_as_targets(self):
        drawn = self.guide()
        painted = self.stroke('Walls')
        for operation, params in (('adjust_layer', {'layer_id': drawn['layer_id'], 'opacity': 0.5}),
                                  ('transform_layer', {'layer_id': drawn['layer_id'], 'move': [1, 1]}),
                                  ('apply_filter', {'target': drawn['layer_id'], 'filter': 'gaussian blur', 'mode': 'copy'}),
                                  ('paint_pass', {'name': 'Shadow', 'preset': 'b) Basic-1', 'strokes': [STROKE], 'clip_to': drawn['layer_id']})):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, 'guide layer'):
                    run(self.h, operation, params, 'target-' + operation)
        self.assertTrue(self.node(painted['layer_id']).visible())

    def test_a_new_stage_group_goes_below_the_guides_group(self):
        self.guide()
        painted = self.stroke('Walls')
        group = self.guides_group()
        self.assertIs(self.h.doc.root.children[-1], group, 'guides stay on top of new paint')
        again = self.stroke('Roofs')
        self.assertEqual(painted['group_id'], again['group_id'], 'the stage group under the guides is reused')

    def test_reject_of_the_move_hides_the_guide(self):
        painted = self.stroke('Walls')
        drawn = self.guide()
        result = run(self.h, 'review_pass', {'pass_id': 'stage:move-1', 'action': 'reject'}, 'undo-move')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertIn('guide-Towers', result['affected_pass_ids'])
        self.assertFalse(self.node(drawn['layer_id']).visible())
        self.assertFalse(self.node(painted['layer_id']).visible())
        again = self.guide(stage='move-2', identifier='guide-again')
        self.assertNotEqual(again['layer_id'], drawn['layer_id'], 'a rejected guide is never painted on again')
        self.assertTrue(self.node(again['layer_id']).visible())

    def test_finish_guide_hides_and_is_idempotent(self):
        drawn = self.guide()
        finished = run(self.h, 'finish_guide', {'element': 'towers'}, 'finish-1')
        self.assertEqual((finished['status'], finished['layer_id'], finished['visible']), ('ok', drawn['layer_id'], False))
        self.assertFalse(self.node(drawn['layer_id']).visible())
        self.assertEqual(finished['image_path'], '/tmp/view.png', 'the painter sees the canvas without it')
        again = run(self.h, 'finish_guide', {'element': 'Towers'}, 'finish-2')
        self.assertEqual((again['status'], again['visible'], again.get('unchanged')), ('ok', False, True))
        self.assertFalse(any(p['kind'] == 'finish_guide' for p in self.h._creative_session['passes']), 'not a pass')
        # The move's undo still works on a finished guide: its recorded state follows the hide.
        result = run(self.h, 'review_pass', {'pass_id': 'stage:move-1', 'action': 'reject'}, 'undo-move')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        with self.assertRaisesRegex(ValueError, "no guide for 'Sky'"):
            run(self.h, 'finish_guide', {'element': 'Sky'}, 'finish-3')
        drawn = self.guide(stage='move-2', identifier='after-finish')
        self.assertTrue(self.node(drawn['layer_id']).visible(), 'a guide drawn after finishing is a fresh layer')

    def test_finish_guide_leaves_a_guide_the_artist_painted_on(self):
        drawn = self.guide()
        self.node(drawn['layer_id']).pixels[4:8] = bytes([0, 0, 255, 255])          # the artist's red dab on the guide layer
        finished = run(self.h, 'finish_guide', {'element': 'Towers'}, 'finish')
        self.assertEqual(finished['status'], 'ok')
        self.assertTrue(self.node(drawn['layer_id']).visible(), "the artist's paint is never hidden")
        self.assertIn('painted on', finished['note'])
        self.assertEqual(finished['kept_showing'], ['Guide · Towers'])

    def test_hide_guides_hides_every_guide_in_one_step(self):
        steps = []
        doc = self.h.doc
        doc.agentMoveOpen = lambda: bool(steps and steps[-1][1])
        doc.beginAgentMove = lambda name: steps.append([name, True]) or True
        doc.agentMoveId = lambda: len(steps)
        doc.endAgentMove = lambda: steps[-1].__setitem__(1, False)
        towers, sky, car = self.guide(identifier='g1'), self.guide(element='Sky', identifier='g2'), self.guide(element='Car', identifier='g3')
        steps.clear()
        run(self.h, 'finish_guide', {'element': 'Sky'}, 'finish-sky')
        self.node(car['layer_id']).pixels[4:8] = bytes([0, 0, 255, 255])           # the artist painted on the car's guide
        steps.clear()
        result = run(self.h, 'hide_guides', {})
        self.assertEqual(result['hidden'], 1)
        self.assertEqual([name for name, _open in steps], ['Hide guides'], 'one undo step')
        self.assertFalse(self.node(towers['layer_id']).visible())
        self.assertTrue(self.node(car['layer_id']).visible())
        self.assertEqual(result['kept_showing'], ['Guide · Car'])
        self.assertEqual(run(self.h, 'hide_guides', {})['hidden'], 0, 'again: nothing to hide')

    def test_health_and_view_options(self):
        prior = module.Krita
        module.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(version=lambda: '6.0.0-agent'))
        self.addCleanup(setattr, module, 'Krita', prior)
        self.h._creative_adapter_capabilities = lambda: {}
        self.h._native_actions = lambda version: []
        self.assertIs(self.h.cmd_creative({'operation': 'health', 'params': {}}).get('guides_view'), True, 'a companion can ask for views without guides')
        self.assertFalse(self.h._creative_session.get('unguided_views'))
        self.assertEqual(run(self.h, 'view_options', {'unguided_views': True})['unguided_views'], True)
        self.assertTrue(self.h._creative_session['unguided_views'])
        with self.assertRaises(ValueError):
            run(self.h, 'view_options', {'unguided_views': 'yes'})
        # luna-goal-reviewer goal 3: the views' long side, set by the companion (what the painter's model reads).
        self.assertIs(self.h.cmd_creative({'operation': 'health', 'params': {}}).get('view_side'), True)
        self.assertEqual(run(self.h, 'view_options', {'view_side': 2048})['view_side'], 2048)
        self.assertEqual(self.h._creative_session['view_side'], 2048)
        self.assertTrue(self.h._creative_session['unguided_views'], 'one option set leaves the other as it was')
        for bad in (100, 9000, '2048', True):
            with self.assertRaises(ValueError):
                run(self.h, 'view_options', {'view_side': bad})

    def test_merge_passes_and_merge_agent_ignore_guides(self):
        a, b = self.stroke('Walls'), self.stroke('Towers')
        drawn = self.guide()
        merged = run(self.h, 'merge_passes', {'stage_id': 'move-1', 'name': 'Move 1 · Kremlin'}, 'merge-1')
        self.assertEqual(merged['merged_layers'], 2)
        guide_layer = self.node(drawn['layer_id'])
        self.assertTrue(guide_layer.visible())
        self.assertIs(guide_layer.parentNode(), self.guides_group(), 'kept as a separate guide layer')
        entry = next(p for p in self.h._creative_session['passes'] if p['id'] == 'guide-Towers')
        self.assertNotIn('merged_into', entry)
        # Ad hoc merge of the painting's kept agent groups: the guides group is not one of them.
        runs = []
        self.h.doc.mergeGroups = lambda groups: runs.append([g.name() for g in groups]) or groups[0]
        self.h.doc.agentMove = lambda name: contextlib.nullcontext()
        self.h._native_merge_signature = lambda doc: b'same'
        self.h._creative_session = None
        result = self.h._native_merge_agent(self.h.doc, {'dry_run': False})
        self.assertEqual(result['groups'], 1)
        self.assertTrue(runs and all('Guides · Creative Agent' not in names for names in runs))
        self.assertIn(self.guides_group(), self.h.doc.root.children)

    def test_tidy_keeps_hidden_guides(self):
        drawn = self.guide()
        self.stroke('Walls')
        rejected = self.stroke('Roofs')
        run(self.h, 'review_pass', {'pass_id': 'Roofs', 'action': 'reject'}, 'reject-roofs')
        run(self.h, 'finish_guide', {'element': 'Towers'}, 'finish')
        kept = run(self.h, 'tidy_kept', {'stage_id': 'move-1'})
        self.assertEqual(kept['removed_layers'], 1, 'the rejected pass goes, the finished guide stays')
        self.assertIn(self.node(drawn['layer_id']), self.guides_group().children)
        with self.assertRaises(ValueError):
            self.node(rejected['layer_id'])
        self.h._creative_session = None
        result = self.h._native_tidy(self.h.doc, {'dry_run': False})
        self.assertEqual(result['layers'], 0)
        self.assertIn(self.node(drawn['layer_id']), self.guides_group().children, 'the artist may show it again')
        self.assertFalse(self.node(drawn['layer_id']).visible())

    def test_line_weights_scale_with_the_canvas(self):
        """Construction about 0.08 % and contour about 0.16 % of the long side, each within its bounds; light lines as
        wide as contours. A 4800 px canvas gets 4 and 8 px lines, visible at fit-to-screen."""
        self.assertEqual(guide.guide_widths(4800, 3200), {'construction': 4, 'contour': 8, 'light': 8})
        self.assertEqual(guide.guide_widths(2400, 3600), {'construction': 3, 'contour': 6, 'light': 6}, 'the long side, either way')
        self.assertEqual(guide.guide_widths(800, 600), {'construction': 2, 'contour': 3, 'light': 3}, 'never thinner than the minimums')
        self.assertEqual(guide.guide_widths(30000, 20000), {'construction': 8, 'contour': 16, 'light': 16}, 'never past the maximums')

    def test_each_line_is_drawn_in_its_weight(self):
        lines = [dict(LINE, weight='construction'), dict(LINE, weight='contour'), dict(LINE, weight='light', start=[3, 3]), dict(LINE)]
        result = self.guide(strokes=lines)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        _node, strokes, _options, _selection = self.h.doc.jobs[-1]
        self.assertEqual([(s['size'], s['color']) for s in strokes],
                         [(2, '#4fb3ff'), (3, '#4fb3ff'), (3, '#ffb347'), (3, '#4fb3ff')],
                         'construction thin, contour the default, light in the warm guide colour')
        self.assertTrue(all((s['opacity'], s['flow']) == (1, 1) for s in strokes))
        entry = next(p for p in self.h._creative_session['passes'] if p['id'] == 'guide-Towers')
        self.assertEqual(entry['guide_raws'], {'#4fb3ff': 'ffb34f', '#ffb347': '47b3ff'},
                         'both guide colours are recorded as the document stores them, for the rebuild')

    def test_replace_tightens_an_element_guide(self):
        """replace: true hides the element's earlier guide and draws on a new layer, in the same move; undoing the move
        shows the rough guide again."""
        rough = self.guide(identifier='rough')
        sky = self.guide(element='Sky', identifier='sky')
        tight = run(self.h, 'draw_guide', {'element': 'towers', 'strokes': [LINE], 'stage_id': 'move-2', 'replace': True}, 'tight')
        self.assertEqual(tight['status'], 'ok', tight.get('error'))
        self.assertNotEqual(tight['layer_id'], rough['layer_id'])
        self.assertFalse(self.node(rough['layer_id']).visible(), 'the rough guide is hidden, not stacked under the tight one')
        self.assertTrue(self.node(tight['layer_id']).visible())
        self.assertTrue(self.node(sky['layer_id']).visible(), 'only the element\'s own guide')
        self.assertEqual(tight['replaced'], ['Guide · Towers'])
        run(self.h, 'review_pass', {'pass_id': 'stage:move-2', 'action': 'reject'}, 'undo-tight')
        self.assertFalse(self.node(tight['layer_id']).visible())
        self.assertTrue(self.node(rough['layer_id']).visible(), 'undoing the tightening move brings the rough guide back')
        # In the same move, replace starts a fresh layer rather than extending this move's.
        again = run(self.h, 'draw_guide', {'element': 'Towers', 'strokes': [LINE], 'stage_id': 'move-1', 'replace': True}, 'again')
        self.assertNotEqual(again['layer_id'], rough['layer_id'])
        self.assertFalse(self.node(rough['layer_id']).visible())
        # A guide the artist painted on is never hidden, not even by a tightening pass.
        painted = self.guide(element='Car', identifier='car')
        self.node(painted['layer_id']).pixels[4:8] = bytes([0, 0, 255, 255])
        car = run(self.h, 'draw_guide', {'element': 'Car', 'strokes': [LINE], 'stage_id': 'move-3', 'replace': True}, 'car-tight')
        self.assertTrue(self.node(painted['layer_id']).visible())
        self.assertIn('painted on', car['note'])
        # Nothing to replace: a plain new guide.
        fresh = run(self.h, 'draw_guide', {'element': 'Moon', 'strokes': [LINE], 'stage_id': 'move-3', 'replace': True}, 'moon')
        self.assertEqual((fresh['status'], fresh['replaced']), ('ok', []))

    def test_each_colour_records_its_own_stored_value_not_what_lies_on_top(self):
        """A warm light outline drawn over a blue silhouette on the same rim: the fake paints each line's colour where it
        starts, so the blue line's start ends up warm. Each colour's stored value comes from the colour itself."""
        silhouette = {'start': [1, 1], 'segments': [[1, 1, 2, 1, 3, 1]], 'weight': 'contour'}
        rim = {'start': [1, 1], 'segments': [[1, 1, 2, 1, 3, 1]], 'weight': 'light'}
        self.guide(element='Moon', strokes=[silhouette, rim], identifier='moon')
        entry = next(p for p in self.h._creative_session['passes'] if p['id'] == 'moon')
        self.assertEqual(entry['guide_raws'], {'#4fb3ff': 'ffb34f', '#ffb347': '47b3ff'})

    def test_sampled_values_skip_points_under_a_later_line_of_the_other_colour(self):
        """Where the colour cannot be converted (here: a profile the plugin does not know as sRGB, and no ManagedColor),
        a colour is read back from the layer, but never where a later line of the other colour covers it."""
        self.h.doc.colorProfile = lambda: 'AdobeRGB-elle-V2-g22.icc'
        silhouette = {'start': [1, 1], 'segments': [[1, 1, 2, 1, 3, 1]], 'weight': 'contour'}
        rim = {'start': [1, 1], 'segments': [[1, 1, 2, 1, 3, 1]], 'weight': 'light'}
        self.guide(element='Moon', strokes=[silhouette, rim], identifier='moon')
        entry = next(p for p in self.h._creative_session['passes'] if p['id'] == 'moon')
        self.assertEqual(entry['guide_raws'], {'#ffb347': '47b3ff'}, 'no value for blue rather than the warm one')

    def test_a_failed_tightening_job_leaves_the_rough_guide_showing(self):
        rough = self.guide(identifier='rough')
        failing = Job(1); failing.state = lambda: 'failed'; failing.errorString = lambda: 'refused'
        original = Layer.paintStrokes
        Layer.paintStrokes = lambda layer, strokes, options=None, selection=None: failing
        self.addCleanup(setattr, Layer, 'paintStrokes', original)
        tight = run(self.h, 'draw_guide', {'element': 'Towers', 'strokes': [LINE], 'stage_id': 'move-2', 'replace': True}, 'tight')
        self.assertEqual(tight['status'], 'rejected')
        self.assertTrue(self.node(rough['layer_id']).visible(), 'nothing painted, nothing replaced')

    def test_undoing_a_tightening_restores_only_a_guide_still_in_use(self):
        for finish in ('finish_guide', 'hide_guides'):
            with self.subTest(after=finish):
                self.setUp()
                rough = self.guide(identifier='rough')
                tight = run(self.h, 'draw_guide', {'element': 'Towers', 'strokes': [LINE], 'stage_id': 'move-2', 'replace': True}, 'tight')
                run(self.h, finish, {'element': 'Towers'} if finish == 'finish_guide' else {}, 'done')
                run(self.h, 'review_pass', {'pass_id': 'stage:move-2', 'action': 'reject'}, 'undo-tight')
                self.assertFalse(self.node(tight['layer_id']).visible())
                self.assertFalse(self.node(rough['layer_id']).visible(), 'the element was finished: its rough guide stays hidden')
        self.setUp()
        rough = self.guide(identifier='rough')
        tight = run(self.h, 'draw_guide', {'element': 'Towers', 'strokes': [LINE], 'stage_id': 'move-2', 'replace': True}, 'tight')
        run(self.h, 'review_pass', {'pass_id': 'stage:move-1', 'action': 'reject'}, 'undo-1')
        run(self.h, 'review_pass', {'pass_id': 'stage:move-2', 'action': 'reject'}, 'undo-2')
        self.assertFalse(self.node(rough['layer_id']).visible(), 'a rejected rough guide is never shown again')
        self.assertFalse(self.node(tight['layer_id']).visible())

    def test_guide_rejects_bad_input(self):
        bad = [
            {'element': '', 'strokes': [LINE]}, {'element': '   ', 'strokes': [LINE]}, {'element': 'x' * 61, 'strokes': [LINE]},
            {'element': 7, 'strokes': [LINE]}, {'element': 'Sky\nnow', 'strokes': [LINE]}, {'element': 'Sky\x7f', 'strokes': [LINE]},
            {'element': 'Sky\u2028now', 'strokes': [LINE]}, {'element': 'Sky\u2029', 'strokes': [LINE]}, {'element': '\u202eykS', 'strokes': [LINE]},
            {'element': 'Sky\u2066x\u2069', 'strokes': [LINE]}, {'element': 'Sky\u202a', 'strokes': [LINE]},
            {'element': 'Sky', 'strokes': []}, {'element': 'Sky', 'strokes': [LINE] * 257}, {'element': 'Sky', 'strokes': 'lines'},
            {'element': 'Sky', 'strokes': [LINE], 'name': 'x'}, {'element': 'Sky', 'strokes': [dict(LINE, pressure=[1, 1])]},
            {'element': 'Sky', 'strokes': [{'start': [0, 0]}]}, {'element': 'Sky', 'strokes': [dict(LINE, start=[float('nan'), 0])]},
            {'element': 'Sky', 'strokes': [dict(LINE, start=[10 ** 400, 0])]}, {'element': 'Sky', 'strokes': [dict(LINE, start=[900, 0])]},
            {'element': 'Sky', 'strokes': [dict(LINE, color='blue')]}, {'element': 'Sky', 'strokes': [dict(LINE, segments=[[1, 2, 3]])]},
            {'element': 'Sky'}, {'element': 'Sky', 'strokes': [dict(LINE, weight='bold')]},
            {'element': 'Sky', 'strokes': [dict(LINE, weight=2)]}, {'element': 'Sky', 'strokes': [dict(LINE, size=4)]}, {'element': 'Sky', 'strokes': [LINE], 'replace': 'yes'},
        ]
        for index, params in enumerate(bad):
            with self.subTest(params=str(params)[:80]):
                with self.assertRaises(ValueError):
                    run(self.h, 'draw_guide', params, 'bad-%d' % index)
        self.assertEqual(self.h.doc.jobs, [], 'nothing painted')
        self.assertFalse(any(c.name() == 'Guides · Creative Agent' for c in self.h.doc.root.children), 'no group made')
        with self.assertRaises(ValueError):
            run(self.h, 'finish_guide', {'element': 'Sky', 'extra': 1}, 'bad-finish')
        with self.assertRaises(ValueError):
            run(self.h, 'finish_guide', {'element': 'Sky\u202e'}, 'bad-finish-2')
        module._FORK = False
        with self.assertRaisesRegex(ValueError, 'our Krita'):
            self.guide(identifier='stock')


class ObserveWithoutGuidesTests(GuideSetup, unittest.TestCase):
    def test_guide_lines_do_not_make_a_blank_canvas_a_painting(self):
        """Block-in guides on a blank canvas measured 10% painted live (New Moscow, 2026-10-23), so the canvas was taken
        for an existing painting and the whole-picture underpainting was refused. The pixels a visible guide layer
        covers are left out of painted_share."""
        self.guide()
        layer = self.guides_group().children[0]
        white, blue, clear = bytes([255, 255, 255, 255]), bytes([79, 179, 255, 255]), bytes(4)
        class Thumb:                                                       # 10 x 10 pixels, rows 3-4 a guide band
            def __init__(self, rest, band): self.data = rest * 30 + band * 20 + rest * 50
        layer.thumbnail = lambda w, h: Thumb(clear, blue)
        self.h._creative_thumb_rgba = lambda image, size=96: (image.data, 10, 10)
        blank_with_guides = Thumb(white, blue)
        session = dict(self.h._creative_session)
        self.assertEqual(self.h._creative_painted_share(blank_with_guides, self.h.doc, session), 0.0)
        layer.setVisible(False)
        self.assertEqual(self.h._creative_painted_share(blank_with_guides, self.h.doc, session), 0.2,
                         'a hidden guide layer covers nothing')

    def test_painted_share_reads_the_painting_without_its_guides(self):
        """Live (2026-10-23, three chats): construction guides on a blank 6000 x 4500 canvas still measured 8-14%
        painted, and the whole-picture transfer was refused as 'this painting already exists'. Krita's layer thumbnail
        maps the layer's own extent, not the canvas, so its alpha does not line up with the canvas thumbnail. The share
        is read from the painting rebuilt without its guides first; the thumbnail cover is the fallback, widened by a
        pixel for the smoothing of the two scalings."""
        self.guide()
        layer = self.guides_group().children[0]
        white, blue, clear = bytes([255, 255, 255, 255]), bytes([79, 179, 255, 255]), bytes(4)
        class Thumb:
            def __init__(self, data): self.data = data
        layer.thumbnail = lambda w, h: Thumb(clear * 100)                  # misaligned: covers nothing
        self.h._creative_thumb_rgba = lambda image, size=96: (image.data, 10, 10)
        blank_with_guides = Thumb(white * 30 + blue * 20 + white * 50)
        rebuilt = []
        self.h._guide_unguided = lambda doc, image, region=None, session=None: rebuilt.append(region) or (Thumb(white * 100), None)
        session = dict(self.h._creative_session)
        self.assertEqual(self.h._creative_painted_share(blank_with_guides, self.h.doc, session), 0.0)
        self.assertEqual(rebuilt, [None], 'the whole canvas, once')
        # No rebuild (the guides lie under other layers): the cover, one pixel wider, takes a band its thumbnail missed.
        self.h._guide_unguided = lambda doc, image, region=None, session=None: (None, 'The guide lines lie under other layers.')
        layer.thumbnail = lambda w, h: Thumb(clear * 40 + blue * 10 + clear * 50)   # row 4 only; the view has rows 3-4
        self.assertEqual(self.h._creative_painted_share(blank_with_guides, self.h.doc, session), 0.0)

    def test_observe_rebuilds_the_painting_without_guides_once(self):
        """Review (2026-10-25): an observation that already tried the rebuild without guides (and got none) must not try
        it again for painted_share."""
        self.guide()
        h = self.h

        class Image:
            def width(self): return 4
            def height(self): return 4
            def isNull(self): return False
            def hasAlphaChannel(self): return False
            def save(self, path, *args):
                with open(path, 'wb') as stream:
                    stream.write(b'x')
                return True
        h.doc.projection = lambda *args: Image()
        h._creative_view_image = lambda doc, image, region=None, scaled_read=True, side=None: image
        h._view_artist_focus = lambda doc: None
        h._creative_thumb_rgba = lambda image, size=96: (bytes([255] * 64), 4, 4)
        asked = []
        h._guide_unguided = lambda doc, image, region=None, session=None: asked.append(region) or (None, 'The guide lines lie under other layers.')
        session = {'output': h._creative_session['output'], 'document_id': 'x', 'passes': []}
        module.CreativeTools._creative_observe(h, h.doc, session, None, guides=False)
        self.assertEqual(asked, [None], 'one rebuild an observation')

    def test_observe_passes_the_flag_and_refuses_a_bad_one(self):
        run(self.h, 'observe', {'guides': False})
        run(self.h, 'observe', {})
        self.assertEqual(self.h.observed, [False, True])
        with self.assertRaises(ValueError):
            run(self.h, 'observe', {'guides': 'no'})

    def test_observe_without_guides_changes_nothing_in_the_painting(self):
        """Hiding the guides for the read would be two undo steps on the fork (Node.setVisible): the painting under
        them is rebuilt from the pixels instead. The revision stays the painting's own, so it still gates the next
        pass. A look that keeps the guides saves the view without them too only while Luna uses it (view_options);
        a rebuild that cannot be made still observes, and says the guides are in the image."""
        self.guide()
        group = self.guides_group()
        changes = []
        for node in [group] + group.children:
            node.setVisible = lambda value, node=node: changes.append((node.name(), value))
        h = self.h

        class Image:
            def __init__(self, tag): self.tag = tag
            def width(self): return 4
            def height(self): return 4
            def isNull(self): return False
            def hasAlphaChannel(self): return False
            def save(self, path, *args):
                with open(path, 'wb') as stream:
                    stream.write(self.tag.encode())
                return True
        projection = Image('with guides')
        h.doc.projection = lambda *args: projection
        shown, asked = [], []
        h._creative_view_image = lambda doc, image, region=None, scaled_read=True, side=None: shown.append(image.tag) or image
        h._creative_painted_share = lambda image, *context: 0.5
        h._view_artist_focus = lambda doc: None
        h._guide_unguided = lambda doc, image, region=None, session=None: asked.append(region) or (Image('without guides'), None)
        session = {'output': h._creative_session['output'], 'document_id': 'x', 'passes': []}
        observe = lambda region=None, **flags: module.CreativeTools._creative_observe(h, h.doc, session, region, **flags)
        seen = observe(guides=False)
        self.assertEqual(shown, ['without guides'])
        self.assertEqual((seen['revision'], seen['guides_hidden']), ('current-revision', True))
        self.assertNotIn('unguided_path', seen)
        shown.clear(); asked.clear()
        seen = observe()
        self.assertEqual((shown, asked), (['with guides'], []), 'the painter alone looks: no second view is made')
        self.assertNotIn('unguided_path', seen)
        session['unguided_views'] = True                                  # Luna is on (view_options)
        seen = observe()
        self.assertEqual(shown[1:], ['with guides', 'without guides'])
        with open(seen['unguided_path']) as stream:
            self.assertEqual(stream.read(), 'without guides')
        asked.clear()
        observe([0, 0, 2, 2], guides=False)
        self.assertEqual(asked, [[0, 0, 2, 2]], 'a close-up rebuilds only its region')
        h._guide_unguided = lambda doc, image, region=None, session=None: (None, None)   # no visible guides: one view, as before
        shown.clear()
        seen = observe(guides=False)
        self.assertEqual(shown, ['with guides'])
        self.assertNotIn('guides_hidden', seen)
        self.assertNotIn('guides_note', seen)
        h._guide_unguided = lambda doc, image, region=None, session=None: (None, 'The guide lines lie under other layers.')
        seen = observe(guides=False)
        self.assertIn('under other layers', seen['guides_note'], 'the image has guides, and says so')
        h._guide_unguided = lambda doc, image, region=None, session=None: (_ for _ in ()).throw(RuntimeError('read failed'))
        shown.clear()
        seen = observe(guides=False)
        self.assertEqual(shown, ['with guides'])
        self.assertIn('read failed', seen['guides_note'])
        self.assertEqual(changes, [], 'no layer was hidden or shown for any look')

    def test_colour_samples_and_seams_read_the_painting_without_guides(self):
        self.guide()
        h = self.h

        class Colour:
            def __init__(self, value): self.value = value
            def red(self): return self.value
            def green(self): return self.value
            def blue(self): return self.value
            def alpha(self): return 255
        projection = types.SimpleNamespace(isNull=lambda: False, pixelColor=lambda x, y: Colour(200))
        clean = types.SimpleNamespace(isNull=lambda: False, pixelColor=lambda x, y: Colour(40))
        h.doc.projection = lambda *args: projection
        h.doc.refreshProjection = lambda *args: None
        asked = []
        h._guide_unguided = lambda doc, image, region=None, session=None: asked.append(region) or (clean, None)
        result = h.cmd_creative({'operation': 'sample_colors', 'params': {'points': [[1, 2]]}})
        self.assertEqual(result['samples'][0]['hex'], '#282828', 'the paint under the guide, not the guide')
        self.assertTrue(asked and all(r[2] * r[3] <= 17 * 17 for r in asked), 'only around the sampled points')
        seen = []
        seams = __import__('importlib').import_module('creative_test_package.seams')
        saved = seams.candidates, seams.close_ups
        seams.candidates = lambda bgra: seen.append(int(bgra[0, 0, 0])) or []
        seams.close_ups = lambda bgra, found, folder: []
        self.addCleanup(lambda: (setattr(seams, 'candidates', saved[0]), setattr(seams, 'close_ups', saved[1])))
        h._guide_unguided = lambda doc, image, region=None, session=None: (types.SimpleNamespace(tag='clean'), None)
        h._creative_image_bgra = lambda image: __import__('numpy').full((4, 4, 4), 7 if getattr(image, 'tag', '') == 'clean' else 99, 'uint8')
        h._creative_seam_candidates(h.doc, {'output': h._creative_session['output'], 'passes': []})
        self.assertEqual(seen, [7], 'seams are looked for in the painting, never along a guide line')

    def test_pass_images_are_of_the_painting_without_guides(self):
        self.h._creative_observe = lambda doc, session, region=None, guides=True: {
            'status': 'ok', 'image_path': '/tmp/before.png', 'unguided_path': '/tmp/before-clean.png', 'revision': 'current-revision'}
        self.h._creative_checkpoint = lambda doc, session, changed=True, wait=False: {
            'status': 'ok', 'image_path': '/tmp/after.png', 'unguided_path': '/tmp/after-clean.png'}
        result = self.stroke('Walls')
        self.assertEqual(result['image_path'], '/tmp/after.png', 'the painter sees its guides')
        entry = next(p for p in self.h._creative_session['passes'] if p['id'] == 'Walls')
        self.assertEqual((entry['before_path'], entry['after_path']), ('/tmp/before-clean.png', '/tmp/after-clean.png'))

    def test_strip_restores_the_painting_under_the_guides(self):
        np = __import__('numpy')
        sky = np.array([40, 60, 90, 255], np.uint8)
        guide_bgr = np.array([255, 179, 79], np.float32)                      # #4fb3ff as BGR
        painting = np.tile(sky, (1, 4, 1))
        cover = np.array([[0.7, 0.7, 0, 0]], np.float32)
        painting[0, :2, :3] = np.rint(guide_bgr * 0.7 + sky[:3] * 0.3)       # Krita's normal blend of a 70 % guide
        out, processed = guide.strip(painting, cover)
        self.assertEqual(processed, 2, 'only the covered pixels are worked on')
        self.assertTrue(np.abs(out.astype(int) - sky.astype(int)).max() <= 2)
        self.assertTrue((out[0, 2:] == painting[0, 2:]).all(), 'pixels without a guide are left exactly as they are')
        solid = np.tile(sky, (1, 4, 1)); solid[0, 0, :3] = guide_bgr
        filled, _ = guide.strip(solid, np.array([[1.0, 0, 0, 0]], np.float32))
        self.assertEqual(filled[0, 0].tolist(), sky.tolist(), 'a guide that covers fully is filled from around it')
        self.assertIs(guide.strip(painting, np.zeros((1, 4), np.float32))[1], 0)
        warm = np.array([71, 179, 255], np.float32)                           # #ffb347 as BGR
        mixed = np.tile(sky, (1, 4, 1))
        mixed[0, 0, :3] = np.rint(guide_bgr * 0.7 + sky[:3] * 0.3)
        mixed[0, 1, :3] = np.rint(warm * 0.7 + sky[:3] * 0.3)
        colours = np.zeros((1, 4, 3), np.float32); colours[0, 0] = guide_bgr; colours[0, 1] = warm
        out, processed = guide.strip(mixed, cover, guide=colours)
        self.assertEqual(processed, 2)
        self.assertTrue(np.abs(out.astype(int) - sky.astype(int)).max() <= 2, 'each pixel unblended with its own guide colour')


SIZE = (4096, 3072)
GUIDE_BGRA = (255, 179, 79, 255)


class BigNode:
    def __init__(self, name, kind, identifier, array=None, bounds=None):
        self.label, self.kind, self.identifier, self.array, self.box = name, kind, identifier, array, bounds
        self.children, self.parent, self.shown, self.reads = [], None, True, []
    def name(self): return self.label
    def type(self): return self.kind
    def visible(self): return self.shown
    def opacity(self): return 255
    def blendingMode(self): return 'normal'
    def childNodes(self): return list(self.children)
    def parentNode(self): return self.parent
    def uniqueId(self): return types.SimpleNamespace(toString=lambda: self.identifier)
    def add(self, node): self.children.append(node); node.parent = self; return node
    def bounds(self):
        x, y, w, h = self.box
        return types.SimpleNamespace(x=lambda: x, y=lambda: y, width=lambda: w, height=lambda: h)
    def projectionPixelData(self, x, y, w, h):
        self.reads.append((x, y, w, h))
        return self.array[y:y + h, x:x + w].tobytes()


class BigDocument:
    def __init__(self, model='RGBA', depth='U8', profile='sRGB-elle-V2-srgbtrc.icc'):
        self.model, self.depth, self.profile = model, depth, profile
        self.root = BigNode('root', 'grouplayer', 'root')
    def width(self): return SIZE[0]
    def height(self): return SIZE[1]
    def rootNode(self): return self.root
    def colorModel(self): return self.model
    def colorDepth(self): return self.depth
    def colorProfile(self): return self.profile


class UnguidedViewTests(GuideSetup, unittest.TestCase):
    """The painting without guides on a 4096 x 3072 canvas with a horizon and a vertical line (the guides group's own
    projection and the painting as numpy arrays): only the tiles the lines touched are read and only covered pixels
    are worked on."""
    LINES = [{'start': [0, 1501], 'segments': [[0, 1501, 4095, 1501, 4095, 1501]], 'size': 4},
             {'start': [2001, 0], 'segments': [[2001, 0, 2001, 3071, 2001, 3071]], 'size': 4}]

    def make(self, model='RGBA', depth='U8', raw=None, alpha=None, channels=4, dtype='uint8', colour=GUIDE_BGRA[:3]):
        np = __import__('numpy')
        w, h = SIZE
        doc = BigDocument(model, depth)
        group_array = np.zeros((h, w, channels), dtype)
        line = np.zeros((h, w), bool); line[1499:1503, :] = True; line[:, 1999:2003] = True
        self.line = line
        group_array[line, :-1] = colour
        group_array[line, -1] = alpha if alpha is not None else round(0.7 * 255)
        doc.root.add(BigNode('Background', 'paintlayer', 'bg', bounds=(0, 0, w, h)))
        group = doc.root.add(BigNode('Guides · Creative Agent', 'grouplayer', 'guides', group_array, (0, 0, w, h)))
        layer = group.add(BigNode('Guide · Horizon', 'paintlayer', 'guide-layer', bounds=(0, 0, w, h)))
        self.sky = np.array([40, 60, 90, 255], np.uint8)
        painting = np.empty((h, w, 4), np.uint8); painting[:] = self.sky
        painting[line, :3] = np.rint(np.array(GUIDE_BGRA[:3], np.float32) * 0.7 + self.sky[:3] * 0.3)
        self.painting = painting
        self.session = {'passes': [{'id': 'g1', 'kind': 'guide', 'element': 'Horizon', 'layer_id': 'guide-layer', 'group_id': 'guides',
                                    'stage_id': 'move-1', 'guide_tiles': guide.stroke_tiles(self.LINES, w, h),
                                    'guide_bounds': [0, 0, w, h], 'guide_raw': raw if raw is not None else bytes(GUIDE_BGRA[:3]).hex()}]}
        self.h._guide_painting_tile = lambda image, x, y, tw, th: image[y:y + th, x:x + tw].tobytes()
        def patched(image, patches):
            out = image.copy()
            for x, y, tw, th, data in patches:
                out[y:y + th, x:x + tw] = np.frombuffer(data, np.uint8).reshape(th, tw, 4)
            return out
        self.h._guide_patched = patched
        return doc, group, layer

    def check_clean(self, image, tolerance=2):
        np = __import__('numpy')
        difference = np.abs(image.astype(int) - self.sky.astype(int)).max(axis=-1)
        self.assertLessEqual(int(difference.max()), tolerance, 'the lines are gone, the sky is back')

    def linear_tolerance(self, cover):
        """Ruling: on a linear painting the rebuild reads the 8-bit sRGB view, which is the composite rounded to half a
        level. Unblending in linear light divides that rounding by 1 - coverage, and a dark sky's sRGB is steep in linear
        light, so the sky comes back only within this bound (in levels), plus one for the final rounding."""
        np = __import__('numpy')
        to_linear, to_srgb = guide._srgb_to_linear, guide._linear_to_srgb
        view = self.painting[..., :3][self.line_mask].astype(np.float32)
        spread = (to_linear(np.clip(view + 0.5, 0, 255)) - to_linear(np.clip(view - 0.5, 0, 255))) / 2 / (1 - cover)
        sky = to_linear(self.sky[:3].astype(np.float32))
        return int(np.ceil((to_srgb(sky + spread) - to_srgb(sky)).max())) + 1

    def test_a_horizon_and_a_vertical_line_never_make_the_work_span_the_canvas(self):
        doc, group, _layer = self.make()
        image, note = self.h._guide_unguided(doc, self.painting, None, self.session)
        self.assertIsNone(note)
        self.check_clean(image)
        canvas = SIZE[0] * SIZE[1]
        read = sum(w * h for _x, _y, w, h in group.reads)
        self.assertLess(read, canvas * 0.08, 'only the tiles the two lines touched are read (%d of %d pixels)' % (read, canvas))
        self.assertLess(max(w * h for _x, _y, w, h in group.reads), canvas * 0.05, 'no single read spans the canvas')
        self.assertEqual(self.h._guide_work['pixels'], int(self.line.sum()), 'only covered pixels are worked on')

    def test_light_lines_in_the_warm_colour_are_rebuilt_too(self):
        """A light line (#ffb347) crossing the blue horizon: both colours recorded, the crossing a mix of the two, and
        all of it taken out of the view without a note."""
        np = __import__('numpy')
        doc, group, _layer = self.make()
        warm = np.array([0x47, 0xb3, 0xff], np.float32)
        light = np.zeros(self.line.shape, bool); light[:, 2999:3003] = True
        group.array[light, :3] = warm.astype(np.uint8)
        group.array[light, 3] = round(0.7 * 255)
        crossing = light & self.line
        group.array[crossing, :3] = np.rint(warm * 0.5 + np.array(GUIDE_BGRA[:3]) * 0.5).astype(np.uint8)   # anti-aliased overlap
        cover = round(0.7 * 255) / 255                                              # the coverage the group's alpha byte holds
        self.painting[light, :3] = np.rint(group.array[light, :3].astype(np.float32) * cover + self.sky[:3] * (1 - cover))
        self.session['passes'].append({'id': 'g2', 'kind': 'guide', 'element': 'Moon', 'layer_id': 'guide-layer', 'group_id': 'guides',
                                       'stage_id': 'move-1', 'guide_tiles': guide.stroke_tiles(
                                           [{'start': [3001, 0], 'segments': [[3001, 0, 3001, 3071, 3001, 3071]], 'size': 4}], *SIZE),
                                       'guide_bounds': [0, 0, *SIZE], 'guide_raws': {'#4fb3ff': 'ffb34f', '#ffb347': '47b3ff'}})
        image, note = self.h._guide_unguided(doc, self.painting, None, self.session)
        self.assertIsNone(note)
        self.check_clean(image)
        # The artist's own paint is still told apart from either guide colour.
        group.array[100, 3001] = (0, 200, 0, 255)
        image, note = self.h._guide_unguided(doc, self.painting, None, self.session)
        self.assertIsNone(image)
        self.assertIn('painted on', note)

    def test_unrecorded_eight_bit_guides_know_both_colours(self):
        np = __import__('numpy')
        doc, group, _layer = self.make()
        for entry in self.session['passes']:
            entry.pop('guide_raw')
        group.array[self.line, :3] = (0x47, 0xb3, 0xff)
        cover = round(0.7 * 255) / 255                                              # the coverage the group's alpha byte holds
        self.painting[self.line, :3] = np.rint(np.array([0x47, 0xb3, 0xff], np.float32) * cover + self.sky[:3] * (1 - cover))
        image, note = self.h._guide_unguided(doc, self.painting, None, self.session)
        self.assertIsNone(note)
        self.check_clean(image)

    def crossing(self, depth='U8', dtype='uint8', scale=255.0, linear=False):
        """A blue horizon and a warm vertical light line that cross, in the given depth (and linear light), each line
        recorded with its own colour's tiles and stored value. Returns (doc, group)."""
        np = __import__('numpy')
        w, h = SIZE
        to_linear, to_srgb = guide._srgb_to_linear, guide._linear_to_srgb
        doc = BigDocument('RGBA', depth, 'Rec2020-elle-V4-g10.icc' if linear else 'sRGB-elle-V2-srgbtrc.icc')
        blue, warm = np.array(GUIDE_BGRA[:3], np.float32), np.array([0x47, 0xb3, 0xff], np.float32)   # 8-bit sRGB BGR
        stored = (lambda bgr: to_linear(bgr)) if linear else (lambda bgr: bgr / 255.0)
        order = (lambda bgr: bgr[::-1]) if dtype.startswith('float') else (lambda bgr: bgr)     # float RGBA is RGB in memory
        horizon = np.zeros((h, w), bool); horizon[1499:1503, :] = True
        light = np.zeros((h, w), bool); light[:, 2999:3003] = True
        group_array = np.zeros((h, w, 4), dtype)
        a = round(0.7 * scale) / scale if dtype == 'uint8' or dtype == 'uint16' else 0.7
        for mask, value in ((horizon, stored(blue)), (light, stored(warm)), (horizon & light, (stored(blue) + stored(warm)) / 2)):
            group_array[mask, :3] = (order(value) * scale).astype(dtype) if dtype.startswith('float') else np.rint(order(value) * scale).astype(dtype)
            group_array[mask, 3] = np.array(a * scale, dtype) if dtype.startswith('float') else round(a * scale)
        self.sky = np.array([40, 60, 90, 255], np.uint8)
        painting = np.empty((h, w, 4), np.uint8); painting[:] = self.sky
        covered = horizon | light
        colour = group_array[..., :3].astype(np.float32) / scale
        colour = colour[..., ::-1] if dtype.startswith('float') else colour                       # back to BGR
        if linear:
            mixed = to_srgb(colour[covered] * a + to_linear(self.sky[:3].astype(np.float32)) * (1 - a))
        else:
            mixed = colour[covered] * 255.0 * a + self.sky[:3] * (1 - a)
        painting[covered, :3] = np.rint(mixed).clip(0, 255).astype(np.uint8)
        self.painting, self.line_mask, self.cover = painting, covered, a
        doc.root.add(BigNode('Background', 'paintlayer', 'bg', bounds=(0, 0, w, h)))
        group = doc.root.add(BigNode('Guides · Creative Agent', 'grouplayer', 'guides', group_array, (0, 0, w, h)))
        group.add(BigNode('Guide · Scene', 'paintlayer', 'guide-layer', bounds=(0, 0, w, h)))
        raw = lambda bgr: (np.array(order(stored(bgr)) * scale, dtype) if dtype.startswith('float')
                           else np.rint(order(stored(bgr)) * scale).astype(dtype)).tobytes().hex()
        vertical = [{'start': [3001, 0], 'segments': [[3001, 0, 3001, 3071, 3001, 3071]], 'size': 4}]
        self.session = {'passes': [
            {'id': 'g1', 'kind': 'guide', 'element': 'Scene', 'layer_id': 'guide-layer', 'group_id': 'guides', 'stage_id': 'move-1',
             'guide_tiles': guide.stroke_tiles(self.LINES[:1], w, h), 'guide_colour_tiles': {'#4fb3ff': guide.stroke_tiles(self.LINES[:1], w, h)},
             'guide_bounds': [0, 0, w, h], 'guide_raws': {'#4fb3ff': raw(blue)}},
            {'id': 'g2', 'kind': 'guide', 'element': 'Scene', 'layer_id': 'guide-layer', 'group_id': 'guides', 'stage_id': 'move-1',
             'guide_tiles': guide.stroke_tiles(vertical, w, h), 'guide_colour_tiles': {'#ffb347': guide.stroke_tiles(vertical, w, h)},
             'guide_bounds': [0, 0, w, h], 'guide_raws': {'#ffb347': raw(warm)}}]}
        self.h._guide_painting_tile = lambda image, x, y, tw, th: image[y:y + th, x:x + tw].tobytes()
        def patched(image, patches):
            out = image.copy()
            for x, y, tw, th, data in patches:
                out[y:y + th, x:x + tw] = np.frombuffer(data, np.uint8).reshape(th, tw, 4)
            return out
        self.h._guide_patched = patched
        return doc, group

    def test_crossings_of_both_colours_are_rebuilt_in_every_depth(self):
        for depth, dtype, scale, linear in (('U8', 'uint8', 255.0, False), ('U16', 'uint16', 65535.0, False),
                                            ('F32', 'float32', 1.0, False), ('F32', 'float32', 1.0, True)):
            with self.subTest(depth=depth, linear=linear):
                doc, _group = self.crossing(depth, dtype, scale, linear)
                image, note = self.h._guide_unguided(doc, self.painting, None, self.session)
                self.assertIsNone(note)
                tolerance = self.linear_tolerance(self.cover) if linear else 2
                self.assertLessEqual(tolerance, 16, 'the bound itself stays small (13 levels for this dark sky under a bright line)')
                self.check_clean(image, tolerance)

    def test_artist_paint_in_a_blend_of_the_guide_colours_is_not_taken_for_a_guide(self):
        """Tan #dbb36b lies on the blend of blue and warm: it is a guide only where both colours were drawn, next to
        both of them (a crossing)."""
        np = __import__('numpy')
        tan = (0x6b, 0xb3, 0xdb)
        for where, (y, x) in (('on the blue line, where no warm line was drawn', (1501, 500)),
                              ('on the warm line, far from any blue', (300, 3001))):
            with self.subTest(where=where):
                doc, group = self.crossing()
                group.array[y, x, :3] = tan
                image, note = self.h._guide_unguided(doc, self.painting, None, self.session)
                self.assertIsNone(image)
                self.assertIn('painted on', note)

    def test_a_close_up_rebuilds_only_its_region(self):
        doc, group, _layer = self.make()
        region = [0, 1400, 1024, 200]
        image, _note = self.h._guide_unguided(doc, self.painting, region, self.session)
        self.assertLessEqual(sum(w * h for _x, _y, w, h in group.reads), 1024 * 200 * 1.6)
        self.check_clean(image[1400:1600, 0:1024])

    def test_stale_tiles_fall_back_to_the_layer_bounds(self):
        doc, group, layer = self.make()
        layer.box = (0, 0, SIZE[0], SIZE[1] - 1)                                  # moved or transformed since it was drawn
        image, note = self.h._guide_unguided(doc, self.painting, None, self.session)
        self.assertIsNone(note)
        self.check_clean(image)
        self.assertGreater(sum(w * h for _x, _y, w, h in group.reads), SIZE[0] * SIZE[1] * 0.9, 'read where the layer now is')

    def test_sixteen_bit_and_float_rgba_are_rebuilt_in_8_bit_srgb(self):
        np = __import__('numpy')
        for depth, dtype, scale in (('U16', 'uint16', 65535), ('F32', 'float32', 1.0)):
            with self.subTest(depth=depth):
                colour = (np.array(GUIDE_BGRA[2::-1] if depth == 'F32' else GUIDE_BGRA[:3]) / 255 * scale).astype(dtype)
                raw = colour.tobytes().hex()
                doc, _group, _layer = self.make('RGBA', depth, raw, alpha=np.array(0.7 * scale, dtype), dtype=dtype, colour=colour)
                image, note = self.h._guide_unguided(doc, self.painting, None, self.session)
                self.assertIsNone(note)
                self.check_clean(image)

    def test_other_colour_models_keep_their_guides_and_say_so(self):
        np = __import__('numpy')
        doc, _group, _layer = self.make('GRAYA', 'U8', raw='9a', channels=2, colour=(154,))
        image, note = self.h._guide_unguided(doc, self.painting, None, self.session)
        self.assertIsNone(image)
        self.assertIn('GRAYA', note)

    def test_artist_paint_on_a_guide_is_not_stripped(self):
        doc, group, _layer = self.make()
        group.array[1501, 50] = (0, 0, 255, 255)                                   # a red dab on the guide layer
        image, note = self.h._guide_unguided(doc, self.painting, None, self.session)
        self.assertIsNone(image)
        self.assertIn('painted on', note)

    def test_guides_under_other_paint_are_left_with_a_note(self):
        doc, _group, _layer = self.make()
        doc.root.add(BigNode('Artist top', 'paintlayer', 'top', bounds=(0, 0, 10, 10)))
        image, note = self.h._guide_unguided(doc, self.painting, None, self.session)
        self.assertIsNone(image)
        self.assertIn('other layers lie over the guides group', note, 'never blurred: the paint above the lines is not touched')

    def test_no_visible_guide_is_no_work(self):
        doc, group, layer = self.make()
        layer.shown = False
        self.assertEqual(self.h._guide_unguided(doc, self.painting, None, self.session), (None, None))
        self.assertEqual(group.reads, [])


if __name__ == '__main__':
    unittest.main()

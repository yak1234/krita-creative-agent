"""Filters as masks, filter layers and filtered copies, on a fake layer tree. Files go to a temporary folder that is removed."""
import json
import os
import sys
import types
import unittest
import test_region_craft as region_tests

layer_tests = region_tests.layer_tests
native = region_tests.native
filters = sys.modules['creative_test_package.filters']


class Filter:
    def __init__(self, name, log):
        self.name, self.log, self.config = name, log, None
    def configuration(self):
        info = native.InfoObject()
        for key, value in {'colorbalance': {'cyan_red_midtones': 0, 'preserve_luminosity': True},
                           'gaussian blur': {'horizRadius': 5, 'vertRadius': 5, 'lockAspect': True}}[self.name].items():
            info.setProperty(key, value)
        return info
    def setConfiguration(self, info): self.config = info.properties()
    def apply(self, node, x, y, w, h):
        self.log.append(('apply', node.id, (x, y, w, h), node.doc.batch))
        node.doc.seen_selection.append(node.doc.chosen)
        node.pixels = bytearray(bytes([1, 2, 3, 255]) * 16)      # the filtered copy
        return True


class Effect(region_tests.Layer):
    """A filter mask or filter layer; its pixel writes are its coverage, one byte per pixel."""
    def setPixelData(self, data, x, y, w, h): self.coverage = (bytes(data), (x, y, w, h)); return True


class Document(region_tests.Document):
    def __init__(self):
        super().__init__(); self.batch = False; self.batch_changes = []; self.chosen, self.seen_selection = None, []
    def selection(self): return self.chosen
    def setSelection(self, selection): self.chosen = selection
    def batchmode(self): return self.batch
    def setBatchmode(self, value): self.batch = value; self.batch_changes.append(value)
    def _effect(self, name, krita_filter, selection, kind):
        node = Effect(self, name, kind); node.filter, node.area = krita_filter, selection; return node
    def createFilterMask(self, name, krita_filter, selection): return self._effect(name, krita_filter, selection, 'filtermask')
    def createFilterLayer(self, name, krita_filter, selection): return self._effect(name, krita_filter, selection, 'filterlayer')


class Harness(region_tests.Harness):
    def __init__(self, folder):
        super().__init__(folder); self.doc = Document()
        self._creative_session.update(document_id=native.module.document_id(self.doc))


def run(h, operation, params, identifier):
    return region_tests.run(h, operation, params, identifier)


class FilterTests(region_tests.RegionSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.h = Harness(self.h._creative_session['output'])
        self.log = []
        previous_selection = filters.Selection; filters.Selection = region_tests.Mask
        self.addCleanup(setattr, filters, 'Selection', previous_selection)
        previous = filters.Krita
        filters.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(filter=lambda name: Filter(name, self.log)))
        self.addCleanup(setattr, filters, 'Krita', previous)
        self.raster.blend = lambda original, filtered, mask, w, h: self.log.append(('blend', (w, h), mask)) or filtered

    def agent_layer(self, name='Painting', **extra):
        run(self.h, 'create_layer', dict({'name': name, 'type': 'paint'}, **extra), 'make-' + name)
        return self.h.doc.root.childNodes()[-1]

    def test_a_filter_mask_grades_an_agent_layer_without_touching_its_pixels(self):
        layer = self.agent_layer()
        pixels = bytes(layer.pixels)
        result = run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'colorbalance', 'config': {'cyan_red_midtones': 20}}, 'warm')
        mask, = layer.childNodes()
        self.assertEqual((result['status'], result['layer_id'], result['layer_type'], mask.kind), ('ok', mask.id, 'filter_mask', 'filtermask'))
        self.assertEqual(mask.filter.config, {'cyan_red_midtones': 20, 'preserve_luminosity': True}, "Krita's defaults with the change")
        self.assertEqual(mask.area.pixelData(0, 0, 4, 4), bytes([255]) * 16, 'no area: the whole canvas')
        self.assertEqual(bytes(layer.pixels), pixels)
        self.assertEqual((self.h.doc.batch_changes, self.h.doc.batch), ([True, False], False), 'batch mode only while filtering')
        entry = self.h._creative_session['passes'][-1]
        self.assertEqual((entry['kind'], entry['title'], entry['filter'], entry['filter_mode'], entry['target_id']),
                         ('apply_filter', 'colorbalance', 'colorbalance', 'mask', layer.id))

    def test_fade_scales_the_mask_coverage_and_reject_hides_it(self):
        layer = self.agent_layer()
        run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'gaussian blur', 'name': 'Soften',
                                     'area': [{'shape': 'rectangle', 'bounds': [0, 0, 2, 2]}]}, 'soften')
        mask, = layer.childNodes()
        run(self.h, 'set_layer', {'layer_id': mask.id, 'visible': True}, 'shown')    # a newer pass on the mask
        run(self.h, 'review_pass', {'pass_id': 'soften', 'action': 'strength', 'value': 0.4}, 'fade')
        self.assertEqual((mask.alpha, mask.coverage), (102, (bytes([102]) * 4, (0, 0, 2, 2))), 'Krita ignores mask opacity')
        run(self.h, 'review_pass', {'pass_id': 'soften', 'action': 'strength', 'value': 1.0}, 'full')
        self.assertEqual(mask.coverage[0], bytes([255]) * 4, 'always scaled from the saved original')
        run(self.h, 'review_pass', {'pass_id': 'soften', 'action': 'reject'}, 'reject')
        self.assertEqual((mask.shown, layer.shown), (False, True))

    def test_a_filter_layer_goes_inside_the_agent_group(self):
        run(self.h, 'create_layer', {'name': 'Flats', 'type': 'paint', 'clip_base': True}, 'flats')
        group = self.h.doc.root.childNodes()[-1]; base = group.childNodes()[0]
        run(self.h, 'create_layer', {'name': 'Shadow', 'type': 'paint', 'clip_to': base.id}, 'shadow')
        run(self.h, 'apply_filter', {'target': base.id, 'filter': 'colorbalance', 'mode': 'layer'}, 'above-base')
        run(self.h, 'apply_filter', {'target': group.id, 'filter': 'gaussian blur', 'mode': 'layer', 'name': 'Haze'}, 'top')
        self.assertEqual([n.label for n in group.childNodes()], ['Flats', 'colorbalance (layer)', 'Shadow', 'Haze'])
        loose = self.agent_layer('Loose')
        with self.assertRaisesRegex(ValueError, 'inside one of your groups'):
            run(self.h, 'apply_filter', {'target': loose.id, 'filter': 'colorbalance', 'mode': 'layer'}, 'root-layer')

    def test_copy_filters_the_pixels_of_a_copy_and_reject_restores_the_original(self):
        layer = self.agent_layer()
        result = run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'gaussian blur', 'mode': 'copy'}, 'blurred')
        copy = self.h.doc.root.childNodes()[-1]
        self.assertEqual((result['layer_id'], result['source_layer_id'], layer.shown), (copy.id, layer.id, False))
        self.assertEqual(self.log, [('apply', copy.id, (0, 0, 4, 4), True)], 'the copy, in batch mode')
        run(self.h, 'review_pass', {'pass_id': 'blurred', 'action': 'reject'}, 'reject')
        self.assertEqual((copy.shown, layer.shown), (False, True))

    def test_the_copy_is_filtered_whole_whatever_selection_the_artist_has_and_the_selection_comes_back(self):
        layer = self.agent_layer()
        artists = region_tests.Mask()
        self.h.doc.chosen = artists
        run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'gaussian blur', 'mode': 'copy'}, 'whole')
        area = [{'shape': 'rectangle', 'bounds': [1, 1, 2, 2]}]
        run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'gaussian blur', 'mode': 'copy', 'area': area}, 'part')
        self.assertEqual(self.h.doc.seen_selection, [None, None], 'Filter.apply keeps to the selection: none while it runs')
        self.assertIs(self.h.doc.chosen, artists, "the artist's selection is back")

    def test_the_selection_comes_back_when_the_filter_is_refused(self):
        layer = self.agent_layer()
        artists = region_tests.Mask()
        self.h.doc.chosen = artists
        previous = filters.Krita
        class Refusing(Filter):
            def apply(self, node, x, y, w, h): return False
        filters.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(filter=lambda name: Refusing(name, self.log)))
        self.addCleanup(setattr, filters, 'Krita', previous)
        result = run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'gaussian blur', 'mode': 'copy'}, 'refused')
        self.assertNotEqual(result.get('status'), 'ok')
        self.assertIn('could not apply', str(result))
        self.assertIs(self.h.doc.chosen, artists, 'back also when the filter was refused')

    def test_an_area_limits_every_mode(self):
        layer = self.agent_layer()
        area = [{'shape': 'rectangle', 'bounds': [1, 1, 2, 2]}]
        run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'colorbalance', 'area': area}, 'masked')
        self.assertEqual(layer.childNodes()[0].area.pixelData(0, 0, 4, 1), bytes(4), 'the mask covers only the area')
        result = run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'gaussian blur', 'mode': 'copy', 'area': area}, 'part')
        self.assertEqual(result['filtered_bounds'], [1, 1, 2, 2])
        self.assertEqual([entry[0] for entry in self.log], ['apply', 'blend'])
        self.assertEqual((self.log[0][2], self.log[1][1]), ((1, 1, 2, 2), (2, 2)))

    def test_a_filter_mask_goes_on_a_clone_of_the_artists_sketch(self):
        sketch = self.artist_layer('Sketch')
        clone = region_tests.Layer(self.h.doc, 'Sketch lifted', 'clonelayer')
        self.h.doc.createCloneLayer = lambda name, source: clone
        result = run(self.h, 'clone_layer', {'source': sketch.id, 'name': 'Sketch lifted'}, 'lift')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        run(self.h, 'apply_filter', {'target': clone.id, 'filter': 'gaussian blur'}, 'lift-blur')
        self.assertEqual([m.kind for m in clone.childNodes()], ['filtermask'])
        self.assertEqual(sketch.childNodes(), [], "the artist's sketch has no mask")

    def test_refusals_change_nothing(self):
        figure = self.artist_layer()
        layer = self.agent_layer()
        run(self.h, 'create_layer', {'name': 'Group', 'type': 'group'}, 'group')
        group = self.h.doc.root.childNodes()[-1]
        area = [{'shape': 'rectangle', 'bounds': [0, 0, 1, 1]}]
        for params, message in (({'target': figure.id, 'filter': 'colorbalance'}, 'never filtered'),
                                ({'target': layer.id, 'filter': 'sharpen'}, 'Unknown filter'),
                                ({'target': layer.id, 'filter': 'gaussian blur', 'config': {'horizRadius': 'big'}}, 'must be int'),
                                ({'target': layer.id, 'filter': 'gaussian blur', 'config': {'radius': 3}}, 'no setting'),
                                ({'target': group.id, 'filter': 'gaussian blur', 'mode': 'copy'}, 'paint layer'),
                                ({'target': layer.id, 'filter': 'gaussian blur', 'mode': 'smudge'}, 'mask, layer or copy'),
                                ({'target': layer.id, 'filter': 'gaussian blur', 'area': area, 'selection': 'Sky'}, 'not both')):
            with self.assertRaisesRegex(ValueError, message): run(self.h, 'apply_filter', params, 'bad-' + message[:8])
        empty = run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'gaussian blur',
                                             'area': area + [dict(area[0], mode='subtract')]}, 'empty')
        self.assertEqual((empty['status'], empty['error_code']), ('rejected', 'validation_rejected'))
        self.assertEqual((layer.childNodes(), figure.childNodes(), self.log), ([], [], []))
        self.assertEqual([p['kind'] for p in self.h._creative_session['passes']], ['create_layer', 'create_layer'])

    def test_an_agent_move_of_craft_is_rejected_together(self):
        move = {'stage_id': 'move-1'}
        area = [{'shape': 'rectangle', 'bounds': [0, 0, 4, 4]}]
        fill = run(self.h, 'fill_region', dict(move, name='Sphere', area=area, color='#3a6ea5', clip_base=True), 'sphere')
        shadow = run(self.h, 'create_layer', dict(move, name='Shadow', type='paint', blend_mode='multiply', clip_to=fill['layer_id']), 'shadow')
        mask = run(self.h, 'apply_filter', dict(move, target=shadow['layer_id'], filter='gaussian blur'), 'soften')
        nodes = [self.h._creative_node(self.h.doc, r['layer_id']) for r in (fill, shadow, mask)]
        self.assertTrue(all(node.shown for node in nodes))
        rows = self.h._creative_passes(self.h._creative_session)
        stage, = [r for r in rows if r['kind'] == 'stage']
        self.assertEqual((stage['id'], stage['pass_ids'], stage['review_actions']), ('stage:move-1', ['sphere', 'shadow', 'soften'], ['strength', 'visibility', 'reject']), 'one card, faded or hidden as a whole')
        run(self.h, 'review_pass', {'pass_id': 'stage:move-1', 'action': 'reject'}, 'undo')
        self.assertEqual([node.shown for node in nodes], [False, False, False], 'Undo hides all three')

    def test_a_crash_during_a_filter_blocks_painting_until_acknowledged(self):
        layer = self.agent_layer()
        class Crash(BaseException): pass                       # Krita quits mid-filter: no result is stored
        def crash(*_args): raise Crash()
        self.h._filter_apply = crash
        with self.assertRaises(Crash):
            run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'colorbalance'}, 'crashed')
        del self.h._filter_apply
        refused = run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'colorbalance'}, 'next')
        self.assertEqual((refused['error_code'], refused['unresolved_operations']), ('outcome_unknown', ['crashed']))
        replay = run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'colorbalance'}, 'crashed')
        self.assertEqual((replay['error_code'], replay['replayed']), ('outcome_unknown', True), 'never re-run blindly')
        revision = self.h._creative_revision(self.h.doc)
        run(self.h, 'reconcile', {'expected_revision': revision}, None)
        self.assertEqual(run(self.h, 'apply_filter', {'target': layer.id, 'filter': 'colorbalance'}, 'next')['status'], 'ok')

    def test_a_saved_session_from_before_filters_loads_unchanged(self):
        session = self.h._creative_session; session.pop('passes')
        old = [{'id': 'p1', 'kind': 'paint_pass', 'layer_id': 'L1', 'title': 'Sky', 'after': {'opacity': 255, 'visible': True},
                'strength': 1.0, 'visible': True, 'rejected': False}]
        with open(os.path.join(session['output'], '.passes.json'), 'w') as stream: json.dump(old, stream)
        rows = self.h._creative_passes(session)
        self.assertEqual([(r['id'], r['kind'], r['title']) for r in rows if not r.get('is_stage')], [('p1', 'paint_pass', 'Sky')])
        self.assertNotIn('filter', rows[0])


if __name__ == '__main__':
    unittest.main()

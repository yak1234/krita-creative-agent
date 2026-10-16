"""Merging accepted stroke passes into one layer, on a fake layer tree. Files go to a temporary folder that is removed."""
import unittest
import test_region_craft as region_tests

native = region_tests.native
run = region_tests.run
STROKE = {'start': [1, 1], 'segments': [[1, 1, 2, 2, 3, 3]], 'size': 2, 'opacity': 1, 'flow': 1, 'color': '#806040'}


class Layer(region_tests.Layer):
    def mergeDown(self):
        """Like Krita: both layers become one new layer in the lower one's place."""
        parent = self.parent; index = parent.children.index(self); below = parent.children[index - 1]
        merged = Layer(self.doc, below.label, 'paintlayer')
        merged.pixels = bytearray(max(a, b) for a, b in zip(below.pixels, self.pixels))
        parent.children[index - 1:index + 1] = [merged]; merged.parent = parent
        return merged


class Document(region_tests.Document):
    def createNode(self, name, kind): return Layer(self, name, kind)


class Harness(region_tests.Harness):
    _creative_new_layer = native.module.CreativeTools._creative_new_layer
    def __init__(self, folder):
        super().__init__(folder); self.doc = Document()
        self._creative_session['document_id'] = native.module.document_id(self.doc)


class MergeTests(region_tests.RegionSetup, unittest.TestCase):
    def setUp(self):
        super().setUp(); self.h = Harness(self.h._creative_session['output'])

    def stroke(self, name, **extra):
        return run(self.h, 'paint_pass', dict({'name': name, 'preset': 'b) Basic-1', 'strokes': [STROKE], 'stage_id': 'move-1'}, **extra), name)

    def merge(self, identifier):
        return run(self.h, 'merge_passes', {'stage_id': 'move-1', 'name': 'Move 1 · Kremlin'}, identifier)

    def test_adjacent_stroke_layers_merge_and_craft_layers_stay(self):
        a, b = self.stroke('Walls'), self.stroke('Towers')
        flat = run(self.h, 'fill_region', {'name': 'Sky', 'color': '#203040', 'stage_id': 'move-1', 'area': [{'shape': 'rectangle', 'bounds': [0, 0, 4, 2]}]}, 'sky')
        d, e = self.stroke('Windows'), self.stroke('Snow')
        group = self.h._creative_node(self.h.doc, a['layer_id']).parentNode()
        self.assertEqual(len(group.childNodes()), 5)
        first = self.merge('merge-1')
        self.assertEqual((first['status'], first['merged_layers'], first['remaining_runs']), ('ok', 2, 1))
        second = self.merge('merge-2')
        self.assertEqual((second['merged_layers'], second['remaining_runs']), (2, 0))
        self.assertEqual(self.merge('merge-3')['merged_layers'], 0, 'nothing left to merge')
        self.assertEqual([c.name() for c in group.childNodes()], ['Move 1 · Kremlin', 'Sky', 'Move 1 · Kremlin'], 'the fill breaks the runs and stays')
        layers = self.h._creative_session['layers']
        self.assertTrue(all(x['layer_id'] not in layers for x in (a, b, d, e)))
        self.assertIn(flat['layer_id'], layers); self.assertIn(first['layer_id'], layers)
        listed = [p for p in self.h._creative_passes(self.h._creative_session) if p['kind'] != 'stage']
        self.assertEqual([p['kind'] for p in listed], ['fill_region', 'merge_passes', 'merge_passes'], 'merged passes leave the history')
        entry = next(p for p in self.h._creative_session['passes'] if p['id'] == 'Walls')
        self.assertEqual(entry['merged_into'], 'merge-1')
        with self.assertRaisesRegex(ValueError, 'merged with others'):
            run(self.h, 'review_pass', {'pass_id': 'Walls', 'action': 'reject'}, 'reject-walls')
        self.assertEqual(run(self.h, 'review_pass', {'pass_id': 'stage:move-1', 'action': 'reject'}, 'undo-move')['status'], 'ok')
        self.assertTrue(all(not c.visible() for c in group.childNodes()), 'Undo of the move still hides all of it')

    def test_edited_blended_and_rejected_layers_are_left_alone(self):
        a, b = self.stroke('Walls'), self.stroke('Towers')
        texture = self.stroke('Brick texture', blend_mode='overlay')
        c = self.stroke('Roofs')
        self.h._creative_node(self.h.doc, a['layer_id']).pixels[0] = 99           # the artist painted on it
        run(self.h, 'review_pass', {'pass_id': 'Roofs', 'action': 'reject'}, 'reject-roofs')
        result = self.merge('merge-1')
        self.assertEqual(result['merged_layers'], 0, 'no run of two plain, unchanged, kept stroke layers is left')
        self.assertTrue(all(self.h._creative_node(self.h.doc, x['layer_id']) for x in (a, b, texture, c)))


if __name__ == '__main__':
    unittest.main()

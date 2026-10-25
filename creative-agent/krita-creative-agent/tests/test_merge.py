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


class Rect:
    def __init__(self, x, y, w, h): self.box = (x, y, w, h)
    def x(self): return self.box[0]
    def y(self): return self.box[1]
    def width(self): return self.box[2]
    def height(self): return self.box[3]
    def isEmpty(self): return not (self.box[2] and self.box[3])


class WholeLayer(Layer):
    """A layer that can be removed, locked and measured, as in Krita."""
    def remove(self):
        self.parent.children.remove(self); self.parent = None; return True
    def setLocked(self, value): self.is_locked = value
    def passThroughMode(self): return getattr(self, 'pass_through', False)
    def bounds(self): return Rect(0, 0, 4, 4)
    def mergeDown(self):
        merged = super().mergeDown(); merged.__class__ = WholeLayer; return merged


class WholeDocument(region_tests.Document):
    def createNode(self, name, kind): return WholeLayer(self, name, kind)


def count_nodes(node):
    return sum(1 + count_nodes(child) for child in node.childNodes())


class WholeMergeTests(region_tests.RegionSetup, unittest.TestCase):
    """layer-plan goal 4: Met merges the whole move (strokes, craft layers, Finish and accents groups) into one named layer
    in the move group's place; its hidden leftovers go with it (goal 5) and the underpainting can be locked (goal 1)."""
    def setUp(self):
        super().setUp(); self.h = Harness(self.h._creative_session['output']); self.h.doc = WholeDocument()
        self.h._creative_session['document_id'] = native.module.document_id(self.h.doc)
        self.background = WholeLayer(self.h.doc, 'Background', 'paintlayer'); self.h.doc.root.addChildNode(self.background, None)

    def node(self, identifier): return self.h._creative_node(self.h.doc, identifier)

    def stroke(self, name, stage='move-1', **extra):
        return run(self.h, 'paint_pass', dict({'name': name, 'preset': 'b) Basic-1', 'strokes': [STROKE], 'stage_id': stage}, **extra), name)

    def group_pass(self, name, layers=('blend', 'strokes'), stage='move-1'):
        """A Finish or accents pass: one group the operation fills with its own layers (finish_pass.py, accent_adjust.py)."""
        made = run(self.h, 'create_layer', {'name': name, 'type': 'group', 'stage_id': stage}, name)
        group = self.node(made['layer_id'])
        for label in layers:
            layer = WholeLayer(self.h.doc, '%s · %s' % (name, label), 'paintlayer')
            group.addChildNode(layer, group.childNodes()[-1] if group.childNodes() else None)
            self.h._creative_session['layers'].add(layer.uniqueId().toString())
        return made

    def merge(self, identifier, stage='move-1', **extra):
        return run(self.h, 'merge_passes', dict({'stage_id': stage, 'name': 'Finish', 'whole': True}, **extra), identifier)

    def test_met_merges_the_whole_move_into_one_named_layer(self):
        walls, towers = self.stroke('Walls'), self.stroke('Towers')
        texture = self.stroke('Brick texture', blend_mode='overlay')
        finish = self.group_pass('Finish 1')
        accents = self.group_pass('Accents 1', ('lights', 'darks', 'lines'))
        self.stroke('Roofs')
        run(self.h, 'review_pass', {'pass_id': 'Roofs', 'action': 'reject'}, 'reject-roofs')     # a hidden leftover
        stage = self.node(walls['layer_id']).parentNode()
        before = count_nodes(self.h.doc.root)
        self.assertEqual(before, 13, 'Background, the move group and its 11 layers and groups')
        result = self.merge('merge-1')
        self.assertEqual((result['status'], result['remaining_runs']), ('ok', 0))
        after = count_nodes(self.h.doc.root)
        self.assertEqual(after, 2, 'the artist’s Background and the one merged layer')
        self.assertEqual(result['merged_layers'], before - 1, 'every node of the move group, the group too')
        merged = self.h.doc.root.childNodes()[-1]
        self.assertEqual((merged.name(), merged.type(), merged.locked()), ('Finish', 'paintlayer', False))
        self.assertNotIn(stage, self.h.doc.root.childNodes(), 'the move group is gone: one layer in its place')
        self.assertIs(self.h.doc.root.childNodes()[0], self.background, 'the artist’s layer is untouched')
        mine = [e for e in self.h._creative_session['passes'] if e.get('stage_id') == 'move-1' and e['kind'] != 'merge_passes']
        self.assertTrue(all(e.get('merged_into') == 'merge-1' for e in mine), 'every pass of the move points to the merged layer')
        layers = self.h._creative_session['layers']
        self.assertIn(result['layer_id'], layers)
        self.assertTrue(all(x['layer_id'] not in layers for x in (walls, towers, texture, finish, accents)))
        listed = [p for p in self.h._creative_passes(self.h._creative_session) if p['kind'] != 'stage']
        self.assertEqual([p['kind'] for p in listed], ['merge_passes'], 'the move is one pass in the history')
        self.assertEqual(self.merge('merge-2')['merged_layers'], 0, 'nothing left to merge')

    def test_the_kept_underpainting_is_locked(self):
        self.stroke('Wash'); self.stroke('Masses')
        result = self.merge('merge-1', name='Underpainting', lock=True)
        merged = self.node(result['layer_id'])
        self.assertEqual((merged.name(), merged.locked()), ('Underpainting', True))
        listed = {l['name']: l for l in self.h._creative_layer_list(self.h.doc)}
        self.assertFalse(listed['Underpainting']['editable_by_agent'], 'the painter sees it locked')
        later = self.stroke('Sky', stage='move-2')
        self.assertEqual(later['status'], 'ok', 'the next move paints in a group of its own above the locked base')
        self.assertIsNot(self.node(later['layer_id']).parentNode(), self.h.doc.root)

    def test_on_the_fork_krita_merges_the_group_as_it_renders(self):
        self.stroke('Walls'); self.group_pass('Finish 1')
        calls = []
        def merge_groups(nodes):
            calls.append([n.name() for n in nodes])
            group = nodes[0]; parent = group.parentNode(); merged = WholeLayer(self.h.doc, group.name(), 'paintlayer')
            parent.children[parent.children.index(group)] = merged; merged.parent = parent
            return merged
        self.h.doc.mergeGroups = merge_groups
        result = self.merge('merge-1')
        self.assertEqual(calls, [['Creative Agent · move-1']])
        self.assertEqual([c.name() for c in self.h.doc.root.childNodes()], ['Background', 'Finish'])
        self.assertEqual(self.node(result['layer_id']).name(), 'Finish')

    def test_a_move_group_holding_an_artist_layer_or_the_guides_is_not_merged_whole(self):
        walls = self.stroke('Walls'); self.stroke('Towers')
        stage = self.node(walls['layer_id']).parentNode()
        figure = WholeLayer(self.h.doc, 'My figure', 'paintlayer'); stage.addChildNode(figure, None)
        result = self.merge('merge-1')
        self.assertEqual(result['merged_layers'], 2, 'only the run of plain strokes merges, as before')
        self.assertIn(figure, stage.childNodes())
        self.assertIn(stage, self.h.doc.root.childNodes())
        other = self.stroke('Sky', stage='move-2'); self.stroke('Clouds', stage='move-2')
        group = self.node(other['layer_id']).parentNode()
        guides = WholeLayer(self.h.doc, 'Guides · Creative Agent', 'grouplayer'); group.addChildNode(guides, None)
        self.merge('merge-2', stage='move-2')
        self.assertIn(group, self.h.doc.root.childNodes(), 'a group holding the guides is never flattened')
        self.assertIn(guides, group.childNodes())

    def test_undo_of_the_next_move_still_works_after_a_merge(self):
        self.stroke('Walls'); self.stroke('Towers')
        merged = self.merge('merge-1')
        nxt = self.stroke('Sky', stage='move-2')
        self.assertEqual(run(self.h, 'review_pass', {'pass_id': 'stage:move-2', 'action': 'reject'}, 'undo-2')['status'], 'ok')
        self.assertFalse(self.node(nxt['layer_id']).visible())
        self.assertTrue(self.node(merged['layer_id']).visible(), 'the kept move stays')

    def test_tidying_an_undone_move_removes_its_emptied_group(self):
        sky = self.stroke('Sky', stage='move-2')
        group = self.node(sky['layer_id']).parentNode()
        run(self.h, 'review_pass', {'pass_id': 'stage:move-2', 'action': 'reject'}, 'undo-2')
        result = self.h.cmd_creative({'operation': 'tidy_kept', 'session_id': 'session', 'params': {'stage_id': 'move-2', 'undone': True}})
        self.assertEqual(result['removed_layers'], 2, 'the rejected layer and the group it leaves empty')
        self.assertNotIn(group, self.h.doc.root.childNodes())
        self.assertEqual(self.h.doc.root.childNodes(), [self.background])


if __name__ == '__main__':
    unittest.main()

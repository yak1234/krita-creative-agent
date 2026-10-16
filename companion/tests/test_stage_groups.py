"""New stage containers must never absorb or change an artist's layers."""
import unittest

from test_native import Document, Harness, Layer, module, request


class TreeNode(Layer):
    def __init__(self, identity, name, kind):
        super().__init__(identity)
        self.label = name; self.kind = kind; self.children = []; self.parent = None; self.blend = 'normal'
    def name(self): return self.label
    def type(self): return self.kind
    def childNodes(self): return self.children
    def parentNode(self): return self.parent
    def blendingMode(self): return self.blend
    def setBlendingMode(self, value): self.blend = value
    def addChildNode(self, child, above):
        self.children.insert(self.children.index(above) + 1 if above else 0, child)
        child.parent = self
        return True


class TreeDocument(Document):
    def __init__(self):
        super().__init__(); self.root = TreeNode(self.identity, 'Root', 'grouplayer'); self.counter = 0
    def rootNode(self): return self.root
    def createNode(self, name, kind):
        self.counter += 1
        return TreeNode('node-' + str(self.counter), name, kind)


class TreeHarness(Harness):
    _creative_new_layer = module.CreativeTools._creative_new_layer
    def __init__(self):
        super().__init__(); self.doc = TreeDocument()
        self._creative_session['document_id'] = module.document_id(self.doc)


def paint(h, key, stage='stage-1-0'):
    item = request(); item['operation_id'] = key; item['params']['stage_id'] = stage
    return h.cmd_creative(item)


class StageGroupsTests(unittest.TestCase):
    def test_same_stage_has_one_container_and_review_preserves_artist_layer(self):
        h = TreeHarness(); artist = h.doc.createNode('Manual painting', 'paintlayer')
        h.doc.root.addChildNode(artist, None); h.doc.active = artist
        first = paint(h, 'first'); second = paint(h, 'second')
        self.assertEqual(first['group_id'], second['group_id'])
        self.assertIs(h.doc.active, artist)
        self.assertEqual(h.doc.root.children[1].name(), 'Creative Agent · Stage 1')
        self.assertEqual(len(h.doc.root.children[1].children), 2)
        h.cmd_creative({'operation':'review_pass','session_id':'session','operation_id':'reject',
                       'params':{'pass_id':'stage:stage-1-0','action':'reject'}})
        self.assertTrue(artist.visible()); self.assertIs(artist.parent, h.doc.root)
        self.assertTrue(all(not n.visible() for n in h.doc.root.children[1].children))

    def test_manual_changes_to_container_are_preserved_instead_of_reused(self):
        for change in ('hide', 'opacity', 'lock', 'mask', 'layer_above', 'blend'):
            with self.subTest(change=change):
                h = TreeHarness(); first = paint(h, 'first'); group = h.doc.root.children[-1]
                if change == 'hide': group.shown = False
                if change == 'opacity': group.alpha = 128
                if change == 'lock': group.is_locked = True
                if change == 'mask': group.addChildNode(h.doc.createNode('Manual mask', 'transparencymask'), group.children[-1])
                if change == 'layer_above': h.doc.root.addChildNode(h.doc.createNode('Manual layer', 'paintlayer'), group)
                if change == 'blend': group.blend = 'multiply'
                before = (group.shown, group.alpha, group.is_locked, group.blend, tuple(group.children))
                second = paint(h, 'second')
                self.assertNotEqual(first['group_id'], second['group_id'])
                self.assertEqual(before, (group.shown, group.alpha, group.is_locked, group.blend, tuple(group.children)))
                self.assertEqual(h.doc.root.children[-1].name(), 'Creative Agent · Stage 1 (continued)')

    def test_new_stage_and_new_session_do_not_claim_existing_container(self):
        h = TreeHarness(); first = paint(h, 'first'); second = paint(h, 'second', 'stage-1-1')
        self.assertNotEqual(first['group_id'], second['group_id'])
        old = tuple(h.doc.root.children)
        h._creative_session['passes'] = []; h._creative_session['layers'] = set()
        third = paint(h, 'third', 'stage-1-1')
        self.assertNotEqual(second['group_id'], third['group_id'])
        self.assertEqual(tuple(h.doc.root.children[:2]), old)


if __name__ == '__main__': unittest.main()

"""Paint only here (element-scoped-painting goals 1, 5, 6): the artist's selection becomes the one area the agent may paint
in. The plugin protects everything outside it as a hidden feature of the fork, so Krita itself keeps every agent write out:
exact at the selection's outer edge, softened a few pixels inside it. A fake fork document on the 4x4 test canvas; the
mask file goes to a temporary folder that is removed."""
import os
import sys
import tempfile
import unittest

import test_region_craft as region_tests

native = region_tests.native
Mask = region_tests.Mask
SIZE = region_tests.SIZE
guard = sys.modules.get('creative_test_package.feature_guard') or __import__('creative_test_package.feature_guard', fromlist=['x'])
shape_mask = sys.modules.get('creative_test_package.shape_mask') or __import__('creative_test_package.shape_mask', fromlist=['x'])
paint_only = sys.modules.get('creative_test_package.paint_only_here') or __import__('creative_test_package.paint_only_here', fromlist=['x'])


class Selection(Mask):
    def duplicate(self):
        copy = Selection(); copy.m = bytearray(self.m); return copy


class Feature:
    def __init__(self, name, kind, mask, author, state, protected):
        self.n, self.k, self.mask, self.a, self.s, self.p = name, kind, mask, author, state, protected
    def name(self): return self.n
    def kind(self): return self.k
    def author(self): return self.a
    def state(self): return self.s
    def isProtected(self): return self.p


class ForkDocument:
    """What Paint only here asks of the fork: features by name, added and removed as undo steps."""
    def __init__(self):
        self.list, self.steps, self.picked = [], [], None
    def width(self): return SIZE
    def height(self): return SIZE
    def features(self): return list(self.list)
    def feature(self, name): return next((f for f in self.list if f.name() == name), None)
    def addFeature(self, name, kind, mask, author='agent', state='proposed', protected=False):
        if self.feature(name) is not None: return None
        feature = Feature(name, kind, mask.duplicate(), author, state, protected); self.list.append(feature); self.steps.append(('add', name))
        return feature
    def removeFeature(self, name):
        found = self.feature(name)
        if found is None: return False
        self.list.remove(found); self.steps.append(('remove', name)); return True
    # The fork's transient features: outside the undo history (no step), only the transient kind.
    def setTransientFeature(self, name, kind, mask, protected=True):
        found = self.feature(name)
        if kind != 'paint-only-here' or (found is not None and found.kind() != kind): return None
        feature = Feature(name, kind, mask.duplicate(), 'artist', 'kept', protected)
        if found is not None: self.list[self.list.index(found)] = feature
        else: self.list.append(feature)
        return feature
    def removeTransientFeature(self, name):
        found = self.feature(name)
        if found is None or found.kind() != 'paint-only-here': return False
        self.list.remove(found); return True
    def protectedSelection(self, inverted=False): return Selection()
    def protectionActive(self): return any(f.isProtected() for f in self.list)
    def selection(self, *args): return self.picked
    def setSelection(self, selection): self.picked = selection


def selected(x, y, w, h, value=255):
    selection = Selection(); selection.select(x, y, w, h, value); return selection


class PaintOnlyHereTests(unittest.TestCase):
    def setUp(self):
        self.doc, self.areas = ForkDocument(), paint_only.PaintOnlyHere(make_selection=Selection)

    def outside(self):
        feature = self.doc.feature(paint_only.SYSTEM_NAME)
        self.assertIsNotNone(feature, 'the outside of the area is a feature')
        return feature

    def test_the_outside_of_the_selection_is_protected_by_the_artist_as_one_hidden_feature(self):
        area = self.areas.capture(self.doc, selected(0, 0, 2, 4))
        feature = self.outside()
        self.assertEqual((feature.kind(), feature.author(), feature.state(), feature.isProtected()), (paint_only.SYSTEM_KIND, 'artist', 'kept', True))
        self.assertEqual(area['bounds'], [0, 0, 2, 4])
        self.assertEqual(area['mask'], b'\xff' * 8, 'the selected pixels, not its bounds')
        for row in range(SIZE):                                        # exact at the outer edge: every pixel outside is whole
            self.assertEqual(feature.mask.m[row * SIZE + 2:row * SIZE + 4], b'\xff\xff', row)
        self.assertTrue(self.areas.present(self.doc))
        listed = guard.FeatureCraft()._feature_list(self.doc)
        self.assertEqual(listed, [], "not in the artist's Protected list, nor in the painter's features")
        self.areas.capture(self.doc, selected(0, 0, 1, 1)); self.areas.clear(self.doc)
        self.assertEqual(self.doc.steps, [], "no undo step: the artist's Undo and Redo never meet it")

    def test_the_inner_edge_is_softened_and_never_reaches_past_the_selection(self):
        selection = selected(0, 0, 2, 4)
        ops = []
        class Recording(Selection):
            def duplicate(self):
                copy = Recording(); copy.m = bytearray(self.m); return copy
            def shrink(self, x, y, lock): ops.append(('shrink', x, lock)); super().shrink(x, y, lock)
            def feather(self, value): ops.append(('feather', value)); self.m = bytearray(v // 2 for v in self.m)   # a soft band
            def intersect(self, other): ops.append('intersect'); super().intersect(other)
        recorded = Recording(); recorded.m = bytearray(selection.m)
        outside = paint_only.outside_mask(self.doc, recorded, Selection)
        self.assertEqual(ops, [('shrink', paint_only.FEATHER, False), ('feather', paint_only.FEATHER), 'intersect'])
        self.assertEqual(outside.m[0], 255 - 127, 'inside the selection the protection fades')
        self.assertEqual(outside.m[3], 255, 'outside it is whole')
        thin = paint_only.outside_mask(self.doc, selected(1, 1, 1, 1), Selection)
        self.assertEqual(thin.m[SIZE + 1], 0, 'a selection thinner than the edge keeps its own pixels')

    def test_a_new_area_replaces_the_old_one_and_clear_removes_it(self):
        self.areas.capture(self.doc, selected(0, 0, 2, 2))
        self.areas.capture(self.doc, selected(2, 2, 2, 2), name='the moon')
        self.assertEqual(len(self.doc.features()), 1, 'one area at a time')
        self.assertEqual(self.areas.area(self.doc)['name'], 'the moon')
        self.assertEqual(self.outside().mask.m[0], 255)
        self.areas.clear(self.doc)
        self.assertIsNone(self.doc.feature(paint_only.SYSTEM_NAME)); self.assertIsNone(self.areas.area(self.doc))

    def test_an_empty_selection_or_a_krita_without_features_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'Select'):
            self.areas.capture(self.doc, None)
        with self.assertRaisesRegex(ValueError, 'Select'):
            self.areas.capture(self.doc, Selection())
        class Stock: pass
        with self.assertRaisesRegex(ValueError, 'our Krita'):
            self.areas.capture(Stock(), selected(0, 0, 1, 1))
        class Older:                                    # features, but no transient ones: never the undo stack instead
            def width(self): return SIZE
            def height(self): return SIZE
            def feature(self, name): return None
            def addFeature(self, *args): raise AssertionError('never on the undo stack')
            def removeFeature(self, name): raise AssertionError('never on the undo stack')
        older = Older()
        with self.assertRaisesRegex(ValueError, 'our Krita'):
            self.areas.capture(older, selected(0, 0, 1, 1))

    def test_ensure_puts_the_protection_back_when_it_is_gone(self):
        self.areas.capture(self.doc, selected(0, 0, 2, 4))
        self.doc.removeTransientFeature(paint_only.SYSTEM_NAME)        # a reverted document
        self.assertTrue(self.areas.ensure(self.doc))
        self.assertTrue(self.areas.present(self.doc))
        self.assertFalse(self.areas.ensure(ForkDocument()), 'a document without an area is left alone')

    def test_a_leftover_protection_without_an_area_is_removed(self):
        other = paint_only.PaintOnlyHere(make_selection=Selection)
        other.capture(self.doc, selected(0, 0, 2, 4))                  # an earlier chat, or a Krita that closed mid-chat
        self.assertTrue(self.areas.drop_stale(self.doc))
        self.assertIsNone(self.doc.feature(paint_only.SYSTEM_NAME))
        self.assertFalse(self.areas.drop_stale(self.doc))

    def test_clear_all_ends_the_area_in_every_document(self):
        other = ForkDocument()
        self.areas.capture(self.doc, selected(0, 0, 2, 2)); self.areas.capture(other, selected(1, 1, 2, 2))
        self.areas.clear_all()
        self.assertIsNone(self.doc.feature(paint_only.SYSTEM_NAME)); self.assertIsNone(other.feature(paint_only.SYSTEM_NAME))
        self.assertIsNone(self.areas.area(other))

    def test_restore_reads_only_a_chat_folders_paint_only_mask(self):
        folder = tempfile.mkdtemp()
        try:
            for name in ('mask.png', os.path.join('.shapes', 'canvas-0123456789abcdef01234567.png'), os.path.join('.shapes', 'paint-only-x.png')):
                os.makedirs(os.path.dirname(os.path.join(folder, name)), exist_ok=True)
                path = os.path.join(folder, name)
                with open(path, 'wb') as handle: handle.write(paint_only.encode_png(1, 1, b'\xff'))
                with self.assertRaisesRegex(ValueError, 'chat folder'):
                    self.areas.restore(self.doc, {'bounds': [0, 0, 1, 1], 'mask_path': path})
        finally:
            import shutil; shutil.rmtree(folder)

    def test_restore_rebuilds_the_area_from_its_mask_file_after_a_resume(self):
        area = self.areas.capture(self.doc, selected(1, 0, 2, 3), name='the sky')
        folder = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(folder, '.shapes'))
            path = paint_only.write_mask(area, os.path.join(folder, '.shapes', 'paint-only-0123456789abcdef01234567.png'))
            with open(path, 'rb') as handle: width, height, plane = shape_mask.read_png(handle.read(), (2, 3))
            self.assertEqual((width, height, plane), (2, 3, b'\xff' * 6), 'a grey PNG the companion and shape_mask read')
            fresh, restored = ForkDocument(), paint_only.PaintOnlyHere(make_selection=Selection)
            restored.restore(fresh, {'bounds': [1, 0, 2, 3], 'mask_path': path, 'name': 'the sky'})
            self.assertEqual(restored.area(fresh)['name'], 'the sky')
            self.assertEqual(fresh.feature(paint_only.SYSTEM_NAME).mask.m[1], 0)
            self.assertEqual(fresh.feature(paint_only.SYSTEM_NAME).mask.m[0], 255)
        finally:
            import shutil; shutil.rmtree(folder)

    def test_a_found_outline_becomes_the_documents_selection(self):
        """Find it for me: the companion's found outline (.shapes/found-*.png, cropped to its bounds) is loaded as the document's
        selection, which the artist adjusts; nothing is protected until they press Paint only here."""
        folder = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(folder, '.shapes'))
            path = os.path.join(folder, '.shapes', 'found-0123456789abcdef01234567.png')
            with open(path, 'wb') as handle: handle.write(paint_only.encode_png(2, 2, b'\xff\x00\xff\xff'))
            self.assertEqual(self.areas.load_found(self.doc, {'bounds': [1, 1, 2, 2], 'mask_path': path}, folder), [1, 1, 2, 2])
            picked = self.doc.picked.m
            self.assertEqual([picked[1 * SIZE + 1], picked[1 * SIZE + 2], picked[2 * SIZE + 1], picked[0]], [255, 0, 255, 0])
            self.assertIsNone(self.doc.feature(paint_only.SYSTEM_NAME), 'a selection only: nothing protected yet')
            self.assertEqual(self.doc.steps, [])
            with self.assertRaisesRegex(ValueError, 'does not fit'):
                self.areas.load_found(self.doc, {'bounds': [3, 3, 2, 2], 'mask_path': path}, folder)
            other = os.path.join(folder, '.shapes', 'paint-only-0123456789abcdef01234567.png')
            with open(other, 'wb') as handle: handle.write(paint_only.encode_png(2, 2, b'\xff' * 4))
            for wrong in (other, os.path.join(folder, 'found-0123456789abcdef01234567.png'), 'found-0123456789abcdef01234567.png'):
                with self.assertRaisesRegex(ValueError, 'only from this chat folder'):
                    self.areas.load_found(self.doc, {'bounds': [0, 0, 2, 2], 'mask_path': wrong}, folder)
            another = os.path.join(folder, 'another-chat')
            with self.assertRaisesRegex(ValueError, 'only from this chat folder'):
                self.areas.load_found(self.doc, {'bounds': [1, 1, 2, 2], 'mask_path': path}, another)
        finally:
            import shutil; shutil.rmtree(folder)

    def test_the_typed_phrase(self):
        for text in ('paint only in my selection', 'Please paint the sky only inside my selection.', 'work only within the selection'):
            self.assertTrue(paint_only.wants_area(text), text)
        for text in ('paint the sky', 'select the moon', 'only my selection is wrong? paint everywhere'):
            self.assertFalse(paint_only.wants_area(text), text)


import test_feature_guard as feature_tests


class BridgeTests(feature_tests.Setup, unittest.TestCase):
    """The bridge puts the protection back before an agent write when an Undo took it."""
    def setUp(self):
        super().setUp()
        doc = self.doc
        def add(name, kind, mask, author='agent', state='proposed', protected=False):
            feature = Feature(name, kind, mask.duplicate(), author, state, protected); feature.bounds = lambda: feature_tests.Rect(0, 0, SIZE, SIZE)
            doc.feature_list.append(feature); return feature
        doc.setTransientFeature = lambda name, kind, mask, protected=True: add(name, kind, mask, 'artist', 'kept', protected)
        doc.removeTransientFeature = lambda name: doc.feature_list.remove(doc.feature(name)) or True
        made = paint_only.AREAS._make; paint_only.AREAS._make = Selection
        self.addCleanup(lambda: (paint_only.AREAS.clear(doc), setattr(paint_only.AREAS, '_make', made)))

    def test_a_write_restores_the_protection_first(self):
        paint_only.AREAS.capture(self.doc, selected(0, 0, 2, 4))
        self.doc.removeTransientFeature(paint_only.SYSTEM_NAME)        # a document reopened, or a hot reload of the plugin
        done = feature_tests.run(self.h, 'fill_region', dict(feature_tests.FILL, selection='Sky'), 'fill')
        self.assertEqual(done['status'], 'ok', done.get('error'))
        self.assertIsNotNone(self.doc.feature(paint_only.SYSTEM_NAME), 'protected again before the fill')

    def test_autopilot_sets_and_clears_a_found_area_through_the_bridge(self):
        """Autopilot's found area (studio adoptFoundArea): the companion's mask copy protects the rest at once, outside the undo
        history; clear ends it. Only a chat folder's paint-only mask, and bounds inside the canvas."""
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(folder))
        os.makedirs(os.path.join(folder, '.shapes'))
        path = os.path.join(folder, '.shapes', 'paint-only-0123456789abcdef01234567.png')
        with open(path, 'wb') as handle: handle.write(paint_only.encode_png(4, 2, b'\xff' * 8))
        run = feature_tests.run
        done = run(self.h, 'paint_only_here', {'action': 'set', 'bounds': [0, 0, 4, 2], 'mask_path': path, 'name': 'Moonlit sky'})
        self.assertEqual(done['status'], 'ok', done.get('error'))
        self.assertEqual(done['name'], 'Moonlit sky')
        self.assertIsNotNone(self.doc.feature(paint_only.SYSTEM_NAME), 'the rest of the painting is protected')
        self.assertEqual(paint_only.AREAS.area(self.doc)['name'], 'Moonlit sky')
        with self.assertRaisesRegex(ValueError, 'inside the canvas'):
            run(self.h, 'paint_only_here', {'action': 'set', 'bounds': [0, 0, 9, 2], 'mask_path': path})
        with self.assertRaisesRegex(ValueError, 'chat folder'):
            run(self.h, 'paint_only_here', {'action': 'set', 'bounds': [0, 0, 4, 2], 'mask_path': os.path.join(folder, 'mask.png')})
        cleared = run(self.h, 'paint_only_here', {'action': 'clear'})
        self.assertEqual((cleared['status'], cleared['cleared']), ('ok', True))
        self.assertIsNone(self.doc.feature(paint_only.SYSTEM_NAME))


if __name__ == '__main__':
    unittest.main()

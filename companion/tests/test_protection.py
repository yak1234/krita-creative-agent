"""Protected areas on a fake layer tree: saved in the painting, proposed by the agent, kept or removed by the
artist, and enforced after every painting operation. Writes only into a temporary study folder."""
import json
import sys
import types
import unittest
import test_region_craft as region_tests

native = region_tests.native
protection = sys.modules['creative_test_package.protection']
SIZE = region_tests.SIZE
ALL = (0, 0, SIZE, SIZE)
AREA = [{'shape': 'rectangle', 'bounds': [0, 0, 2, 2]}]


class Layer(region_tests.Layer):
    """As in Krita: a node can be locked and removed."""
    def setLocked(self, value): self.is_locked = value
    def remove(self):
        self.parent.children.remove(self); self.parent = None; return True


class CloneLayer(Layer):
    """Krita's clone layer: no paint device of its own (pixelData is empty); its projection shows the source."""
    def __init__(self, doc, name, source):
        super().__init__(doc, name, 'clonelayer'); self.source = source
    def pixelData(self, x, y, w, h): return b''
    def projectionPixelData(self, x, y, w, h): return self.source.pixelData(x, y, w, h)


class SelectionMaskNode(Layer):
    """Krita's selection mask: its selection is read with selection()."""
    def __init__(self, doc, name):
        super().__init__(doc, name, 'selectionmask'); self.mask = region_tests.Mask()
        del self.selection                        # the shared fake Node's attribute would hide selection()
    def selection(self): return self.mask
    def setSelection(self, value): self.mask = value


class Document(region_tests.Document):
    def __init__(self):
        super().__init__(); self.annotations = {}
    def createSelectionMask(self, name): return SelectionMaskNode(self, name)
    def createNode(self, name, kind): return Layer(self, name, kind)
    def annotation(self, kind): return self.annotations.get(kind, b'')
    def setAnnotation(self, kind, description, data): self.annotations[kind] = bytes(data)
    def annotationTypes(self): return list(self.annotations)
    def pixelData(self, x, y, w, h):
        """The projection: visible paint and fill layers bottom to top, each pixel the topmost opaque one, its alpha
        scaled by the layer's transparency mask."""
        out = bytearray(w * h * 4)
        def visit(node):
            for child in node.children:
                if child.kind in ('grouplayer',):
                    visit(child); continue
                if child.kind not in ('paintlayer', 'filllayer', 'clonelayer') or not child.shown:
                    continue
                pixels = child.projectionPixelData(x, y, w, h) if child.kind == 'clonelayer' else child.pixelData(x, y, w, h)
                masks = [m for m in child.children if m.kind == 'transparencymask']
                for i in range(w * h):
                    alpha = pixels[i * 4 + 3]
                    for m in masks:
                        alpha = alpha * m.selection.pixelData(x + i % w, y + i // w, 1, 1)[0] // 255
                    if alpha:
                        out[i * 4:i * 4 + 4] = bytes(pixels[i * 4:i * 4 + 3]) + bytes([alpha])
        visit(self.root)
        return bytes(out)


def fake_raster():
    """protection_raster without Qt, on the same byte layouts."""
    raster = types.ModuleType('creative_test_package.protection_raster')
    raster.union = lambda masks, w, h: bytes(max(values) for values in zip(*masks)) if masks else bytes(w * h)
    def erase_inside(bgra, mask, w, h):
        out, removed = bytearray(bgra), 0
        for i, m in enumerate(mask):
            if m >= 128 and out[i * 4 + 3]: removed += 1
            out[i * 4 + 3] = 0 if m >= 128 else out[i * 4 + 3] * (255 - m) // 255
        return bytes(out), removed
    raster.erase_inside = erase_inside
    raster.inside_count = lambda mask: sum(1 for m in mask if m >= 128)
    raster.visible_inside = lambda bgra, mask: sum(1 for i, m in enumerate(mask) if m >= 128 and bgra[i * 4 + 3])
    def restore_inside(later, earlier, mask, w, h):
        out = bytearray(later)
        for i, m in enumerate(mask):
            if m >= 128: out[i * 4:i * 4 + 4] = earlier[i * 4:i * 4 + 4]
        return bytes(out)
    raster.restore_inside = restore_inside
    raster.invert = lambda mask: bytes(255 - m for m in mask)
    raster.changed_inside = lambda before, after, mask, w, h: sum(
        1 for i, m in enumerate(mask) if m >= 128 and before[i * 4:i * 4 + 4] != after[i * 4:i * 4 + 4])
    return raster


class ProtectionSetup(region_tests.RegionSetup):
    def setUp(self):
        super().setUp()
        self.h.doc = Document()
        self.h._creative_session.update(document_id=native.module.document_id(self.h.doc))
        self.prot_raster = fake_raster()
        prior = sys.modules.get(self.prot_raster.__name__)
        sys.modules[self.prot_raster.__name__] = self.prot_raster; native.package.protection_raster = self.prot_raster
        self.addCleanup(lambda: sys.modules.__setitem__(self.prot_raster.__name__, prior) if prior else sys.modules.pop(self.prot_raster.__name__, None))
        previous = protection.Selection
        protection.Selection = region_tests.Mask
        self.addCleanup(lambda: setattr(protection, 'Selection', previous))
        self.h._creative_new_layer = self.new_layer
        self.h.cmd_curve_stroke = self.stroke

    def new_layer(self, doc, session, params):
        """As the plugin does: pass layers go in a stage group, so a group above it does not end a continuation."""
        stage = next((n for n in doc.root.children if n.label == 'Stage'), None)
        if stage is None:
            stage = Layer(doc, 'Stage', 'grouplayer'); doc.root.addChildNode(stage, None)
        node = Layer(doc, params.get('name', 'Pass'), 'paintlayer'); node.pixels = bytearray(SIZE * SIZE * 4)
        stage.addChildNode(node, None); doc.active = node
        return {'id': node.uniqueId().toString()}

    colour = bytes([0, 0, 255, 255])                                                  # red, BGRA

    def stroke(self, stroke, settle=True):
        """Every stroke paints the whole active layer in self.colour."""
        self.h.doc.active.pixels = bytearray(self.colour * (SIZE * SIZE)); return {'status': 'ok'}

    def keep(self, name='Woman and car', bounds=(0, 0, 2, 2)):
        area = self.propose(name, [{'shape': 'rectangle', 'bounds': list(bounds)}])['area']
        self.h._protect_set_state(self.h.doc, area['id'], 'active'); return area

    def paint(self, identifier='pass', **extra):
        return region_tests.run(self.h, 'paint_pass', dict({'name': 'Street', 'preset': 'b) Basic-1', 'stage_id': 's',
                                'strokes': [region_tests.TexturePassTests.STROKE]}, **extra), identifier)

    def inside(self, bounds=(0, 0, 2, 2)):
        return self.h.doc.pixelData(*bounds)

    def propose(self, name='Woman and car', area=AREA):
        return region_tests.run(self.h, 'propose_protection', {'name': name, 'area': area}, 'propose-' + name)

    def group(self):
        return next((n for n in self.h.doc.root.children if n.name() == self.h.PROTECTION_GROUP), None)


class ProtectedAreaTests(ProtectionSetup, unittest.TestCase):
    def test_propose_creates_a_pending_area_in_the_owned_group(self):
        result = self.propose()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        area = result['area']
        self.assertEqual((area['name'], area['state'], area['by'], area['bounds']), ('Woman and car', 'pending', 'agent', [0, 0, 2, 2]))
        group = self.group()
        self.assertIsNotNone(group, 'the plugin-owned group exists')
        self.assertIs(self.h.doc.root.children[-1], group, 'at the top of the layer stack')
        self.assertTrue(group.locked())
        self.assertEqual([(n.name(), n.type()) for n in group.children], [('Woman and car', 'selectionmask')])
        saved = json.loads(self.h.doc.annotation('creative-agent-protection'))
        self.assertEqual(saved[area['id']]['state'], 'pending', 'state is saved in the painting')

    def test_pending_areas_protect_nothing(self):
        self.propose()
        self.assertIsNone(self.h._protect_mask(self.h.doc, ALL))

    def test_keep_makes_it_active_and_remove_deletes_the_mask(self):
        area = self.propose()['area']
        self.h._protect_set_state(self.h.doc, area['id'], 'active')
        mask = self.h._protect_mask(self.h.doc, ALL)
        self.assertEqual(mask[0], 255); self.assertEqual(mask[SIZE + 1], 255); self.assertEqual(mask[3], 0)
        self.assertEqual(self.h._protect_list(self.h.doc)[0]['state'], 'active')
        self.h._protect_remove(self.h.doc, area['id'])
        self.assertEqual(self.group().children, [])
        self.assertEqual(self.h._protect_list(self.h.doc), [])
        self.assertIsNone(self.h._protect_mask(self.h.doc, ALL))

    def test_locked_layers_are_listed_but_add_nothing_to_the_mask(self):
        layer = self.artist_layer('Background'); layer.is_locked = True
        listed = self.h._protect_list(self.h.doc)
        self.assertEqual([(a['id'], a['name'], a['by'], a['count']) for a in listed], [('locked-layers', 'Locked layers', 'automatic', 1)])
        self.assertIsNone(self.h._protect_mask(self.h.doc, ALL), 'a locked opaque background must not stop all painting')

    def test_a_mask_deleted_by_hand_is_dropped_and_the_group_recreated(self):
        area = self.propose()['area']
        self.h._protect_set_state(self.h.doc, area['id'], 'active')
        self.h.doc.root.children.remove(self.group())
        self.assertEqual(self.h._protect_list(self.h.doc), [])
        self.assertNotIn(area['id'], json.loads(self.h.doc.annotation('creative-agent-protection') or b'{}'))
        self.assertEqual(self.propose('Sky')['status'], 'ok')
        self.assertEqual([n.name() for n in self.group().children], ['Sky'])

    def test_companion_cannot_keep_or_remove(self):
        area = self.propose()['area']
        for operation in ('protection_keep', 'protection_remove', 'protection_discard', 'protection_set_state'):
            with self.assertRaisesRegex(ValueError, 'Only the artist can change protection in the panel.'):
                region_tests.run(self.h, operation, {'id': area['id']}, operation)
        self.assertEqual(self.h._protect_list(self.h.doc)[0]['state'], 'pending')

    def test_list_operation_and_active_summary(self):
        kept = self.propose()['area']; self.propose('Sky', [{'shape': 'rectangle', 'bounds': [2, 2, 2, 2]}])
        self.h._protect_set_state(self.h.doc, kept['id'], 'active')
        listed = region_tests.run(self.h, 'protection_list', {}, None)
        self.assertEqual([a['name'] for a in listed['areas']], ['Woman and car', 'Sky'])
        self.assertEqual(self.h._protect_active(self.h.doc), [{'id': kept['id'], 'name': 'Woman and car', 'bounds': [0, 0, 2, 2]}])

    def test_an_empty_area_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'empty'):
            self.propose('Nothing', [{'shape': 'rectangle', 'bounds': [0, 0, 1, 1]}, {'shape': 'rectangle', 'bounds': [0, 0, 1, 1], 'mode': 'subtract'}])


class EnforcementTests(ProtectionSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.car = self.artist_layer('Car')
        self.car.pixels = bytearray(bytes([200, 100, 50, 255]) * (SIZE * SIZE))     # the artist's opaque painting

    def test_a_stroke_pass_into_an_area_is_erased_there_and_reported(self):
        self.keep(); before = self.inside()
        result = self.paint()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['protected'], [{'name': 'Woman and car', 'pixels': 4, 'share': 1.0}])
        self.assertEqual(self.inside(), before, 'nothing inside the area changed')
        self.assertEqual(self.h.doc.pixelData(3, 3, 1, 1), bytes([0, 0, 255, 255]), 'the rest of the pass stays')

    def test_a_fill_layer_over_everything_gets_a_mask(self):
        self.keep(); before = self.inside()
        result = region_tests.run(self.h, 'create_layer', {'name': 'Wash', 'type': 'fill', 'generator': 'color',
                                                           'generator_config': {'color': '#ff0000'}, 'stage_id': 's'}, 'wash')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        fill = self.h._creative_node(self.h.doc, result['layer_id'])
        self.assertEqual([m.kind for m in fill.children], ['transparencymask'])
        self.assertEqual(self.inside(), before)
        self.assertEqual(result['protected'][0]['name'], 'Woman and car')

    def test_a_clone_is_masked_inside_a_protected_area(self):
        figure = Layer(self.h.doc, 'Figure', 'paintlayer'); figure.pixels = bytearray(bytes([0, 255, 0, 255]) * (SIZE * SIZE))
        self.h.doc.root.addChildNode(figure, None)
        self.keep(); before = self.inside()
        self.h.doc.createCloneLayer = lambda name, source: CloneLayer(self.h.doc, name, source)
        result = region_tests.run(self.h, 'clone_layer', {'name': 'Echo', 'source': figure.id, 'stage_id': 's'}, 'echo')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        clone = self.h._creative_node(self.h.doc, result['layer_id'])
        self.assertEqual([m.kind for m in clone.children], ['transparencymask'])
        self.assertEqual(self.inside(), before)
        self.assertEqual(result['protected'][0]['name'], 'Woman and car')

    def test_an_artist_layer_overlapping_an_area_cannot_change_opacity(self):
        self.keep()
        with self.assertRaisesRegex(ValueError, "That layer shows inside the protected area 'Woman and car'."):
            region_tests.run(self.h, 'adjust_layer', {'layer_id': self.car.uniqueId().toString(), 'opacity': 0.5, 'stage_id': 's'}, 'fade')
        self.assertEqual(self.car.opacity(), 255)

    def test_an_artist_layer_away_from_the_areas_can_change(self):
        self.keep(); other = self.artist_layer('Moon'); other.pixels = bytearray(SIZE * SIZE * 4)
        other.pixels[15 * 4 + 3] = 255                                                 # one pixel, far corner
        result = region_tests.run(self.h, 'adjust_layer', {'layer_id': other.uniqueId().toString(), 'opacity': 0.5, 'stage_id': 's'}, 'moon')
        self.assertEqual(result['status'], 'ok', result.get('error'))

    def test_the_backstop_removes_a_new_layer_that_still_changes_the_area(self):
        self.keep(); before = self.inside()
        self.h._protect_erase = lambda *args: []                                       # an operation erase does not cover
        result = self.paint('escaped')
        self.assertEqual(result['error_code'], 'protected_change')
        self.assertIn("'Woman and car'", result['error'])
        self.assertEqual(self.inside(), before, 'the escaped change is gone')
        stage = next(n for n in self.h.doc.root.children if n.label == 'Stage')
        self.assertEqual(stage.children, [], 'the escaped pass layer is gone')

    def test_operations_without_a_layer_still_run_the_backstop(self):
        self.keep(); captured = self.h._protect_capture(self.h.doc, self.h._creative_session, 'merge_passes', {})
        self.car.pixels[0:4] = bytes([1, 2, 3, 255])                                   # something changed the area
        result = self.h._protect_enforce(self.h.doc, self.h._creative_session, 'merge_passes', {}, {'status': 'ok'}, captured)
        self.assertEqual(result['error_code'], 'protected_change')

    def test_enforcement_reads_only_the_overlap(self):
        self.keep(); reads = []; recording = []
        original, enforce = Layer.pixelData, self.h._protect_enforce
        def recorded(node, x, y, w, h):
            if recording and node.kind == 'paintlayer' and node.label == 'Street': reads.append((x, y, w, h))
            return original(node, x, y, w, h)
        def enforcing(*args):
            recording.append(True)
            try: return enforce(*args)
            finally: recording.clear()
        Layer.pixelData = recorded; self.addCleanup(lambda: setattr(Layer, 'pixelData', original))
        self.h._protect_enforce = enforcing                                              # only enforcement's reads count
        self.paint(region=[1, 1, 3, 3])
        self.assertTrue(reads); self.assertTrue(all(r == (1, 1, 1, 1) for r in reads), reads)

    def test_without_active_areas_nothing_is_added(self):
        self.propose()                                                                  # pending only
        result = self.paint()
        self.assertNotIn('protected', result)
        self.assertEqual(self.h.doc.pixelData(0, 0, 1, 1), bytes([0, 0, 255, 255]), 'pending areas protect nothing')


class ReviewFixTests(ProtectionSetup, unittest.TestCase):
    """The final review's findings, each pinned."""
    def setUp(self):
        super().setUp()
        self.car = self.artist_layer('Car')
        self.car.pixels = bytearray(bytes([200, 100, 50, 255]) * (SIZE * SIZE))

    keep, paint, inside = EnforcementTests.keep, EnforcementTests.paint, EnforcementTests.inside

    def test_a_painting_that_is_not_8_bit_refuses_before_painting(self):
        self.keep(); self.h.doc.colorDepth = lambda: 'U16'
        layers = len(self.h.doc.root.children)
        with self.assertRaisesRegex(ValueError, '8-bit RGBA'):
            self.paint('deep')
        self.assertEqual(len(self.h.doc.root.children), layers, 'nothing was painted')
        with self.assertRaisesRegex(ValueError, '8-bit RGBA'):
            self.propose('Sky')

    def test_existing_agent_paint_inside_an_area_is_kept(self):
        first = self.paint('sky')                                                       # red everywhere, nothing protected yet
        self.keep(); before = self.inside()
        self.colour = bytes([255, 0, 0, 255])                                           # the next chunk paints blue
        result = self.paint('sky more', continue_layer_id=first['layer_id'])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        layer = self.h._creative_node(self.h.doc, first['layer_id'])
        self.assertEqual(bytes(layer.pixelData(0, 0, 1, 1)), bytes([0, 0, 255, 255]), 'the earlier sky stays inside the area')
        self.assertEqual(bytes(layer.pixelData(3, 3, 1, 1)), bytes([255, 0, 0, 255]), 'the new paint outside it')
        self.assertEqual(self.inside(), before)

    def test_a_toolbox_edit_of_an_artist_layer_inside_an_area_is_refused(self):
        self.keep()
        with self.assertRaisesRegex(ValueError, "That layer shows inside the protected area 'Woman and car'."):
            self.h._protect_refuse(self.h.doc, self.h._creative_session, 'painting_toolbox', {'source_layer_id': self.car.uniqueId().toString()})

    def test_a_review_that_changes_an_area_is_reported(self):
        self.keep()
        def review(doc, session, params, operation_id, fingerprint):
            self.car.shown = False; return {'status': 'ok'}                          # a reject that hides the car
        self.h._creative_review = review
        result = region_tests.run(self.h, 'review_pass', {'action': 'reject', 'pass_id': 'p1'}, 'reject')
        self.assertEqual(result['error_code'], 'protected_change')

    def test_renaming_the_group_or_moving_a_mask_keeps_the_areas(self):
        area = self.keep()
        group = self.group(); group.label = 'My protections'
        self.assertEqual([a['name'] for a in self.h._protect_list(self.h.doc)], ['Woman and car'])
        mask = group.children[0]; group.children.remove(mask); self.h.doc.root.addChildNode(mask, None)
        self.assertEqual([a['id'] for a in self.h._protect_active(self.h.doc)], [area['id']])

    def test_editing_unlocks_the_group_and_locks_it_again(self):
        self.keep()
        self.h._protect_editing(self.h.doc, True); self.assertFalse(self.group().locked())
        self.h._protect_editing(self.h.doc, False); self.assertTrue(self.group().locked())

    def test_a_settings_change_that_reaches_an_area_is_undone(self):
        own = Layer(self.h.doc, 'Glow', 'paintlayer'); own.pixels = bytearray(bytes([9, 9, 9, 255]) * (SIZE * SIZE)); own.shown = False
        self.h.doc.root.addChildNode(own, None); self.h._creative_session['layers'].add(own.uniqueId().toString())
        self.keep(); before = self.inside()
        result = region_tests.run(self.h, 'adjust_layer', {'layer_id': own.uniqueId().toString(), 'visible': True, 'stage_id': 's'}, 'show')
        self.assertEqual((result['status'], result['error_code']), ('error', 'protected_change'))
        self.assertFalse(own.visible(), 'the earlier setting is back')
        self.assertEqual(self.inside(), before)

    def test_a_pass_reaches_its_strokes_widened_for_scattering_brushes(self):
        stroke = {'start': [1000, 800], 'segments': [[1000, 800, 1100, 800, 1200, 900]], 'size': 10}
        self.assertEqual(self.h._protect_reach({'strokes': [stroke]}, 'paint_pass'), [924, 724, 1277, 977], '6 sizes + 16 px')
        self.assertEqual(self.h._protect_reach({'strokes': [stroke], 'region': [950, 750, 100, 100]}, 'paint_pass'), [950, 750, 1050, 850])
        self.assertIsNone(self.h._protect_reach({'name': 'Wash'}, 'create_layer'), 'other operations can reach anywhere')


if __name__ == '__main__':
    unittest.main()

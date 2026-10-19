"""canvas_projection.py and its callers: the fork's region refresh and scaled read (Krita master, tasks 2.1 and 2.3)
where Krita has them, the native helper's region refresh on stock Krita when it is loaded, and the whole-image refresh
otherwise. Fake documents with and without the fork's overloads; the first part with real Qt (QRect, QImage, the
helper found through Qt's meta-object system), the second on the shared stub package. Writes no files outside the
temporary folders the shared setups remove."""
import importlib
import sys
import types
import unittest
import test_agent_accel as accel_tests
import test_native as native
import test_region_craft as region_tests
import test_layer_craft as layer_tests
import test_material_stamp as stamp_tests
import test_toolbox as toolbox_tests

qt, app, FakeService = accel_tests.qt, accel_tests.app, accel_tests.FakeService
# Loaded beside agent_accel in the package test_agent_accel made with the real binding, so it finds that module's helper.
projection = importlib.import_module('accel_test_package.canvas_projection')


class StockDocument:
    """Stock Krita 5.3.3: refreshProjection() and projection(x, y, w, h) only; SIP refuses a QRect with a TypeError."""
    def __init__(self, path='', size=(6000, 4500)):
        self.path, self.size = path, size
        self.full, self.waits, self.tried = 0, 0, 0
    def fileName(self): return self.path
    def width(self): return self.size[0]
    def height(self): return self.size[1]
    def waitForDone(self): self.waits += 1
    def refreshProjection(self, *args):
        if args:
            self.tried += 1
            raise TypeError('refreshProjection(self): too many arguments')
        self.full += 1
    def projection(self, x=0, y=0, w=0, h=0):
        if not all(isinstance(v, int) for v in (x, y, w, h)):
            self.tried += 1
            raise TypeError("projection(self, x: int = 0, y: int = 0, w: int = 0, h: int = 0): argument 1 has unexpected type 'QRect'")
        return qt.QImage(w, h, qt.QImage.Format.Format_ARGB32)


class ForkDocument(StockDocument):
    """The fork: refreshProjection(QRect) and projection(QRect, float) besides the stock overloads."""
    def __init__(self, path='', size=(6000, 4500)):
        super().__init__(path, size); self.regions, self.reads = [], []
    def refreshProjection(self, rect=None):
        if rect is None:
            self.full += 1
        else:
            self.regions.append((rect.x(), rect.y(), rect.width(), rect.height()))
    def projection(self, *args):
        if len(args) == 2 and isinstance(args[0], qt.QRect):
            rect, scale = args
            self.reads.append(((rect.x(), rect.y(), rect.width(), rect.height()), scale))
            return qt.QImage(round(rect.width() * scale), round(rect.height() * scale), qt.QImage.Format.Format_ARGB32)
        return super().projection(*args)


class RegionRefreshTests(unittest.TestCase):
    def setUp(self):
        projection._SUPPORTED.clear()
        saved = self.default = projection.HELPER_REGION_REFRESH
        projection.HELPER_REGION_REFRESH = True            # on by default; one test turns it off
        self.addCleanup(lambda: setattr(projection, 'HELPER_REGION_REFRESH', saved))

    def tearDown(self):
        projection._SUPPORTED.clear()
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def test_the_fork_recomposites_only_the_rect(self):
        doc = ForkDocument('/art/new_moscow.kra'); fake = FakeService()
        self.assertEqual(projection.refresh(doc, [10, 20, 300, 400]), 'fork')
        self.assertEqual((doc.regions, doc.full, fake.calls), ([(10, 20, 300, 400)], 0, []), 'the fork first, not the helper')

    def test_by_default_stock_keeps_the_whole_refresh(self):
        # Protocol 7's grown region equals a whole refresh, but measured on New Moscow (6000x4500, wavelet filter masks)
        # it was no faster than the whole refresh (medians 38/42/47 ms against 21-25 ms), so stock keeps the whole one.
        self.assertIs(self.default, False)
        doc = StockDocument('/art/new_moscow.kra'); fake = FakeService(version=7)
        projection.HELPER_REGION_REFRESH = self.default
        self.assertEqual(projection.refresh(doc, [10, 20, 300, 400]), 'full')
        self.assertEqual((fake.calls, doc.full), ([], 1))

    def test_turned_on_stock_uses_a_protocol_7_helper_s_grown_region(self):
        doc = StockDocument('/art/new_moscow.kra'); fake = FakeService(version=7)
        self.assertEqual(projection.refresh(doc, [10, 20, 300, 400]), 'helper')
        self.assertEqual((fake.calls, doc.full), ([('region', '/art/new_moscow.kra', 10, 20, 300, 400)], 0))

    def test_an_older_helper_is_never_trusted_with_a_region(self):
        # Before protocol 7 the helper recomposited exactly the rect, leaving a filter mask's or layer style's halo stale.
        doc = StockDocument('/art/new_moscow.kra'); fake = FakeService(version=6)
        self.assertEqual(projection.refresh(doc, [10, 20, 300, 400]), 'full')
        self.assertEqual((fake.calls, doc.full), ([], 1))

    def test_turned_off_stock_keeps_the_whole_refresh_even_with_the_helper(self):
        projection.HELPER_REGION_REFRESH = False
        doc = StockDocument('/art/new_moscow.kra'); fake = FakeService(version=7)
        self.assertEqual(projection.refresh(doc, [10, 20, 300, 400]), 'full')
        self.assertEqual((fake.calls, doc.full), ([], 1))

    def test_stock_with_the_helper_recomposites_the_rect_there(self):
        doc = StockDocument('/art/new_moscow.kra'); fake = FakeService(version=7)
        self.assertEqual(projection.refresh(doc, [10, 20, 300, 400]), 'helper')
        self.assertEqual((fake.calls, doc.full), ([('region', '/art/new_moscow.kra', 10, 20, 300, 400)], 0))

    def test_stock_without_the_helper_recomposites_everything(self):
        doc = StockDocument('/art/new_moscow.kra')
        self.assertEqual(projection.refresh(doc, [10, 20, 300, 400]), 'full')
        self.assertEqual(doc.full, 1)

    def test_a_helper_that_cannot_find_the_document_falls_back_to_everything(self):
        doc = StockDocument('/missing.kra'); FakeService(version=7)
        self.assertEqual(projection.refresh(doc, [0, 0, 10, 10]), 'full')
        self.assertEqual(doc.full, 1)

    def test_an_unsaved_document_never_goes_to_the_helper(self):
        # The helper finds a document by its file: '' would mean whichever document is active.
        doc = StockDocument(''); fake = FakeService(version=7)
        self.assertEqual(projection.refresh(doc, [0, 0, 10, 10]), 'full')
        self.assertEqual((fake.calls, doc.full), ([], 1))

    def test_the_rect_is_cut_to_the_canvas_and_one_outside_it_does_nothing(self):
        doc = ForkDocument(size=(100, 100))
        self.assertEqual(projection.refresh(doc, [-10, -20, 50, 500]), 'fork')
        self.assertEqual(doc.regions, [(0, 0, 40, 100)])
        self.assertEqual(projection.refresh(doc, [200, 0, 10, 10]), 'none')
        self.assertEqual((doc.regions, doc.full), ([(0, 0, 40, 100)], 0), 'nothing inside the canvas changed')

    def test_no_rect_is_the_whole_image_even_on_the_fork(self):
        doc = ForkDocument()
        self.assertEqual(projection.refresh(doc), 'full')
        self.assertEqual((doc.full, doc.regions), (1, []))

    def test_stock_is_learned_once_per_document_class(self):
        doc = StockDocument('/art/new_moscow.kra')
        for _ in range(3):
            projection.refresh(doc, [0, 0, 10, 10])
        self.assertEqual((doc.tried, doc.full), (1, 3), 'the QRect overload is tried once, then never again')


class PixelWriteTests(unittest.TestCase):
    """After Node.setPixelData: the fork's write marks its own rect dirty, so waiting is enough once the fork is known."""
    def setUp(self):
        projection._SUPPORTED.clear()
        saved = projection.HELPER_REGION_REFRESH
        projection.HELPER_REGION_REFRESH = True            # on by default; one test turns it off
        self.addCleanup(lambda: setattr(projection, 'HELPER_REGION_REFRESH', saved))

    def tearDown(self):
        projection._SUPPORTED.clear()
        for child in app.findChildren(qt.QObject, 'creative-agent-accel'):
            child.setParent(None); child.deleteLater()

    def test_on_the_fork_a_write_only_waits_once_the_fork_is_known(self):
        doc = ForkDocument()
        self.assertEqual(projection.pixels_written(doc, [0, 0, 8, 8]), 'fork', 'not known yet: the region refresh tells')
        self.assertEqual(projection.pixels_written(doc, [8, 8, 8, 8]), 'dirty')
        self.assertEqual((doc.regions, doc.full, doc.waits), ([(0, 0, 8, 8)], 0, 1))

    def test_on_stock_a_write_is_recomposited_by_the_helper_or_whole(self):
        helped, whole = StockDocument('/art/a.kra'), StockDocument('/art/b.kra', (64, 64))
        fake = FakeService(version=7)
        self.assertEqual(projection.pixels_written(helped, [0, 0, 8, 8]), 'helper')
        self.assertEqual(fake.calls, [('region', '/art/a.kra', 0, 0, 8, 8)])
        fake.setParent(None)
        self.assertEqual(projection.pixels_written(whole, [0, 0, 8, 8]), 'full')
        self.assertEqual((whole.full, whole.waits), (1, 0))


class ScaledReadTests(unittest.TestCase):
    def setUp(self):
        projection._SUPPORTED.clear()

    def tearDown(self):
        projection._SUPPORTED.clear()

    def test_the_fork_reads_a_view_scaled_in_one_call_with_a_qrect_and_a_float(self):
        doc = ForkDocument()
        image = projection.read_scaled(doc, [0, 0, 6000, 4500], 1568 / 6000)
        (rect, scale), = doc.reads
        self.assertEqual((rect, type(scale)), ((0, 0, 6000, 4500), float))
        self.assertEqual((image.width(), image.height()), (1568, 1176))

    def test_stock_has_no_scaled_read_and_is_asked_once(self):
        doc = StockDocument()
        self.assertIsNone(projection.read_scaled(doc, [0, 0, 6000, 4500], 0.25))
        self.assertIsNone(projection.read_scaled(doc, [0, 0, 6000, 4500], 0.25))
        self.assertEqual(doc.tried, 1)

    def test_a_null_answer_is_none_so_the_caller_reads_as_before(self):
        doc = ForkDocument(); doc.projection = lambda *args: qt.QImage()
        self.assertIsNone(projection.read_scaled(doc, [0, 0, 10, 10], 0.5))


# ----- the plugin's callers, on the stub package ------------------------------------------------------------------
stub_projection = sys.modules['creative_test_package.canvas_projection']


class Rect:
    """QRect as the plugin builds it, for the stub package (which has no Qt)."""
    def __init__(self, x, y, w, h): self.box = (x, y, w, h)
    def x(self): return self.box[0]
    def y(self): return self.box[1]
    def width(self): return self.box[2]
    def height(self): return self.box[3]


class Fork:
    """The fork's overloads over any fake document: each refresh recorded, None for the whole image."""
    def refreshProjection(self, rect=None):
        self.__dict__.setdefault('refreshes', []).append(None if rect is None else rect.box)
    def projection(self, *args):
        if len(args) == 2 and isinstance(args[0], Rect):
            self.__dict__.setdefault('reads', []).append((args[0].box, args[1]))
            return View(round(args[0].box[2] * args[1]), round(args[0].box[3] * args[1]), 'fork')
        raise AssertionError('no full-size read expected here')


class Stock:
    """Stock Krita's overloads: no QRect anywhere (SIP's TypeError)."""
    def refreshProjection(self, *args):
        if args: raise TypeError('refreshProjection(self): too many arguments')
        self.__dict__.setdefault('refreshes', []).append(None)
    def projection(self, x=0, y=0, w=0, h=0):
        if isinstance(x, Rect): raise TypeError("projection(self, x: int = 0, ...): argument 1 has unexpected type 'QRect'")
        raise AssertionError('no full-size read expected here')


def restore(test, owner, name, value):
    """Set owner.name for one test, then put back what was there (or nothing)."""
    missing = object(); prior = owner.__dict__.get(name, missing)
    setattr(owner, name, value)
    test.addCleanup(lambda: delattr(owner, name) if prior is missing else setattr(owner, name, prior))


def build(doc, kind):
    """`doc` as the fork or stock Krita builds it: a class of its own, so what the plugin learns about one never
    reaches another test's documents."""
    doc.__class__ = type(kind.__name__ + doc.__class__.__name__, (kind, doc.__class__), {})
    doc.refreshes = []
    return doc


class StubSetup:
    def setUp(self):
        super().setUp()
        restore(self, native.qt, 'QRect', Rect)
        stub_projection._SUPPORTED.clear(); self.addCleanup(stub_projection._SUPPORTED.clear)
        saved = stub_projection.HELPER_REGION_REFRESH
        stub_projection.HELPER_REGION_REFRESH = True       # on by default; kept on whatever another test did
        self.addCleanup(lambda: setattr(stub_projection, 'HELPER_REGION_REFRESH', saved))

    def fake_accel(self, refresh_region=None):
        """agent_accel with no stroke helper and, when given, the helper's region refresh."""
        accel = types.ModuleType('creative_test_package.agent_accel')
        accel.NATIVE_STROKES, accel.paint_strokes = False, lambda *args, **kwargs: None
        if refresh_region is not None:
            accel.refresh_region = refresh_region
        prior = sys.modules.get(accel.__name__)
        sys.modules[accel.__name__] = accel; native.package.agent_accel = accel
        def restore():
            if prior: sys.modules[accel.__name__] = prior; native.package.agent_accel = prior
            else: sys.modules.pop(accel.__name__, None); native.package.__dict__.pop('agent_accel', None)
        self.addCleanup(restore)
        return accel


# One stroke from (10, 20) to (40, 20), size 20: reach is its points widened by 6 sizes + 16 (protection's reach),
# [-126, -116, 177, 157], cut to the 768x1024 canvas.
REACH = (0, 0, 177, 157)


class PaintPassRefreshTests(StubSetup, unittest.TestCase):
    def pass_on(self, kind, path=''):
        h = native.Harness(); build(h.doc, kind)
        h.doc.fileName = lambda: path
        h._creative_checkpoint = lambda doc, session: {'status': 'ok'}
        h._creative_session['passes'] = []
        result = h.cmd_creative(native.request())
        self.assertEqual(result['status'], 'ok', result.get('error'))
        return h

    def test_on_the_fork_a_pass_recomposites_only_its_strokes_reach(self):
        self.fake_accel()
        h = self.pass_on(Fork)
        self.assertEqual(h.doc.refreshes, [REACH])
        self.assertTrue(h._creative_session.get('projection_fresh'), 'the observation after it still skips a refresh')

    def test_on_stock_with_the_helper_the_helper_recomposites_the_reach(self):
        calls = []
        self.fake_accel(lambda path, rect, app=None: calls.append((path, tuple(rect))) or {'ms': 5, 'rect': tuple(rect)})
        h = self.pass_on(Stock, '/art/painting.kra')
        self.assertEqual((calls, h.doc.refreshes), ([('/art/painting.kra', REACH)], []))

    def test_on_stock_without_the_helper_a_pass_recomposites_everything_as_before(self):
        self.fake_accel()
        h = self.pass_on(Stock, '/art/painting.kra')
        self.assertEqual(h.doc.refreshes, [None])


class PixelPassRefreshTests(StubSetup, region_tests.RegionSetup, unittest.TestCase):
    """fill_region on a new layer: its settings were composited when it was made, so only the filled rect changes."""
    def test_a_fill_on_a_new_layer_recomposites_its_rect_on_the_fork(self):
        build(self.h.doc, Fork)
        result = region_tests.run(self.h, 'fill_region', {'name': 'Sky flat', 'color': '#3a6ea5',
                                  'area': [{'shape': 'rectangle', 'bounds': [0, 0, 4, 2]}]}, 'sky')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(self.h.doc.refreshes, [None, (0, 0, 4, 2)], 'the new layer whole, then the fill by its rect')

    def test_a_fill_on_stock_without_the_helper_recomposites_everything(self):
        build(self.h.doc, Stock)
        region_tests.run(self.h, 'fill_region', {'name': 'Sky flat', 'color': '#3a6ea5',
                         'area': [{'shape': 'rectangle', 'bounds': [0, 0, 4, 2]}]}, 'sky')
        self.assertEqual(self.h.doc.refreshes, [None, None])

    def test_a_fill_on_an_edit_copy_hides_the_original_so_it_stays_whole(self):
        build(self.h.doc, Fork)
        region_tests.run(self.h, 'create_layer', {'name': 'Flats', 'type': 'paint'}, 'flats')
        flats = self.h.doc.root.childNodes()[-1]
        result = region_tests.run(self.h, 'fill_region', {'layer_id': flats.id, 'color': '#ff0000',
                                  'area': [{'shape': 'rectangle', 'bounds': [0, 0, 2, 2]}]}, 'recolour')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(self.h.doc.refreshes[-1], None, 'a visibility change: the whole image')
        self.assertNotIn((0, 0, 2, 2), self.h.doc.refreshes)


class StampRefreshTests(StubSetup, stamp_tests.MaterialSetup, unittest.TestCase):
    def setUp(self):
        super().setUp(); self.make()

    def test_a_stamp_recomposites_its_rect_on_the_fork(self):
        build(self.h.doc, Fork)
        result = self.stamp(area=[{'shape': 'rectangle', 'bounds': [0, 0, 2, 4]}], dabs=[self.dab(x=1, y=2, scale=0.1)])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(self.h.doc.refreshes[-1], tuple(result['stamped_bounds']))
        self.assertEqual(self.h.doc.refreshes.count(None), 1, 'only the new layer whole')


class PropertyChangeRefreshTests(StubSetup, unittest.TestCase):
    def test_layer_settings_keep_the_whole_image_refresh_on_the_fork(self):
        h = layer_tests.Harness(); build(h.doc, Fork)
        layer_tests.run(h, 'create_layer', {'name': 'Glow', 'type': 'paint'}, 'glow')
        glow = h.doc.root.childNodes()[-1]
        h.doc.refreshes = []
        layer_tests.run(h, 'set_layer', {'layer_id': glow.id, 'blend_mode': 'overlay', 'opacity': 0.5}, 'adjust')
        self.assertEqual(h.doc.refreshes, [None])


class TexturePassRefreshTests(StubSetup, region_tests.RegionSetup, unittest.TestCase):
    def test_a_texture_pass_s_layer_is_composited_whole_before_its_strokes_by_their_reach(self):
        # blend_mode and clip_to make the layer with its settings (create_layer's whole refresh); the strokes after it
        # change only their reach.
        build(self.h.doc, Fork)
        self.h.cmd_curve_stroke = lambda stroke, settle=True: {'status': 'ok'}
        stroke = {'start': [1, 1], 'segments': [[1, 1, 2, 2, 3, 3]], 'size': 2, 'opacity': 1, 'flow': 1, 'color': '#806040'}
        result = region_tests.run(self.h, 'paint_pass', {'name': 'Fur', 'preset': 'b) Basic-1', 'strokes': [stroke],
                                                         'blend_mode': 'overlay', 'layer_opacity': 0.4}, 'fur')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(self.h.doc.refreshes, [None, (0, 0, 4, 4)], 'settings whole, then the strokes by their reach (cut to 4x4)')


class ToolboxSnapshotRefreshTests(StubSetup, unittest.TestCase):
    def test_the_visible_region_copy_recomposites_only_its_region_before_reading_it(self):
        h = toolbox_tests.Harness(); h.doc = build(toolbox_tests.ProjectionDocument(), Fork)
        h._creative_session.update(document_id=native.module.document_id(h.doc), width=4, height=4)
        previous = native.module.Selection; native.module.Selection = toolbox_tests.Mask
        self.addCleanup(lambda: setattr(native.module, 'Selection', previous))
        result = toolbox_tests.call(h, [('curve_stroke', {})], projection=[0, 0, 2, 2])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(h.doc.refreshes, [(0, 0, 2, 2), None], 'the read by its region; the toolbox ends whole as before')


class View:
    """A QImage stand-in: its size, where it came from, and whether Qt scaled it."""
    def __init__(self, w, h, source): self.w, self.h, self.source, self.qt_scaled = w, h, source, None
    def width(self): return self.w
    def height(self): return self.h
    def isNull(self): return False
    def copy(self, x, y, w, h): return View(w, h, self.source + ' crop')
    def scaled(self, w, h, *modes):
        side = max(self.w, self.h); out = View(self.w * w // side, self.h * h // side, self.source + ' qt-scaled')
        self.qt_scaled = modes; return out


class ObservationViewTests(StubSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        restore(self, native.module, 'Qt', types.SimpleNamespace(AspectRatioMode=types.SimpleNamespace(KeepAspectRatio='keep'),
                                                                 TransformationMode=types.SimpleNamespace(SmoothTransformation='smooth')))
        self.h = native.Harness()
        self.h.doc.width, self.h.doc.height = (lambda: 6000), (lambda: 4500)

    def test_on_the_fork_the_view_is_one_scaled_read_not_a_qt_scale_of_the_full_size_canvas(self):
        build(self.h.doc, Fork); full = View(6000, 4500, 'full')
        image = self.h._creative_view_image(self.h.doc, full, None)
        self.assertEqual((image.source, image.width(), image.height()), ('fork', 1568, 1176))
        (rect, scale), = self.h.doc.reads
        self.assertEqual(rect, (0, 0, 6000, 4500)); self.assertAlmostEqual(scale, 1568 / 6000)
        self.assertIsNone(full.qt_scaled)

    def test_on_the_fork_a_large_region_is_read_scaled_too(self):
        build(self.h.doc, Fork)
        image = self.h._creative_view_image(self.h.doc, View(6000, 4500, 'full'), [1000, 500, 3136, 2000])
        self.assertEqual((image.source, image.width(), image.height()), ('fork', 1568, 1000))
        self.assertEqual(self.h.doc.reads[0][0], (1000, 500, 3136, 2000))

    def test_a_small_region_is_cut_from_the_full_size_read_without_another_read(self):
        build(self.h.doc, Fork)
        image = self.h._creative_view_image(self.h.doc, View(6000, 4500, 'full'), [0, 0, 800, 600])
        self.assertEqual((image.source, image.width()), ('full crop', 800))
        self.assertEqual(self.h.doc.__dict__.get('reads', []), [])

    def test_on_stock_the_full_size_canvas_is_scaled_with_qt_as_before(self):
        build(self.h.doc, Stock); full = View(6000, 4500, 'full')
        image = self.h._creative_view_image(self.h.doc, full, None)
        self.assertEqual((image.source, image.width()), ('full qt-scaled', 1568))
        self.assertEqual(full.qt_scaled, ('keep', 'smooth'))


class MergeSignatureTests(StubSetup, unittest.TestCase):
    def test_on_the_fork_the_before_and_after_canvas_is_one_scaled_read(self):
        doc = native.Document(); build(doc, Fork)
        doc.width, doc.height = (lambda: 6000), (lambda: 4500)
        class Converted:
            def constBits(self): return types.SimpleNamespace(asstring=lambda size: b'pixels')
            def sizeInBytes(self): return 6
        restore(self, View, 'convertToFormat', lambda self, fmt: Converted())
        restore(self, native.gui, 'QImage', types.SimpleNamespace(Format=types.SimpleNamespace(Format_ARGB32='argb32')))
        self.assertEqual(native.module.CreativeTools._native_merge_signature(doc), b'pixels')
        (rect, scale), = doc.reads
        self.assertEqual(rect, (0, 0, 6000, 4500)); self.assertAlmostEqual(scale, 600 / 6000)
        self.assertEqual(doc.refreshes, [None], 'the merge changed layers: the whole image is recomposited first')


if __name__ == '__main__':
    unittest.main()

"""Flat colours from line art through a colorize mask, on a fake 4x4 canvas. Files go to a temporary folder that is removed."""
import sys
import unittest
import test_region_craft as region_tests

colorize = sys.modules['creative_test_package.colorize']
LINE = bytes([0, 0, 0, 255])
OPEN = bytes(4)


def bgra(hex_colour):
    return bytes.fromhex(hex_colour[1:])[::-1] + b'\xff'


class ColorizeMask(region_tests.Layer):
    """Krita's colorize mask: the left half takes the first key colour, the right half the second."""
    def __init__(self, doc, name, log):
        super().__init__(doc, name, 'colorizemask'); self.log, self.done = log, False
    def initializeKeyStrokeColors(self, colours, transparent):
        self.colours, self.transparent = list(colours), transparent; self.log.append(('keys', tuple(colours), transparent))
    def setKeyStrokePixelData(self, data, colour, x, y, w, h):
        self.log.append(('seed', colour, (x, y, w, h), len(data))); return True
    def setUseEdgeDetection(self, value): self.log.append(('edges', value))
    def setCleanUpAmount(self, value): self.log.append(('cleanup', value))
    def setLimitToDeviceBounds(self, value): self.log.append(('bounds', value))
    def updateMask(self, force): self.log.append(('update', force)); self.done = True
    def setEditKeyStrokes(self, value): self.log.append(('edit keys', value))
    def setShowOutput(self, value): self.log.append(('show output', value))
    def colour_at(self, x):
        index = 0 if x < 2 else min(1, len(self.colours) - 1)
        return OPEN if index == self.transparent else bgra(self.colours[index])


class Layer(region_tests.Layer):
    """A paint layer whose projection shows a finished colorize mask behind its own pixels."""
    def projectionPixelData(self, x, y, w, h):
        own = self.pixelData(x, y, w, h)
        mask = next((child for child in self.children if child.kind == 'colorizemask' and child.done), None)
        if mask is None:
            return own
        out = bytearray()
        for i in range(w * h):
            pixel = own[i * 4:i * 4 + 4]
            out += pixel if pixel[3] else mask.colour_at(x + i % w)
        return bytes(out)


class Document(region_tests.Document):
    def __init__(self, log):
        super().__init__(); self.log = log
    def createNode(self, name, kind): return Layer(self, name, kind)
    def createColorizeMask(self, name): return ColorizeMask(self, name, self.log)
    def waitForDone(self): self.log.append(('wait',))


def result_name(doc):
    return 'Flats'


class MoveDocument(Document):
    """The fork's agent moves: pixel writes made outside one are history steps of their own."""
    def __init__(self, log):
        super().__init__(log); self.moves, self.open, self.move_id = [], False, 0
    def beginAgentMove(self, name):
        if self.open: return False
        self.open, self.move_id = True, self.move_id + 1; self.moves.append(name); return True
    def endAgentMove(self): self.open = False; return True
    def agentMoveOpen(self): return self.open
    def agentMoveId(self): return self.move_id


class StepLayer(Layer):
    def setPixelData(self, data, x, y, w, h):
        self.doc.writes.append(self.doc.open); return super().setPixelData(data, x, y, w, h)


class StepDocument(MoveDocument):
    def __init__(self, log):
        super().__init__(log); self.writes = []
    def createNode(self, name, kind): return StepLayer(self, name, kind)


class ColorizeTests(region_tests.RegionSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.log = []
        self.h.doc = Document(self.log)
        self.h._creative_session.update(document_id=region_tests.native.module.document_id(self.h.doc))
        self.line = Layer(self.h.doc, 'Line art', 'paintlayer')
        self.line.pixels = bytearray(b''.join(LINE if i % 4 == 2 else OPEN for i in range(16)))   # a line down column 2
        self.h.doc.root.addChildNode(self.line, None)

    def colorize(self, params, identifier='flats'):
        return region_tests.run(self.h, 'colorize_flats', dict({'line_layer': self.line.id}, **params), identifier)

    def test_seeds_become_flat_colours_below_the_unchanged_line_art(self):
        line_before = (bytes(self.line.pixels), self.line.parent, self.line.label, self.line.shown)
        result = self.colorize({'seeds': [{'x': 0, 'y': 1, 'color': '#3a6ea5'}, {'x': 3, 'y': 1, 'color': '#d9a441', 'radius': 1}]})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(line_before, (bytes(self.line.pixels), self.line.parent, self.line.label, self.line.shown))
        helper, group, line = self.h.doc.root.childNodes()
        flats, = group.childNodes()
        self.assertIs(line, self.line, 'the flats and helper go directly below the line art')
        self.assertEqual((result['layer_id'], result['clip_group_id'], result['helper_layer_id']), (flats.id, group.id, helper.id))
        self.assertEqual(flats.pixelData(0, 0, 1, 1), bgra('#3a6ea5'))
        self.assertEqual(flats.pixelData(3, 3, 1, 1), bgra('#d9a441'))
        self.assertEqual(flats.pixelData(2, 0, 1, 1), bgra('#d9a441'), 'colour runs under the lines too')
        self.assertEqual((helper.shown, bytes(helper.pixels)), (False, bytes(self.line.pixels)), 'hidden, with its lines put back')
        self.assertEqual((result['colors'], result['filled_pixels']), (2, 16))
        steps = [entry[0] for entry in self.log]
        self.assertLess(steps.index('keys'), steps.index('seed'))
        self.assertLess(steps.index('update'), len(steps) - 1 - steps[::-1].index('wait'), 'waits for Krita after the update')
        self.assertLess(steps.index('update'), steps.index('edit keys'))
        self.assertIn(('seed', '#d9a441', (2, 0, 2, 3), 6), self.log, 'radius 1 is a 3x3 dot, cropped to the canvas')
        self.assertIn(('seed', '#3a6ea5', (0, 0, 4, 4), 16), self.log, 'the default radius is 3')
        entry = self.h._creative_session['passes'][-1]
        self.assertEqual((entry['kind'], entry['title'], entry['layer_id']), ('colorize_flats', 'Colorized flats', flats.id))

    def test_pixel_write_loops_are_one_agent_move_each_never_one_step_per_strip(self):
        self.h.doc = StepDocument(self.log)
        self.h._creative_session.update(document_id=region_tests.native.module.document_id(self.h.doc))
        self.line = Layer(self.h.doc, 'Line art', 'paintlayer')
        self.line.pixels = bytearray(b''.join(LINE if i % 4 == 2 else OPEN for i in range(16)))
        self.h.doc.root.addChildNode(self.line, None)
        result = self.colorize({'seeds': [{'x': 0, 'y': 1, 'color': '#3a6ea5'}, {'x': 3, 'y': 1, 'color': '#d9a441'}]})
        self.assertEqual(result['status'], 'ok')
        doc = self.h.doc
        self.assertTrue(doc.writes)
        self.assertEqual([w for w in doc.writes if not w], [], 'every pixel write of the loops is inside an agent move')
        self.assertEqual(doc.moves, ['Colorize helper', 'Colorize read', 'Colorize read', result_name(doc)])
        self.assertFalse(doc.open, 'no move is left open')

    def test_a_stock_krita_without_agent_moves_still_colorizes(self):
        result = self.colorize({'seeds': [{'x': 0, 'y': 1, 'color': '#3a6ea5'}, {'x': 3, 'y': 1, 'color': '#d9a441'}]})
        self.assertEqual(result['status'], 'ok')

    def test_a_transparent_seed_keeps_its_region_empty(self):
        self.colorize({'seeds': [{'x': 0, 'y': 0, 'color': 'transparent'}, {'x': 3, 'y': 0, 'color': '#d9a441'}], 'clip_base': False})
        keys = next(entry for entry in self.log if entry[0] == 'keys')
        self.assertEqual(keys, ('keys', ('#000001', '#d9a441'), 0), 'a stand-in colour is keyed as transparent')
        flats = self.h.doc.root.childNodes()[1]
        self.assertEqual((flats.kind, flats.pixelData(0, 0, 1, 1), flats.pixelData(3, 0, 1, 1)), ('paintlayer', OPEN, bgra('#d9a441')))

    def test_reject_hides_the_flats(self):
        self.colorize({'seeds': [{'x': 0, 'y': 0, 'color': '#3a6ea5'}, {'x': 3, 'y': 0, 'color': '#d9a441'}]})
        region_tests.run(self.h, 'review_pass', {'pass_id': 'flats', 'action': 'reject'}, 'reject')
        flats = self.h.doc.root.childNodes()[1].childNodes()[0]
        self.assertEqual((flats.shown, self.line.shown), (False, True))

    def test_a_crash_while_colorizing_blocks_painting_until_acknowledged(self):
        seeds = {'seeds': [{'x': 0, 'y': 0, 'color': '#3a6ea5'}, {'x': 3, 'y': 0, 'color': '#d9a441'}]}
        class Crash(BaseException): pass
        def crash(*_args): raise Crash()
        self.h._colorize_apply = crash
        with self.assertRaises(Crash):
            self.colorize(seeds, 'crashed')
        del self.h._colorize_apply
        refused = self.colorize(seeds, 'next')
        self.assertEqual((refused['error_code'], refused['unresolved_operations']), ('outcome_unknown', ['crashed']))
        region_tests.run(self.h, 'reconcile', {'expected_revision': self.h._creative_revision(self.h.doc)})
        self.assertEqual(self.colorize(seeds, 'next')['status'], 'ok')

    def test_refusals_change_nothing(self):
        good = {'x': 0, 'y': 0, 'color': '#3a6ea5'}
        for params, message in (({'seeds': [good]}, '2-48 seeds'),
                                ({'seeds': [good, {'x': 4, 'y': 0, 'color': '#000000'}]}, 'Seed 2: x must be between'),
                                ({'seeds': [good, {'x': 1, 'y': 0, 'color': 'red'}]}, 'Seed 2: Color must be'),
                                ({'seeds': [good, {'x': 1, 'y': 0, 'color': '#000000', 'radius': 30}]}, 'radius'),
                                ({'seeds': [good, {'x': 1, 'y': 0, 'colour': '#000000'}]}, 'Unknown parameters'),
                                ({'seeds': [dict(good, color='transparent')] * 2}, 'at least one seed with a colour'),
                                ({'seeds': [good, good], 'cleanup': 2}, 'cleanup')):
            with self.assertRaisesRegex(ValueError, message):
                self.colorize(params, 'refused')
        with self.assertRaisesRegex(ValueError, 'no longer in this painting'):
            region_tests.run(self.h, 'colorize_flats', {'line_layer': 'missing', 'seeds': [good, good]}, 'missing')
        self.assertEqual(self.h.doc.root.childNodes(), [self.line])
        self.assertEqual(self.log, [])


if __name__ == '__main__':
    unittest.main()

"""Element shapes (element-shapes 1.5, 1.6): a shape's mask file becomes a Krita selection for one painting call, or a
proposed protected area. The companion writes the mask (8-bit PNG at canvas resolution, cropped to its bounds) into
the chat folder; the plugin reads it without Qt. Writes only into temporary folders that are removed."""
import os
import struct
import sys
import tempfile
import unittest
import zlib

import test_region_craft as region_tests
import test_protection as protection_tests

native = region_tests.native
SIZE = region_tests.SIZE
region = region_tests.region
shape_mask = sys.modules.get('creative_test_package.shape_mask')
if shape_mask is None:
    import importlib.util
    spec = importlib.util.spec_from_file_location('creative_test_package.shape_mask', native.SOURCE / 'shape_mask.py')
    shape_mask = importlib.util.module_from_spec(spec); spec.loader.exec_module(shape_mask)
    sys.modules[spec.name] = shape_mask


def png(width, height, rows, colour_type=0, filters=None):
    """An 8-bit PNG of `rows` (bytes per row, already in the colour type's layout), each row with its filter byte
    (filters[i], default 0) applied as an encoder would."""
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[colour_type]
    raw, previous = bytearray(), bytes(width * channels)
    for index, row in enumerate(rows):
        kind = (filters or [0] * height)[index]
        out = bytearray(row)
        for i in range(len(row)):
            left = row[i - channels] if i >= channels else 0
            up, corner = previous[i], previous[i - channels] if i >= channels else 0
            if kind == 1: out[i] = (row[i] - left) & 255
            elif kind == 2: out[i] = (row[i] - up) & 255
            elif kind == 3: out[i] = (row[i] - (left + up) // 2) & 255
            elif kind == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                out[i] = (row[i] - (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
        raw += bytes([kind]) + out; previous = row
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, colour_type, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw))) + chunk(b'IEND', b''))


class PngTests(unittest.TestCase):
    def test_every_filter_decodes_to_the_same_mask(self):
        rows = [bytes((x * 37 + y * 11) % 256 for x in range(7)) for y in range(5)]
        for kind in range(5):
            self.assertEqual(shape_mask.read_png(png(7, 5, rows, filters=[kind] * 5)), (7, 5, b''.join(rows)), kind)

    def test_colour_and_alpha_masks_read_their_first_channel_times_alpha(self):
        rgba = [bytes([255, 0, 0, 255, 255, 0, 0, 0])]
        self.assertEqual(shape_mask.read_png(png(2, 1, rgba, 6)), (2, 1, bytes([255, 0])))
        self.assertEqual(shape_mask.read_png(png(2, 1, [bytes([200, 9, 9, 0, 0, 0])], 2)), (2, 1, bytes([200, 0])))

    def test_not_a_mask_is_refused(self):
        for data in (b'not a png', png(2, 1, [bytes([1, 2])])[:-20]):
            with self.assertRaises(ValueError):
                shape_mask.read_png(data)

    def test_a_short_or_late_header_is_a_clean_refusal(self):
        good = png(2, 1, [bytes([1, 2])])
        short = good[:8] + struct.pack('>I', 4) + b'IHDR' + b'\0\0\0\2' + b'\0\0\0\0' + good[33:]
        late = good[:8] + good[33:]                                   # IDAT first, no IHDR before it
        for data in (short, late):
            with self.assertRaisesRegex(ValueError, 'damaged'):
                shape_mask.read_png(data)

    def test_a_header_larger_than_expected_is_refused_before_inflating(self):
        huge = bytearray(png(2, 1, [bytes([1, 2])]))
        huge[16:24] = struct.pack('>II', 60000, 60000)                # the header claims 3.6 G pixels
        inflated = []
        real = shape_mask.zlib
        class Spy:
            error = real.error
            @staticmethod
            def decompressobj(*args):
                inflated.append(1); return real.decompressobj(*args)
        shape_mask.zlib = Spy
        self.addCleanup(setattr, shape_mask, 'zlib', real)
        with self.assertRaisesRegex(ValueError, '60000 x 60000'):
            shape_mask.read_png(bytes(huge), (2, 1))
        self.assertEqual(inflated, [], 'refused from the header alone')
        # A stream that inflates to more than the header allows is refused without holding all of it.
        bomb = png(2, 1, [bytes([1, 2])])
        body = zlib.compress(bytes(10_000_000))
        chunk = struct.pack('>I', len(body)) + b'IDAT' + body + struct.pack('>I', zlib.crc32(b'IDAT' + body) & 0xffffffff)
        bomb = bomb[:33] + chunk + bomb[-12:]
        with self.assertRaisesRegex(ValueError, 'damaged'):
            shape_mask.read_png(bomb, (2, 1))


class Folder:
    def folder(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        os.makedirs(os.path.join(folder.name, '.shapes'))
        return folder.name

    def write(self, folder, name, data):
        path = os.path.join(folder, '.shapes', name)
        with open(path, 'wb') as stream: stream.write(data)
        return path


class ReadShapeTests(Folder, unittest.TestCase):
    def test_a_mask_in_the_chat_folder_is_read_at_its_bounds(self):
        folder = self.folder()
        path = self.write(folder, 'moon.png', png(3, 2, [bytes([0, 255, 0]), bytes([255, 255, 255])]))
        rect, data = shape_mask.read_shape({'mask_path': path, 'bounds': [1, 1, 3, 2]}, folder, 4, 4)
        self.assertEqual((rect, data), ((1, 1, 3, 2), bytes([0, 255, 0, 255, 255, 255])))

    def test_refusals(self):
        folder, other = self.folder(), self.folder()
        good = self.write(folder, 'a.png', png(2, 2, [bytes([255, 255])] * 2))
        outside = self.write(other, 'b.png', png(2, 2, [bytes([255, 255])] * 2))
        cases = [
            ({'mask_path': outside, 'bounds': [0, 0, 2, 2]}, 'chat folder'),
            ({'mask_path': good, 'bounds': [0, 0, 3, 2]}, '2 x 2'),
            ({'mask_path': good, 'bounds': [3, 3, 2, 2]}, 'inside the image'),
            ({'mask_path': good}, 'bounds'),
            ({'mask_path': os.path.join(folder, '.shapes', 'gone.png'), 'bounds': [0, 0, 2, 2]}, 'no longer'),
            ({'mask_path': self.write(folder, 'empty.png', png(2, 2, [bytes(2)] * 2)), 'bounds': [0, 0, 2, 2]}, 'empty'),
        ]
        for spec, message in cases:
            with self.assertRaisesRegex(ValueError, message):
                shape_mask.read_shape(spec, folder, 4, 4)
        with self.assertRaisesRegex(ValueError, 'chat folder'):
            shape_mask.read_shape({'mask_path': good, 'bounds': [0, 0, 2, 2]}, None, 4, 4)

    def test_links_and_dot_dot_are_refused(self):
        folder, other = self.folder(), self.folder()
        outside = self.write(other, 'b.png', png(2, 2, [bytes([255, 255])] * 2))
        inside = self.write(folder, 'a.png', png(2, 2, [bytes([255, 255])] * 2))
        link = os.path.join(folder, '.shapes', 'link.png'); os.symlink(outside, link)
        inner = os.path.join(folder, '.shapes', 'inner.png'); os.symlink(inside, inner)
        hard = os.path.join(folder, '.shapes', 'hard.png'); os.link(inside, hard)
        dotted = os.path.join(folder, '.shapes', '..', '.shapes', 'a.png')
        escape = os.path.join(folder, '.shapes', '..', '..', os.path.basename(other), '.shapes', 'b.png')
        for path, message in ((link, 'chat folder'), (inner, 'chat folder'), (hard, 'chat folder'), (dotted, 'chat folder'), (escape, 'chat folder')):
            with self.assertRaisesRegex(ValueError, message, msg=path):
                shape_mask.read_shape({'mask_path': path, 'bounds': [0, 0, 2, 2]}, folder, 4, 4)

    def test_a_header_other_than_the_bounds_is_refused_before_inflating(self):
        folder = self.folder()
        huge = bytearray(png(2, 2, [bytes([255, 255])] * 2)); huge[16:24] = struct.pack('>II', 60000, 60000)
        path = self.write(folder, 'huge.png', bytes(huge))
        with self.assertRaisesRegex(ValueError, '60000 x 60000'):
            shape_mask.read_shape({'mask_path': path, 'bounds': [0, 0, 2, 2]}, folder, 4, 4)


class SelectionStepTests(Folder, region_tests.RegionSetup, unittest.TestCase):
    def test_an_element_shape_step_selects_the_mask(self):
        folder = self.h._creative_session['output']
        os.makedirs(os.path.join(folder, '.shapes'), exist_ok=True)
        path = self.write(folder, 'tower.png', png(2, 3, [bytes([255, 0]), bytes([255, 255]), bytes([128, 255])]))
        done = region_tests.run(self.h, 'select', {'name': 'Tower', 'steps': [{'element_shape': {'mask_path': path, 'bounds': [1, 0, 2, 3]}}]})
        self.assertEqual(done['bounds'], [1, 0, 2, 3])
        header, data = self.h._region_read(self.h._region_saved_path(self.h._creative_session, 'Tower'))
        self.assertEqual(data, bytes([255, 0, 255, 255, 128, 255]))
        with self.assertRaisesRegex(ValueError, 'Step 1: choose one source'):
            region_tests.run(self.h, 'select', {'name': 'x', 'steps': [{'element_shape': {'mask_path': path, 'bounds': [1, 0, 2, 3]}, 'saved': 'Tower'}]})


class ShapedPassTests(Folder, unittest.TestCase):
    """On the fork a pass inside a shape paints as one Node.paintStrokes job clipped to the shape: the job's own
    selection, so the artist's selection is never swapped, and no undo step of its own."""
    setUp = native.ForkStrokeJobTests.setUp
    harness = native.ForkStrokeJobTests.harness
    _pass = native.ForkStrokeJobTests._pass

    def shaped(self):
        h = self.harness(); folder = self.folder(); h._creative_session['output'] = folder
        mask = [bytes([0, 255, 255, 0]), bytes([255, 255, 255, 255]), bytes([0, 255, 255, 0])]
        return h, {'mask_path': self.write(folder, 'moon.png', png(4, 3, mask)), 'bounds': [100, 200, 4, 3]}, b''.join(mask)

    def test_strokes_are_limited_to_the_shape_and_the_selection_is_left_as_it_was(self):
        h, shape, mask = self.shaped()
        artist = object(); h.doc.selected = artist
        result = self._pass(h, 3, inside_shape=shape)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(len(h.job_calls), 1, 'one job')
        selection = h.job_calls[0][2]
        self.assertEqual((selection.bounds, selection.data), ((100, 200, 4, 3), mask), 'the job paints only inside the shape')
        self.assertEqual((h.doc.selected, h.doc.selection_changes), (artist, []), "the artist's selection is never changed")

    def test_the_shape_is_read_once_a_pass_and_bounds_the_pass_s_reach(self):
        h, shape, _mask = self.shaped()
        reads, real = [], shape_mask.read_shape
        shape_mask.read_shape = lambda *args: reads.append(1) or real(*args)
        self.addCleanup(setattr, shape_mask, 'read_shape', real)
        self.assertEqual(self._pass(h, 2, inside_shape=shape)['status'], 'ok')
        self.assertEqual(len(reads), 1, 'decoded in validation, used for the job')
        stroke = dict(native.request()['params']['strokes'][0], start=[102, 201], segments=[[102, 201, 103, 202, 103, 202]])
        params = dict(native.request()['params'], strokes=[stroke], inside_shape=shape)
        self.assertEqual(h._protect_reach(params, 'paint_pass'), [100, 200, 104, 203], 'cut to the shape\'s bounds')

    def test_the_shape_adds_no_undo_step(self):
        plain = self.harness(); plain._creative_session['output'] = self.folder()
        self.assertEqual(self._pass(plain, 2)['status'], 'ok')
        h, shape, _mask = self.shaped()
        self.assertEqual(self._pass(h, 2, inside_shape=shape)['status'], 'ok')
        self.assertEqual(h.doc.steps, plain.doc.steps, 'the same steps as a pass without a shape: the layer and the job')

    def test_refusals(self):
        h, shape, _mask = self.shaped()
        for extra, message in (({'region': [0, 0, 10, 10]}, 'one limit'), ({'selection': 'Sky'}, 'one limit'),
                               ({'inside_shape': dict(shape, bounds=[100, 200, 5, 3])}, '4 x 3')):
            with self.assertRaisesRegex(ValueError, message):
                self._pass(h, 1, **dict({'inside_shape': shape}, **extra))
        self.assertEqual(h.job_calls, [], 'nothing painted')
        native.module._FORK = False
        with self.assertRaisesRegex(ValueError, 'our Krita'):
            self._pass(h, 1, inside_shape=shape, operation_id='stock')


class ShapeProtectionTests(Folder, protection_tests.ProtectionSetup, unittest.TestCase):
    def test_a_shape_is_proposed_as_a_pending_area_the_artist_keeps(self):
        folder = self.h._creative_session['output']
        os.makedirs(os.path.join(folder, '.shapes'), exist_ok=True)
        path = self.write(folder, 'car.png', png(2, 2, [bytes([255, 255]), bytes([0, 255])]))
        done = self.propose('Car', [{'element_shape': {'mask_path': path, 'bounds': [2, 2, 2, 2]}}])
        self.assertEqual(done['status'], 'ok')
        self.assertEqual((done['area']['state'], done['area']['bounds']), ('pending', [2, 2, 2, 2]))
        mask = next(n for n in self.group().children if n.name() == 'Car').selection()
        self.assertEqual(mask.pixelData(2, 2, 2, 2), bytes([255, 255, 0, 255]), 'stored as the shape itself, a selection mask')
        # The artist keeps it with one click: then it is theirs and enforced like any area.
        self.h._protect_set_state(self.h.doc, done['area']['id'], 'active')
        self.assertEqual([(a['name'], a['state']) for a in self.h._protect_list(self.h.doc)], [('Car', 'active')])
        enforced = self.h._protect_mask(self.h.doc, (0, 0, SIZE, SIZE))
        self.assertEqual((enforced[2 * SIZE + 2], enforced[3 * SIZE + 2], enforced[3 * SIZE + 3]), (255, 0, 255))


if __name__ == '__main__':
    unittest.main()

# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""finish_pass.py: paint_finish (openspec finish-stage, approved by the artist 2026-10-24): the canvas's own paint smoothed
where the goal is soft, form-following strokes from the goal where it is hard, baked per tile into two layers of one
Finish group. Pure parts on numpy and OpenCV; the operation on the pixel layer tree of the accents tests. Files go to a
temporary folder that is removed."""
import hashlib
import os
import sys
import tempfile
import unittest
import numpy as np
import cv2
import test_accent_adjust as accent_tests

region_tests = accent_tests.region_tests
finish = sys.modules.get('creative_test_package.finish_pass')
if finish is None:
    import importlib
    finish = importlib.import_module('creative_test_package.finish_pass')


def goal_picture(width, height):
    """A goal: a smooth sky gradient on the left half, a busy 'building' of 3 px blocks on the right (BGR uint8)."""
    rng = np.random.default_rng(3)
    goal = np.zeros((height, width, 3), np.uint8)
    ys = np.linspace(0, 1, height)[:, None]
    goal[:, :width // 2] = (np.array([200, 160, 120]) * (1 - ys[..., None] * 0.3)).astype(np.uint8)
    blocks = rng.integers(20, 235, ((height + 2) // 3, (width - width // 2 + 2) // 3, 3)).astype(np.uint8)
    goal[:, width // 2:] = np.repeat(np.repeat(blocks, 3, 0), 3, 1)[:height, :width - width // 2]
    return goal


def dabbed(goal, seed=5, radius=5):
    """An underpainting of the goal: round dabs of its colour, a few pixels apart (BGRA uint8)."""
    rng = np.random.default_rng(seed)
    h, w = goal.shape[:2]
    out = cv2.GaussianBlur(goal, (0, 0), 3).copy()
    for _ in range(w * h // 20):
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        colour = goal[y, x].astype(int) + rng.integers(-25, 26, 3)
        cv2.circle(out, (x, y), radius, tuple(int(c) for c in np.clip(colour, 0, 255)), -1)
    return np.dstack([out, np.full((h, w), 255, np.uint8)])


class SpikeScale:
    """The canvases here are small: sizes as on the spike's canvas (SCALE_SIDE patched to theirs), so the spike's numbers apply."""
    def setUp(self):
        super().setUp()
        previous = finish.SCALE_SIDE, finish.TILE
        self.addCleanup(lambda: (setattr(finish, 'SCALE_SIDE', previous[0]), setattr(finish, 'TILE', previous[1])))
        finish.SCALE_SIDE = 600


def run_tiles(canvas, goal_bgr, rect, tile, coverage=None):
    """finish_tile over `rect` in squares of `tile`, as _finish_apply runs it: both layers (BGRA uint8, whole canvas)."""
    finish.TILE = tile
    h, w = canvas.shape[:2]
    size = finish.sizes(w, h)
    spec = {'size': [goal_bgr.shape[1], goal_bgr.shape[0]], 'source': [0, 0, goal_bgr.shape[1], goal_bgr.shape[0]], 'target': [0, 0, w, h]}
    goal = finish.GoalOnCanvas(goal_bgr, spec)
    work = finish.tiles(rect, w, h)
    goal_union = finish.bounding([finish.grow(t, size['goal_pad'], w, h) for t in work])
    pixels = goal.rect(goal_union)
    out = {'blend': np.zeros((h, w, 4), np.uint8), 'strokes': np.zeros((h, w, 4), np.uint8)}
    count = 0
    for t in work:
        gr, cr = finish.grow(t, size['goal_pad'], w, h), finish.grow(t, size['canvas_pad'], w, h)
        x, y, tw, th = t
        cut = None if coverage is None else coverage[y:y + th, x:x + tw]
        blend, strokes, report = finish.finish_tile(t, finish.crop(canvas, [0, 0, w, h], cr), cr, finish.crop(pixels, goal_union, gr), gr,
                                                    [0, 0, w, h], w, h, size, cut)
        count += report['strokes']
        for key, data in (('blend', blend), ('strokes', strokes)):
            if data:
                out[key][y:y + th, x:x + tw] = np.frombuffer(data, np.uint8).reshape(th, tw, 4)
    return out, count


def over(base, layer):
    a = layer[..., 3:4].astype(np.float32) / 255
    return base[..., :3].astype(np.float32) * (1 - a) + layer[..., :3].astype(np.float32) * a


def premultiplied(layer):
    return layer[..., :3].astype(int) * layer[..., 3:4] // 255


class SizeTests(unittest.TestCase):
    def test_the_spikes_sizes_on_its_canvas_and_scaled_on_others_never_below_a_pixel_or_two(self):
        spike = finish.sizes(6000, 4500)
        self.assertEqual((spike['edge'], spike['r'], spike['spacing'], spike['step'], spike['length'], spike['width'], spike['tensor']),
                         (40, 10, 4, 2, (10, 34), (5, 9), 3), 'the approved look, at the spike’s 6000 px')
        big, small = finish.sizes(12000, 9000), finish.sizes(600, 450)
        self.assertEqual((big['edge'], big['width'], big['r']), (80, (10, 18), 20))
        self.assertGreaterEqual(small['width'][0], 1.5); self.assertGreaterEqual(small['spacing'], 2); self.assertGreaterEqual(small['step'], 1)
        self.assertEqual(finish.sizes(4500, 6000)['edge'], 40, 'the long side, either way round')

    def test_the_work_is_the_squares_the_area_touches_inside_the_canvas(self):
        finish_tile = finish.TILE
        self.assertEqual(finish.tiles([0, 0, 6000, 4500], 6000, 4500)[-1], [5632, 4096, 368, 404])
        self.assertEqual(len(finish.tiles([0, 0, 6000, 4500], 6000, 4500)), 12 * 9)
        self.assertEqual(finish.tiles([600, 10, 10, 1000], 6000, 4500), [[600, 10, 10, 502], [600, 512, 10, 498]], 'cut to the area')
        self.assertEqual(finish_tile, 512)


class GoalTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder = folder.name

    def goal_file(self, name='goal.png', pixels=None, folder=None):
        data = cv2.imencode('.png', goal_picture(64, 48) if pixels is None else pixels)[1].tobytes()
        path = os.path.join(folder or self.folder, name)
        with open(path, 'wb') as stream:
            stream.write(data)
        return {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': [64, 48], 'source': [0, 0, 64, 48], 'target': [0, 0, 640, 480]}

    def test_the_goal_is_a_file_of_the_chat_folder_read_as_it_was_listed(self):
        spec = finish.check_goal(self.goal_file(), self.folder, 640, 480)
        self.assertEqual(finish.read_goal(spec).shape, (48, 64, 3))
        os.makedirs(os.path.join(self.folder, 'goal-sharpen'))
        finish.check_goal(self.goal_file('x4.png', folder=os.path.join(self.folder, 'goal-sharpen')), self.folder, 640, 480)
        with tempfile.TemporaryDirectory() as elsewhere:
            with self.assertRaisesRegex(ValueError, 'chat folder'):
                finish.check_goal(self.goal_file(folder=elsewhere), self.folder, 640, 480)
        link = os.path.join(self.folder, 'link.png'); os.symlink(spec['path'], link)
        with self.assertRaisesRegex(ValueError, 'chat folder'):
            finish.check_goal(dict(spec, path=link), self.folder, 640, 480)
        with self.assertRaisesRegex(ValueError, 'changed'):
            finish.read_goal(dict(spec, sha256='0' * 64))
        with self.assertRaisesRegex(ValueError, 'proportions'):
            finish.check_goal(dict(spec, target=[0, 0, 640, 300]), self.folder, 640, 480)
        with self.assertRaisesRegex(ValueError, 'canvas'):
            finish.check_goal(dict(spec, target=[700, 0, 640, 480]), self.folder, 640, 480)
        text = os.path.join(self.folder, 'notes.png')
        with open(text, 'wb') as stream:
            stream.write(b'not an image')
        with self.assertRaisesRegex(ValueError, 'PNG or JPEG'):
            finish.read_goal(dict(spec, path=text, sha256=hashlib.sha256(b'not an image').hexdigest()))

    def test_the_headers_size_is_read_before_decoding(self):
        picture = goal_picture(40, 30)
        self.assertEqual(finish.declared_size(cv2.imencode('.png', picture)[1].tobytes()), (40, 30))
        self.assertEqual(finish.declared_size(cv2.imencode('.jpg', picture)[1].tobytes()), (40, 30))
        self.assertIsNone(finish.declared_size(b'GIF89a....'))

    def test_the_goal_lands_where_its_placement_says_whatever_rect_is_read(self):
        pixels = np.zeros((40, 40, 3), np.uint8); pixels[10:20, 20:30] = (0, 0, 255)       # a red square
        goal = finish.GoalOnCanvas(pixels, {'size': [80, 80], 'source': [0, 0, 80, 80], 'target': [100, 50, 400, 400]})
        whole = goal.rect([0, 0, 600, 500])
        red = np.argwhere(whole[..., 2] > 128)
        self.assertEqual((red.min(0).tolist(), red.max(0).tolist()), ([150, 300], [249, 399]), 'listed px 20-40 (decoded 10-20) at 5x from (100, 50)')
        self.assertEqual(goal.rect([300, 200, 50, 50]).tolist(), whole[200:250, 300:350].tolist())


class FinishTileTests(SpikeScale, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.goal = goal_picture(600, 400)
        self.canvas = dabbed(self.goal)

    def test_soft_areas_are_blended_from_the_canvas_and_hard_areas_restroked_from_the_goal(self):
        out, count = run_tiles(self.canvas, self.goal, [0, 0, 600, 400], 512)
        self.assertGreater(count, 1000)
        left, right = (slice(40, 360), slice(40, 240)), (slice(40, 360), slice(380, 560))
        self.assertGreater(out['blend'][left][..., 3].mean(), 200, 'the sky is blended')
        self.assertLess(out['blend'][right][..., 3].mean(), 20, 'the building is not')
        self.assertGreater(out['strokes'][right][..., 3].mean(), 150, 'the building is restroked')
        self.assertLess(out['strokes'][left][..., 3].mean(), 10, 'the sky has no strokes')
        after = over(over(self.canvas, out['blend']), out['strokes'])
        texture = lambda image: float(np.abs(image - cv2.GaussianBlur(image, (0, 0), 3)).mean())
        self.assertLess(texture(after[left]), texture(self.canvas[..., :3].astype(np.float32)[left]) * 0.6, 'the dabs melt in the sky')
        distance = lambda image: float(np.abs(cv2.GaussianBlur(image, (0, 0), 2) - cv2.GaussianBlur(self.goal.astype(np.float32), (0, 0), 2))[right].mean())
        self.assertLess(distance(after), distance(self.canvas[..., :3].astype(np.float32)), 'the building is nearer the goal')

    def test_tiles_join_without_seams_and_a_call_paints_the_same_strokes_again(self):
        coarse, _ = run_tiles(self.canvas, self.goal, [0, 0, 600, 400], 1024)
        fine, _ = run_tiles(self.canvas, self.goal, [0, 0, 600, 400], 96)
        again, _ = run_tiles(self.canvas, self.goal, [0, 0, 600, 400], 96)
        for key in ('blend', 'strokes'):
            self.assertEqual(int(np.abs(premultiplied(coarse[key]) - premultiplied(fine[key])).max()), 0, key + ': no seam at the tiles')
            self.assertEqual(int(np.abs(coarse[key][..., 3].astype(int) - fine[key][..., 3]).max()), 0)
            self.assertTrue(np.array_equal(fine[key], again[key]), key + ': deterministic')

    def test_the_area_cuts_both_layers_to_its_own_pixels(self):
        coverage = np.zeros((400, 600), np.float32); coverage[:, 200:450] = 1
        out, _ = run_tiles(self.canvas, self.goal, [200, 0, 250, 400], 512, coverage)
        for key in ('blend', 'strokes'):
            self.assertEqual(int(out[key][:, :200, 3].max()), 0, key); self.assertEqual(int(out[key][:, 450:, 3].max()), 0, key)
        self.assertGreater(int(out['blend'][:, 200:300, 3].max()), 0); self.assertGreater(int(out['strokes'][:, 350:450, 3].max()), 0)


class FinishNode(accent_tests.PixelNode):
    def remove(self):
        self.parent.children.remove(self); self.parent = None; return True


class FinishDocument(accent_tests.PixelDocument):
    def createNode(self, name, kind): return FinishNode(self, name, kind)


class FinishOperationTests(SpikeScale, region_tests.RegionSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.h = accent_tests.filter_tests.Harness(self.h._creative_session['output'])
        doc = self.h.doc = FinishDocument(600, 400)
        self.h._creative_session.update(document_id=accent_tests.filter_tests.native.module.document_id(doc), width=600, height=400)
        base = doc.createNode('Underpainting', 'paintlayer'); doc.root.addChildNode(base, None)
        self.goal = goal_picture(300, 200)                     # listed at half the canvas: enlarged 2x onto it
        base.data[...] = dabbed(cv2.resize(self.goal, (600, 400), interpolation=cv2.INTER_CUBIC))
        self.base = base
        data = cv2.imencode('.png', self.goal)[1].tobytes()
        self.goal_path = os.path.join(self.h._creative_session['output'], 'reference-goal.png')
        with open(self.goal_path, 'wb') as stream:
            stream.write(data)
        self.spec = {'path': self.goal_path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': [300, 200], 'source': [0, 0, 300, 200], 'target': [0, 0, 600, 400]}

    def run_finish(self, identifier='f1', **extra):
        return region_tests.run(self.h, 'finish', dict({'name': 'Finish', 'goal': self.spec, 'stage_id': 'move-1'}, **extra), identifier)

    def shown(self):
        return np.round(accent_tests.composite(self.h.doc.root, 600, 400) * 255)

    def test_one_finish_group_of_two_baked_layers_from_the_clean_canvas(self):
        before = self.shown()
        result = self.run_finish()
        self.assertEqual(result['status'], 'ok', result.get('error'))
        group = self.h._creative_node(self.h.doc, result['layer_id'])
        self.assertEqual([c.label for c in group.childNodes()], ['Finish · blend', 'Finish · strokes'], 'the strokes above the blend')
        self.assertTrue(all(c.blend == 'normal' for c in group.childNodes()), 'every blend baked')
        self.assertEqual((result['finish']['tiles'], result['finish']['of_tiles']), (2, 2))
        self.assertGreater(result['finish']['strokes'], 1000)
        after = self.shown()
        self.assertGreater(float(np.abs(after - before)[..., :3].mean()), 2, 'the painting changed')
        self.assertTrue(len(self.h.doc.reads) == 1, 'one clean read of the canvas, before anything was written')

    def test_a_box_limits_the_finish_and_a_saved_selection_cuts_it(self):
        result = self.run_finish(box=[300, 0, 200, 400])
        group = self.h._creative_node(self.h.doc, result['layer_id'])
        for layer in group.childNodes():
            self.assertEqual(int(layer.data[:, :300, 3].max()) + int(layer.data[:, 500:, 3].max()), 0, layer.label)
        coverage = np.zeros((400, 600), np.uint8); coverage[:, 400:] = 255
        class Sel:
            def x(self): return 400
            def y(self): return 0
            def width(self): return 200
            def height(self): return 400
            def pixelData(self, x, y, w, h): return coverage[y:y + h, x:x + w].tobytes()
        self.h._region_check_named = lambda doc, session, name: None
        self.h._region_load = lambda session, name, doc=None: Sel()
        result = self.run_finish('f2', selection='Towers')
        for layer in self.h._creative_node(self.h.doc, result['layer_id']).childNodes():
            self.assertEqual(int(layer.data[:, :400, 3].max()), 0, layer.label + ': nothing outside the selection')
        with self.assertRaisesRegex(ValueError, 'one area'):
            self.run_finish('f3', box=[0, 0, 10, 10], selection='Towers')

    def test_an_area_off_the_goal_or_a_goal_outside_the_chat_folder_paints_nothing(self):
        before = len(self.h.doc.root.childNodes())
        with self.assertRaisesRegex(ValueError, 'outside where the goal sits'):
            self.run_finish('off', goal=dict(self.spec, target=[0, 0, 300, 200]), box=[400, 300, 100, 100])
        with tempfile.TemporaryDirectory() as elsewhere:
            with self.assertRaisesRegex(ValueError, 'chat folder'):
                self.run_finish('away', goal=dict(self.spec, path=os.path.join(elsewhere, 'goal.png')))
        self.assertEqual(len(self.h.doc.root.childNodes()), before)

    def test_stop_keeps_the_squares_painted_and_says_so(self):
        class StopAfterFirst:
            calls = 0
            def is_set(self):
                StopAfterFirst.calls += 1
                return StopAfterFirst.calls > 1
        previous = finish.stop_requested
        finish.stop_requested = StopAfterFirst()
        self.addCleanup(setattr, finish, 'stop_requested', previous)
        result = self.run_finish()
        self.assertEqual((result['finish']['tiles'], result['stopped_after_tiles']), (1, 1))
        self.assertIn('Stopped by the artist', result['stopped'])

    def test_a_placement_reaching_past_the_canvas_finishes_the_canvas_part(self):
        # Review finding (2026-10-24): a target rounded past the edge, or a goal placed partly off the canvas, raised IndexError.
        for number, target in enumerate(([0, 0, 600.4, 400], [100, 0, 600, 400], [-50, 0, 600, 400])):
            result = self.run_finish('past-%d' % number, goal=dict(self.spec, target=target))
            self.assertEqual(result['status'], 'ok', result.get('error'))
            self.assertGreater(result['finish']['strokes'], 0)
        group = self.h._creative_node(self.h.doc, result['layer_id'])
        self.assertEqual(int(group.childNodes()[-1].data[:, 550:, 3].max()), 0, 'nothing where the goal is not')

    def test_a_stop_before_anything_is_painted_leaves_no_empty_group(self):
        class Stopped:
            def is_set(self): return True
        previous = finish.stop_requested
        finish.stop_requested = Stopped()
        self.addCleanup(setattr, finish, 'stop_requested', previous)
        before = self.shown()
        result = self.run_finish()
        self.assertTrue(result.get('contribution_removed'))
        self.assertEqual(result['finish']['tiles'], 0)
        def labels(node): return [node.label] + [label for child in node.childNodes() for label in labels(child)]
        self.assertNotIn('Finish', labels(self.h.doc.root), 'the empty Finish group is gone')
        self.assertTrue(np.array_equal(before, self.shown()))

    def test_a_layer_with_nothing_to_show_is_not_left_in_the_group(self):
        flat = np.full((200, 300, 3), (180, 150, 120), np.uint8)              # a goal with no structure: all soft
        data = cv2.imencode('.png', flat)[1].tobytes()
        with open(self.goal_path, 'wb') as stream:
            stream.write(data)
        result = self.run_finish(goal=dict(self.spec, sha256=hashlib.sha256(data).hexdigest()))
        group = self.h._creative_node(self.h.doc, result['layer_id'])
        self.assertEqual([c.label for c in group.childNodes()], ['Finish · blend'])
        self.assertEqual(result['finish']['strokes'], 0)


if __name__ == '__main__':
    unittest.main()

# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""flatten_passes (flatten_craft.py): a refine round's finish passes, and its accents passes, flattened into one layer
each (the artist, 2026-10-25: 146 layers and 10.1 GiB after one refine step). What shows stays the same, the passes'
groups go, the flattened layer is one pass of the move (its Undo hides it), and anything that would change the picture
is refused before anything changes. The pixel layer tree of the finish tests; files in a temporary folder."""
import unittest
import numpy as np
import test_finish_pass as finish_tests

accent_tests = finish_tests.accent_tests
region_tests = finish_tests.region_tests


class FlattenTests(finish_tests.FinishOperationTests):
    def three_passes(self):
        """Three finish passes of move 1 side by side (boxes), each a group of two layers."""
        for i, box in enumerate(([0, 0, 200, 400], [200, 0, 200, 400], [400, 0, 200, 400])):
            result = self.run_finish('f%d' % (i + 1), box=box)
            self.assertEqual(result['status'], 'ok', result.get('error'))

    def flatten(self, ids, identifier='flat', **extra):
        return region_tests.run(self.h, 'flatten_passes', dict({'pass_ids': ids, 'name': 'Refine 1', 'stage_id': 'move-1'}, **extra), identifier)

    def stage(self):
        """The move's stage group, where its passes are."""
        return self.h.doc.root.childNodes()[1]

    def labels(self):
        return [c.label for c in self.stage().childNodes()]

    def count(self, node):
        return 1 + sum(self.count(c) for c in node.childNodes())

    def test_a_rounds_passes_become_one_layer_that_shows_the_same_and_undo_hides_it(self):
        self.before_passes = self.shown()
        self.three_passes()
        before = self.shown()
        self.assertEqual(self.labels(), ['Finish'] * 3)
        nodes = self.count(self.stage()) - 1
        result = self.flatten(['f1', 'f2', 'f3'])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(self.labels(), ['Refine 1'], 'three groups of baked layers: one layer')
        self.assertEqual((result['flattened_passes'], result['removed_layers']), (3, nodes))
        self.assertLessEqual(float(np.abs(self.shown() - before).max()), 1, 'the picture is the same')
        passes = {p['id']: p for p in self.h._creative_session['passes']}
        self.assertTrue(all(passes[i]['merged_into'] == 'flat' for i in ('f1', 'f2', 'f3')))
        self.assertEqual((passes['flat']['kind'], passes['flat']['stage_id']), ('flatten_passes', 'move-1'))
        # The move's Undo rejects its stage: the flattened layer is hidden, the painting as before the passes.
        undone = region_tests.run(self.h, 'review_pass', {'pass_id': 'stage:move-1', 'action': 'reject'}, 'undo')
        self.assertEqual(undone['status'], 'ok', undone.get('error'))
        self.assertFalse(self.stage().childNodes()[-1].visible())
        self.assertLessEqual(float(np.abs(self.shown() - self.before_passes).max()), 1)

    def test_passes_at_the_bottom_of_the_move_flatten_without_move_layer_down(self):
        # Live, 2026-10-25: the flattened layer went in below the bottom pass with Krita's Move Layer Down, which moves a
        # layer INTO a group below it (each pass is a group): "'{...}' is not in list", a partial change, and the texture
        # pass after it refused. The layer now goes above the top pass, where nothing has to move.
        self.three_passes()
        before = self.shown()
        def no_lowering(doc, node):
            raise AssertionError('Move Layer Down moves a layer into the group below it in Krita')
        self.h._craft_lower = no_lowering
        result = self.flatten(['f1', 'f2', 'f3'])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(self.labels(), ['Refine 1'])
        self.assertLessEqual(float(np.abs(self.shown() - before).max()), 1, 'the picture is the same')

    def test_it_writes_only_the_squares_that_hold_paint(self):
        self.run_finish('f1', box=[0, 0, 100, 100], detail='fine')
        result = self.flatten(['f1'])
        self.assertEqual(result['status'], 'ok', result.get('error'))
        layer = self.stage().childNodes()[-1]
        painted = layer.data[..., 3] > 0
        self.assertTrue(painted[:100, :100].any() and not painted[:, 160:].any())
        self.assertLessEqual(result['written_squares'], 9, 'a 100 px box (and its strokes’ reach): a few 64 px squares')

    def test_anything_that_would_change_the_picture_is_refused_and_nothing_changes(self):
        self.three_passes()
        layers = self.labels()
        other = self.h.doc.createNode('Artist', 'paintlayer')
        self.stage().addChildNode(other, self.stage().childNodes()[1])             # between f2 and f3
        with self.assertRaisesRegex(ValueError, 'between'):
            self.flatten(['f1', 'f2', 'f3'])
        other.remove()
        self.stage().childNodes()[1].setVisible(False)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.flatten(['f1', 'f2'], 'flat2')
        self.stage().childNodes()[1].setVisible(True)
        with self.assertRaisesRegex(ValueError, 'Unknown pass'):
            self.flatten(['f1', 'nope'], 'flat3')
        with self.assertRaisesRegex(ValueError, 'this move'):
            self.flatten(['f1'], 'flat4', stage_id='move-2')
        self.assertEqual(self.labels(), layers)


def load_tests(loader, tests, pattern):
    """Only this file's tests: the finish tests' painting and goal, without running their tests again here."""
    return unittest.TestSuite(FlattenTests(name) for name in sorted(vars(FlattenTests)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()

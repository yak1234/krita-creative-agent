"""script_steps.one_step: a loop of pixel writes as one agent move, or nothing on stock Krita."""
import sys
import unittest
import test_region_craft  # loads the plugin package the other tests use

one_step = sys.modules['creative_test_package.script_steps'].one_step


class Doc:
    def __init__(self, open_move=False, accept=True):
        self.open, self.accept, self.begun, self.ended, self.id = open_move, accept, [], 0, 0
    def beginAgentMove(self, name):
        if not self.accept: return False
        self.open, self.id = True, self.id + 1; self.begun.append(name); return True
    def endAgentMove(self): self.open = False; self.ended += 1; return True
    def agentMoveOpen(self): return self.open
    def agentMoveId(self): return self.id


class OneStepTests(unittest.TestCase):
    def test_a_block_is_one_move(self):
        doc = Doc()
        with one_step(doc, 'strips'):
            self.assertTrue(doc.open)
        self.assertEqual((doc.begun, doc.ended, doc.open), (['strips'], 1, False))

    def test_the_move_ends_when_the_block_raises(self):
        doc = Doc()
        with self.assertRaises(ValueError):
            with one_step(doc, 'strips'):
                raise ValueError()
        self.assertEqual((doc.ended, doc.open), (1, False))

    def test_a_block_inside_an_open_move_joins_it(self):
        doc = Doc(open_move=True)
        with one_step(doc, 'strips'):
            pass
        self.assertEqual((doc.begun, doc.ended, doc.open), ([], 0, True))

    def test_a_refused_move_runs_the_block_anyway(self):
        doc = Doc(accept=False); ran = []
        with one_step(doc, 'strips'):
            ran.append(1)
        self.assertEqual((ran, doc.ended), ([1], 0))

    def test_stock_krita_has_no_moves(self):
        ran = []
        with one_step(object(), 'strips'):
            ran.append(1)
        self.assertEqual(ran, [1])

    def test_a_move_closed_meanwhile_is_not_ended_again(self):
        doc = Doc()
        with one_step(doc, 'strips'):
            doc.open = False; doc.id += 1     # closed by itself, and another began
        self.assertEqual(doc.ended, 0)


if __name__ == '__main__':
    unittest.main()

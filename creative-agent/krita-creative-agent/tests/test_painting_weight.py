"""painting_weight: what makes a painting heavy for Krita, from layer metadata only. Pure Python; writes no files."""
import importlib.util
import pathlib
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
spec = importlib.util.spec_from_file_location('painting_weight', PLUGIN / 'painting_weight.py')
pw = importlib.util.module_from_spec(spec); spec.loader.exec_module(pw)

W, H = 6000, 4500
FULL = (0, 0, W, H)


def record(kind, name='Layer', visible=True, agent=False, bounds=FULL, filter=None):
    return {'type': kind, 'name': name, 'visible': visible, 'agent': agent, 'bounds': bounds, 'filter': filter}


def new_moscow():
    """The shape of new_moscow_finished.kra on 2026-10-18: 147 groups, 92 paint layers, 10 filter masks."""
    rows = [record('grouplayer', 'Creative Agent · Stage %d' % i, agent=True) for i in range(147)]
    rows += [record('paintlayer', 'Pass %d' % i, agent=i >= 6, bounds=(0, 0, 3000, 1500)) for i in range(92)]
    rows += [record('filtermask', 'Blur %d' % i, agent=True, filter='gaussian blur', bounds=(0, 0, 3000, 1500)) for i in range(8)]
    rows += [record('filtermask', 'AI Filter Realism — wavelet texture reduction', agent=True, filter='waveletnoisereducer'),
             record('filtermask', 'AI Filter Realism — edge-aware fine texture reduction', agent=True, filter='gaussiannoisereducer')]
    return rows


class WeightTests(unittest.TestCase):
    def test_new_moscow_is_too_heavy_and_the_reasons_name_the_noise_reducers(self):
        weight = pw.weight(new_moscow(), W, H)
        self.assertEqual((weight['nodes'], weight['groups'], weight['paint_layers'], weight['filter_masks']), (249, 147, 92, 10))
        self.assertEqual(weight['expensive_filters'], ['waveletnoisereducer', 'gaussiannoisereducer'])
        self.assertEqual(weight['level'], 'too_heavy')
        self.assertTrue(any('wavelet noise reducer' in reason for reason in weight['reasons']), weight['reasons'])
        self.assertTrue(any('147 groups' in reason for reason in weight['reasons']), weight['reasons'])
        self.assertEqual(weight['fixes'], ['bake_filters', 'merge_kept'])
        self.assertGreater(weight['estimated_mb'], 6000)

    def test_a_small_painting_is_ok_and_says_nothing(self):
        rows = [record('paintlayer', 'Background', bounds=(0, 0, 1024, 768)), record('grouplayer', 'Creative Agent · move-1', agent=True, bounds=(0, 0, 1024, 768)),
                record('paintlayer', 'Sky', agent=True, bounds=(0, 0, 1024, 300))]
        weight = pw.weight(rows, 1024, 768)
        self.assertEqual((weight['level'], weight['reasons'], weight['fixes']), ('ok', [], []))

    def test_many_hidden_agent_layers_are_heavy_with_tidy_as_the_fix(self):
        rows = [record('paintlayer', 'Background', bounds=(0, 0, 2000, 1500))]
        rows += [record('paintlayer', 'Rejected %d' % i, visible=False, agent=True, bounds=(0, 0, 200, 200)) for i in range(40)]
        weight = pw.weight(rows, 2000, 1500)
        self.assertEqual(weight['hidden_agent_layers'], 40)
        self.assertEqual(weight['level'], 'heavy')
        self.assertEqual(weight['fixes'], ['tidy'])
        self.assertTrue(any('40 hidden' in reason for reason in weight['reasons']))

    def test_an_expensive_filter_on_a_small_canvas_is_only_named_not_too_heavy(self):
        rows = [record('paintlayer', 'Base', bounds=(0, 0, 1000, 1000)), record('filtermask', 'Smooth', filter='waveletnoisereducer', bounds=(0, 0, 1000, 1000))]
        weight = pw.weight(rows, 1000, 1000)
        self.assertEqual(weight['level'], 'ok')
        self.assertEqual(weight['expensive_filters'], ['waveletnoisereducer'])

    def test_hidden_layers_add_no_projection_weight_and_bounds_are_clipped_to_the_canvas(self):
        visible = pw.weight([record('grouplayer', 'G', bounds=(-500, -500, 3000, 2500))], 2000, 1500)
        hidden = pw.weight([record('grouplayer', 'G', visible=False, bounds=(0, 0, 2000, 1500))], 2000, 1500)
        self.assertAlmostEqual(visible['estimated_mb'], 2000 * 1500 * 4 / 1e6, places=1)
        self.assertEqual(hidden['estimated_mb'], 0)


if __name__ == '__main__':
    unittest.main()


class Rect:
    def __init__(self, x, y, w, h): self.v = (x, y, w, h)
    def x(self): return self.v[0]
    def y(self): return self.v[1]
    def width(self): return self.v[2]
    def height(self): return self.v[3]


class Node:
    """Metadata only: any pixel read fails the test."""
    def __init__(self, kind, name, visible=True, children=(), filter_name=None, bounds=(0, 0, 10, 10)):
        self.kind, self.label, self.shown, self.children, self.filter_name, self.rect = kind, name, visible, list(children), filter_name, Rect(*bounds)
    def type(self): return self.kind
    def name(self): return self.label
    def visible(self): return self.shown
    def childNodes(self): return self.children
    def bounds(self): return self.rect
    def filter(self):
        class F:
            def __init__(s, n): s.n = n
            def name(s): return s.n
        return F(self.filter_name)
    def __getattr__(self, attr):
        if 'ixel' in attr or 'projection' in attr.lower(): raise AssertionError('read pixels: ' + attr)
        raise AttributeError(attr)


class Doc:
    def __init__(self, nodes): self.root = Node('grouplayer', 'root', children=nodes)
    def rootNode(self): return self.root


class RecordsTests(unittest.TestCase):
    def test_records_walk_the_tree_from_metadata_and_carry_hidden_and_agent_down(self):
        doc = Doc([Node('paintlayer', 'Background'),
                   Node('grouplayer', 'Creative Agent · move-1', visible=False, children=[
                       Node('paintlayer', 'Sky'), Node('filtermask', 'Smooth', filter_name='waveletnoisereducer')])])
        rows = pw.records(doc)
        self.assertEqual([(r['name'], r['visible'], r['agent'], r['filter']) for r in rows],
                         [('Background', True, False, None), ('Creative Agent · move-1', False, True, None),
                          ('Sky', False, True, None), ('Smooth', False, True, 'waveletnoisereducer')])
        self.assertEqual(pw.weight(rows, 10, 10)['hidden_agent_layers'], 2)

"""precision_tools.cmd_move_layer reports a move Krita refused (krita-fork 5.3: Node.move returns a bool)."""
import importlib.util
import pathlib
import sys
import types
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
PACKAGE = 'precision_move_test_package'


def load_precision_tools():
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(SOURCE)]
    sys.modules[PACKAGE] = package
    if 'krita' not in sys.modules:
        krita = types.ModuleType('krita')
        krita.Krita = types.SimpleNamespace(instance=lambda: None)
        krita.Selection = object
        sys.modules['krita'] = krita
    compat = types.ModuleType(PACKAGE + '.qt_compat')
    for name in ('Qt', 'QPointF', 'QCoreApplication', 'QImage', 'QPainter', 'QPainterPath', 'QColor'):
        setattr(compat, name, object())
    compat.QT6 = False
    sys.modules[compat.__name__] = compat
    spec = importlib.util.spec_from_file_location(PACKAGE + '.precision_tools', SOURCE / 'precision_tools.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Point:
    def __init__(self, x, y): self._x, self._y = x, y
    def x(self): return self._x
    def y(self): return self._y


class Rect(Point):
    def width(self): return 10
    def height(self): return 10


class Layer:
    def __init__(self, answer):
        self.answer, self.at, self.moves = answer, (0, 0), []
    def type(self): return 'paintlayer'
    def locked(self): return False
    def position(self): return Point(*self.at)
    def bounds(self): return Rect(*self.at)
    def move(self, x, y):
        self.moves.append((x, y))
        if self.answer:
            self.at = (x, y)
        return self.answer


class Document:
    def waitForDone(self): pass
    def refreshProjection(self): pass


class MoveLayerTest(unittest.TestCase):
    def tools_with(self, layer):
        tools = load_precision_tools().PrecisionTools()
        tools._require_layer = lambda: (Document(), layer, None)
        return tools

    def test_a_move_krita_makes_reports_the_new_position(self):
        layer = Layer(True)
        result = self.tools_with(layer).cmd_move_layer({'dx': 5, 'dy': -3})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['position'], [5, -3])

    def test_a_move_krita_refuses_is_an_error(self):
        layer = Layer(False)
        with self.assertRaises(RuntimeError) as caught:
            self.tools_with(layer).cmd_move_layer({'dx': 5, 'dy': 0})
        self.assertIn('refused', str(caught.exception))
        self.assertEqual(layer.moves, [(5, 0)])


if __name__ == '__main__':
    unittest.main()

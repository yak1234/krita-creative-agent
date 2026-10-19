"""qt_compat.scoped: an enum member of Krita's own classes, scoped under PyQt6 (the fork's Qt6 bindings require
`DockWidgetFactoryBase.DockPosition.DockRight`) and unscoped where only that exists (Krita 5's)."""
import importlib.util
import pathlib
import types
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
spec = importlib.util.spec_from_file_location('qt_compat_under_test', PLUGIN / 'qt_compat.py')
qt_compat = importlib.util.module_from_spec(spec); spec.loader.exec_module(qt_compat)


class ScopedTests(unittest.TestCase):
    def test_the_scoped_member_when_the_enum_is_a_class_of_its_own(self):
        qt6 = types.SimpleNamespace(DockPosition=types.SimpleNamespace(DockRight='scoped'))
        self.assertEqual(qt_compat.scoped(qt6, 'DockPosition', 'DockRight'), 'scoped')

    def test_the_unscoped_member_otherwise(self):
        qt5 = types.SimpleNamespace(DockRight=2)
        self.assertEqual(qt_compat.scoped(qt5, 'DockPosition', 'DockRight'), 2)
        # A PyQt5 enum type that does not carry its members: the owner's member.
        mixed = types.SimpleNamespace(DockPosition=types.SimpleNamespace(), DockRight=2)
        self.assertEqual(qt_compat.scoped(mixed, 'DockPosition', 'DockRight'), 2)

    def test_the_docker_registers_through_it(self):
        source = (PLUGIN / 'creative_docker.py').read_text()
        self.assertIn("scoped(DockWidgetFactoryBase, 'DockPosition', 'DockRight')", source)
        self.assertNotIn('DockWidgetFactoryBase.DockRight', source)


if __name__ == '__main__': unittest.main()

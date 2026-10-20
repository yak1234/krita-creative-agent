"""The panel names the application it runs in (Toska in the fork, Krita in stock Krita), and keeps 'Krita' only where it
means upstream or the file format. No Qt application is started: the names come from a fake."""
import importlib.util
import pathlib
import re
import types
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
spec = importlib.util.spec_from_file_location('product_name_under_test', PLUGIN / 'product_name.py')
product = importlib.util.module_from_spec(spec); spec.loader.exec_module(product)


class ProductNameTests(unittest.TestCase):
    def test_the_applications_display_name(self):
        self.assertEqual(product.product_name(types.SimpleNamespace(applicationDisplayName=lambda: 'Toska')), 'Toska')
        self.assertEqual(product.product_name(types.SimpleNamespace(applicationDisplayName=lambda: ' Krita ')), 'Krita')

    def test_krita_when_there_is_no_name(self):
        self.assertEqual(product.product_name(types.SimpleNamespace(applicationDisplayName=lambda: '')), 'Krita')
        self.assertEqual(product.product_name(types.SimpleNamespace(applicationDisplayName=lambda: None)), 'Krita')
        self.assertEqual(product.product_name(types.SimpleNamespace()), 'Krita')

    def test_without_an_application_it_is_krita(self):
        self.assertEqual(product.product_name(), 'Krita')           # tests run with no QCoreApplication


class PanelTextTests(unittest.TestCase):
    """What the artist reads in the panel goes through product_name(): a literal 'Krita' in a string shown to the artist is a
    regression, except the file format name and upstream's own words."""
    ALLOWED = ("'Krita paintings (*.kra)'",)

    def test_no_artist_visible_string_in_the_panel_hardcodes_krita(self):
        source = (PLUGIN / 'creative_docker.py').read_text()
        shown = re.compile(r"(setText|setToolTip|setPlaceholderText|setWindowTitle|setStatusTip|QLabel|QPushButton|RuntimeError)\(([^\n]*)")
        offenders = []
        for number, line in enumerate(source.splitlines(), 1):
            if line.lstrip().startswith(('#', '"""')):
                continue
            for match in shown.finditer(line):
                text = match.group(2)
                if 'Krita' in text and 'product_name()' not in line and not any(a in text for a in self.ALLOWED):
                    offenders.append('%d: %s' % (number, line.strip()[:140]))
        self.assertEqual(offenders, [])
        self.assertIn("'Match %s' % product_name()", source)
        self.assertNotIn('Krita Agent', source.replace('"""', ''))

    def test_the_installed_plugin_lists_the_new_module(self):
        self.assertTrue((PLUGIN / 'product_name.py').is_file())


if __name__ == '__main__': unittest.main()

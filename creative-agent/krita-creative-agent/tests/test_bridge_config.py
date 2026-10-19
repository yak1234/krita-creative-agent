"""bridge_config.py: the bridge's port follows the plugin's own creative-agent-config.json, so stock Krita and the fork
(its own settings folder) can run at once. Uses a temporary folder that is removed."""
import ast
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
spec = importlib.util.spec_from_file_location('bridge_config_under_test', PLUGIN / 'bridge_config.py')
bridge_config = importlib.util.module_from_spec(spec); spec.loader.exec_module(bridge_config)


class BridgePortTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.config = os.path.join(folder.name, 'creative-agent-config.json')

    def write(self, settings):
        with open(self.config, 'w') as stream:
            stream.write(settings if isinstance(settings, str) else json.dumps(settings))

    def test_stock_krita_without_a_config_keeps_5678(self):
        self.assertEqual(bridge_config.bridge_port(self.config, ''), 5678)

    def test_an_app_with_its_own_settings_folder_defaults_to_its_own_port(self):
        # The fork sets QCoreApplication.organizationName() to its settings folder; stock Krita leaves it empty.
        self.assertEqual(bridge_config.bridge_port(self.config, 'KritaAgent'), 5679)

    def test_the_configs_bridge_url_names_the_port(self):
        self.write({'bridge_url': 'http://127.0.0.1:5690'})
        self.assertEqual(bridge_config.bridge_port(self.config, ''), 5690)
        self.assertEqual(bridge_config.bridge_port(self.config, 'KritaAgent'), 5690)

    def test_an_unusable_config_falls_back_to_the_apps_default(self):
        for broken in ('not json', {'bridge_url': 'http://127.0.0.1'}, {'bridge_url': 'http://127.0.0.1:99999'},
                       {'bridge_url': 42}, ['list']):
            self.write(broken)
            self.assertEqual(bridge_config.bridge_port(self.config, ''), 5678, broken)
            self.assertEqual(bridge_config.bridge_port(self.config, 'KritaAgent'), 5679, broken)


class OutputDirTests(unittest.TestCase):
    """Canvas exports (get_canvas writes canvas.png each time) go to a folder of the running app's own, so the fork never
    overwrites stock Krita's while both run."""
    def test_stock_keeps_its_folder_and_the_fork_has_its_own(self):
        home = os.path.expanduser('~')
        self.assertEqual(bridge_config.output_dir({}, ''), os.path.join(home, 'krita-mcp-output'))
        self.assertEqual(bridge_config.output_dir({}, 'KritaAgent'), os.path.join(home, 'krita-mcp-output', 'KritaAgent'))
        self.assertEqual(bridge_config.output_dir({'KRITA_MCP_OUTPUT': '/exports'}, ''), '/exports')
        self.assertEqual(bridge_config.output_dir({'KRITA_MCP_OUTPUT': '/exports'}, 'KritaAgent'), '/exports/KritaAgent')

    def test_the_plugin_exports_there(self):
        init = (PLUGIN / '__init__.py').read_text()
        self.assertIn('CANVAS_OUTPUT_DIR = output_dir(os.environ, QCoreApplication.organizationName())', init)
        self.assertNotIn("'~/krita-mcp-output'", (PLUGIN / 'precision_tools.py').read_text())


class PluginWiringTests(unittest.TestCase):
    def test_the_bridge_starts_on_the_running_apps_port(self):
        tree = ast.parse((PLUGIN / '__init__.py').read_text())
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        port = ast.unparse(functions['server_port'])
        self.assertIn('bridge_port(', port); self.assertIn('creative-agent-config.json', port)
        self.assertIn('QCoreApplication.organizationName()', port)
        starts = [ast.unparse(node) for node in ast.walk(functions['createActions'])
                  if isinstance(node, ast.Call) and ast.unparse(node.func) == 'ServerThread']
        self.assertEqual(starts, ['ServerThread(port)'])
        self.assertIn('port = server_port()', ast.unparse(functions['createActions']))


if __name__ == '__main__': unittest.main()

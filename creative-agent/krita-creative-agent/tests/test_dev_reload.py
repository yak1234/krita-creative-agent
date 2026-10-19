"""Hot reload swaps fresh methods onto a live object. Uses a throwaway package in a temporary folder that is removed."""
import importlib
import os
import pathlib
import shutil
import sys
import tempfile
import textwrap
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp/dev_reload.py'


def write(folder, name, body):
    with open(os.path.join(folder, name + '.py'), 'w') as stream:
        stream.write(textwrap.dedent(body))


class DevReloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.folder = os.path.join(temporary.name, 'reloadpkg'); os.makedirs(self.folder)
        write(self.folder, '__init__', '')
        write(self.folder, 'layer_craft', '''
            class LayerCraft:
                def craft(self): return 'old craft'
            ''')
        write(self.folder, 'creative_tools', '''
            from .layer_craft import LayerCraft
            CREATIVE_BUILD = {'build_id': 'old'}
            class CreativeTools(LayerCraft):
                def dispatch(self): return 'old dispatch ' + self.craft()
            ''')
        sys.path.insert(0, temporary.name)
        self.addCleanup(lambda: sys.path.remove(temporary.name))
        self.addCleanup(lambda: [sys.modules.pop(name) for name in list(sys.modules) if name.startswith('reloadpkg')])
        sys.dont_write_bytecode, previous = True, sys.dont_write_bytecode
        self.addCleanup(setattr, sys, 'dont_write_bytecode', previous)
        tools = importlib.import_module('reloadpkg.creative_tools')
        shutil.copy(SOURCE, self.folder)                         # installed beside the modules it reloads
        self.reload = importlib.import_module('reloadpkg.dev_reload')
        class Plugin(tools.CreativeTools): pass                  # stands in for KritaMCPExtension
        Plugin.__module__ = 'reloadpkg'
        self.plugin = Plugin()

    def test_every_plugin_module_reloads_dependencies_first_not_only_a_list(self):
        write(self.folder, 'native_craft', '''
            from .layer_craft import LayerCraft
            class NativeCraft:
                def act(self): return 'old act'
            ''')
        write(self.folder, 'creative_tools', '''
            from .layer_craft import LayerCraft
            from .native_craft import NativeCraft
            CREATIVE_BUILD = {'build_id': 'old'}
            class CreativeTools(LayerCraft, NativeCraft):
                def dispatch(self): return 'old dispatch ' + self.craft()
            ''')
        importlib.reload(sys.modules['reloadpkg.creative_tools'])
        class Plugin(sys.modules['reloadpkg.creative_tools'].CreativeTools): pass
        Plugin.__module__ = 'reloadpkg'
        plugin = Plugin()
        write(self.folder, 'native_craft', '''
            class NativeCraft:
                def act(self): return 'new act'
            ''')
        result = self.reload.reload(plugin, companion=False)
        self.assertEqual(plugin.act(), 'new act', 'a module no list names still reloads')
        order = result['reloaded']
        self.assertLess(order.index('layer_craft'), order.index('native_craft'))
        self.assertLess(order.index('native_craft'), order.index('creative_tools'))
        self.assertNotIn('dev_reload', order)

    def test_a_live_object_gets_fresh_methods_and_new_mixins(self):
        self.assertEqual(self.plugin.dispatch(), 'old dispatch old craft')
        write(self.folder, 'layer_craft', '''
            class LayerCraft:
                def craft(self): return 'new craft'
            ''')
        write(self.folder, 'filters', '''
            class FilterCraft:
                def blur(self): return 'blurred'
            ''')
        write(self.folder, 'creative_tools', '''
            from .layer_craft import LayerCraft
            from .filters import FilterCraft
            CREATIVE_BUILD = {'build_id': 'new'}
            class CreativeTools(LayerCraft, FilterCraft):
                def dispatch(self): return 'new dispatch ' + self.craft()
            ''')
        result = self.reload.reload(self.plugin, companion=False)
        self.assertEqual(result['reloaded'], ['layer_craft', 'creative_tools'])
        self.assertEqual(result['build_id'], 'new')
        self.assertEqual(self.plugin.dispatch(), 'new dispatch new craft')
        self.assertEqual(self.plugin.blur(), 'blurred', 'a mixin added since start is reachable')
        self.assertIsNone(self.plugin._craft_manifest_cache)


if __name__ == '__main__':
    unittest.main()

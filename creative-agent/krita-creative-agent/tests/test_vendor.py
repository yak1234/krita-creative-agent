"""vendor.py: native packages the plugin ships for Krita's own Python (Krita bundles no numpy). Uses a temporary
folder that is removed; restores sys.path."""
import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
spec = importlib.util.spec_from_file_location('vendor_under_test', PLUGIN / 'vendor.py')
vendor = importlib.util.module_from_spec(spec); spec.loader.exec_module(vendor)


class VendorTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.root = folder.name
        saved = list(sys.path); self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved))

    def test_the_platform_folder_is_appended_once_never_ahead_of_krita(self):
        path = os.path.join(self.root, '_vendor', vendor.platform_tag())
        os.makedirs(path)
        self.assertEqual(vendor.add_vendor_path(self.root, os.path.join(self.root, 'nowhere')), path)
        self.assertEqual(sys.path[-1], path, 'appended: Krita’s own PyQt5 is never shadowed')
        vendor.add_vendor_path(self.root, os.path.join(self.root, 'nowhere'))
        self.assertEqual(sys.path.count(path), 1)

    def test_no_folder_no_change(self):
        before = list(sys.path)
        self.assertIsNone(vendor.add_vendor_path(self.root, os.path.join(self.root, 'nowhere')))
        self.assertEqual(sys.path, before)

    def test_the_shared_package_folder_is_used_and_named_for_this_python(self):
        # Shared by releases, like the Node runtime: an install replaces the plugin folder, never this one.
        shared = vendor.shared_root(os.path.join(self.root, 'Creative Agent', 'runtimes'))
        self.assertTrue(shared.endswith(os.path.join('Creative Agent', 'python', '%s-py%d%d' % ((vendor.platform_tag(),) + sys.version_info[:2]))), shared)
        os.makedirs(shared)
        self.assertEqual(vendor.add_vendor_path(self.root, shared), shared)
        self.assertEqual(sys.path[-1], shared)

    def test_a_plugin_that_carries_its_packages_never_reads_the_shared_user_writable_folder(self):
        # The packaged app ships numpy & co. inside the signed bundle (disable-library-validation is on: a folder anyone can
        # write to must not also be searched for native libraries).
        own = os.path.join(self.root, '_vendor', vendor.platform_tag())
        shared = os.path.join(self.root, 'shared')
        os.makedirs(own); os.makedirs(shared)
        self.assertEqual(vendor.add_vendor_path(self.root, shared), own)
        self.assertIn(own, sys.path)
        self.assertNotIn(shared, sys.path)

    def test_the_tag_names_os_and_machine(self):
        self.assertRegex(vendor.platform_tag(), r'^(macos|linux|windows)-[a-z0-9_]+$')


if __name__ == '__main__':
    unittest.main()

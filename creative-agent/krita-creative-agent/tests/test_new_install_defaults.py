# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Task 3.3, new-install defaults: the shipped files cannot rot.

A new KritaAgent install gets the Photoshop shortcut scheme, a layout with the Creative Agent panel docked beside the usual
dockers, and the dark theme, all from krita/data/kritarc (compiled in as :/kconfig/KritaAgent/kritarc and read UNDER the
artist's own kritarc, so any value the artist has set wins). These tests parse the files; when Qt is importable they also
restore the saved layout into a window with the real docker ids and see which dockers are visible.
"""
import base64
import importlib.util
import os
import pathlib
import re
import struct
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')   # before any QApplication: the layout sizes depend on the platform

REPO = pathlib.Path(__file__).resolve().parents[3]
DATA = REPO / 'krita/data'
SCHEME = DATA / 'shortcuts/photoshop_compatible.shortcuts'
KRITARC = DATA / 'kritarc'
WORKSPACE = DATA / 'workspaces/Photoshop_Agent.kws'
DOCKER_PY = REPO / 'creative-agent/krita-mcp/krita-plugin/kritamcp/creative_docker.py'

_spec = importlib.util.spec_from_file_location('make_agent_workspace', REPO / 'agent/make_agent_workspace.py')
maker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(maker)

# The Photoshop habit: action id -> key, as Krita's scheme file spells it (Qt's Ctrl is Cmd on macOS, as in Photoshop).
HABIT = {
    'KritaShape/KisToolBrush': 'B', 'erase_action': 'E', 'KritaTransform/KisToolMove': 'V',
    'KisToolSelectRectangular': 'M', 'KisToolSelectOutline': 'L', 'KisToolSelectContiguous': 'W',
    'KritaFill/KisToolGradient': 'G', 'KritaFill/KisToolFill': 'Shift+G', 'KritaSelected/KisToolColorSampler': 'I',
    'KisToolCrop': 'C', 'KritaShape/KisToolText': 'T',
    'edit_undo': 'Ctrl+Z', 'edit_redo': 'Ctrl+Shift+Z', 'duplicatelayer': 'Ctrl+J', 'KisToolTransform': 'Ctrl+T',
    'decrease_brush_size': '[', 'increase_brush_size': ']', 'toggle_fg_bg': 'X', 'reset_fg_bg': 'D',
    'fill_selection_foreground_color': 'Alt+Backspace', 'fill_selection_background_color': 'Ctrl+Backspace',
}
SHOWN_DOCKERS = {'ToolBox', 'ColorSelectorNg', 'sharedtooldocker', 'PaletteDocker', 'PresetDocker', 'OverviewDocker',
                 'History', 'KisLayerBox', 'krita_creative_agent'}


def scheme_entries():
    entries = {}
    for line in SCHEME.read_text().splitlines():
        if '=' in line and not line.startswith('['):
            key, value = line.rsplit('=', 1) if line.endswith('=') else line.split('=', 1)
            assert key not in entries, 'duplicate action %s in the scheme' % key
            entries[key] = value
    return entries


def kritarc_group(name):
    text = KRITARC.read_text()
    match = re.search(r'(?ms)^\[%s\]\n(.*?)(?=^\[|\Z)' % re.escape(name), text)
    return dict(l.split('=', 1) for l in match.group(1).splitlines() if '=' in l) if match else {}


# Restoring the saved layout needs a Qt application: done in a child process so it has a clean one.
RESTORE_CHECK = r"""
import base64, re, sys
from %(binding)s import QtCore, QtWidgets
Qt = QtCore.Qt
names, toolbars, shown_expected = %(names)r, %(toolbars)r, set(%(shown)r)
text = open(%(path)r).read()
blob = base64.b64decode(re.search(r'<state><!\[CDATA\[(.*?)\]\]', text, re.S).group(1))
app = QtWidgets.QApplication([])
window = QtWidgets.QMainWindow(); window.resize(1700, 1000); window.setCentralWidget(QtWidgets.QLabel('canvas'))
area = Qt.DockWidgetArea.RightDockWidgetArea if hasattr(Qt, 'DockWidgetArea') else Qt.RightDockWidgetArea
for name in names:
    if name in toolbars:
        widget = QtWidgets.QToolBar(name); window.addToolBar(widget)
    else:
        widget = QtWidgets.QDockWidget(name); widget.setWidget(QtWidgets.QLabel(name)); window.addDockWidget(area, widget)
    widget.setObjectName(name)
window.show()
assert window.restoreState(QtCore.QByteArray(blob)), 'restoreState failed'
app.processEvents()
docks = {d.objectName(): d for d in window.findChildren(QtWidgets.QDockWidget)}
agent = docks[%(agent)r]
assert agent.isVisible() and agent.width() > 300, 'the agent panel is not docked and visible'
shown = {n for n, d in docks.items() if d.isVisible() or (not d.isHidden() and window.tabifiedDockWidgets(d))}
assert shown == shown_expected, sorted(shown ^ shown_expected)
"""


class ShortcutSchemeTest(unittest.TestCase):
    def test_habit_keys(self):
        entries = scheme_entries()
        for action, key in HABIT.items():
            self.assertEqual(entries.get(action), key, action)

    def test_habit_keys_do_not_clash_with_each_other_or_with_a_tool_or_fill(self):
        keys = {}
        for action, key in HABIT.items():
            self.assertNotIn(key, keys, '%s and %s share %s' % (action, keys.get(key), key))
            keys[key] = action
        taken = {}
        for action, key in scheme_entries().items():
            if key in HABIT.values() and action not in HABIT:
                taken.setdefault(key, []).append(action)
        # the only other holders allowed are text-editing or filter commands, which are in other contexts (the scheme's own)
        for key, actions in taken.items():
            for action in actions:
                self.assertTrue(action.startswith(('format_', 'insert_', 'krita_filter_', 'pathpoint-', 'save_incremental',
                                                   'file_open_recent', 'canvassize', 'copy_merged', 'change_text')),
                                '%s also uses %s' % (action, key))

    def test_the_scheme_is_installed_and_named_by_its_file(self):
        self.assertIn('photoshop_compatible.shortcuts', (DATA / 'shortcuts/CMakeLists.txt').read_text())
        self.assertEqual(kritarc_group('Shortcut Schemes').get('Current Scheme'), SCHEME.stem)

    def test_the_panels_own_keys_do_not_clash_with_the_scheme(self):
        source = DOCKER_PY.read_text()
        statement = re.search(r"for key, callback in \[(.*?)\]:\n\s*shortcut = QShortcut\(QKeySequence\(key\)", source, re.S)
        keys = re.findall(r"\('([^']+)',", statement.group(1)) + re.findall(r"QKeySequence\('([^']+)'\)", source)
        self.assertGreaterEqual(len(keys), 3)
        used = {v.lower() for v in scheme_entries().values() if v != 'none'}
        for key in keys:
            self.assertNotIn(key.lower(), used, 'the panel uses %s, which the Photoshop scheme binds' % key)


class ThemeTest(unittest.TestCase):
    def test_dark_theme(self):
        self.assertEqual(kritarc_group('theme').get('Theme'), 'Krita dark')


class WorkspaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ET.parse(WORKSPACE).getroot()
        cls.blob = base64.b64decode(cls.root.find('state').text)
        cls.names = set(maker.state_names(cls.blob))

    def test_file(self):
        self.assertEqual(self.root.tag, 'Workspace')
        self.assertEqual(self.root.get('name'), maker.NAME)
        self.assertEqual(self.blob[:4], struct.pack('>I', 0xFF), 'a QMainWindow state starts with its magic number')
        self.assertIn('Photoshop_Agent.kws', (DATA / 'workspaces/CMakeLists.txt').read_text())

    def test_agent_docker_id_is_the_registered_one(self):
        registered = re.search(r"DockWidgetFactory\(\s*'([^']+)'", DOCKER_PY.read_text()).group(1)
        self.assertEqual(registered, maker.AGENT)
        self.assertIn(registered, self.names)

    def test_has_the_usual_dockers_and_toolbars(self):
        self.assertLessEqual(SHOWN_DOCKERS | set(maker.TOOLBARS), self.names)

    def test_every_shipped_docker_is_listed_so_none_appears_by_surprise(self):
        # Qt leaves a docker that is not in the state visible where it was created; the stock ids must all be placeholders.
        self.assertLessEqual(set(maker.hidden_dockers()), self.names)

    def test_every_python_docker_id_is_listed(self):
        ids = maker.python_docker_ids()
        self.assertGreaterEqual(len(ids), 10, ids)
        self.assertLessEqual(set(ids), self.names, 'a shipped Python docker would show on a new profile')
        self.assertIn('mutatorDocker', ids)

    def test_generator_reproduces_the_committed_blob(self):
        try:
            import PyQt6.QtCore  # noqa: F401
        except ImportError:
            self.skipTest('needs PyQt6 (the blob is a Qt 6 saveState)')
        # In a child process: a clean QApplication, whatever other tests in this process did to theirs.
        done = subprocess.run([sys.executable, str(REPO / 'agent/make_agent_workspace.py'), '--check'], capture_output=True,
                              text=True, env=dict(os.environ, QT_QPA_PLATFORM='offscreen'))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr[-500:])

    def test_kritarc_starts_a_new_install_in_this_layout(self):
        state = kritarc_group('MainWindow')['State']
        self.assertEqual(base64.b64decode(state), self.blob, 'run agent/make_agent_workspace.py')

    def test_restores_with_the_agent_docked_and_only_the_usual_dockers_shown(self):
        binding = self._binding()
        if binding is None:
            self.skipTest('no PyQt')
        code = RESTORE_CHECK % dict(binding=binding, path=str(WORKSPACE), agent=maker.AGENT,
                                    names=sorted(self.names), toolbars=list(maker.TOOLBARS), shown=sorted(SHOWN_DOCKERS))
        done = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                              env=dict(os.environ, QT_QPA_PLATFORM='offscreen'))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr[-800:])

    @staticmethod
    def _binding():
        for name in ('PyQt6', 'PyQt5'):
            try:
                __import__(name + '.QtWidgets')
                return name
            except ImportError:
                continue
        return None


if __name__ == '__main__':
    unittest.main()

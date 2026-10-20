"""Run: uv run -q --with pyqt5 python tests/ui_panel_features.py (a UI script like ui_smoke; it stubs krita for the whole process).
The panel's Protected section (krita-fork 6.6): the painting's features, protected first, with a toggle the artist alone can use."""
import json
import os
from pathlib import Path
import re
import sys
import types
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['KRITA_CREATIVE_NO_AUTOSTART'] = '1'
import importlib.util

PLUGIN = Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
package = types.ModuleType('panel_features_test'); package.__path__ = [str(PLUGIN)]; sys.modules['panel_features_test'] = package
from panel_features_test.qt_compat import QApplication, QDockWidget

state = types.SimpleNamespace(document=None)


class Instance:
    activeDocument = staticmethod(lambda: state.document)
    documents = staticmethod(lambda: [state.document] if state.document else [])
    addDockWidgetFactory = staticmethod(lambda factory: None)


stub = types.ModuleType('krita'); stub.DockWidget = QDockWidget
stub.DockWidgetFactory = object; stub.DockWidgetFactoryBase = types.SimpleNamespace(DockRight=2)
stub.Krita = types.SimpleNamespace(instance=lambda: Instance)
stub.Selection = object
sys.modules['krita'] = stub
spec = importlib.util.spec_from_file_location('panel_features_test.creative_docker', PLUGIN / 'creative_docker.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
app = QApplication.instance() or QApplication([])
QProcess = module.QProcess
# Panels stay referenced until the process ends: a panel collected by Python's cycle GC mid-run can crash PyQt5 when one
# of its timers fires (seen with the unchanged panel too, in a loop of 40 panels). Krita keeps its one docker for the session.
KEEP = []


class Feature:
    """The fork's Feature as Python sees it."""
    def __init__(self, name, kind='region', protected=False, result=True):
        self.n, self.k, self.p, self.result, self.calls = name, kind, protected, result, []
    def name(self): return self.n
    def kind(self): return self.k
    def author(self): raise AssertionError('the poll reads name, kind and isProtected only')
    def state(self): raise AssertionError('the poll reads name, kind and isProtected only')
    def isProtected(self): return self.p
    def setProtected(self, value):
        self.calls.append(value)
        if getattr(self, 'during', None): self.during()
        if self.result: self.p = bool(value)
        return self.result


class StockDocument:
    """Stock Krita's Document: no features API."""
    def fileName(self): return '/tmp/stock.kra'
    def modified(self): return False
    def width(self): return 800
    def height(self): return 600


class ForkDocument(StockDocument):
    def __init__(self, features=()):
        self.list = list(features); self.reads = 0; self.selected = None; self.move_open = False; self.active = False
    def fileName(self): return '/tmp/fork.kra'
    def features(self): self.reads += 1; return list(self.list)
    def feature(self, name): return next((f for f in self.list if f.name() == name), None)
    def protectionActive(self): return any(f.isProtected() for f in self.list)
    def agentMoveOpen(self): return self.move_open
    def agentActive(self): return self.active
    def protectedSelection(self, inverted=False): return None
    def selection(self, expression=None): return self.selected
    def addFeature(self, name, kind, selection, author, state_, protected):
        if self.feature(name): return None
        feature = Feature(name, kind, protected); self.list.append(feature); return feature


class FakeProtection:
    """The legacy annotation-based areas (protection.py): none here."""
    def __init__(self): self.areas = []
    def _protect_list(self, doc): return list(self.areas)


def names(panel): return [row['name'] for row in panel.features_section.rows]


class ProtectedSection(unittest.TestCase):
    def setUp(self):
        state.document = None
        self.commands = []
        self.panel = module.CreativeAgentDocker(); self.panel.resize(440, 820); self.panel.show()
        self.panel.protection = FakeProtection()
        self.panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running,
                                                   write=lambda data: self.commands.append(json.loads(data)))
        self.panel.handle_event({'type': 'ready', 'models': [{'provider': 'openrouter', 'id': 'm', 'name': 'M', 'configured': True}],
                                 'bridge': {}, 'build': {'version': '1', 'build_id': 'b'}})
        self.section = self.panel.features_section

    def tearDown(self):
        self.panel.process = None; self.panel.close(); KEEP.append(self.panel)
        for _ in range(4): app.processEvents()
        state.document = None

    def open(self, *features):
        state.document = ForkDocument(features); self.panel.poll_canvas_metadata(); app.processEvents()
        return state.document

    def test_rows_are_shown_protected_first_and_by_name(self):
        self.open(Feature('Sky'), Feature('Buildings', 'region', True), Feature('moon', 'object', True), Feature('Ark', 'seam'))
        self.assertTrue(self.section.isVisible())
        self.assertEqual(names(self.panel), ['Buildings', 'moon', 'Ark', 'Sky'])
        self.assertEqual([row['check'].isChecked() for row in self.section.rows], [True, True, False, False])
        self.assertEqual([row['kind'].text() for row in self.section.rows], ['region', 'object', 'seam', 'region'])
        self.assertFalse(self.section.empty.isVisible())
        self.assertIn('2 of 4', self.section.summary.text())
        self.assertEqual(self.section.rows[0]['check'].accessibleName(), 'Protect Buildings')

    def test_a_painting_without_features_says_how_to_add_one(self):
        self.open()
        self.assertTrue(self.section.isVisible())
        self.assertEqual(self.section.rows, [])
        self.assertTrue(self.section.empty.isVisible())
        self.assertEqual(self.section.empty.text(), 'No features yet: select an area and use the shield to protect it')

    def test_no_painting_hides_the_section(self):
        self.panel.poll_canvas_metadata()
        self.assertFalse(self.section.isVisible())
        self.open(Feature('Sky'))
        self.assertTrue(self.section.isVisible())
        state.document = None; self.panel.poll_canvas_metadata()
        self.assertFalse(self.section.isVisible(), 'closing the painting hides the list')

    def test_stock_krita_has_no_features_and_no_section(self):
        state.document = StockDocument(); self.panel.poll_canvas_metadata()
        self.assertFalse(self.section.isVisible())
        self.assertEqual(self.panel.feature_rows(), [])

    def test_a_deleted_document_hides_the_section(self):
        document = self.open(Feature('Sky'))
        def deleted(): raise RuntimeError('wrapped C/C++ object has been deleted')
        document.features = deleted
        self.panel.refresh_features()
        self.assertFalse(self.section.isVisible())

    def test_toggling_protects_the_feature_and_the_list_follows(self):
        sky = Feature('Sky')
        self.open(Feature('Buildings', protected=True), sky)
        self.section.rows[1]['check'].click(); app.processEvents()
        self.assertEqual(sky.calls, [True])
        self.assertEqual(self.panel.status.text(), "'Sky' is protected.")
        self.assertEqual(names(self.panel), ['Buildings', 'Sky'])
        self.assertTrue(all(row['check'].isChecked() for row in self.section.rows))
        self.assertIn('2 of 2', self.section.summary.text())
        self.section.rows[0]['check'].click(); app.processEvents()      # Buildings off: it stays where it is until reopened
        self.assertEqual(self.panel.status.text(), "'Buildings' is no longer protected.")
        self.assertEqual(names(self.panel), ['Buildings', 'Sky'])
        self.assertEqual([r['check'].isChecked() for r in self.section.rows], [False, True])
        self.assertIn('1 of 2', self.section.summary.text())
        self.assertEqual(self.section.builds, 1, 'a flag change updates the boxes in place')

    def test_the_clicked_box_keeps_its_place_and_focus(self):
        self.open(Feature('Buildings', protected=True), Feature('Sky'), Feature('Moon'))
        self.panel.activateWindow()
        box = self.section.rows[2]['check']                # Sky
        box.setFocus(); app.processEvents()
        focused = app.focusWidget() is box
        box.click(); app.processEvents()
        self.assertIs(self.section.rows[2]['check'], box)
        self.assertTrue(box.isChecked())
        self.assertTrue(focused); self.assertIs(app.focusWidget(), box)

    def test_toggling_goes_through_set_feature_protected(self):
        self.open(Feature('Sky'))
        seen = []
        original = self.panel.set_feature_protected
        self.panel.set_feature_protected = lambda name, value: seen.append((name, value)) or original(name, value)
        self.section.rows[0]['check'].click(); app.processEvents()
        self.assertEqual(seen, [('Sky', True)])

    def test_a_refused_toggle_says_so_and_shows_the_real_state(self):
        refused = Feature('Sky', result=False)
        self.open(refused)
        self.section.rows[0]['check'].click(); app.processEvents()
        self.assertEqual(refused.calls, [True])
        self.assertIn('did not change the protection', self.panel.status.text())
        self.assertIn('try again', self.panel.status.text())
        self.assertNotIn('Krita', self.panel.status.text().replace(module.product_name(), ''))
        self.assertFalse(self.section.rows[0]['check'].isChecked(), 'the box shows what Krita has, not what was clicked')

    def test_a_feature_removed_meanwhile_is_reported(self):
        document = self.open(Feature('Sky'))
        document.list = []                                 # gone (an undo) before the next poll
        self.section.rows[0]['check'].click(); app.processEvents()
        self.assertIn("No feature called 'Sky'", self.panel.status.text())
        self.assertEqual(self.section.rows, [])

    def test_the_list_is_rebuilt_only_when_the_features_change(self):
        sky = Feature('Sky')
        document = self.open(sky, Feature('Moon'))
        first = [row['check'] for row in self.section.rows]
        for _ in range(5): self.panel.poll_canvas_metadata(); app.processEvents()
        self.assertEqual([row['check'] for row in self.section.rows], first, 'the same widgets: no flicker')
        self.assertEqual(self.section.builds, 1)
        sky.p = True                                       # the artist protects it elsewhere (an undo, a script)
        self.panel.poll_canvas_metadata(); app.processEvents()
        self.assertEqual(self.section.builds, 1, 'only a flag changed: updated in place')
        self.assertEqual([r['check'] for r in self.section.rows], first)
        self.assertEqual(names(self.panel), ['Moon', 'Sky'])
        self.assertEqual([r['check'].isChecked() for r in self.section.rows], [False, True])
        document.list.append(Feature('Lamp', 'object'))
        self.panel.poll_canvas_metadata(); app.processEvents()
        self.assertEqual(names(self.panel), ['Sky', 'Lamp', 'Moon'], 'a new name re-sorts')
        self.assertEqual(self.section.builds, 2)

    def test_switching_paintings_shows_the_other_paintings_features(self):
        self.open(Feature('Sky'))
        self.open(Feature('River'), Feature('Bridge', protected=True))
        self.assertEqual(names(self.panel), ['Bridge', 'River'])

    def test_the_shield_adding_a_feature_refreshes_the_list(self):
        document = self.open(Feature('Sky'))
        document.selected = types.SimpleNamespace(x=lambda: 0, y=lambda: 0, width=lambda: 10, height=lambda: 10, duplicate=lambda: None)
        real, module.QInputDialog = module.QInputDialog, types.SimpleNamespace(getText=lambda *args: ('Buildings', True))
        try: self.panel.protect_selection()
        finally: module.QInputDialog = real
        self.assertEqual(names(self.panel), ['Buildings', 'Sky'])
        self.assertEqual(self.panel.status.text(), "'Buildings' is protected.")

    def test_the_protected_areas_dialog_lists_features_too(self):
        self.open(Feature('Buildings', protected=True), Feature('Sky'))
        dialog = self.panel.open_protection(modal=False)
        try:
            listed = [row['name'] for row in dialog.rows]
            self.assertEqual(listed, ['Buildings'], 'protected features are listed; unprotected ones are not protected areas')
            self.assertNotIn('Nothing is protected yet.', [w.text() for w in dialog.findChildren(module.QLabel)])
        finally:
            dialog.close(); dialog.deleteLater()

    def test_toggles_wait_while_the_agent_paints(self):
        self.open(Feature('Sky'))
        self.panel.handle_event({'type': 'busy', 'busy': True})
        self.assertFalse(self.section.rows[0]['check'].isEnabled())
        self.assertEqual(self.section.rows[0]['check'].toolTip(), 'Pause to change protection')
        self.panel.handle_event({'type': 'busy', 'busy': False})
        self.assertTrue(self.section.rows[0]['check'].isEnabled())

    def test_an_open_agent_move_locks_the_boxes(self):
        sky = Feature('Sky')
        document = self.open(sky)
        for flag in ('move_open', 'active'):
            setattr(document, flag, True)
            self.panel.poll_canvas_metadata(); app.processEvents()
            self.assertFalse(self.section.rows[0]['check'].isEnabled(), flag)
            self.panel.toggle_feature('Sky', True)         # a click that slipped in before the poll
            self.assertEqual(sky.calls, [], flag)
            self.assertIn('agent', self.panel.status.text())
            self.assertIn('Pause', self.panel.status.text())
            self.assertFalse(self.section.rows[0]['check'].isChecked())
            setattr(document, flag, False)
            self.panel.poll_canvas_metadata(); app.processEvents()
            self.assertTrue(self.section.rows[0]['check'].isEnabled(), flag)

    def test_a_running_bridge_command_locks_the_boxes(self):
        sky = Feature('Sky')
        self.open(sky)
        module.command_executing.set()
        try:
            self.panel.poll_canvas_metadata(); app.processEvents()
            self.assertFalse(self.section.rows[0]['check'].isEnabled())
            self.panel.toggle_feature('Sky', True)
            self.assertEqual(sky.calls, [])
        finally:
            module.command_executing.clear()
        self.panel.poll_canvas_metadata()
        self.assertTrue(self.section.rows[0]['check'].isEnabled())

    def test_the_shield_waits_for_an_open_agent_move(self):
        document = self.open(Feature('Sky'))
        document.move_open = True
        document.selected = types.SimpleNamespace(x=lambda: 0, y=lambda: 0, width=lambda: 10, height=lambda: 10, duplicate=lambda: None)
        asked = []
        real, module.QInputDialog = module.QInputDialog, types.SimpleNamespace(getText=lambda *args: asked.append(1) or ('Buildings', True))
        try: self.panel.protect_selection()
        finally: module.QInputDialog = real
        self.assertEqual((asked, names(self.panel)), ([], ['Sky']))
        self.assertIn('Pause', self.panel.status.text())

    def test_a_second_toggle_during_the_first_is_refused(self):
        sky, moon = Feature('Sky'), Feature('Moon')
        self.open(sky, moon)
        locked = []
        def reenter():
            locked.append(all(not r['check'].isEnabled() for r in self.section.rows))
            self.panel.toggle_feature('Moon', True)        # a nested event loop delivers another click
        sky.during = reenter
        self.panel.toggle_feature('Sky', True)
        self.assertEqual((sky.calls, moon.calls, locked), ([True], [], [True]))
        self.assertTrue(all(r['check'].isEnabled() for r in self.section.rows), 'unlocked again')
        self.assertEqual(self.panel.status.text(), "'Sky' is protected.")

    def test_a_change_krita_did_not_make_is_reported(self):
        stubborn = Feature('Sky')
        stubborn.setProtected = lambda value: True         # says yes, changes nothing
        self.open(stubborn)
        self.section.rows[0]['check'].click(); app.processEvents()
        self.assertIn('did not change', self.panel.status.text())
        self.assertIn('try again', self.panel.status.text())
        self.assertFalse(self.section.rows[0]['check'].isChecked())

    def test_names_are_shown_as_text(self):
        self.open(Feature('Salt & Pepper', '<b>kind</b>'))
        row = self.section.rows[0]
        self.assertEqual(row['check'].text(), 'Salt && Pepper', 'an & is not a shortcut marker')
        self.assertEqual(row['check'].accessibleName(), 'Protect Salt & Pepper')
        self.assertEqual(row['kind'].textFormat(), module.Qt.TextFormat.PlainText)

    def test_the_dialog_shows_names_as_text(self):
        self.panel.protection.areas = [{'id': 'm1', 'name': '<i>Car</i>', 'state': 'active', 'by': 'artist'}]
        self.open(Feature('<b>Sky</b>', protected=True))
        dialog = self.panel.open_protection(modal=False)
        try:
            labels = [w for w in dialog.findChildren(module.QLabel) if 'Sky' in w.text() or 'Car' in w.text()]
            self.assertEqual(len(labels), 2)
            self.assertTrue(all(w.textFormat() == module.Qt.TextFormat.PlainText for w in labels))
        finally:
            dialog.close(); dialog.deleteLater()

    def test_the_section_collapses(self):
        self.open(Feature('Sky'))
        self.section.toggle.click()
        self.assertFalse(self.section.body.isVisible())
        self.section.toggle.click()
        self.assertTrue(self.section.body.isVisible())


class ArtistOnly(unittest.TestCase):
    """Only the artist's click changes protection: nothing the companion (and so the model) sends reaches it."""
    def setUp(self):
        self.panel = module.CreativeAgentDocker(); self.panel.show(); self.panel.protection = FakeProtection()
        self.panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running, write=lambda data: None)
        self.sky = Feature('Sky', protected=True)
        state.document = ForkDocument([self.sky]); self.panel.poll_canvas_metadata()

    def tearDown(self):
        self.panel.process = None; self.panel.close(); KEEP.append(self.panel)
        for _ in range(4): app.processEvents()
        state.document = None

    def test_companion_events_never_change_protection(self):
        for event in ({'type': 'feature_set_protected', 'name': 'Sky', 'value': False},
                      {'type': 'set_feature_protected', 'name': 'Sky', 'value': False},
                      {'type': 'features', 'features': [{'name': 'Sky', 'protected': False}]},
                      {'type': 'protection_hit', 'message': "Kept out of 'Sky'.", 'setProtected': False},
                      {'type': 'context', 'selected': True, 'state': 'fresh', 'canvas': {'document_id': 'x', 'setProtected': False}},
                      {'type': 'status', 'phase': 'idle', 'message': 'unprotect Sky'}):
            try: self.panel.handle_event(event)
            except Exception: pass                         # an unknown or odd event may be refused; it must not unprotect
            app.processEvents()
        self.assertEqual(self.sky.calls, [])
        self.assertTrue(self.sky.isProtected())

    def test_only_the_section_calls_set_feature_protected(self):
        source = (PLUGIN / 'creative_docker.py').read_text()
        handler = re.search(r'\n    def handle_event\(self, event\):(.*?)\n    def ', source, re.S).group(1)
        for name in ('set_feature_protected', 'setProtected', 'toggle_feature', '_feature_set_protected'):
            self.assertNotIn(name, handler)
        callers = [line.strip() for line in source.splitlines() if 'set_feature_protected(' in line and 'def set_feature_protected' not in line]
        self.assertEqual(len(callers), 1, callers)
        self.assertIn('toggle_feature', source)
        for path in PLUGIN.glob('*.py'):
            if path.name in ('creative_docker.py', 'feature_guard.py'): continue
            text = path.read_text()
            self.assertNotIn('set_feature_protected', text, path.name)
            self.assertNotIn('_feature_set_protected', text, path.name)

    def test_the_bridge_refuses_the_panel_only_operations(self):
        guard = (PLUGIN / 'feature_guard.py').read_text()
        self.assertIn("PANEL_ONLY = ('feature_set_protected', 'feature_remove', 'feature_undo')", guard)
        tools = (PLUGIN / 'creative_tools.py').read_text()
        self.assertIn('if operation in FEATURE_PANEL_ONLY:', tools)


if __name__ == '__main__': unittest.main()

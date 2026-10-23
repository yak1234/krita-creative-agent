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

state = types.SimpleNamespace(document=None, open=None)    # open: the documents Krita has, when not only the active one


class Instance:
    tools = []                                             # tool actions triggered, by name
    activeDocument = staticmethod(lambda: state.document)
    action = staticmethod(lambda name: types.SimpleNamespace(trigger=lambda: Instance.tools.append(name)))
    documents = staticmethod(lambda: list(state.open) if state.open is not None else [state.document] if state.document else [])
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
    def _protect_set_state(self, doc, area_id, value):
        for area in self.areas:
            if area['id'] == area_id: area['state'] = value
    def _protect_remove(self, doc, area_id): self.areas = [a for a in self.areas if a['id'] != area_id]


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

    def test_areas_the_agent_proposed_are_listed_while_they_wait(self):
        # element-scoped-painting 3: "No features yet" must not show while the artist has proposals to answer.
        doc = self.open()
        moon = {'id': 'm', 'name': 'Moon', 'state': 'pending', 'by': 'agent', 'bounds': [0, 0, 10, 10]}
        self.panel.protection.areas.append(moon)
        self.panel.handle_event({'type': 'protection_proposed', 'area': moon}); app.processEvents()   # listed at once, not at the next poll
        self.assertFalse(self.section.empty.isVisible())
        self.assertEqual([(r['name'], r['kind'].text()) for r in self.section.pending_rows], [('Moon', 'proposed, waiting for you')])
        self.assertTrue(self.section.pending_rows[0]['widget'].isVisible())
        self.assertEqual(self.section.rows, [], 'a proposal is not a feature box')
        # Locked layers and kept areas are not proposals.
        self.panel.protection.areas.append({'id': 'locked-layers', 'name': 'Locked layers', 'state': 'active', 'by': 'automatic', 'count': 1})
        self.panel.answer_protection(moon, 'discard'); app.processEvents()
        self.assertEqual(self.section.pending_rows, [])
        self.assertTrue(self.section.empty.isVisible())
        # Features and proposals together: both listed.
        doc.list.append(Feature('Sky'))
        self.panel.protection.areas.append(dict(moon, id='m2'))
        self.panel.poll_canvas_metadata(); app.processEvents()
        self.assertEqual(names(self.panel), ['Sky'])
        self.assertEqual([r['name'] for r in self.section.pending_rows], ['Moon'])
        self.assertFalse(self.section.empty.isVisible())

    def test_kept_agent_areas_are_listed_as_protected(self):
        # Review: a proposal that vanished from the list on Keep would read as lost protection.
        self.open()
        moon = {'id': 'm', 'name': 'Moon', 'state': 'pending', 'by': 'agent', 'bounds': [0, 0, 10, 10]}
        self.panel.protection.areas += [moon, {'id': 'locked-layers', 'name': 'Locked layers', 'state': 'active', 'by': 'automatic', 'count': 1}]
        self.panel.handle_event({'type': 'protection_proposed', 'area': moon}); app.processEvents()
        self.panel.answer_protection(moon, 'keep'); app.processEvents()
        self.assertEqual([(r['name'], r['kind'].text()) for r in self.section.pending_rows], [('Moon', 'protected')])
        self.assertFalse(self.section.empty.isVisible())

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


class Sel:
    """A Krita Selection: bounds, and duplicate() a copy carrying the same label."""
    def __init__(self, label, bounds=(0, 0, 0, 0)): self.label, self.bounds = label, tuple(bounds)
    def x(self): return self.bounds[0]
    def y(self): return self.bounds[1]
    def width(self): return self.bounds[2]
    def height(self): return self.bounds[3]
    def duplicate(self): return Sel(self.label, self.bounds)


class AdjustDocument(ForkDocument):
    def __init__(self):
        super().__init__(); self.active_node = 'painting-layer'; self.set_selections = []
    def activeNode(self): return self.active_node
    def setActiveNode(self, node): self.active_node = node
    def setSelection(self, value): self.set_selections.append(value); self.selected = value


class AdjustProtection(FakeProtection):
    """protection.py's panel calls for one proposed area whose mask holds the selection 'proposal'."""
    def __init__(self):
        super().__init__(); self.calls = []
        self.mask = types.SimpleNamespace(selection=lambda: Sel('proposal', (10, 10, 50, 40)), setSelection=lambda value: self.calls.append(('mask', value.label)))
        self.areas = [{'id': 'm', 'name': 'Buildings', 'state': 'pending', 'by': 'agent', 'bounds': [10, 10, 50, 40]}]
    def _protect_mask_node(self, doc, area_id): return self.mask if area_id == 'm' else None
    def _protect_set_bounds(self, doc, area_id, bounds): self.calls.append(('bounds', area_id, list(bounds)))
    def _protect_set_state(self, doc, area_id, value): self.calls.append(('state', area_id, value)); super()._protect_set_state(doc, area_id, value)
    def _protect_editing(self, doc, on): self.calls.append(('editing', on))
    def _protect_remove(self, doc, area_id): self.calls.append(('remove', area_id)); super()._protect_remove(doc, area_id)


class AdjustWithSelectionTools(unittest.TestCase):
    """element-scoped-painting 2: Adjust on a proposed area loads it as the document selection and hands the artist the
    Freehand Selection Tool (the Magnetic one a click away), never the brush. Done writes the selection back into the
    area; Cancel leaves it; the artist's own selection comes back either way."""
    def setUp(self):
        Instance.tools.clear()
        self.panel = module.CreativeAgentDocker(); self.panel.resize(440, 820); self.panel.show()
        self.panel.protection = self.protection = AdjustProtection()
        self.doc = state.document = AdjustDocument()
        self.panel.handle_event({'type': 'protection_proposed', 'area': dict(self.protection.areas[0])})

    def tearDown(self):
        self.panel.close(); KEEP.append(self.panel)
        for _ in range(4): app.processEvents()
        state.document = None; Instance.tools.clear()

    def adjust(self):
        buttons = {b.text(): b for b in self.panel.protection_controls}
        buttons['Adjust'].click(); app.processEvents()

    def test_adjust_loads_the_area_and_hands_over_the_freehand_selection_tool(self):
        self.doc.selected = Sel('artist', (0, 0, 5, 5))
        self.adjust()
        self.assertEqual(Instance.tools, ['KisToolSelectOutline'], 'the Freehand Selection Tool, never the brush')
        self.assertEqual(self.doc.selected.label, 'proposal', 'the proposal is the document selection')
        self.assertTrue(self.panel.protection_bar.isVisible())
        self.assertIn('Buildings', self.panel.protection_bar_label.text())
        self.assertNotIn('mask', self.panel.protection_bar_label.text().lower())
        self.assertTrue(self.panel.protection_tool_button.isVisible())
        self.assertNotIn(('editing', True), self.protection.calls, 'a selection is changed, not the mask painted')

    def test_done_writes_the_selection_back_and_restores_the_artists_selection(self):
        self.doc.selected = Sel('artist', (0, 0, 5, 5))
        self.adjust()
        self.doc.selected = Sel('changed', (20, 5, 30, 60))          # the artist reshaped it with a selection tool
        self.panel.finish_protection(True)
        self.assertIn(('mask', 'changed'), self.protection.calls)
        self.assertIn(('bounds', 'm', [20, 5, 30, 60]), self.protection.calls)
        self.assertIn(('state', 'm', 'active'), self.protection.calls)
        self.assertEqual(self.doc.selected.label, 'artist', 'the artist\'s earlier selection is back')
        self.assertFalse(self.panel.protection_bar.isVisible())
        self.assertIsNone(self.panel.protection_editing)
        self.assertEqual([r['kind'].text() for r in self.panel.features_section.pending_rows], ['protected'], 'kept: no longer waiting')

    def test_cancel_leaves_the_area_and_clears_a_selection_the_artist_did_not_have(self):
        self.adjust()
        self.doc.selected = Sel('changed', (20, 5, 30, 60))
        self.panel.finish_protection(False)
        self.assertFalse([c for c in self.protection.calls if c[0] in ('mask', 'bounds', 'state')], 'the area is unchanged')
        self.assertIsNone(self.doc.selected, 'no earlier selection: cleared')
        self.assertFalse(self.panel.protection_bar.isVisible())

    def test_done_with_nothing_selected_keeps_the_bar_open(self):
        self.adjust()
        self.doc.selected = None
        self.panel.finish_protection(True)
        self.assertEqual(self.panel.status.text(), 'Select an area first.')
        self.assertTrue(self.panel.protection_bar.isVisible())
        self.assertIsNotNone(self.panel.protection_editing)
        self.assertFalse([c for c in self.protection.calls if c[0] in ('mask', 'bounds', 'state')])
        self.doc.selected = Sel('changed', (1, 1, 4, 4)); self.panel.finish_protection(True)
        self.assertIn(('mask', 'changed'), self.protection.calls)

    def test_the_bar_switches_to_the_magnetic_selection_tool_and_back(self):
        self.adjust()
        button = self.panel.protection_tool_button
        button.click()
        self.assertEqual(Instance.tools, ['KisToolSelectOutline', 'KisToolSelectMagnetic'])
        button.click()
        self.assertEqual(Instance.tools[-1], 'KisToolSelectOutline')
        self.panel.finish_protection(False)
        self.assertFalse(self.panel.protection_bar.isVisible())

    def test_adjust_waits_while_the_agent_paints(self):
        self.doc.selected = Sel('artist', (0, 0, 5, 5))
        self.panel.handle_event({'type': 'busy', 'busy': True})
        self.adjust()
        self.assertEqual(Instance.tools, [])
        self.assertEqual(self.doc.selected.label, 'artist', 'the artist\'s selection is untouched')
        self.assertFalse(self.panel.protection_bar.isVisible())
        self.assertIn('Pause', self.panel.status.text())
        self.assertTrue(all(b.isEnabled() for b in self.panel.protection_controls), 'the artist can answer again later')

    def test_done_and_cancel_act_on_the_painting_adjusted_not_the_active_one(self):
        # Review I2: the artist switched to another document while adjusting.
        self.doc.selected = Sel('artist', (0, 0, 5, 5))
        self.adjust()
        other = AdjustDocument(); other.selected = Sel('other', (1, 1, 2, 2))
        state.open = [self.doc, other]; state.document = other
        self.doc.selected = Sel('changed', (20, 5, 30, 60))
        self.panel.finish_protection(True)
        self.assertIn(('mask', 'changed'), self.protection.calls)
        self.assertEqual(self.doc.selected.label, 'artist')
        self.assertEqual((other.selected.label, other.set_selections), ('other', []), 'the other document is never touched')
        state.open = None

    def test_a_closed_painting_just_closes_the_bar(self):
        self.adjust()
        other = AdjustDocument(); state.open = [other]; state.document = other
        self.panel.finish_protection(True)
        self.assertFalse(self.panel.protection_bar.isVisible())
        self.assertIsNone(self.panel.protection_editing)
        self.assertFalse([c for c in self.protection.calls if c[0] in ('mask', 'bounds', 'state')])
        self.assertEqual(other.set_selections, [])
        state.open = None

    def test_agent_commands_are_held_while_adjusting(self):
        # Review I3: the bridge refuses agent writes while this is set (creative_tools.cmd_creative).
        held = sys.modules['panel_features_test.command_queue'].artist_editing
        self.adjust()
        self.assertTrue(held.is_set())
        self.panel.finish_protection(False)
        self.assertFalse(held.is_set())

    def test_done_and_cancel_wait_for_an_open_agent_move(self):
        self.doc.selected = Sel('artist', (0, 0, 5, 5))
        self.adjust()
        self.doc.selected = Sel('changed', (20, 5, 30, 60))
        self.doc.move_open = True
        for keep in (True, False):
            self.panel.finish_protection(keep)
            self.assertIn('Pause', self.panel.status.text())
            self.assertTrue(self.panel.protection_bar.isVisible())
            self.assertEqual(self.doc.selected.label, 'changed', 'nothing written inside the agent move')
        self.assertFalse([c for c in self.protection.calls if c[0] in ('mask', 'bounds', 'state')])
        self.doc.move_open = False
        self.panel.finish_protection(True)
        self.assertIn(('mask', 'changed'), self.protection.calls)

    def test_discard_waits_for_an_open_agent_move_and_keep_does_not(self):
        self.doc.move_open = True
        buttons = {b.text(): b for b in self.panel.protection_controls}
        buttons['Discard'].click(); app.processEvents()
        self.assertNotIn(('remove', 'm'), self.protection.calls)
        self.assertIn('Pause', self.panel.status.text())
        self.assertTrue(all(b.isEnabled() for b in self.panel.protection_controls))
        buttons['Keep'].click(); app.processEvents()
        self.assertIn(('state', 'm', 'active'), self.protection.calls)

    def test_a_refused_adjust_shows_the_area_in_red_again(self):
        self.panel.handle_event({'type': 'busy', 'busy': True})
        self.adjust()
        self.assertIs(self.doc.active_node, self.protection.mask)

    def test_paint_over_it_still_hands_over_the_brush(self):
        self.panel.paint_protection({'id': 'm', 'name': 'Buildings'})
        self.assertEqual(Instance.tools, ['KritaShape/KisToolBrush'])
        self.assertFalse(self.panel.protection_tool_button.isVisible(), 'no selection tools while painting a shape')
        self.panel.finish_protection(False)


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



class ShapesModelPrompt(unittest.TestCase):
    """Element shapes (src/shapes/chat.ts): before the one-time model download the panel shows its size and waits for the
    artist's answer, which it sends as the shapes_model command; the companion downloads nothing without it."""
    def setUp(self):
        state.document = None
        self.commands = []
        self.panel = module.CreativeAgentDocker(); self.panel.resize(440, 820); self.panel.show()
        self.panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running,
                                                   write=lambda data: self.commands.append(json.loads(data)))
        self.event = {'type': 'shapes_model_needed', 'model': 'sam2.1-hiera-base-plus', 'revision': 'bab1', 'size_mb': 328, 'licence': 'Apache-2.0',
                      'message': 'Finding the exact shape of an element needs a one-time download of its model, SAM 2.1 base-plus (328 MB). Download it now?'}

    def tearDown(self):
        self.panel.process = None; self.panel.close(); KEEP.append(self.panel)
        for _ in range(4): app.processEvents()

    def buttons(self): return [button.text() for button in self.panel.shapes_model_controls]

    def test_the_question_shows_the_size_and_accept_sends_the_answer_once(self):
        self.panel.handle_event(self.event)
        self.assertIn('328 MB', self.panel.transcript.messages[-1]['text'])
        self.assertEqual(self.buttons(), ['Download (328 MB)', 'Not now'])
        self.panel.shapes_model_controls[0].click()
        self.assertEqual(self.commands, [{'type': 'shapes_model', 'action': 'accept'}])
        self.assertTrue(all(not button.isEnabled() for button in self.panel.shapes_model_controls), 'answered once')

    def test_not_now_declines_for_the_chat_and_ask_again_allows_it(self):
        self.panel.handle_event(self.event)
        self.panel.shapes_model_controls[1].click()
        self.assertEqual(self.commands, [{'type': 'shapes_model', 'action': 'decline'}])
        again = self.panel.shapes_allow_button
        self.assertEqual(again.text(), 'Ask again')
        self.assertTrue(again.isEnabled())
        again.click()
        self.assertEqual(self.commands[-1], {'type': 'shapes_model', 'action': 'enable'})
        self.assertFalse(again.isEnabled(), 'sent once')

    def test_ready_and_progress_are_shown_and_nothing_is_sent_by_itself(self):
        self.panel.handle_event({'type': 'status', 'phase': 'downloading', 'message': 'Downloading the shape model: 40% of 328 MB…'})
        self.assertIn('40%', self.panel.status.text())
        self.panel.handle_event({'type': 'shapes_model_ready', 'model': 'sam2.1-hiera-base-plus', 'revision': 'bab1'})
        self.assertIn('shape model', self.panel.status.text())
        self.panel.handle_event({'type': 'shape_timing', 'kind': 'shape', 'ms': 19, 'peak_mb': 1600, 'provider': 'cpu'})
        self.assertEqual(self.commands, [])

    def test_the_artist_reads_shape_not_mask(self):
        source = (PLUGIN / 'creative_docker.py').read_text()
        block = source[source.index("kind == 'shapes_model_needed'"):source.index("kind == 'shapes_model_ready'")]
        self.assertNotIn('mask', block.lower())


# The "/" menu (skill-commands.ts): the companion sends the commands in its skills event, so the panel names no skill.
import subprocess
SKILLS_EVENT = json.loads(subprocess.run(['node', '-e', "import('./src/skills.mjs').then(m=>process.stdout.write(JSON.stringify(m.skillsEvent())))"],
    cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, check=True, env={**os.environ, 'NODE_OPTIONS': ''}).stdout)
from panel_features_test.qt_compat import QKeyEvent, QEvent, Qt


class SlashMenu(unittest.TestCase):
    def setUp(self):
        state.document = None
        self.panel = module.CreativeAgentDocker(); self.panel.resize(440, 820); self.panel.show()
        self.panel.handle_event(SKILLS_EVENT)
        self.menu = self.panel.slash_menu; self.prompt = self.panel.prompt

    def tearDown(self):
        self.panel.process = None; self.panel.close(); KEEP.append(self.panel)
        for _ in range(4): app.processEvents()

    def rows(self): return [self.menu.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.menu.count())]
    def key(self, key): self.prompt.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

    def test_typing_a_slash_lists_the_short_commands_then_every_skill(self):
        self.prompt.setPlainText('/')
        self.assertTrue(self.menu.isVisible())
        self.assertEqual(self.rows(), [entry['command'] for entry in SKILLS_EVENT['commands']])
        self.assertEqual(self.rows()[:3], ['/trace', '/colour', '/refine'])
        self.assertIn('/skill:guided-trace', self.rows())
        self.assertIn('Draw guides', self.menu.item(0).text(), 'each entry shows its one-line description')

    def test_the_list_filters_by_command_and_alias(self):
        self.prompt.setPlainText('/col'); self.assertEqual(self.rows(), ['/colour'])
        self.prompt.setPlainText('/color'); self.assertEqual(self.rows(), ['/colour'], 'an alias finds its command')
        self.prompt.setPlainText('/skill:paint'); self.assertEqual(self.rows(), ['/skill:paint-scene', '/skill:paint-sky'])
        self.prompt.setPlainText('/x'); self.assertFalse(self.menu.isVisible())
        self.prompt.setPlainText('trace /'); self.assertFalse(self.menu.isVisible(), 'only at the start of the input')

    def test_arrows_then_enter_or_tab_insert_and_escape_closes(self):
        self.prompt.setPlainText('/'); self.key(Qt.Key.Key_Down)
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.prompt.toPlainText(), '/colour ')
        self.assertFalse(self.menu.isVisible())
        self.prompt.setPlainText('/tr'); self.key(Qt.Key.Key_Tab)
        self.assertEqual(self.prompt.toPlainText(), '/trace ')
        self.prompt.setPlainText('/'); self.assertTrue(self.menu.isVisible())
        self.key(Qt.Key.Key_Escape)
        self.assertFalse(self.menu.isVisible()); self.assertEqual(self.prompt.toPlainText(), '/')

    def test_choosing_an_entry_inserts_it(self):
        self.prompt.setPlainText('/skill:guid')
        self.panel.choose_skill(self.menu.item(0))
        self.assertEqual(self.prompt.toPlainText(), '/skill:guided-trace ')
        self.assertFalse(self.menu.isVisible())

    def test_the_panel_lists_exactly_the_commands_the_companion_sends(self):
        self.panel.handle_event({'type': 'skills', 'skills': [{'name': 'zap-sky', 'description': 'A made-up skill.'}],
                                 'commands': [{'command': '/zap', 'aliases': ['/zip'], 'description': 'A made-up command.'},
                                              {'command': '/skill:zap-sky', 'aliases': [], 'description': 'A made-up skill.'}]})
        self.prompt.setPlainText('/')
        self.assertEqual(self.rows(), ['/zap', '/skill:zap-sky'], 'only what the companion sent: the panel adds no skill of its own')
        self.prompt.setPlainText('/zi'); self.assertEqual(self.rows(), ['/zap'])

    def test_an_older_companion_sends_skills_only_and_they_list_as_skill_commands(self):
        self.panel.handle_event({'type': 'skills', 'skills': [{'name': 'paint-sky', 'description': 'Paint a sky.'}]})
        self.prompt.setPlainText('/')
        self.assertEqual(self.rows(), ['/skill:paint-sky'])
        self.prompt.setPlainText('/pa'); self.assertEqual(self.rows(), ['/skill:paint-sky'], 'the bare skill name finds it')
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.prompt.toPlainText(), '/skill:paint-sky ')

    def test_typing_matches_whatever_the_case(self):
        self.prompt.setPlainText('/TR'); self.assertEqual(self.rows(), ['/trace'])

    def test_enter_sends_when_the_menu_is_closed(self):
        sent = []
        self.prompt.submitted.connect(lambda: sent.append(self.prompt.toPlainText()))
        self.prompt.setPlainText('/trace the moon'); self.assertFalse(self.menu.isVisible())
        self.key(Qt.Key.Key_Return)
        self.assertEqual(sent, ['/trace the moon'])
        self.prompt.setPlainText('/trace'); self.assertTrue(self.menu.isVisible())
        self.key(Qt.Key.Key_Return)
        self.assertEqual(sent, ['/trace the moon'], 'Enter on an open menu inserts the command, it does not send')
        self.assertEqual(self.prompt.toPlainText(), '/trace ')
        self.assertFalse(self.menu.isVisible())


if __name__ == '__main__': unittest.main()

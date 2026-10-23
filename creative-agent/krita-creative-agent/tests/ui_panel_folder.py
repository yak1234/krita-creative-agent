"""Run: uv run -q --with pyqt5 python tests/ui_panel_folder.py (and --with pyqt6). A UI script like ui_panel_no_document:
it stubs krita for the whole process. Project folder B2/B3: the attach menu opens a folder, the folder card shows the goal,
the elements and what was skipped, editing an element's name sends folder_guess, the plan bar names the current element.
No dialog opens (the folder chooser is replaced) and no profile is touched (Qt's test mode for standard paths)."""
import json
import os
from pathlib import Path
import sys
import types
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['KRITA_CREATIVE_NO_AUTOSTART'] = '1'
import importlib.util

PLUGIN = Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
package = types.ModuleType('panel_folder_test'); package.__path__ = [str(PLUGIN)]; sys.modules['panel_folder_test'] = package
from panel_folder_test.qt_compat import QApplication, QDockWidget, QStandardPaths, Qt
QStandardPaths.setTestModeEnabled(True)


class Instance:
    activeDocument = staticmethod(lambda: None)
    documents = staticmethod(lambda: [])
    addDockWidgetFactory = staticmethod(lambda factory: None)


stub = types.ModuleType('krita'); stub.DockWidget = QDockWidget
stub.DockWidgetFactory = object; stub.DockWidgetFactoryBase = types.SimpleNamespace(DockRight=2)
stub.Krita = types.SimpleNamespace(instance=lambda: Instance)
stub.Selection = object
sys.modules['krita'] = stub
spec = importlib.util.spec_from_file_location('panel_folder_test.creative_docker', PLUGIN / 'creative_docker.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
app = QApplication.instance() or QApplication([])
QProcess = module.QProcess

INDEX = {'root': '/folders/new_moscow', 'name': 'new_moscow',
         'goal': {'name': 'final_goal.png', 'width': 1448, 'height': 1086, 'role': 'goal', 'guess': 'Goal image'},
         'elements': [{'name': 'assets/%02d-%s.png' % (i + 1, slug), 'guess': guess, 'number': i + 1, 'role': 'element', 'width': 8, 'height': 6}
                      for i, (slug, guess) in enumerate([('moonlit-sky', 'Moonlit sky'), ('historic-buildings', 'Historic buildings'), ('lamps-and-trees', 'Lamps and trees')])],
         'others': [{'name': 'finished_review.png'}, {'name': 'skies.png'}],
         'texts': [{'name': 'ART_BRIEF.md', 'kind': 'brief', 'chars': 120}],
         'skipped': [{'name': 'old.kra', 'reason': 'a Krita document or other painting file (not read)'}, {'name': 'run.py', 'reason': 'a script or program (not run)'},
                     {'name': 'sky.webp', 'reason': 'WebP is not supported yet'}]}


class PanelFolder(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.panel = module.CreativeAgentDocker(); self.panel.resize(440, 820); self.panel.show()
        self.panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running,
                                                   write=lambda data: self.commands.append(json.loads(data)))
        self.panel.handle_event({'type': 'ready', 'models': [{'provider': 'openrouter', 'id': 'm', 'name': 'M', 'configured': True}],
                                 'bridge': {}, 'build': {'version': '1', 'build_id': 'b'}})
        self.commands.clear()

    def tearDown(self):
        self.panel.process = None; self.panel.close(); self.panel.deleteLater()
        for _ in range(4): app.processEvents()

    def test_the_attach_menu_has_open_project_folder(self):
        actions = [action.text() for action in self.panel.attach_menu.actions()]
        self.assertIn('Open project folder…', actions)
        chosen = []
        original = module.QFileDialog.getExistingDirectory
        module.QFileDialog.getExistingDirectory = staticmethod(lambda *args, **kwargs: chosen.append(args) or '/folders/new_moscow')
        try:
            next(a for a in self.panel.attach_menu.actions() if a.text() == 'Open project folder…').trigger()
        finally:
            module.QFileDialog.getExistingDirectory = original
        self.assertEqual(len(chosen), 1)
        self.assertEqual(self.commands, [{'type': 'open_folder', 'path': '/folders/new_moscow'}])

    def test_a_folder_event_shows_the_goal_the_elements_and_the_skipped_count(self):
        self.assertFalse(self.panel.folder_card.isVisible())
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {'final_goal.png': 'reference-1'}})
        self.assertTrue(self.panel.folder_card.isVisible())
        self.assertIn('new_moscow', self.panel.folder_title.text())
        self.assertIn('final_goal.png', self.panel.folder_goal.text())
        items = [self.panel.folder_elements.item(i) for i in range(self.panel.folder_elements.count())]
        self.assertEqual([item.text() for item in items], ['Moonlit sky', 'Historic buildings', 'Lamps and trees'])
        self.assertIn('assets/01-moonlit-sky.png', items[0].toolTip())
        footer = self.panel.folder_footer.text()
        self.assertIn('3 elements', footer); self.assertIn('2 other images', footer); self.assertIn('3 skipped', footer)
        self.assertIn('WebP is not supported yet', self.panel.folder_footer.toolTip())
        self.assertIn('skies.png', self.panel.folder_footer.toolTip())
        self.assertEqual(self.commands, [], 'showing the folder sends nothing')
        self.panel.new_chat()
        self.assertFalse(self.panel.folder_card.isVisible(), 'a new chat starts without the folder')

    def test_editing_a_guess_sends_folder_guess(self):
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {}})
        item = self.panel.folder_elements.item(1)
        self.assertTrue(item.flags() & Qt.ItemFlag.ItemIsEditable)
        item.setText('  Towers and walls ')
        self.assertEqual(self.commands, [{'type': 'folder_guess', 'name': 'assets/02-historic-buildings.png', 'guess': 'Towers and walls'}])
        item.setText('')
        self.assertEqual(len(self.commands), 1, 'an empty name is not sent')
        self.assertEqual(item.text(), 'Towers and walls', 'and the name is put back')

    def test_folder_references_stay_out_of_the_reference_tiles(self):
        references = [{'id': 'r%d' % i, 'path': '/chat/r%d.png' % i, 'name': 'e%d.png' % i, 'role': 'asset', 'source': 'folder', 'folder_name': 'e%d.png' % i} for i in range(5)]
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': references})
        self.assertFalse(self.panel.attachments.isVisible(), 'the folder card shows them; the four reference slots stay free')

    def test_the_plan_bar_names_the_current_element_and_the_ticks(self):
        brief = {'title': 'New Moscow', 'objective': 'o', 'requirements': [], 'freedom': [], 'completion': ['c'],
                 'steps': [{'title': 'Block-in', 'done_when': 'd', 'scope': 'whole composition'},
                           {'title': 'Moonlit sky', 'done_when': 'd', 'scope': 'assets/01-moonlit-sky.png'}]}
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'paused', 'brief': brief, 'current_step': 1, 'done_steps': [0]}, 'mode': 'agent', 'references': []})
        text = self.panel.plan_summary.text()
        self.assertIn('Moonlit sky', text); self.assertIn('01-moonlit-sky.png', text); self.assertIn('1 of 2 done', text)


    def test_file_names_are_shown_as_text_and_a_long_folder_says_what_the_plan_leaves_out(self):
        index = dict(INDEX, goal=dict(INDEX['goal'], name='<b>goal</b>.png'),
                     elements=[{'name': '%02d-<i>e</i>.png' % (i + 1), 'guess': 'E%d' % i, 'number': i + 1} for i in range(17)],
                     skipped=[{'name': '<img src=x>.kra', 'reason': 'a Krita document'}])
        self.panel.handle_event({'type': 'folder', 'index': index, 'references': {}, 'plan_limit': 15})
        self.assertEqual(self.panel.folder_goal.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn('<b>goal</b>.png', self.panel.folder_goal.text())
        self.assertIn('&lt;img src=x&gt;.kra', self.panel.folder_footer.toolTip(), 'tooltips escape file names')
        self.assertIn('&lt;i&gt;', self.panel.folder_elements.item(0).toolTip())
        self.assertIn('the plan takes the first 15', self.panel.folder_footer.text())

    def mass_thumbnail(self):
        """A small PNG in a temporary folder, removed when the test ends."""
        import tempfile
        from panel_folder_test.qt_compat import QImage, QColor
        folder = tempfile.TemporaryDirectory(prefix='panel-masses-'); self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, 'masses.png')
        image = QImage(160, 120, QImage.Format.Format_RGB32); image.fill(QColor('#203050')); image.save(path)
        return path

    def test_a_whole_picture_reference_shows_its_mass_map_beside_it(self):
        thumbnail = self.mass_thumbnail()
        summary = '5 masses, largest first: 40% dark cool blue top'
        references = [{'id': 'r1', 'path': thumbnail, 'name': 'goal.png', 'role': 'reference', 'purpose': 'general',
                       'mass_map': {'thumbnail': thumbnail, 'summary': summary, 'masses': 5}},
                      {'id': 'r2', 'path': thumbnail, 'name': 'palette.png', 'role': 'reference', 'purpose': 'palette'}]
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': references})
        maps = self.panel.attachments.findChildren(module.QLabel, 'massMap')
        self.assertEqual(len(maps), 1, 'only the reference with a mass map')
        self.assertFalse(maps[0].pixmap().isNull())
        self.assertLessEqual(maps[0].pixmap().width(), 72)
        self.assertIn('40% dark cool blue top', maps[0].toolTip())
        self.assertIn('Mass map', maps[0].toolTip())

    def test_the_folder_goal_shows_its_mass_map_on_the_folder_card(self):
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {'final_goal.png': 'reference-1'}})
        self.assertFalse(self.panel.folder_masses.isVisible(), 'none yet')
        thumbnail = self.mass_thumbnail()
        goal = {'id': 'reference-1', 'path': thumbnail, 'name': 'final_goal.png', 'role': 'reference', 'source': 'folder',
                'folder_name': 'final_goal.png', 'mass_map': {'thumbnail': thumbnail, 'summary': '<b>6</b> masses', 'masses': 6}}
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': [goal]})
        self.assertTrue(self.panel.folder_masses.isVisible())
        self.assertFalse(self.panel.folder_masses.pixmap().isNull())
        self.assertIn('&lt;b&gt;6', self.panel.folder_masses.toolTip(), 'the summary is text')
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': []})
        self.assertFalse(self.panel.folder_masses.isVisible())

    def test_a_new_chat_and_a_new_folder_drop_the_old_mass_map(self):
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {'final_goal.png': 'reference-1'}})
        thumbnail = self.mass_thumbnail()
        goal = {'id': 'reference-1', 'path': thumbnail, 'name': 'final_goal.png', 'role': 'reference', 'source': 'folder',
                'folder_name': 'final_goal.png', 'mass_map': {'thumbnail': thumbnail, 'summary': 'six masses', 'masses': 6}}
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': [goal]})
        self.assertTrue(self.panel.folder_masses.isVisible())
        self.panel.attached_references = []                     # another folder, before its references arrive
        self.panel.handle_event({'type': 'folder', 'index': dict(INDEX, name='other'), 'references': {}})
        self.assertFalse(self.panel.folder_masses.isVisible(), 'a new folder does not show the old goal\'s mass map')
        self.assertTrue(self.panel.folder_masses.pixmap() is None or self.panel.folder_masses.pixmap().isNull())
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': [goal]})
        self.assertTrue(self.panel.folder_masses.isVisible())
        self.panel.new_chat()
        self.assertFalse(self.panel.folder_masses.isVisible())
        self.assertTrue(self.panel.folder_masses.pixmap() is None or self.panel.folder_masses.pixmap().isNull())
        self.assertEqual(self.panel.folder_masses.toolTip(), '')

if __name__ == '__main__':
    unittest.main()

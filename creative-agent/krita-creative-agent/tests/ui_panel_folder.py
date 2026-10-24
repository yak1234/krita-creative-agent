"""Run: uv run -q --with pyqt5 python tests/ui_panel_folder.py (and --with pyqt6). A UI script like ui_panel_no_document:
it stubs krita for the whole process. Project folder B2/B3: the attach menu opens a folder, the Folder tab's card shows the
goal, the elements (until the plan lists them) and what was skipped, editing an element's name sends folder_guess, the plan
bar names the current element; a whole picture's masses show as a flat colour bar with a plain sentence.
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
        # processEvents() never runs a deleteLater posted outside an event loop: without this the panel lived on, its timers
        # firing, while the collector freed its Python side, and the script crashed at random at exit.
        module.QCoreApplication.sendPostedEvents(None, module.QEvent.Type.DeferredDelete)

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
        self.assertFalse(self.panel.tabs.isTabVisible(self.panel.folder_tab))
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {'final_goal.png': 'reference-1'}})
        self.assertTrue(self.panel.tabs.isTabVisible(self.panel.folder_tab))
        self.panel.tabs.setCurrentIndex(self.panel.folder_tab)
        self.assertTrue(self.panel.folder_card.isVisible())
        self.assertIn('new_moscow', self.panel.folder_title.text())
        self.assertEqual(self.panel.folder_goal_choice.currentText(), 'final_goal.png')
        items = [self.panel.folder_elements.item(i) for i in range(self.panel.folder_elements.count())]
        self.assertEqual([item.text() for item in items], ['Moonlit sky', 'Historic buildings', 'Lamps and trees'])
        self.assertIn('assets/01-moonlit-sky.png', items[0].toolTip())
        footer = self.panel.folder_footer.text()
        self.assertIn('3 element images', footer); self.assertIn('2 other images', footer); self.assertIn('3 skipped', footer)
        self.assertIn('WebP is not supported yet', self.panel.folder_footer.toolTip())
        self.assertIn('skies.png', self.panel.folder_footer.toolTip())
        self.assertEqual(self.commands, [], 'showing the folder sends nothing')
        self.panel.new_chat()
        self.assertFalse(self.panel.folder_card.isVisible(), 'a new chat starts without the folder')
        self.assertFalse(self.panel.tabs.isTabVisible(self.panel.folder_tab))

    def test_the_element_list_shows_every_row_until_the_plan_lists_them(self):
        index = dict(INDEX, elements=[{'name': 'e%02d.png' % i, 'guess': 'Element %d' % i, 'number': i} for i in range(12)])
        self.panel.handle_event({'type': 'folder', 'index': index, 'references': {}})
        self.panel.tabs.setCurrentIndex(self.panel.folder_tab); app.processEvents()
        elements = self.panel.folder_elements
        self.assertTrue(elements.isVisible())
        self.assertEqual(elements.verticalScrollBar().maximum(), 0, 'no scroll bar inside the Folder tab')
        brief = {'title': 'T', 'objective': 'o', 'requirements': [], 'freedom': [], 'completion': ['c'], 'steps': [{'title': 'Element 0', 'done_when': 'd'}]}
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'ready', 'brief': brief}, 'mode': 'agent', 'references': [],
                                 'plan_steps': [{'index': 0, 'key': 'k', 'title': 'Element 0', 'state': 'open'}]})
        self.assertFalse(elements.isVisible(), 'the plan lists them: not twice')

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
        # (a goal event without plan_steps, as an older companion sends: the header says the step itself)
        text = self.panel.plan_summary.text()
        self.assertIn('Moonlit sky', text); self.assertIn('01-moonlit-sky.png', text); self.assertIn('1 of 2 done', text)


    def test_file_names_are_shown_as_text_and_a_long_folder_says_what_the_plan_leaves_out(self):
        index = dict(INDEX, goal=dict(INDEX['goal'], name='<b>goal</b>.png'),
                     elements=[{'name': '%02d-<i>e</i>.png' % (i + 1), 'guess': 'E%d' % i, 'number': i + 1} for i in range(17)],
                     skipped=[{'name': '<img src=x>.kra', 'reason': 'a Krita document'}])
        self.panel.handle_event({'type': 'folder', 'index': index, 'references': {}, 'plan_limit': 15})
        self.assertEqual(self.panel.folder_goal.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(self.panel.folder_goal_choice.currentText(), '<b>goal</b>.png', 'a list item is text')
        self.assertIn('&lt;img src=x&gt;.kra', self.panel.folder_footer.toolTip(), 'tooltips escape file names')
        self.assertIn('&lt;i&gt;', self.panel.folder_elements.item(0).toolTip())
        self.assertIn('the plan takes the first 15', self.panel.folder_footer.text())

    MASS_MAP = {'summary': '30 masses, largest first: 40% dark cool blue top [x 0-100%, y 0-41%]', 'masses': 30, 'version': 2,
                'colours': [{'colour': '#1b2a44', 'share': 0.5}, {'colour': '#2b2f36', 'share': 0.3}, {'colour': '#f2d79a', 'share': 0.2}],
                'overview': 'Mostly dark cool blue at the top and dark grey at the bottom, with a light warm yellow spot at the top right.'}

    def goal_image(self):
        """A small PNG in a temporary folder, removed when the test ends."""
        import tempfile
        from panel_folder_test.qt_compat import QImage, QColor
        folder = tempfile.TemporaryDirectory(prefix='panel-masses-'); self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, 'final_goal.png')
        image = QImage(160, 120, QImage.Format.Format_RGB32); image.fill(QColor('#203050')); image.save(path)
        return path

    def test_a_whole_picture_reference_shows_its_masses_as_a_colour_bar_beside_it(self):
        path = self.goal_image()
        references = [{'id': 'r1', 'path': path, 'name': 'goal.png', 'role': 'reference', 'purpose': 'general', 'mass_map': self.MASS_MAP},
                      {'id': 'r2', 'path': path, 'name': 'palette.png', 'role': 'reference', 'purpose': 'palette'}]
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': references})
        bars = self.panel.attachments.findChildren(module.MassBar, 'massMap')
        self.assertEqual(len(bars), 1, 'only the reference with a mass map')
        self.assertEqual([c.name() for c, _ in bars[0].colours], ['#1b2a44', '#2b2f36', '#f2d79a'])
        self.assertLessEqual(bars[0].width(), 72)
        tip = bars[0].toolTip()
        self.assertIn('light warm yellow spot', tip)
        self.assertNotIn('%', tip); self.assertNotIn('[x', tip, "the painter's coordinates are not the artist's tooltip")

    def test_the_folder_goal_shows_its_masses_and_its_picture_on_the_folder_card(self):
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {'final_goal.png': 'reference-1'}})
        self.panel.tabs.setCurrentIndex(self.panel.folder_tab)
        self.assertFalse(self.panel.folder_masses.isVisible(), 'none yet')
        path = self.goal_image()
        goal = {'id': 'reference-1', 'path': path, 'name': 'final_goal.png', 'role': 'reference', 'source': 'folder',
                'folder_name': 'final_goal.png', 'mass_map': dict(self.MASS_MAP, overview='<b>Mostly</b> blue at the top.')}
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': [goal]})
        self.assertTrue(self.panel.folder_masses.isVisible())
        self.assertEqual(len(self.panel.folder_masses.colours), 3)
        self.assertIn('&lt;b&gt;Mostly', self.panel.folder_masses.toolTip(), 'the sentence is text')
        self.assertTrue(self.panel.folder_mass_text.isVisible())
        self.assertEqual(self.panel.folder_mass_text.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn('<b>Mostly</b> blue at the top.', self.panel.folder_mass_text.text())
        self.assertTrue(self.panel.folder_picture.isVisible()); self.assertFalse(self.panel.folder_picture.pixmap().isNull())
        self.assertEqual(self.panel.findChildren(module.QLabel, 'massMap'), [], 'no outline picture any more')
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': []})
        self.assertFalse(self.panel.folder_masses.isVisible()); self.assertFalse(self.panel.folder_mass_text.isVisible())

    def test_an_older_mass_map_without_colours_shows_nothing(self):
        path = self.goal_image()
        goal = {'id': 'reference-1', 'path': path, 'name': 'final_goal.png', 'role': 'reference', 'source': 'folder', 'folder_name': 'final_goal.png',
                'mass_map': {'version': 1, 'thumbnail': path, 'summary': '6 masses, largest first: 40% dark cool blue top [x 0-100%]', 'masses': 6}}
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {'final_goal.png': 'reference-1'}})
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': [goal]})
        self.panel.tabs.setCurrentIndex(self.panel.folder_tab)
        self.assertFalse(self.panel.folder_masses.isVisible()); self.assertEqual(self.panel.folder_masses.toolTip(), '')

    def test_a_new_chat_and_a_new_folder_drop_the_old_mass_map(self):
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {'final_goal.png': 'reference-1'}})
        self.panel.tabs.setCurrentIndex(self.panel.folder_tab)
        path = self.goal_image()
        goal = {'id': 'reference-1', 'path': path, 'name': 'final_goal.png', 'role': 'reference', 'source': 'folder',
                'folder_name': 'final_goal.png', 'mass_map': self.MASS_MAP}
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': [goal]})
        self.assertTrue(self.panel.folder_masses.isVisible())
        self.panel.attached_references = []                     # another folder, before its references arrive
        self.panel.handle_event({'type': 'folder', 'index': dict(INDEX, name='other'), 'references': {}})
        self.assertFalse(self.panel.folder_masses.isVisible(), 'a new folder does not show the old goal\'s mass map')
        self.assertEqual(self.panel.folder_masses.colours, []); self.assertFalse(self.panel.folder_picture.isVisible())
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': [goal]})
        self.assertTrue(self.panel.folder_masses.isVisible())
        self.panel.new_chat()
        self.assertFalse(self.panel.folder_masses.isVisible())
        self.assertEqual(self.panel.folder_masses.colours, [])
        self.assertEqual(self.panel.folder_masses.toolTip(), '')

    # Goal picker and Sharpen goal (goal-image change, 2026-10-24).
    def test_the_goal_list_holds_every_folder_image_and_choosing_one_sends_folder_goal(self):
        index = dict(INDEX, goal_choices=['final_goal.png'] + [e['name'] for e in INDEX['elements']] + ['finished_review.png', 'skies.png'])
        self.panel.handle_event({'type': 'folder', 'index': index, 'references': {}})
        self.panel.tabs.setCurrentIndex(self.panel.folder_tab)
        choice = self.panel.folder_goal_choice
        self.assertTrue(choice.isVisible()); self.assertTrue(choice.isEnabled())
        self.assertEqual([choice.itemText(i) for i in range(choice.count())], index['goal_choices'])
        self.assertEqual(choice.currentText(), 'final_goal.png')
        self.assertEqual(self.commands, [], 'filling the list sends nothing')
        choice.setCurrentIndex(choice.findData('assets/02-historic-buildings.png'))
        self.assertEqual(self.commands, [{'type': 'folder_goal', 'name': 'assets/02-historic-buildings.png'}])
        self.panel.handle_event({'type': 'busy', 'busy': True})
        self.assertFalse(choice.isEnabled(), 'not while the painter reads it')
        self.panel.handle_event({'type': 'busy', 'busy': False})
        self.assertTrue(choice.isEnabled())
        older = dict(INDEX); older.pop('goal_choices', None)            # an older companion: built from the index
        self.panel.handle_event({'type': 'folder', 'index': older, 'references': {}})
        self.assertEqual(choice.count(), 1 + 3 + 2)
        none = dict(INDEX, goal=None)
        self.panel.handle_event({'type': 'folder', 'index': none, 'references': {}})
        self.assertEqual(choice.currentIndex(), -1); self.assertIn('No goal image found', self.panel.folder_goal.text())

    def test_the_folder_card_says_what_happened_to_a_small_goal(self):
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {}, 'goal_sharpen': {'state': 'offered', 'factor': 4.1}})
        self.panel.tabs.setCurrentIndex(self.panel.folder_tab)
        self.assertIn('4.1x smaller than the canvas: sharpening is offered', self.panel.folder_goal.text())
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {},
                                 'goal_sharpen': {'state': 'used', 'sharpened': {'width': 2309, 'height': 1732, 'full': [5792, 4344]}}})
        self.assertIn('Sharpened 4x on this computer (5792 x 4344); the painter reads it at 2309 x 1732', self.panel.folder_goal.text())
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {}})
        self.assertFalse(self.panel.folder_goal.isVisible(), 'nothing to say')

    def test_the_sharpen_offer_and_the_side_by_side_are_cards_whose_buttons_answer_once(self):
        self.panel.handle_event({'type': 'goal_sharpen_offer', 'id': 'o1', 'options': ['Sharpen', 'Use as is'],
                                 'message': 'Your goal image is 4.1x smaller than the canvas, so detail will blur. Sharpen it 4x on this Mac (about 15 s, nothing uploaded)?'})
        offer = list(self.panel.sharpen_controls)
        self.assertEqual([b.text() for b in offer], ['Sharpen', 'Use as is'])
        offer[0].click()
        self.assertEqual(self.commands, [{'type': 'goal_sharpen', 'id': 'o1', 'action': 'sharpen'}])
        self.assertFalse(any(b.isEnabled() for b in offer), 'answered once')
        path = self.goal_image()
        self.panel.handle_event({'type': 'goal_sharpen_review', 'id': 'o1', 'image_path': path, 'options': ['Use sharpened', 'Keep original'],
                                 'question': 'Sharpened 4x. Left: your goal image enlarged; right: sharpened. Use the sharpened goal?'})
        review = list(self.panel.sharpen_controls)
        self.assertEqual([b.text() for b in review], ['Use sharpened', 'Keep original'])
        pictures = [label for label in self.panel.transcript.findChildren(module.QLabel, 'questionImage') if label.pixmap() is not None and not label.pixmap().isNull()]
        self.assertTrue(pictures, 'the side by side is shown on the card')
        review[1].click()
        self.assertEqual(self.commands[-1], {'type': 'goal_sharpen', 'id': 'o1', 'action': 'keep'})

    def test_sharpening_shows_on_the_now_card_with_cancel_and_goes_when_it_ends(self):
        self.assertFalse(self.panel.plan_steps.now.isVisible())
        self.panel.handle_event({'type': 'goal_sharpen_progress', 'id': 'o1', 'done': 77, 'total': 154, 'message': 'Sharpening the goal image: 50%…'})
        app.processEvents()
        self.assertTrue(self.panel.plan_steps.now.isVisible(), 'the Now card shows it even with no plan yet')
        self.assertTrue(self.panel.sharpen_row.isVisible())
        self.assertEqual(self.panel.sharpen_bar.value(), 500)
        self.assertEqual(self.panel.sharpen_text.text(), 'Sharpening the goal image: 50%…')
        self.panel.sharpen_cancel.click()
        self.assertEqual(self.commands, [{'type': 'goal_sharpen', 'action': 'cancel'}])
        self.assertFalse(self.panel.sharpen_cancel.isEnabled())
        self.panel.handle_event({'type': 'goal_sharpen_progress', 'id': 'o1', 'done': 0, 'total': 0, 'finished': True, 'message': ''})
        self.assertFalse(self.panel.sharpen_row.isVisible()); self.assertFalse(self.panel.plan_steps.now.isVisible())
        self.panel.handle_event({'type': 'goal_sharpen_progress', 'id': 'o2', 'done': 1, 'total': 10, 'message': 'Downloading the sharpening model: 10% of 62 MB…'})
        self.assertTrue(self.panel.sharpen_cancel.isEnabled(), 'a new run can be cancelled again')
        self.panel.new_chat()
        self.assertFalse(self.panel.sharpen_row.isVisible())

    def test_a_sharpened_goal_s_thumbnails_come_from_its_picture_before(self):
        self.assertEqual(module.CreativeAgentDocker.picture_path({'path': '/c/x4.png', 'sharpened': {'from': {'path': '/c/goal.png'}}}), '/c/goal.png')
        self.assertEqual(module.CreativeAgentDocker.picture_path({'path': '/c/goal.png'}), '/c/goal.png')
        self.assertEqual(module.CreativeAgentDocker.picture_path(None), '')
        self.panel.handle_event({'type': 'folder', 'index': INDEX, 'references': {'final_goal.png': 'reference-1'}})
        path = self.goal_image()
        goal = {'id': 'reference-1', 'path': '/nonexistent/x4.png', 'name': 'final_goal.png', 'role': 'reference', 'source': 'folder',
                'folder_name': 'final_goal.png', 'sharpened': {'from': {'path': path}}}
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': [goal]})
        self.panel.tabs.setCurrentIndex(self.panel.folder_tab)
        self.assertEqual(self.panel.folder_picture_path, path)
        self.assertFalse(self.panel.folder_picture.pixmap().isNull())

if __name__ == '__main__':
    unittest.main()

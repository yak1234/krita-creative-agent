"""Run: uv run -q --with pyqt5 python tests/ui_panel_canvas_reference.py (and --with pyqt6). A UI script like
ui_panel_auto_approve: it stubs krita for the whole process. The canvas reference card (canvas-reference.ts; the artist,
2026-10-25: "not make the edits but make a reference generation of what the edit would look like"): the canvas and the
reference side by side in one picture, the card's notes (the change's share, a warning when it changed a lot, where the
canvas was sent) always visible, and Use as the target / Use as the new goal / Try again / Discard, each sending the card's answer once. It is
never answered by Auto-approve, even set to Immediately. The clock is faked; the picture is written to a temporary
folder that is removed. No dialog opens and no profile is touched (Qt's test mode for standard paths)."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['KRITA_CREATIVE_NO_AUTOSTART'] = '1'
import importlib.util

PLUGIN = Path(__file__).resolve().parents[2] / 'krita-mcp/krita-plugin/kritamcp'
package = types.ModuleType('panel_reference_test'); package.__path__ = [str(PLUGIN)]; sys.modules['panel_reference_test'] = package
from panel_reference_test.qt_compat import QApplication, QDockWidget, QStandardPaths, QPushButton, QLabel, QImage, QColor, QObject
from panel_reference_test import auto_approve
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
spec = importlib.util.spec_from_file_location('panel_reference_test.creative_docker', PLUGIN / 'creative_docker.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
app = QApplication.instance() or QApplication([])
QProcess = module.QProcess

FIELD = {'key': 'auto_approve', 'label': 'Auto-approve', 'accessible': 'Auto-approve', 'tooltip': 't', 'note': '', 'control': 'combo',
         'options': [{'value': 'off', 'label': 'Off'}, {'value': 0, 'label': 'Immediately'}, {'value': 10, 'label': '10 s'},
                     {'value': 30, 'label': '30 s'}, {'value': 60, 'label': '60 s'}]}
OPTIONS = ['Use as the target', 'Use as the new goal', 'Try again', 'Discard']
ACTIONS = ['use', 'goal', 'retry', 'discard']
MESSAGE = ('A reference of “add more ghosts”: the canvas (left) and the reference (right). The change covers 18% of the canvas, '
           'outlined in red. Nothing is painted until you use it.\n\nYour canvas was sent to ChatGPT (your Codex sign-in) to make this picture.')


class Rules(unittest.TestCase):
    def test_the_canvas_reference_is_never_offered(self):
        class Owner(QObject):
            def show_auto_status(self, text): pass
            def auto_answered(self, card): pass
        owner = Owner(); auto = auto_approve.AutoApprove(owner, clock=lambda: 0.0); auto.set_delay(0)
        self.assertIn('canvas_reference', auto_approve.NEVER)
        self.assertFalse(auto.offer('ref:r1', 'canvas_reference', 'use', 'Using', 'x', lambda panel: None))
        self.assertFalse(auto.counting())


class PanelCanvasReference(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='ui-canvas-reference-')
        self.picture = os.path.join(self.folder, 'compare.png')
        image = QImage(408, 150, QImage.Format.Format_RGB32); image.fill(QColor(90, 110, 160)); image.save(self.picture)
        self.commands = []; self.now = [1000.0]
        self.panel = module.CreativeAgentDocker(); self.panel.resize(320, 900); self.panel.show()
        self.panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running,
                                                   write=lambda data: self.commands.append(json.loads(data)))
        self.panel.auto_approve.clock = lambda: self.now[0]
        self.panel.handle_event({'type': 'ready', 'models': [{'provider': 'openrouter', 'id': 'm', 'name': 'M', 'configured': True}],
                                 'bridge': {}, 'build': {'version': '1', 'build_id': 'b'}})
        self.panel.handle_event({'type': 'settings_schema', 'fields': [FIELD]})
        self.panel.handle_event({'type': 'execution_settings', 'settings': {'auto_approve': 0, 'reasoning': 'auto'}})   # Immediately
        self.commands.clear()

    def tearDown(self):
        self.panel.process = None; self.panel.close(); self.panel.deleteLater()
        for _ in range(4): app.processEvents()
        module.QCoreApplication.sendPostedEvents(None, module.QEvent.Type.DeferredDelete)
        shutil.rmtree(self.folder, ignore_errors=True)

    def card(self, **extra):
        event = dict({'type': 'canvas_reference', 'id': 'r1', 'title': 'Canvas reference', 'message': MESSAGE, 'image_path': self.picture,
                      'options': OPTIONS, 'actions': ACTIONS, 'share': 0.18, 'wide': False, 'auto_approve': False}, **extra)
        self.panel.handle_event(event); app.processEvents()
        return [b for b in self.panel.canvas_reference_controls]

    def wait(self, seconds):
        self.now[0] += seconds; self.panel.auto_approve.tick(); app.processEvents()

    def texts(self):
        return [label.text() for label in self.panel.findChildren(QLabel) if label.isVisible()]

    def test_the_card_shows_both_pictures_its_notes_and_its_answers(self):
        buttons = self.card()
        self.assertEqual([b.text() for b in buttons], OPTIONS)
        pictures = [l for l in self.panel.findChildren(QLabel) if l.objectName() == 'questionImage' and l.isVisible()]
        self.assertTrue(pictures and not pictures[-1].pixmap().isNull(), 'the side-by-side picture')
        shown = '\n'.join(self.texts())
        self.assertIn('18% of the canvas', shown)
        self.assertIn('Your canvas was sent to ChatGPT', shown, 'the upload notice is always visible, not folded away')

    def test_auto_approve_never_answers_it(self):
        self.card()
        self.wait(0); self.wait(120)
        self.assertEqual([c for c in self.commands if c['type'] in ('canvas_reference', 'auto_approved')], [])
        self.assertFalse([t for t in self.texts() if t.startswith('Auto-approve:')])

    def test_each_answer_is_sent_once(self):
        for action, index in (('use', 0), ('goal', 1), ('retry', 2), ('discard', 3)):
            self.commands.clear()
            buttons = self.card(id='r-' + action)
            buttons[index].click(); app.processEvents()
            self.assertEqual([c for c in self.commands if c['type'] == 'canvas_reference'], [{'type': 'canvas_reference', 'id': 'r-' + action, 'action': action}])
            self.assertTrue(all(not b.isEnabled() for b in buttons), 'answered once')

    def test_a_wide_change_is_warned_about(self):
        self.card(message=MESSAGE.split('\n\n')[0] + '\n\nThe model changed a lot (72% of the canvas): try a narrower instruction, or name an area (… in the sky).', wide=True)
        self.assertTrue(any('changed a lot' in t for t in self.texts()))

    def test_no_change_offers_only_try_again_and_discard(self):
        buttons = self.card(options=['Try again', 'Discard'], actions=['retry', 'discard'])
        self.assertEqual([b.text() for b in buttons], ['Try again', 'Discard'])
        buttons[0].click()
        self.assertEqual(self.commands[-1], {'type': 'canvas_reference', 'id': 'r1', 'action': 'retry'})


if __name__ == '__main__':
    unittest.main()

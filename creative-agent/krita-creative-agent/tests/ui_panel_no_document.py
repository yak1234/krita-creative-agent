"""Run: uv run -q --with pyqt5 python tests/ui_panel_no_document.py (a UI script like ui_smoke; it stubs krita for the whole process).
The panel with no document open (task 4.1): registration, empty state, first prompt, open and close."""
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
package = types.ModuleType('panel_nodoc_test'); package.__path__ = [str(PLUGIN)]; sys.modules['panel_nodoc_test'] = package
from panel_nodoc_test.qt_compat import QApplication, QDockWidget

state = types.SimpleNamespace(document=None, error=None, factories=[])


def active_document():
    if state.error: raise state.error
    return state.document


class Instance:
    activeDocument = staticmethod(active_document)
    documents = staticmethod(lambda: [state.document] if state.document else [])
    addDockWidgetFactory = staticmethod(lambda factory: state.factories.append(factory))


class Factory:
    def __init__(self, identifier, position, cls): self.identifier, self.position, self.cls = identifier, position, cls


stub = types.ModuleType('krita'); stub.DockWidget = QDockWidget
stub.DockWidgetFactory = Factory; stub.DockWidgetFactoryBase = types.SimpleNamespace(DockRight=2)
stub.Krita = types.SimpleNamespace(instance=lambda: Instance)
stub.Selection = object
sys.modules['krita'] = stub
spec = importlib.util.spec_from_file_location('panel_nodoc_test.creative_docker', PLUGIN / 'creative_docker.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
app = QApplication.instance() or QApplication([])
QProcess = module.QProcess


def fake_document(name=''):
    return types.SimpleNamespace(fileName=lambda: name, modified=lambda: False, width=lambda: 800, height=lambda: 600)


class PanelWithoutDocument(unittest.TestCase):
    def setUp(self):
        state.document, state.error = None, None
        self.commands = []
        self.panel = module.CreativeAgentDocker(); self.panel.resize(440, 820); self.panel.show()
        self.panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running,
                                                   write=lambda data: self.commands.append(json.loads(data)))
        self.panel.handle_event({'type': 'ready', 'models': [{'provider': 'openrouter', 'id': 'm', 'name': 'M', 'configured': True}],
                                 'bridge': {}, 'build': {'version': '1', 'build_id': 'b'}})
        self.panel.poll_canvas_metadata()
        self.commands.clear()

    def tearDown(self):
        self.panel.process = None; self.panel.close(); self.panel.deleteLater()
        for _ in range(4): app.processEvents()
        # processEvents() never runs a deleteLater posted outside an event loop: without this the panel lived on, its timers
        # firing, while the collector freed its Python side, and the script crashed at random at exit.
        module.QCoreApplication.sendPostedEvents(None, module.QEvent.Type.DeferredDelete)

    def test_the_docker_registers_on_the_right_without_needing_a_document(self):
        state.factories.clear()
        module.register_creative_docker()
        factory, = state.factories
        self.assertEqual((factory.identifier, factory.position, factory.cls), ('krita_creative_agent', 2, module.CreativeAgentDocker))

    def test_empty_state_invites_a_painting(self):
        self.assertTrue(self.panel.empty_state.isVisible())
        text = self.panel.no_document_label.text()
        self.assertTrue(self.panel.no_document_label.isVisible())
        self.assertTrue(text.startswith('Start a painting'), text)
        self.assertIn('open one', text)
        self.assertEqual(self.panel.chat_mode, 'agent', 'with nothing to discuss the chat starts in Agent')
        self.assertTrue(self.panel.canvas_width.isEnabled() and self.panel.canvas_height.isEnabled())
        self.assertEqual(self.panel.source.currentData(), 'current')

    def test_first_prompt_creates_a_new_painting(self):
        self.panel.prompt.setPlainText('a winter street in Moscow at night')
        self.panel.submit()
        command, = [c for c in self.commands if c['type'] == 'start']
        self.assertEqual(command['mode'], 'new')
        self.assertEqual((command['width'], command['height']), (768, 1024))
        self.assertEqual(command['chat_mode'], 'agent')
        self.assertEqual(command['name'], 'A winter street in Moscow at night')
        self.assertNotIn('document_id', command['canvas'])

    def test_a_name_the_artist_typed_is_kept(self):
        self.panel.name.setText('Moscow')
        self.panel.prompt.setPlainText('a winter street in Moscow at night'); self.panel.submit()
        self.assertEqual([c for c in self.commands if c['type'] == 'start'][0]['name'], 'Moscow')

    def test_an_open_document_is_still_the_default_target(self):
        state.document = fake_document('/tmp/x.kra')
        self.panel.poll_canvas_metadata()
        self.assertFalse(self.panel.no_document_label.isVisible())
        self.assertEqual(self.panel.chat_mode, 'ask', 'the automatic Agent choice is undone when a painting opens')
        self.panel.prompt.setPlainText('what do you see?'); self.panel.submit()
        command, = [c for c in self.commands if c['type'] == 'start']
        self.assertEqual(command['mode'], 'current')
        self.assertFalse(self.panel.canvas_width.isEnabled())

    def test_the_artists_own_mode_choice_survives_documents_opening_and_closing(self):
        self.panel.mode_selector.setCurrentIndex(self.panel.mode_selector.findData('plan'))
        state.document = fake_document(); self.panel.poll_canvas_metadata()
        state.document = None; self.panel.poll_canvas_metadata()
        self.assertEqual(self.panel.chat_mode, 'plan')

    def test_a_deleted_document_object_counts_as_no_document(self):
        state.error = RuntimeError('wrapped C/C++ object has been deleted')
        self.assertFalse(self.panel.has_open_document())
        self.panel.poll_canvas_metadata(); self.panel.canvasChanged(None); self.panel.update_controls()
        self.panel.prompt.setPlainText('a pond'); self.panel.submit()
        self.assertEqual([c for c in self.commands if c['type'] == 'start'][0]['mode'], 'new')

    def test_closing_the_last_document_in_a_chat_does_not_raise(self):
        state.document = fake_document('/tmp/x.kra'); self.panel.poll_canvas_metadata()
        self.panel.study_active = True
        self.panel.painting_target = {'document_id': 'canvas-1', 'filename': '/tmp/x.kra', 'bound': True, 'mode': 'new'}
        self.panel.goal = {'status': 'paused', 'brief': None}
        state.document = None
        self.panel.poll_canvas_metadata(); self.panel.refresh_document_state(); self.panel.update_controls(); self.panel.render_target()
        self.assertIn('closed', self.panel.status.text().lower())
        self.assertFalse(self.panel.no_document_label.isVisible(), 'a running chat keeps its transcript, not the invitation')

    def test_a_new_chat_without_a_document_is_the_empty_state_again(self):
        self.panel.mode_selector.setCurrentIndex(self.panel.mode_selector.findData('plan'))
        self.panel.new_chat()
        self.assertTrue(self.panel.no_document_label.isVisible())
        self.assertEqual(self.panel.chat_mode, 'agent')

    def test_closing_the_only_painting_then_sending_at_once_creates_a_new_one(self):
        state.document = fake_document('/tmp/x.kra'); self.panel.poll_canvas_metadata()
        self.panel.handle_event({'type': 'context', 'selected': True, 'follow_active': True, 'state': 'fresh',
                                 'canvas': {'document_id': 'canvas-1', 'name': 'x', 'filename': '/tmp/x.kra'}})
        self.assertTrue(self.panel.has_open_document())
        state.document = None
        self.assertFalse(self.panel.has_open_document(), 'a stale canvas context must not outvote Krita')
        self.panel.canvasChanged(None)
        self.assertEqual(self.panel.canvas_context.get('state'), 'none')
        self.panel.prompt.setPlainText('a pond'); self.panel.chat_mode = 'agent'; self.panel.submit()
        self.assertEqual([c for c in self.commands if c['type'] == 'start'][0]['mode'], 'new')

    def test_the_closed_message_is_said_once_on_the_transition(self):
        state.document = fake_document('/tmp/x.kra'); self.panel.poll_canvas_metadata()
        self.panel.study_active = True
        state.document = None; self.panel.poll_canvas_metadata()
        self.assertIn('closed', self.panel.status.text())
        self.panel.status.setText('Waiting for the model')
        self.panel.poll_canvas_metadata(); self.panel.poll_canvas_metadata()
        self.assertEqual(self.panel.status.text(), 'Waiting for the model')

    def test_ask_and_plan_do_not_create_a_painting(self):
        for mode in ('ask', 'plan'):
            self.commands.clear()
            self.panel.mode_selector.setCurrentIndex(self.panel.mode_selector.findData(mode))
            self.assertFalse(self.panel.canvas_width.isEnabled(), mode)
            self.panel.prompt.setPlainText('how do I paint snow?'); self.panel.submit()
            self.assertEqual([c for c in self.commands if c['type'] == 'start'][0]['mode'], 'current', mode)
            self.panel.study_active = False


if __name__ == '__main__': unittest.main()

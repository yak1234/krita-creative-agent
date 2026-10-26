"""Run: uv run -q --with pyqt5 python tests/ui_panel_custom_effects.py (and --with pyqt6). A UI script like
ui_panel_canvas_reference: it stubs krita for the whole process. Custom effects in the panel (openspec custom-effects):
the build's card (effects/build.ts) shows the canvas beside the canvas with the new effect and Keep / Try again / Discard,
each sending the card's answer once; after Keep the companion sends the card again with Remove effect. Auto-approve
presses Keep, never sooner than 20 s whatever its delay (10 s: at 20 s; 30 s: at 30 s), and says so (`auto: true`). A
companion that stops or restarts takes the open card's buttons away: its build records lived only in that process. The
setting is one checkbox, "Custom effects (experimental)", with Reset custom effects… beside it, which asks first and
sends reset_effects only on Yes (the question is stubbed: no dialog opens). The clock is faked; the picture is written to
a temporary folder that is removed. No profile is touched (Qt's test mode for standard paths)."""
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
package = types.ModuleType('panel_effects_test'); package.__path__ = [str(PLUGIN)]; sys.modules['panel_effects_test'] = package
from panel_effects_test.qt_compat import QApplication, QDockWidget, QStandardPaths, QPushButton, QLabel, QImage, QColor, QCheckBox
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
spec = importlib.util.spec_from_file_location('panel_effects_test.creative_docker', PLUGIN / 'creative_docker.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
app = QApplication.instance() or QApplication([])
QProcess = module.QProcess

AUTO = {'key': 'auto_approve', 'label': 'Auto-approve', 'accessible': 'Auto-approve', 'tooltip': 't', 'note': '', 'control': 'combo',
        'options': [{'value': 'off', 'label': 'Off'}, {'value': 0, 'label': 'Immediately'}, {'value': 10, 'label': '10 s'},
                    {'value': 30, 'label': '30 s'}, {'value': 60, 'label': '60 s'}]}
TOOLTIP = ('Off by default. When painting an effect fails twice, Toska builds a new effect from tested building blocks and asks you to keep it. '
           'Keep it, try again or discard it; Reset removes all your own effects.')
CONFIRM = 'Remove all your own effects? Fog and snow stay. This cannot be undone.'
EFFECTS = {'key': 'custom_effects', 'label': 'Custom effects (experimental)', 'accessible': 'Custom effects', 'tooltip': TOOLTIP, 'note': '',
           'control': 'checkbox', 'options': [{'value': False, 'label': 'Off'}, {'value': True, 'label': 'Paint effects from the effect library'}],
           'button': {'label': 'Reset custom effects…', 'command': {'type': 'reset_effects'}, 'confirm': CONFIRM}}
MESSAGE = ('A new effect for “rain over the street”: the canvas (left) and the canvas with it (right), on a small copy; nothing is painted.'
           '\n\nLuna chose B of 2, seeing only your words and the pictures.\n\nKeep adds “rain” to your effects and the painter can use it at once.')
KEPT = 'Kept “rain”: it is in your effects and the painter can use it now. Remove effect takes it out of the library; paint it already made stays (Undo removes that).'


class PanelCustomEffects(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='ui-custom-effects-')
        self.picture = os.path.join(self.folder, 'compare.png')
        image = QImage(408, 150, QImage.Format.Format_RGB32); image.fill(QColor(90, 110, 160)); image.save(self.picture)
        self.commands = []; self.now = [1000.0]; self.asked = []; self.answer = False
        self.panel = module.CreativeAgentDocker(); self.panel.resize(320, 900); self.panel.show()
        self.panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running,
                                                   write=lambda data: self.commands.append(json.loads(data)))
        self.panel.auto_approve.clock = lambda: self.now[0]
        self.panel.confirm = lambda title, text: self.asked.append((title, text)) or self.answer   # never a real dialog
        self.ready()
        self.panel.handle_event({'type': 'settings_schema', 'fields': [AUTO, EFFECTS]})
        self.settings('off')
        self.commands.clear()

    def tearDown(self):
        self.panel.process = None; self.panel.close(); self.panel.deleteLater()
        for _ in range(4): app.processEvents()
        module.QCoreApplication.sendPostedEvents(None, module.QEvent.Type.DeferredDelete)
        shutil.rmtree(self.folder, ignore_errors=True)

    def ready(self):
        self.panel.handle_event({'type': 'ready', 'models': [{'provider': 'openrouter', 'id': 'm', 'name': 'M', 'configured': True}],
                                 'bridge': {}, 'build': {'version': '1', 'build_id': 'b'}})

    def settings(self, auto_approve):
        self.panel.handle_event({'type': 'execution_settings', 'settings': {'auto_approve': auto_approve, 'custom_effects': True, 'reasoning': 'auto'}})

    def card(self, **extra):
        event = dict({'type': 'effect_build', 'id': 'e1', 'title': 'Custom effect', 'message': MESSAGE, 'image_path': self.picture,
                      'options': ['Keep', 'Try again', 'Discard'], 'actions': ['keep', 'retry', 'discard'], 'auto_keep_seconds': None}, **extra)
        self.panel.handle_event(event); app.processEvents()
        return list(self.panel.effect_build_controls)

    def wait(self, seconds):
        self.now[0] += seconds; self.panel.auto_approve.tick(); app.processEvents()

    def texts(self):
        return [label.text() for label in self.panel.findChildren(QLabel) if label.isVisible()]

    def answers(self):
        return [c for c in self.commands if c['type'] in ('effect_build', 'auto_approved')]

    def test_the_card_shows_the_picture_and_keep_try_again_discard_then_remove_effect_after_keep(self):
        buttons = self.card()
        self.assertEqual([b.text() for b in buttons], ['Keep', 'Try again', 'Discard'])
        pictures = [l for l in self.panel.findChildren(QLabel) if l.objectName() == 'questionImage' and l.isVisible()]
        self.assertTrue(pictures and not pictures[-1].pixmap().isNull(), 'the canvas beside the canvas with the effect')
        shown = '\n'.join(self.texts())
        self.assertIn('Luna chose B of 2', shown); self.assertIn('Keep adds “rain”', shown)
        buttons[0].click(); app.processEvents()
        self.assertEqual(self.answers(), [{'type': 'effect_build', 'id': 'e1', 'action': 'keep'}])
        self.assertTrue(all(not b.isEnabled() for b in buttons), 'answered once')
        # The companion sends the card again once the effect is kept: Remove effect only.
        self.commands.clear()
        kept = self.card(message=KEPT, image_path=self.picture, options=['Remove effect'], actions=['remove'])
        self.assertEqual([b.text() for b in kept], ['Remove effect'])
        kept[0].click(); app.processEvents()
        self.assertEqual(self.answers(), [{'type': 'effect_build', 'id': 'e1', 'action': 'remove'}])
        self.assertFalse(kept[0].isEnabled())

    def test_try_again_and_discard_each_send_their_answer_once(self):
        for action, index in (('retry', 1), ('discard', 2)):
            self.commands.clear()
            buttons = self.card(id='e-' + action)
            buttons[index].click(); buttons[index].click(); app.processEvents()
            self.assertEqual(self.answers(), [{'type': 'effect_build', 'id': 'e-' + action, 'action': action}])

    def test_no_effect_found_offers_only_try_again_and_discard(self):
        buttons = self.card(options=['Try again', 'Discard'], actions=['retry', 'discard'])
        self.assertEqual([b.text() for b in buttons], ['Try again', 'Discard'])

    def test_auto_approve_at_10_s_keeps_at_20_s(self):
        self.settings(10); self.commands.clear()
        self.card(auto_keep_seconds=20)
        self.wait(10); self.wait(9.5)
        self.assertEqual(self.answers(), [], 'never before 20 s, whatever the delay')
        self.assertTrue(any(t.startswith('Auto-approve: Keeping in 1 s') for t in self.texts()), 'the countdown shows on the card')
        self.wait(0.5)
        self.assertEqual(self.answers(), [{'type': 'auto_approved', 'kind': 'effect_build', 'answer': 'keep', 'delay': 10, 'card': 'effect:e1'},
                                          {'type': 'effect_build', 'id': 'e1', 'action': 'keep', 'auto': True}])
        self.assertTrue(all(not b.isEnabled() for b in self.panel.effect_build_controls), 'its buttons are answered')
        self.commands.clear()
        self.card(message=KEPT + ' (Auto-approve)', options=['Remove effect'], actions=['remove'])
        self.wait(120)
        self.assertEqual(self.answers(), [], 'Remove effect is never pressed for the artist')

    def test_auto_approve_at_30_s_keeps_at_30_s(self):
        self.settings(30); self.commands.clear()
        self.card(auto_keep_seconds=30)
        self.wait(29.5)
        self.assertEqual(self.answers(), [])
        self.wait(0.5)
        self.assertEqual(self.answers()[-1], {'type': 'effect_build', 'id': 'e1', 'action': 'keep', 'auto': True})

    def test_auto_approve_keeps_no_sooner_than_20_s_when_the_card_names_no_wait(self):
        self.settings(0); self.commands.clear()
        self.card()                                        # auto_keep_seconds null: Auto-approve was off when it was made
        self.wait(19.5)
        self.assertEqual(self.answers(), [])
        self.wait(0.5)
        self.assertEqual(self.answers()[-1], {'type': 'effect_build', 'id': 'e1', 'action': 'keep', 'auto': True})

    def test_a_card_sending_5_s_is_kept_no_sooner_than_20_s(self):
        # The panel's own floor: a card's auto_keep_seconds below 20 never shortens the wait.
        self.settings(0); self.commands.clear()
        self.card(auto_keep_seconds=5)
        self.wait(5); self.wait(14.5)
        self.assertEqual(self.answers(), [], 'never before 20 s, whatever the card says')
        self.wait(0.5)
        self.assertEqual(self.answers()[-1], {'type': 'effect_build', 'id': 'e1', 'action': 'keep', 'auto': True})

    def test_a_move_keeps_its_countdown_while_an_effect_card_counts(self):
        # Nothing waits for the card: a move that arrives while the card counts is kept on its own schedule (10 s), and
        # the card is still kept at its 20 s.
        self.settings(10); self.commands.clear()
        self.card(auto_keep_seconds=20)
        self.wait(2)
        self.panel.handle_event({'type': 'move', 'move': {'number': 1, 'status': 'ready', 'title': 'Snow', 'actions': 2, 'step': None}})
        app.processEvents(); self.wait(0)
        self.wait(9.5)
        self.assertEqual([c for c in self.commands if c['type'] == 'move'], [])
        self.wait(0.5)
        self.assertEqual([c for c in self.commands if c['type'] == 'move'], [{'type': 'move', 'action': 'keep', 'move': 1}],
                         'the move is kept 10 s after it came, while the effect card counts')
        self.assertEqual([c for c in self.commands if c['type'] == 'effect_build'], [])
        self.wait(7.5)
        self.assertEqual([c for c in self.commands if c['type'] == 'effect_build'], [], 'not before its 20 s')
        self.wait(0.5)
        self.assertEqual([c for c in self.commands if c['type'] == 'effect_build'], [{'type': 'effect_build', 'id': 'e1', 'action': 'keep', 'auto': True}],
                         'the effect card is still kept, at 20 s')

    def test_a_card_without_keep_or_with_auto_approve_off_waits(self):
        self.card(id='off')                                # Auto-approve off when the card came: it waits
        self.wait(120)
        self.settings(10); self.commands.clear()
        self.card(id='nothing', options=['Try again', 'Discard'], actions=['retry', 'discard'])
        self.wait(120)
        self.assertEqual(self.answers(), [])

    def test_a_button_pressed_first_stops_the_countdown(self):
        self.settings(10); self.commands.clear()
        buttons = self.card(auto_keep_seconds=20)
        self.wait(5); buttons[2].click(); self.wait(120)
        self.assertEqual(self.answers(), [{'type': 'effect_build', 'id': 'e1', 'action': 'discard'}])

    def test_a_companion_restart_takes_the_open_card_away(self):
        self.settings(10); self.commands.clear()
        buttons = self.card(auto_keep_seconds=20)
        self.panel.process_finished(); app.processEvents()
        self.assertTrue(all(not b.isEnabled() for b in buttons), 'its build record died with the companion')
        self.assertTrue(any('companion restarted' in t for t in self.texts()))
        self.wait(120)
        self.assertEqual(self.answers(), [], 'Auto-approve no longer counts for it')
        buttons = self.card(id='e2')
        self.ready(); app.processEvents()                  # a new companion process answered
        self.assertTrue(all(not b.isEnabled() for b in buttons))
        self.assertEqual(self.panel.effect_build_controls, [])

    def test_the_setting_is_one_checkbox_with_reset_beside_it_asked_first(self):
        box = self.panel.setting_widgets['custom_effects']
        self.assertIsInstance(box, QCheckBox)
        self.assertTrue(box.isChecked()); self.assertEqual(box.toolTip(), TOOLTIP)
        self.assertEqual(self.panel.generic_settings.labelForField(box.parentWidget()).text(), 'Custom effects (experimental)')
        reset = [b for b in box.parentWidget().findChildren(QPushButton) if b.text() == 'Reset custom effects…']
        self.assertEqual(len(reset), 1, 'beside the checkbox')
        self.answer = False; reset[0].click(); app.processEvents()
        self.assertEqual(self.asked, [('Reset custom effects', CONFIRM)])
        self.assertEqual([c for c in self.commands if c['type'] == 'reset_effects'], [], 'No: nothing is sent')
        self.answer = True; reset[0].click(); app.processEvents()
        self.assertEqual([c for c in self.commands if c['type'] == 'reset_effects'], [{'type': 'reset_effects'}])
        self.assertFalse([c for c in self.commands if c['type'] == 'set_execution_settings'], 'Reset is not a settings change')


if __name__ == '__main__':
    unittest.main()

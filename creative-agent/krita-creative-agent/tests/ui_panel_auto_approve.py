"""Run: uv run -q --with pyqt5 python tests/ui_panel_auto_approve.py (and --with pyqt6). A UI script like ui_panel_plan_steps:
it stubs krita for the whole process. Auto-approve (openspec auto-approve; the artist 2026-10-25: "an auto approve mode,
it's standard in agentic systems"): every card that waits for the artist counts down on screen and takes its default
answer after the delay (a finished plan step: Met; a move: Keep; the goal image: Sharpen, then Use sharpened; a question
or close-up only when it marks a recommended option), unless the artist acts first: Undo, Redo, Stop, typing, sending,
any card button or editing the plan. Start painting is never pressed. The clock is faked: no test waits for real.
No dialog opens and no profile is touched (Qt's test mode for standard paths)."""
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
package = types.ModuleType('panel_auto_test'); package.__path__ = [str(PLUGIN)]; sys.modules['panel_auto_test'] = package
from panel_auto_test.qt_compat import QApplication, QDockWidget, QStandardPaths, QPushButton, QLabel
from panel_auto_test import auto_approve
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
spec = importlib.util.spec_from_file_location('panel_auto_test.creative_docker', PLUGIN / 'creative_docker.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
app = QApplication.instance() or QApplication([])
QProcess = module.QProcess

BRIEF = {'title': 'New Moscow', 'objective': 'o', 'requirements': [], 'freedom': [], 'completion': ['c'],
         'steps': [{'title': 'Underpainting from the goal image', 'done_when': 'd'}, {'title': 'Moonlit sky', 'done_when': 'd'}]}
KEYS = ['title:underpainting from the goal image#0', 'file:01-moonlit-sky.png']
# The setting as the companion's settings-schema.mjs declares it (auto-approve.test.mjs checks that side).
FIELD = {'key': 'auto_approve', 'label': 'Auto-approve', 'accessible': 'Auto-approve', 'tooltip': 't', 'note': '', 'control': 'combo',
         'options': [{'value': 'off', 'label': 'Off'}, {'value': 0, 'label': 'Immediately'}, {'value': 10, 'label': '10 s'},
                     {'value': 30, 'label': '30 s'}, {'value': 60, 'label': '60 s'}]}
MERGE = {'key': 'merge_kept', 'label': 'Layers after accepting', 'accessible': 'Layers after accepting', 'tooltip': '', 'note': '', 'control': 'combo',
         'options': [{'value': True, 'label': 'Merge kept passes'}, {'value': False, 'label': 'Keep every pass'}]}
MOVE = {'number': 1, 'status': 'ready', 'title': 'Underpainting', 'actions': 2, 'step': 0}


def steps(*states):
    return [{'index': i, 'key': KEYS[i], 'title': BRIEF['steps'][i]['title'], 'state': state} for i, state in enumerate(states)]


class Rules(unittest.TestCase):
    def test_the_countdown_words(self):
        self.assertEqual(auto_approve.countdown_text('Keeping', 'Undo or type to stop', 41.2), 'Auto-approve: Keeping in 42 s — Undo or type to stop')
        self.assertEqual(auto_approve.countdown_text('Sharpen', 'press a button to stop', 8), 'Auto-approve: Sharpen in 8 s — press a button to stop')
        self.assertEqual(auto_approve.countdown_text('Keeping', 'x', 0), 'Auto-approve: Keeping now')
        self.assertEqual(auto_approve.delay_of('off'), None); self.assertEqual(auto_approve.delay_of(0), 0); self.assertEqual(auto_approve.delay_of(60), 60)
        self.assertEqual(auto_approve.delay_of('30'), None, 'only the values the setting offers'); self.assertEqual(auto_approve.delay_of(True), None)


class PanelAutoApprove(unittest.TestCase):
    def setUp(self):
        self.commands = []; self.now = [1000.0]
        self.panel = module.CreativeAgentDocker(); self.panel.resize(320, 900); self.panel.show()
        self.panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running,
                                                   write=lambda data: self.commands.append(json.loads(data)))
        self.panel.auto_approve.clock = lambda: self.now[0]          # fake time: tick() is called by hand
        self.panel.handle_event({'type': 'ready', 'models': [{'provider': 'openrouter', 'id': 'm', 'name': 'M', 'configured': True}],
                                 'bridge': {}, 'build': {'version': '1', 'build_id': 'b'}})
        self.panel.handle_event({'type': 'settings_schema', 'fields': [MERGE, FIELD]})
        self.commands.clear()

    def tearDown(self):
        self.panel.process = None; self.panel.close(); self.panel.deleteLater()
        for _ in range(4): app.processEvents()
        module.QCoreApplication.sendPostedEvents(None, module.QEvent.Type.DeferredDelete)

    def setting(self, value):
        self.panel.handle_event({'type': 'execution_settings', 'settings': {'merge_kept': True, 'auto_approve': value, 'reasoning': 'auto'}})

    def wait(self, seconds):
        self.now[0] += seconds; self.panel.auto_approve.tick(); app.processEvents()

    def goal(self, rows, status='move_ready', busy=False, **extra):
        if self.panel.busy != busy: self.panel.handle_event({'type': 'busy', 'busy': busy})
        self.panel.handle_event({'type': 'goal', 'goal': dict({'status': status, 'brief': BRIEF, 'current_step': 0}, **extra),
                                 'mode': 'agent', 'references': [], 'plan_steps': rows})
        app.processEvents()

    def finished_step(self):
        self.panel.handle_event({'type': 'move', 'move': MOVE})
        self.goal(steps('finished', 'open'), moves=[MOVE])

    def answers(self):
        return [c for c in self.commands if c['type'] != 'auto_approved']

    def records(self):
        return [{k: v for k, v in c.items() if k != 'type'} for c in self.commands if c['type'] == 'auto_approved']

    def visible_text(self):
        return [label.text() for label in self.panel.findChildren(QLabel) if label.isVisible() and label.text().startswith('Auto-approve:')]

    def test_off_by_default_nothing_is_answered(self):
        self.finished_step()
        self.wait(600)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.visible_text(), [])
        self.assertFalse(self.panel.auto_toggle.isChecked())

    def test_a_finished_plan_step_is_met_after_the_delay_with_a_visible_countdown(self):
        self.setting(30)
        self.finished_step()
        self.wait(0)
        texts = self.visible_text()
        self.assertTrue(texts and all(t == 'Auto-approve: Met in 30 s — Redo or type to stop' for t in texts), texts)
        self.assertIn('Met in 30 s', self.panel.status.text(), 'the status line counts down too')
        self.wait(18)
        self.assertIn('Auto-approve: Met in 12 s — Redo or type to stop', self.visible_text())
        self.assertEqual(self.commands, [])
        self.wait(12)
        self.assertEqual([{k: v for k, v in c.items() if k != 'id'} for c in self.answers()],
                         [{'type': 'plan_step', 'action': 'met', 'step_key': KEYS[0]}], 'the same command as the Met button')
        self.assertEqual(self.records(), [{'kind': 'plan_step', 'answer': 'met', 'delay': 30, 'card': KEYS[0]}])
        self.assertFalse(self.panel.move_bar.isVisible(), 'Met answers the move card too')
        self.assertEqual(self.visible_text(), [])
        self.wait(100)
        self.assertEqual(len(self.answers()), 1, 'answered once')

    def test_any_artist_action_stops_the_countdown_and_the_card_waits(self):
        actions = {'typing': lambda: self.panel.prompt.setPlainText('darker'),
                   'stop': lambda: self.panel.request_stop(),
                   'redo': lambda: self.panel.plan_steps.rows[0]['redo'].click(),
                   'undo': lambda: self.panel.move_undo.click()}
        for name, act in actions.items():
            with self.subTest(name):
                self.commands.clear(); self.panel.auto_approve.forget()
                self.setting(10); self.finished_step(); self.wait(5)
                act(); self.wait(60)
                self.assertFalse([c for c in self.commands if c['type'] in ('auto_approved',) or c.get('action') == 'met'], name)
                self.assertEqual(self.visible_text(), [], name)
                self.goal(steps('finished', 'open'), moves=[MOVE]); self.wait(60)   # a later goal event does not start it again
                self.assertFalse([c for c in self.commands if c['type'] == 'auto_approved'], name)
                self.panel.prompt.clear()

    def test_editing_the_plan_stops_it(self):
        self.setting(10)
        self.panel.handle_event({'type': 'move', 'move': MOVE})
        self.goal(steps('finished', 'open'), moves=[MOVE], limits={'minutes': 0, 'passes': 0})
        self.wait(2)
        original = module.PlanDialog.exec
        module.PlanDialog.exec = lambda dialog: module.QDialog.DialogCode.Rejected   # the dialog opens and is closed unchanged
        try: self.panel.edit_plan()
        finally: module.PlanDialog.exec = original
        self.wait(30); self.assertEqual(self.commands, [])

    def test_a_move_outside_a_plan_is_kept(self):
        self.setting(10)
        self.panel.handle_event({'type': 'move', 'move': dict(MOVE, step=None)})
        self.wait(0)
        self.assertIn('Auto-approve: Keeping in 10 s — Undo or type to stop', self.visible_text())
        self.wait(10)
        self.assertEqual(self.answers(), [{'type': 'move', 'action': 'keep', 'move': 1}])
        self.assertEqual(self.records(), [{'kind': 'move', 'answer': 'keep', 'delay': 10, 'card': 'move:1'}])

    def test_it_waits_while_the_agent_is_busy(self):
        self.setting(10); self.finished_step()
        self.panel.handle_event({'type': 'busy', 'busy': True}); self.wait(60)
        self.assertEqual(self.commands, [], 'Met waits for the move to end, as its button')
        self.panel.handle_event({'type': 'busy', 'busy': False}); self.wait(5)
        self.assertEqual(self.commands, [], 'the countdown starts again when the agent stops')
        self.wait(5)
        self.assertEqual(self.answers()[0]['action'], 'met')

    def test_immediately_answers_at_the_next_tick(self):
        self.setting(0)
        self.panel.handle_event({'type': 'move', 'move': dict(MOVE, step=None)})
        self.assertEqual(self.commands, [], 'never inside the event itself')
        self.wait(0)
        self.assertEqual(self.answers(), [{'type': 'move', 'action': 'keep', 'move': 1}])
        self.assertEqual(self.records()[0]['delay'], 0)

    def test_the_goal_image_is_sharpened_then_the_sharpened_copy_used(self):
        self.setting(10)
        self.panel.handle_event({'type': 'goal_sharpen_offer', 'id': 'g1', 'message': 'Sharpen it?', 'options': ['Sharpen', 'Use as is']})
        self.wait(0)
        self.assertIn('Auto-approve: Sharpen in 10 s — press a button to stop', self.visible_text())
        self.wait(10)
        self.assertEqual(self.answers(), [{'type': 'goal_sharpen', 'id': 'g1', 'action': 'sharpen'}])
        self.panel.handle_event({'type': 'goal_sharpen_review', 'id': 'g1', 'question': 'Use it?', 'options': ['Use sharpened', 'Keep original']})
        self.wait(10)
        self.assertEqual(self.answers()[-1], {'type': 'goal_sharpen', 'id': 'g1', 'action': 'use'})
        self.assertEqual([r['kind'] for r in self.records()], ['sharpen_offer', 'sharpen_review'])

    def test_a_question_is_answered_only_with_its_recommended_option(self):
        self.setting(10)
        self.panel.handle_event({'type': 'question', 'id': 'q1', 'question': 'Which sky?', 'options': ['Warm', 'Cool']})
        self.wait(120)
        self.assertEqual(self.commands, [], 'no recommended option: the card waits for the artist')
        self.panel.handle_event({'type': 'question', 'id': 'q2', 'question': 'Which stages?', 'options': ['The underpainting only', 'The whole plan'],
                                 'recommended': 'The whole plan'})
        self.wait(0)
        self.assertIn('Auto-approve: “The whole plan” in 10 s — press a button or type to stop', self.visible_text())
        self.wait(10)
        prompts = [c for c in self.answers() if c['type'] in ('prompt', 'start')]
        self.assertEqual([c.get('text') or c.get('prompt') for c in prompts], ['The whole plan'], 'the same as pressing the option')
        self.assertEqual(self.records(), [{'kind': 'question', 'answer': 'The whole plan', 'delay': 10, 'card': 'q2'}])

    def test_you_decide_is_found_on_the_card(self):
        self.setting(10)
        self.panel.handle_event({'type': 'question', 'id': 'q3', 'question': 'Which sky?', 'options': ['Warm', 'Cool'], 'recommended': 'You decide'})
        self.wait(10)
        self.assertEqual([c.get('text') or c.get('prompt') for c in self.answers() if c['type'] in ('prompt', 'start')], ['You decide'])

    def test_a_closeup_question_with_its_recommended_option(self):
        self.setting(30)
        self.panel.handle_event({'type': 'closeup_question', 'id': 'c1', 'question': 'Use it?', 'options': ['Use the close-up there', 'Not this close-up'],
                                 'recommended': 'Use the close-up there'})
        self.wait(30)
        self.assertEqual(self.answers(), [{'type': 'closeup_answer', 'question_id': 'c1', 'answer': 'Use the close-up there'}])

    def test_a_move_that_reached_its_size_limit_is_met_in_a_plan_and_kept_outside_one(self):
        self.setting(10)
        limited = dict(MOVE, limited=True)                # "Move 1 reached its size limit: keep it, undo it, or say continue"
        self.panel.handle_event({'type': 'move', 'move': limited})
        self.goal(steps('finished', 'open'), status='limited', moves=[limited])
        self.wait(10)
        self.assertEqual([c['action'] for c in self.answers()], ['met'])
        self.panel.new_chat(); self.commands.clear()
        self.panel.handle_event({'type': 'move', 'move': dict(limited, number=2, step=None)})
        self.wait(10)
        self.assertEqual(self.answers(), [{'type': 'move', 'action': 'keep', 'move': 2}])

    def test_the_select_area_card_finds_the_part(self):
        self.setting(10); self.panel.study_active = True
        self.panel.handle_event({'type': 'question', 'id': 's1', 'question': 'Select the sky: Find it for me outlines it…',
                                 'options': ['Find it for me', 'Select with Freehand', 'Use my selection', 'Paint everywhere'],
                                 'recommended': 'Find it for me', 'select_area': {'part': 'the sky'}})
        self.wait(0)
        self.assertIn('Auto-approve: “Find it for me” in 10 s — press a button or type to stop', self.visible_text())
        self.wait(10)
        self.assertEqual([(c['type'], c['part']) for c in self.answers()], [('find_it', 'the sky')], 'the shapes model outlines it')
        self.assertEqual(self.records()[0]['answer'], 'Find it for me')

    def test_pressing_a_card_button_stops_it(self):
        self.setting(10)
        self.panel.handle_event({'type': 'goal_sharpen_offer', 'id': 'g1', 'message': 'Sharpen it?', 'options': ['Sharpen', 'Use as is']})
        self.wait(3)
        self.panel.sharpen_controls[1].click()
        self.wait(30)
        self.assertEqual(self.answers(), [{'type': 'goal_sharpen', 'id': 'g1', 'action': 'original'}])
        self.assertEqual(self.records(), [])

    def test_never_start_painting_nor_a_destructive_card(self):
        self.setting(0)
        self.goal(steps('open', 'open'), status='ready')
        self.panel.handle_event({'type': 'protection_proposed', 'area': {'name': 'face', 'id': 'a1'}})
        self.panel.handle_event({'type': 'shapes_model_needed', 'size_mb': 300})
        self.wait(600)
        self.assertEqual(self.commands, [], 'Start painting, Discard and downloads wait for the artist')

    def test_the_quick_toggle_turns_it_on_and_off_and_waits_for_a_pause_to_save(self):
        toggle = self.panel.auto_toggle
        self.assertTrue(toggle.isVisible()); self.assertEqual(toggle.accessibleName(), 'Auto-approve')
        toggle.click()
        self.assertEqual(self.commands[-1]['type'], 'set_execution_settings')
        self.assertEqual(self.commands[-1]['settings']['auto_approve'], 60, 'on: the last delay chosen, else a minute')
        toggle.click()
        self.assertEqual(self.commands[-1]['settings']['auto_approve'], 'off')
        widget = self.panel.setting_widgets['auto_approve']
        widget.setCurrentIndex(widget.findData(10))
        self.assertTrue(toggle.isChecked(), 'the setting shows on the toggle')
        toggle.click(); self.commands.clear()
        self.panel.handle_event({'type': 'busy', 'busy': True})
        toggle.click()                                    # while painting: on at once, saved when the run pauses
        self.assertTrue(toggle.isChecked()); self.assertEqual(self.commands, [])
        self.assertEqual(self.panel.auto_approve.delay, 10)
        self.setting('off')                               # the companion's settings meanwhile do not undo the artist's toggle
        self.assertTrue(toggle.isChecked())
        self.panel.handle_event({'type': 'busy', 'busy': False})
        self.assertEqual(self.commands[-1]['settings']['auto_approve'], 10)

    def test_turning_it_off_stops_a_countdown(self):
        self.setting(10); self.finished_step(); self.wait(3)
        self.panel.auto_toggle.click()
        self.wait(60)
        self.assertFalse([c for c in self.commands if c['type'] != 'set_execution_settings'])
        self.assertEqual(self.visible_text(), [])


if __name__ == '__main__':
    unittest.main()

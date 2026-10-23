"""Run: uv run -q --with pyqt5 python tests/ui_panel_plan_steps.py (and --with pyqt6). A UI script like ui_panel_folder: it
stubs krita for the whole process. Plan step controls (plan-step-controls, mockup B: plain-word buttons, no ticks): the
plan bar lists the steps from the goal event's plan_steps; Skip / Restore before painting (a skipped step greyed and struck
through), "✓ Good enough → next step" on the step that paints, "✓ Met" and "↺ Redo" (with what to change) after it
finishes. Each sends a plan_step command with an id. Both themes keep the coloured buttons readable at the panel's narrow
width. With PLAN_STEPS_SCREENSHOTS=<folder> it also saves the plan list in Toska Night and Toska Day there.
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
package = types.ModuleType('panel_steps_test'); package.__path__ = [str(PLUGIN)]; sys.modules['panel_steps_test'] = package
from panel_steps_test.qt_compat import QApplication, QDockWidget, QStandardPaths, QPushButton, QLineEdit, QColor
from panel_steps_test import plan_steps
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
spec = importlib.util.spec_from_file_location('panel_steps_test.creative_docker', PLUGIN / 'creative_docker.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
app = QApplication.instance() or QApplication([])
QProcess = module.QProcess

BRIEF = {'title': 'New Moscow', 'objective': 'o', 'requirements': [], 'freedom': [], 'completion': ['c'],
         'steps': [{'title': 'Underpainting from the goal image', 'done_when': 'd'}, {'title': 'Moonlit sky', 'done_when': 'd'},
                   {'title': 'Soften the foreground into readable masses', 'done_when': 'd'}, {'title': 'Historic buildings', 'done_when': 'd'},
                   {'title': 'Kremlin towers', 'done_when': 'd'}]}
KEYS = ['title:underpainting from the goal image#0', 'file:01-moonlit-sky.png', 'title:soften the foreground into readable masses#0',
        'file:02-historic-buildings.png', 'file:04-kremlin-towers.png']


def steps(*states, redone=None):
    rows = [{'index': i, 'key': KEYS[i], 'title': BRIEF['steps'][i]['title'], 'state': state} for i, state in enumerate(states)]
    for index, count in (redone or {}).items(): rows[index]['redone'] = count
    return rows


def contrast(a, b):
    def luminance(color):
        c = QColor(color)
        channels = [v / 255 for v in (c.red(), c.green(), c.blue())]
        channels = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class PlanStepsRules(unittest.TestCase):
    def test_each_state_offers_its_plain_word_buttons(self):
        self.assertEqual([a for a, *_ in plan_steps.step_actions('open')], ['skip'])
        self.assertEqual([a for a, *_ in plan_steps.step_actions('skipped')], ['restore'])
        self.assertEqual([(a, label) for a, label, *_ in plan_steps.step_actions('painting')], [('good_enough', '✓ Good enough → next step')])
        self.assertEqual([(a, label) for a, label, *_ in plan_steps.step_actions('finished')], [('met', '✓ Met'), ('redo', '↺ Redo')])
        for state in ('finishing', 'met', 'good_enough', 'done'):
            self.assertEqual(plan_steps.step_actions(state), [], state)

    def test_a_command_has_an_id_the_action_the_step_key_and_text_only_for_redo(self):
        first = plan_steps.plan_step_command('skip', KEYS[1]); second = plan_steps.plan_step_command('redo', KEYS[1], '  darker sky ')
        self.assertEqual({k: v for k, v in first.items() if k != 'id'}, {'type': 'plan_step', 'action': 'skip', 'step_key': KEYS[1]})
        self.assertEqual(second['text'], 'darker sky')
        self.assertNotIn('text', plan_steps.plan_step_command('redo', KEYS[1], '   '))
        self.assertRegex(first['id'], r'^[A-Za-z0-9_-]{1,80}$'); self.assertNotEqual(first['id'], second['id'])

    def test_the_coloured_buttons_are_readable_in_both_themes(self):
        from panel_steps_test.panel_theme import TOSKA_NIGHT, TOSKA_DAY, DARK, LIGHT
        for colors, dark in ((TOSKA_NIGHT, True), (TOSKA_DAY, False), (DARK, True), (LIGHT, False)):
            palette = plan_steps.step_colors(colors, dark)
            for role in ('met', 'redo'):
                self.assertGreaterEqual(contrast(palette[role + 'Text'], palette[role]), 4.5, (role, dark))
                self.assertGreaterEqual(contrast(palette[role + 'Label'], colors['surface']), 4.5, (role, 'label', dark))


class PanelPlanSteps(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.panel = module.CreativeAgentDocker(); self.panel.resize(300, 900); self.panel.show()
        self.panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running,
                                                   write=lambda data: self.commands.append(json.loads(data)))
        self.panel.handle_event({'type': 'ready', 'models': [{'provider': 'openrouter', 'id': 'm', 'name': 'M', 'configured': True}],
                                 'bridge': {}, 'build': {'version': '1', 'build_id': 'b'}})
        self.commands.clear()

    def tearDown(self):
        self.panel.process = None; self.panel.close(); self.panel.deleteLater()
        for _ in range(4): app.processEvents()

    def goal(self, rows, status='ready', busy=False, **extra):
        if self.panel.busy != busy: self.panel.handle_event({'type': 'busy', 'busy': busy})
        self.panel.handle_event({'type': 'goal', 'goal': dict({'status': status, 'brief': BRIEF, 'current_step': 0}, **extra),
                                 'mode': 'agent', 'references': [], 'plan_steps': rows})
        app.processEvents()

    def buttons(self, index):
        return [b for b in self.panel.plan_steps.rows[index]['widget'].findChildren(QPushButton) if b.isVisible()]

    def test_skip_and_restore_before_painting(self):
        self.goal(steps('open', 'open', 'open', 'open', 'open'))
        self.assertTrue(self.panel.plan_steps.isVisible())
        self.assertEqual(len(self.panel.plan_steps.rows), 5)
        skip = self.buttons(2)
        self.assertEqual([b.text() for b in skip], ['Skip'])
        self.assertEqual(skip[0].accessibleName(), 'Skip step 3: Soften the foreground into readable masses')
        skip[0].click()
        self.assertEqual(len(self.commands), 1)
        self.assertEqual({k: v for k, v in self.commands[0].items() if k != 'id'}, {'type': 'plan_step', 'action': 'skip', 'step_key': KEYS[2]})
        self.assertFalse(skip[0].isEnabled(), 'one press sends once')
        self.goal(steps('open', 'open', 'skipped', 'open', 'open'))
        title = self.panel.plan_steps.rows[2]['title']
        self.assertTrue(title.font().strikeOut(), 'a skipped step is struck through')
        self.assertEqual(title.objectName(), 'stepSkipped')
        restore = self.buttons(2)
        self.assertEqual([b.text() for b in restore], ['Restore'])
        restore[0].click()
        self.assertEqual(self.commands[-1]['action'], 'restore')
        self.assertIn('1 skipped', self.panel.plan_steps.summary.text())

    def test_good_enough_while_a_step_paints(self):
        self.goal(steps('painting', 'open', 'skipped', 'open', 'open'), status='active', busy=True)
        good = self.buttons(0)
        self.assertEqual([b.text() for b in good], ['✓ Good enough → next step'])
        self.assertEqual(good[0].objectName(), 'stepMet')
        self.assertTrue(good[0].isEnabled())
        self.assertIn('next step', good[0].accessibleName())
        self.assertTrue(all(b.isEnabled() for b in self.buttons(1)), 'later steps can still be skipped while painting')
        good[0].click()
        self.assertEqual(self.commands[-1]['action'], 'good_enough'); self.assertEqual(self.commands[-1]['step_key'], KEYS[0])
        self.goal(steps('finishing', 'open', 'skipped', 'open', 'open'), status='active', busy=True)
        self.assertEqual(self.buttons(0), [])
        self.assertIn('Finishing', self.panel.plan_steps.rows[0]['status'].text())

    def test_met_and_redo_after_a_step_finishes(self):
        self.panel.handle_event({'type': 'move', 'move': {'number': 1, 'status': 'ready', 'title': 'Underpainting', 'actions': 2}})
        self.assertTrue(self.panel.move_bar.isVisible())
        self.goal(steps('finished', 'open', 'open', 'open', 'open', redone={0: 1}), status='move_ready')
        met, redo = self.buttons(0)
        self.assertEqual((met.text(), met.objectName(), redo.text(), redo.objectName()), ('✓ Met', 'stepMet', '↺ Redo', 'stepRedo'))
        self.assertIn('redone 1', self.panel.plan_steps.rows[0]['status'].text())
        redo.click()
        self.assertEqual(self.commands, [], 'Redo first asks what to change')
        editor = self.panel.plan_steps.rows[0]['editor']
        self.assertTrue(editor.isVisible())
        field = editor.findChild(QLineEdit); field.setText('keep the sky darker')
        self.assertEqual(field.accessibleName(), 'What to change in step 1 (optional)')
        confirm = next(b for b in editor.findChildren(QPushButton) if b.text() == '↺ Redo step')
        confirm.click()
        self.assertEqual({k: v for k, v in self.commands[-1].items() if k != 'id'},
                         {'type': 'plan_step', 'action': 'redo', 'step_key': KEYS[0], 'text': 'keep the sky darker'})
        self.assertFalse(self.panel.move_bar.isVisible(), 'the move card goes: the step answered it')
        self.goal(steps('finished', 'open', 'open', 'open', 'open'), status='move_ready')
        self.buttons(0)[0].click()
        self.assertEqual(self.commands[-1]['action'], 'met')
        self.goal(steps('met', 'painting', 'open', 'open', 'open'), status='active', busy=True)
        self.assertEqual(self.buttons(0), [])
        self.assertEqual(self.panel.plan_steps.rows[0]['status'].text(), '✓ Met')
        self.assertEqual(self.panel.plan_steps.rows[0]['status'].objectName(), 'stepMetText')

    def test_met_and_redo_wait_while_the_agent_is_busy(self):
        self.goal(steps('finished', 'open', 'open', 'open', 'open'), status='move_ready', busy=True)
        self.assertTrue(all(not b.isEnabled() for b in self.buttons(0)))
        self.panel.handle_event({'type': 'busy', 'busy': False})
        self.assertTrue(all(b.isEnabled() for b in self.buttons(0)))

    def test_the_move_card_stays_while_its_move_is_ready_whatever_the_goal_status(self):
        move = {'number': 1, 'status': 'ready', 'title': 'Underpainting', 'actions': 2, 'step': 0}
        self.panel.handle_event({'type': 'move', 'move': move})
        for status in ('limited', 'paused', 'move_ready'):
            self.goal(steps('finished', 'open', 'open', 'open', 'open'), status=status, moves=[move])
            self.assertTrue(self.panel.move_bar.isVisible(), status)
            self.assertEqual([b.text() for b in self.buttons(0)], ['✓ Met', '↺ Redo'], status)
        self.goal(steps('met', 'painting', 'open', 'open', 'open'), status='active', busy=True, moves=[dict(move, status='kept')])
        self.assertFalse(self.panel.move_bar.isVisible(), 'kept: the card goes')

    def test_a_refused_answer_gives_the_buttons_and_the_move_card_back(self):
        move = {'number': 1, 'status': 'ready', 'title': 'Underpainting', 'actions': 2, 'step': 0}
        self.panel.handle_event({'type': 'move', 'move': move})
        self.goal(steps('finished', 'open', 'open', 'open', 'open'), status='limited', moves=[move])
        self.buttons(0)[0].click()
        self.assertFalse(self.panel.move_bar.isVisible())
        self.assertFalse(any(b.isEnabled() for b in self.buttons(0)))
        self.panel.handle_event({'type': 'error', 'message': 'Wait for the painting in progress to finish.'})
        self.assertTrue(all(b.isEnabled() for b in self.buttons(0)), 'the step can be answered again')
        self.assertTrue(self.panel.move_bar.isVisible(), 'and the move card is back')
        self.panel.move_command('keep')
        self.panel.handle_event({'type': 'error', 'message': 'refused'})
        self.assertTrue(self.panel.move_bar.isVisible(), 'a refused Keep gives the card back too')

    def test_the_plan_dialog_keeps_each_step_id(self):
        brief = dict(BRIEF, steps=[dict(step, id='s%d' % i) for i, step in enumerate(BRIEF['steps'])])
        dialog = module.PlanDialog(self.panel, {'brief': brief, 'limits': {'minutes': 0, 'passes': 0}, 'status': 'ready'})
        dialog.steps.item(1, 0).setText('A moonlit sky')
        self.assertEqual([s.get('id') for s in dialog.brief()['steps']], ['s0', 's1', 's2', 's3', 's4'])
        self.assertEqual(dialog.brief()['steps'][1]['title'], 'A moonlit sky')
        dialog.deleteLater()

    def test_no_plan_steps_hides_the_list(self):
        self.goal([])
        self.assertFalse(self.panel.plan_steps.isVisible())

    def test_the_list_fits_the_narrow_panel_in_both_themes(self):
        rows = steps('good_enough', 'skipped', 'painting', 'open', 'open', redone={0: 1})
        for mode in (1, 2):                                     # Dark, Light
            self.panel.set_theme(mode)
            self.goal(rows, status='active', busy=True)
            frame = self.panel.plan_steps
            for row in frame.rows:
                for button in row['widget'].findChildren(QPushButton):
                    if button.isVisible():
                        self.assertLessEqual(button.sizeHint().width(), 260, button.text())
            self.assertIn('stepMet', self.panel.styleSheet())
        shots = os.environ.get('PLAN_STEPS_SCREENSHOTS')
        if shots:
            os.makedirs(shots, exist_ok=True)
            original = module.QApplication.palette
            for name, window in (('toska-night', '#141b25'), ('toska-day', '#efe8dc')):
                palette = module.QPalette(); palette.setColor(module.QPalette.ColorRole.Window, QColor(window))
                module.QApplication.palette = staticmethod(lambda palette=palette: palette)
                try:
                    self.panel.set_theme(0)
                    for label, (state_rows, status, busy) in {'before': (steps('open', 'open', 'skipped', 'open', 'open'), 'ready', False),
                                                                'painting': (steps('good_enough', 'skipped', 'painting', 'open', 'open'), 'active', True),
                                                                'finished': (steps('met', 'skipped', 'finished', 'open', 'open', redone={2: 1}), 'move_ready', False)}.items():
                        self.goal(state_rows, status=status, busy=busy)
                        if label == 'finished': self.panel.plan_steps.rows[2]['redo'].click()
                        app.processEvents()
                        self.panel.plan_bar.grab().save(os.path.join(shots, 'plan-steps-%s-%s.png' % (name, label)))
                finally:
                    module.QApplication.palette = original


if __name__ == '__main__':
    unittest.main()

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
from panel_steps_test.qt_compat import QApplication, QDockWidget, QStandardPaths, QPushButton, QLineEdit, QColor, QAbstractScrollArea
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
            for ground in ('surface', 'raised'):             # the Now painting caption, on the card and the highlighted row
                self.assertGreaterEqual(contrast(palette['paintingLabel'], colors[ground]), 4.5, ('painting', ground, dark))


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
        # processEvents() never runs a deleteLater posted outside an event loop: without this the panel lived on, its timers
        # firing, while the collector freed its Python side, and the script crashed at random at exit.
        module.QCoreApplication.sendPostedEvents(None, module.QEvent.Type.DeferredDelete)

    def goal(self, rows, status='ready', busy=False, **extra):
        if self.panel.busy != busy: self.panel.handle_event({'type': 'busy', 'busy': busy})
        self.panel.handle_event({'type': 'goal', 'goal': dict({'status': status, 'brief': BRIEF, 'current_step': 0}, **extra),
                                 'mode': 'agent', 'references': [], 'plan_steps': rows})
        self.panel.tabs.setCurrentIndex(self.panel.plan_tab)   # the list is on the Plan tab; the painting step on the card
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


TITLES = ['Underpainting from the goal image', 'Moonlit sky', 'Historic buildings', 'Domed church', 'Kremlin towers', 'Modern skyline',
          'Arched bridge', 'River reflections', 'Snowy street with pedestrians and cars', 'Lamps and trees', 'Snowy railing',
          'Woman back view', 'Vintage convertible']
BIG_BRIEF = dict(BRIEF, title='Moscow winter night', steps=[{'title': t, 'done_when': 'd'} for t in TITLES])


def painting_step_five():
    """Step 5 of 13 painting: steps 1, 3 and 4 met, 2 and 9 skipped (the artist's New Moscow chat)."""
    states = ['met', 'skipped', 'met', 'met', 'painting'] + ['open'] * 8; states[8] = 'skipped'
    rows = []
    for i, (title, state) in enumerate(zip(TITLES, states)):
        row = {'index': i, 'key': 'k%d' % i, 'title': title, 'state': state}
        if i: row['source'] = 'assets/%02d-%s.png' % (i, title.lower().replace(' ', '-'))
        if state == 'painting': row['batches'] = 3
        rows.append(row)
    return rows


class PanelNowPainting(unittest.TestCase):
    """The artist's layout B: a progress strip, a Now painting card above the tabs, and Chat · Plan · Folder tabs, each
    with one scroll area at most."""
    def setUp(self):
        self.commands = []
        self.panel = module.CreativeAgentDocker(); self.panel.resize(360, 900); self.panel.show()
        self.panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running,
                                                   write=lambda data: self.commands.append(json.loads(data)))
        self.panel.handle_event({'type': 'ready', 'models': [{'provider': 'openrouter', 'id': 'm', 'name': 'M', 'configured': True}],
                                 'bridge': {}, 'build': {'version': '1', 'build_id': 'b'}})
        self.commands.clear()

    tearDown = PanelPlanSteps.tearDown

    def paint(self, rows=None, status='active', busy=True, **goal):
        if self.panel.busy != busy: self.panel.handle_event({'type': 'busy', 'busy': busy})
        self.panel.handle_event({'type': 'goal', 'goal': dict({'status': status, 'brief': BIG_BRIEF, 'current_step': 0, 'done_steps': [0, 2, 3]}, **goal),
                                 'mode': 'agent', 'references': [], 'plan_steps': rows or painting_step_five()})
        for _ in range(3): app.processEvents()

    def shown(self, widget):
        """On screen: visible, and not scrolled or clipped out of the panel."""
        return widget.isVisible() and not widget.visibleRegion().isEmpty()

    def test_the_now_painting_card_shows_the_step_its_source_and_its_buttons(self):
        self.paint()
        now = self.panel.plan_steps.now
        self.assertTrue(self.shown(now))
        text = ' '.join(label.text() for label in now.findChildren(module.QLabel) if label.isVisible())
        self.assertIn('step 5 of 13', text.lower()); self.assertIn('Kremlin towers', text)
        self.assertIn('04-kremlin-towers.png', text); self.assertNotIn('assets/', text, 'the file name, not its folder')
        self.assertIn('batch 3', text)
        good = next(b for b in now.findChildren(QPushButton) if b.text().startswith('✓ Good enough'))
        self.assertTrue(self.shown(good), 'Good enough is on screen whatever the list shows')
        stop = next(b for b in now.findChildren(QPushButton) if b.text() == 'Stop')
        self.assertTrue(stop.isEnabled()); self.assertTrue(stop.accessibleName())
        for tab in range(self.panel.tabs.count()):           # pinned above the tabs: every tab shows it
            if self.panel.tabs.isTabVisible(tab):
                self.panel.tabs.setCurrentIndex(tab); app.processEvents()
                self.assertTrue(self.shown(good), self.panel.tabs.tabText(tab))

    def test_finished_step_offers_met_and_redo_on_the_card(self):
        rows = painting_step_five(); rows[4]['state'] = 'finished'
        self.paint(rows, status='move_ready', busy=False)
        now = self.panel.plan_steps.now
        self.assertEqual(sorted(b.text() for b in now.findChildren(QPushButton) if b.isVisible()), ['↺ Redo', '✓ Met'])

    def test_the_header_agrees_with_the_steps(self):
        self.paint()
        header = self.panel.plan_summary.text()
        self.assertNotIn('Step 1 of', header, 'the goal current_step (0) must not contradict the step painting')
        self.assertNotIn('done', header, 'one count, in the list summary')
        self.assertIn('Moscow winter night', header)
        self.assertEqual(self.panel.plan_steps.summary.text(), '3 of 13 met · 2 skipped')
        self.assertEqual(self.panel.tabs.tabText(self.panel.plan_tab), 'Plan · 13')

    def test_the_progress_strip_has_a_segment_per_step(self):
        self.paint()
        strip = self.panel.plan_steps.strip
        self.assertTrue(strip.isVisible())
        self.assertEqual([s['state'] for s in strip.segments][:5], ['met', 'skipped', 'met', 'met', 'painting'])
        self.assertEqual(len(strip.segments), 13)
        self.assertIn('Step 5 of 13 · Kremlin towers · painting', strip.tip_at(strip.segment_rect(4).center()))
        self.assertIn('3 of 13 met', strip.accessibleName()); self.assertIn('step 5 painting', strip.accessibleName())
        from panel_steps_test.panel_theme import TOSKA_NIGHT, TOSKA_DAY, DARK, LIGHT
        for colors, dark in ((TOSKA_NIGHT, True), (TOSKA_DAY, False), (DARK, True), (LIGHT, False)):
            palette = plan_steps.step_colors(colors, dark)
            for state in ('met', 'painting'):                # graphics: 3:1 against the panel (WCAG 1.4.11)
                self.assertGreaterEqual(contrast(palette['segment_' + state], colors['bg']), 3, (state, dark))
        self.panel.handle_event({'type': 'goal', 'goal': {'status': 'draft', 'brief': None}, 'mode': 'ask', 'references': [], 'plan_steps': []})
        self.assertFalse(strip.isVisible(), 'no plan, no strip')
        self.assertFalse(self.panel.tabs.isTabVisible(self.panel.plan_tab))

    def test_done_steps_fold_into_a_summary_that_expands(self):
        self.paint()
        self.panel.tabs.setCurrentIndex(self.panel.plan_tab); app.processEvents()
        fold = self.panel.plan_steps.fold
        self.assertTrue(fold.isVisible()); self.assertIn('3 met · 1 skipped', fold.text())
        done = [self.panel.plan_steps.list_rows[i] for i in range(4)]
        self.assertFalse(any(row.isVisible() for row in done), 'folded')
        fold.click(); app.processEvents()
        self.assertTrue(all(row.isVisible() for row in done))
        later = self.panel.plan_steps.rows[8]['widget']
        self.assertTrue(later.isVisible(), 'a later skipped step stays in the list, with Restore')
        self.assertEqual([b.text() for b in self.buttons(8)], ['Restore'])

    def buttons(self, index):
        return [b for b in self.panel.plan_steps.rows[index]['widget'].findChildren(QPushButton) if b.isVisible()]

    def test_the_current_step_is_highlighted_and_scrolled_into_view(self):
        self.panel.resize(360, 560)
        self.paint()
        self.panel.plan_steps.fold.click()                   # the done steps open above it
        self.panel.tabs.setCurrentIndex(self.panel.plan_tab)
        for _ in range(4): app.processEvents()
        current = self.panel.plan_steps.list_rows[4]
        self.assertEqual(current.objectName(), 'planStepCurrent')
        self.assertTrue(self.shown(current), 'the plan tab shows the step that paints')

    def test_no_nested_scrollbars(self):
        self.paint()
        self.panel.handle_event({'type': 'folder', 'index': {'root': '/f', 'name': 'f', 'goal': {'name': 'final_goal.png'},
                                 'elements': [{'name': 'e%d.png' % i, 'guess': 'E%d' % i, 'number': i} for i in range(12)], 'others': [], 'skipped': []},
                                 'references': {}})
        def scrolls(area):
            bars = (area.verticalScrollBar(), area.horizontalScrollBar())
            return any(bar.isVisible() and bar.maximum() > 0 for bar in bars)
        for tab in range(self.panel.tabs.count()):
            if not self.panel.tabs.isTabVisible(tab): continue
            self.panel.tabs.setCurrentIndex(tab)
            for _ in range(3): app.processEvents()
            for area in self.panel.findChildren(QAbstractScrollArea):
                if not area.isVisible() or not scrolls(area): continue
                parent = area.parentWidget()
                while parent is not None and not isinstance(parent, QAbstractScrollArea): parent = parent.parentWidget()
                self.assertIsNone(parent, '%s scrolls inside %s (%s tab)' % (area.objectName() or type(area).__name__,
                                                                             parent and (parent.objectName() or type(parent).__name__), self.panel.tabs.tabText(tab)))
        self.assertEqual(self.panel.plan_steps.widget.findChildren(QAbstractScrollArea), [])

    def test_start_painting_and_resume_are_on_the_card_from_every_tab(self):
        rows = [dict(r, state='open') for r in painting_step_five()]
        self.paint(rows, status='ready', busy=False)
        start = self.panel.card_start
        for tab in range(self.panel.tabs.count()):
            if not self.panel.tabs.isTabVisible(tab): continue
            self.panel.tabs.setCurrentIndex(tab); app.processEvents()
            self.assertTrue(self.shown(start), self.panel.tabs.tabText(tab)); self.assertEqual(start.text(), 'Start painting')
        self.assertEqual(start.isEnabled(), self.panel.execute_button.isEnabled(), 'the Plan tab\'s own rule')
        started = []; self.panel.start_plan = lambda: started.append(True)
        start.click(); self.assertEqual(started, [True])
        self.paint(rows, status='paused', busy=False)
        self.assertEqual(start.text(), 'Resume')
        self.paint()                                         # a step paints: Stop, not Start
        self.assertFalse(start.isVisible())
        self.paint(rows, status='ready', busy=False, question={'id': 'q', 'question': '?', 'options': []})
        self.assertFalse(start.isVisible(), 'an open question comes first')

    def test_the_plan_tab_keeps_its_scroll_until_another_step_paints(self):
        self.panel.resize(360, 560)
        self.paint(); self.panel.plan_steps.fold.click()
        self.panel.tabs.setCurrentIndex(self.panel.plan_tab)
        for _ in range(4): app.processEvents()
        bar = self.panel.plan_scroll.verticalScrollBar(); self.assertGreater(bar.maximum(), 0, 'the list scrolls here')
        bar.setValue(bar.maximum()); app.processEvents()
        builds = self.panel.plan_steps.builds
        rows = painting_step_five(); rows[4]['batches'] = 4
        self.paint(rows)
        for _ in range(4): app.processEvents()
        self.assertEqual(bar.value(), bar.maximum(), 'a new batch does not jump the list back')
        self.assertEqual(self.panel.plan_steps.builds, builds, 'a batch count is updated in place')
        text = ' '.join(l.text() for l in self.panel.plan_steps.now.findChildren(module.QLabel) if l.isVisible())
        self.assertIn('batch 4', text)
        rows = painting_step_five(); rows[4]['state'] = 'met'; rows[5]['state'] = 'painting'
        bar.setValue(bar.maximum()); self.paint(rows)
        for _ in range(4): app.processEvents()
        self.assertTrue(self.shown(self.panel.plan_steps.list_rows[5]), 'the next step paints: shown')

    def test_titles_are_text_in_tooltips_and_rows_without_an_index(self):
        rows = painting_step_five(); rows[4]['title'] = '<b>Kremlin</b> towers'; rows[4]['source'] = 'assets/<i>x</i>.png'
        rows[6]['index'] = None
        self.paint(rows)
        strip = self.panel.plan_steps.strip
        self.assertIn('&lt;b&gt;Kremlin', strip.tip_at(strip.segment_rect(4).center()))
        tips = [l.toolTip() for l in self.panel.plan_steps.now.findChildren(module.QLabel) if l.toolTip()]
        self.assertTrue(tips and all('&lt;i&gt;' in t for t in tips), tips)

    def test_no_duplicate_titles(self):
        self.paint()
        self.panel.transcript.add_message('Creative Agent', 'A reply.')
        app.processEvents()
        texts = [l.text() for l in self.panel.findChildren(module.QLabel) if l.isVisible()]
        self.assertFalse(any(t == 'Creative Agent' for t in texts), texts)
        self.assertIn(module.product_name(), texts)


if __name__ == '__main__':
    unittest.main()

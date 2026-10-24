"""Run: uv run -q --with pyqt5 python tests/ui_panel_paint_only_here.py (and --with pyqt6). A UI script like ui_panel_features:
it stubs krita for the whole process. Paint only here (element-scoped-painting goal 1; the artist, 2026-10-23): the button
captures the document's selection as the chat's one area (the rest of the painting protected as a hidden feature), the chip
"Painting only inside: ..." with ✕ clears it, the typed phrase does the same with its message, the painter's
ask_for_selection card offers Select with Freehand / Use my selection / Paint everywhere, and the document follows the chat.
With PAINT_ONLY_SCREENSHOTS=<folder> it also saves the panel with the chip in Toska Night at 360 px there.
Mask files go to a temporary folder that is removed; no dialog opens and no profile is touched."""
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
package = types.ModuleType('panel_paint_only_test'); package.__path__ = [str(PLUGIN)]; sys.modules['panel_paint_only_test'] = package
from panel_paint_only_test.qt_compat import QApplication, QDockWidget, QStandardPaths, QPushButton, QColor
QStandardPaths.setTestModeEnabled(True)

W, H = 40, 30
state = types.SimpleNamespace(document=None)


class Selection:
    """Krita's Selection on the W x H test canvas, one byte a pixel."""
    def __init__(self): self.m = bytearray(W * H)
    def _box(self):
        cells = [(i % W, i // W) for i, v in enumerate(self.m) if v]
        if not cells: return 0, 0, 0, 0
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    def x(self): return self._box()[0]
    def y(self): return self._box()[1]
    def width(self): return self._box()[2]
    def height(self): return self._box()[3]
    def select(self, x, y, w, h, value):
        for row in range(y, y + h): self.m[row * W + x:row * W + x + w] = bytes([value]) * w
    def pixelData(self, x, y, w, h): return b''.join(bytes(self.m[row * W + x:row * W + x + w]) for row in range(y, y + h))
    def setPixelData(self, data, x, y, w, h):
        for index, row in enumerate(range(y, y + h)): self.m[row * W + x:row * W + x + w] = bytes(data[index * w:(index + 1) * w])
    def duplicate(self):
        copy = Selection(); copy.m = bytearray(self.m); return copy
    def shrink(self, x, y, lock): pass
    def feather(self, value): pass
    def intersect(self, other): self.m = bytearray(min(a, b) for a, b in zip(self.m, other.m))
    def subtract(self, other): self.m = bytearray(max(0, a - b) for a, b in zip(self.m, other.m))


class Feature:
    def __init__(self, name, kind, mask, protected):
        self.n, self.k, self.mask, self.p = name, kind, mask, protected
    def name(self): return self.n
    def kind(self): return self.k
    def isProtected(self): return self.p


class Document:
    """A fork painting: features, protection and the artist's selection."""
    def __init__(self): self.list, self.selected, self.move_open, self.undo_steps = [], None, False, []
    def fileName(self): return '/tmp/paint-only.kra'
    def modified(self): return False
    def width(self): return W
    def height(self): return H
    def features(self): return list(self.list)
    def feature(self, name): return next((f for f in self.list if f.name() == name), None)
    # The artist's history: the ordinary feature calls are undo steps (and clear the Redo); the transient ones are not.
    def addFeature(self, name, kind, mask, author, state_, protected):
        if self.feature(name): return None
        feature = Feature(name, kind, mask.duplicate(), protected); self.list.append(feature); self.undo_steps.append(('add', name)); return feature
    def removeFeature(self, name):
        found = self.feature(name)
        if found: self.list.remove(found); self.undo_steps.append(('remove', name))
        return bool(found)
    def setTransientFeature(self, name, kind, mask, protected=True):
        found = self.feature(name)
        if kind != 'paint-only-here' or (found and found.kind() != kind): return None
        if found: self.list.remove(found)
        feature = Feature(name, kind, mask.duplicate(), protected); self.list.append(feature); return feature
    def removeTransientFeature(self, name):
        found = self.feature(name)
        if not found or found.kind() != 'paint-only-here': return False
        self.list.remove(found); return True
    def protectionActive(self): return any(f.isProtected() for f in self.list)
    def protectedSelection(self, inverted=False): return None
    def agentMoveOpen(self): return self.move_open
    def agentActive(self): return False
    def selection(self, expression=None): return self.selected


class Instance:
    tools = []
    activeDocument = staticmethod(lambda: state.document)
    action = staticmethod(lambda name: types.SimpleNamespace(trigger=lambda: Instance.tools.append(name)))
    documents = staticmethod(lambda: [state.document] if state.document else [])
    addDockWidgetFactory = staticmethod(lambda factory: None)


stub = types.ModuleType('krita'); stub.DockWidget = QDockWidget
stub.DockWidgetFactory = object; stub.DockWidgetFactoryBase = types.SimpleNamespace(DockRight=2)
stub.Krita = types.SimpleNamespace(instance=lambda: Instance)
stub.Selection = Selection
sys.modules['krita'] = stub
spec = importlib.util.spec_from_file_location('panel_paint_only_test.creative_docker', PLUGIN / 'creative_docker.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
from panel_paint_only_test import paint_only_here, shape_mask
app = QApplication.instance() or QApplication([])
QProcess = module.QProcess
KEEP = []
SYSTEM = paint_only_here.SYSTEM_NAME


def selected(x, y, w, h):
    selection = Selection(); selection.select(x, y, w, h, 255); return selection


class PaintOnlyHere(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.folder, True)
        paint_only_here.AREAS._areas = []
        state.document = Document(); self.doc = state.document; Instance.tools.clear()
        self.commands = []
        self.panel = module.CreativeAgentDocker(); self.panel.resize(360, 820); self.panel.show()
        self.panel.pasted_folder = lambda: self.folder
        self.panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running,
                                                   write=lambda data: self.commands.append(json.loads(data)))
        self.panel.handle_event({'type': 'ready', 'models': [{'provider': 'openrouter', 'id': 'm', 'name': 'M', 'configured': True}],
                                 'bridge': {}, 'build': {'version': '1', 'build_id': 'b'}})
        self.commands.clear()
        self.bar = self.panel.paint_only

    def tearDown(self):
        self.bar.timer.stop()
        self.panel.process = None; self.panel.close(); KEEP.append(self.panel)
        for _ in range(4): app.processEvents()
        paint_only_here.AREAS._areas = []; state.document = None

    def chat(self, area=None, **goal):
        self.panel.study_active = True
        self.panel.handle_event({'type': 'goal', 'goal': dict({'status': 'ready', 'paint_only_here': area}, **goal), 'mode': 'agent', 'references': []})
        app.processEvents()

    def sent(self, kind):
        return [c for c in self.commands if c.get('type') == kind]

    def test_without_a_selection_the_button_chooses_the_freehand_tool_and_says_what_to_do(self):
        self.bar.button.click()
        self.assertEqual(Instance.tools, ['KisToolSelectOutline'])
        self.assertTrue(self.bar.hint.isVisible())
        self.assertIn('Draw around the area, then press Paint only here again', self.bar.hint.text())
        self.assertIn('Magnetic', self.bar.hint.text())
        self.assertIsNone(self.doc.feature(SYSTEM)); self.assertEqual(self.sent('paint_only_here'), [])

    def test_the_button_protects_everything_outside_the_selection_and_shows_the_chip(self):
        self.chat()
        self.doc.selected = selected(0, 0, W, 12)                  # the sky: the top rows
        self.bar.button.click(); app.processEvents()
        feature = self.doc.feature(SYSTEM)
        self.assertTrue(feature.isProtected()); self.assertEqual(feature.kind(), paint_only_here.SYSTEM_KIND)
        self.assertEqual(feature.mask.m[0], 0, 'inside the selection: free'); self.assertEqual(feature.mask.m[W * 20], 255, 'outside: protected')
        self.assertTrue(self.bar.chip.isVisible()); self.assertFalse(self.bar.button.isVisible())
        self.assertEqual(self.bar.chip.text(), 'Painting only inside: your selection')
        self.assertEqual(self.panel.feature_rows(), [], 'not in the Protected list')
        [command] = self.sent('paint_only_here')
        self.assertEqual((command['action'], command['bounds'], command['canvas'], command['name']), ('set', [0, 0, W, 12], [W, H], None))
        with open(command['mask_path'], 'rb') as handle:
            self.assertEqual(shape_mask.read_png(handle.read(), (W, 12)), (W, 12, b'\xff' * (W * 12)))
        # A goal event from before the companion took it does not undo it; the companion's own keeps it.
        self.chat(None); self.assertIsNotNone(self.doc.feature(SYSTEM)); self.assertTrue(self.bar.chip.isVisible())
        self.assertEqual(self.doc.undo_steps, [], "the artist's Undo and Redo never meet it")

    def test_the_cross_clears_it(self):
        self.chat()
        self.doc.selected = selected(0, 0, 10, 10); self.bar.button.click()
        self.bar.clear_button.click(); app.processEvents()
        self.assertIsNone(self.doc.feature(SYSTEM))
        self.assertFalse(self.bar.chip.isVisible()); self.assertTrue(self.bar.button.isVisible())
        self.assertEqual(self.sent('paint_only_here')[-1], {'type': 'paint_only_here', 'action': 'clear'})
        self.assertEqual(self.doc.undo_steps, [], 'setting and clearing are no undo steps')

    def test_not_while_the_agent_writes(self):
        self.chat()
        self.doc.selected = selected(0, 0, 10, 10); self.doc.move_open = True
        self.bar.button.click()
        self.assertIsNone(self.doc.feature(SYSTEM)); self.assertIn('agent is working', self.panel.status.text())

    def test_the_typed_phrase_with_a_selection_sends_the_area_with_its_message(self):
        self.chat()
        self.doc.selected = selected(5, 5, 10, 10)
        self.panel.prompt.setPlainText('Paint the clouds only in my selection'); self.panel.submit()
        [prompt] = self.sent('prompt')
        self.assertEqual(prompt['paint_only_here']['bounds'], [5, 5, 10, 10])
        self.assertIsNotNone(self.doc.feature(SYSTEM))
        self.assertEqual(self.sent('paint_only_here'), [], 'one command: the message carries it')
        self.panel.prompt.setPlainText('Now the moon'); self.panel.submit()
        self.assertNotIn('paint_only_here', self.sent('prompt')[-1], 'once')

    def test_before_a_chat_the_area_goes_with_the_first_message(self):
        self.doc.selected = selected(0, 0, 8, 8); self.bar.button.click()
        self.assertEqual(self.sent('paint_only_here'), [])
        self.assertIn('from your next message', self.panel.status.text())
        self.panel.prompt.setPlainText('Paint the sky'); self.panel.submit()
        [start] = self.sent('start'); self.assertEqual(start['paint_only_here']['bounds'], [0, 0, 8, 8])
        self.chat(None)                                          # the new chat's first goal, before the message's area
        self.assertIsNotNone(self.doc.feature(SYSTEM), 'still protected while the message is on its way')

    def test_a_resumed_chat_puts_its_area_back_and_a_chat_without_one_removes_a_leftover(self):
        os.makedirs(os.path.join(self.folder, '.shapes'))
        path = os.path.join(self.folder, '.shapes', 'paint-only-0123456789abcdef01234567.png')
        with open(path, 'wb') as handle: handle.write(paint_only_here.encode_png(10, 4, b'\xff' * 40))
        self.chat({'name': 'the sky', 'bounds': [0, 0, 10, 4], 'mask_path': path})
        self.assertEqual(self.doc.feature(SYSTEM).mask.m[0], 0); self.assertEqual(self.doc.feature(SYSTEM).mask.m[W * 10], 255)
        self.assertEqual(self.bar.chip.text(), 'Painting only inside: the sky')
        self.chat(None)
        self.assertIsNone(self.doc.feature(SYSTEM)); self.assertFalse(self.bar.chip.isVisible())
        paint_only_here.PaintOnlyHere(make_selection=Selection).capture(self.doc, selected(0, 0, 4, 4))   # a leftover
        self.panel.process = None; self.panel.poll_canvas_metadata()
        self.assertIsNone(self.doc.feature(SYSTEM), 'a protection no chat holds goes, without the companion too')
        self.assertEqual(self.doc.undo_steps, [])

    def test_the_poll_never_puts_back_a_protection_the_document_lost(self):
        self.chat(); self.doc.selected = selected(0, 0, 8, 8); self.bar.button.click()
        self.doc.removeTransientFeature(SYSTEM); self.panel.poll_canvas_metadata()
        self.assertIsNone(self.doc.feature(SYSTEM), 'only the bridge, right before an agent write')

    def test_a_waiting_mask_file_goes_when_cleared_or_replaced(self):
        self.doc.selected = selected(0, 0, 8, 8); self.bar.button.click()
        first = self.bar.pending['mask_path']; self.assertTrue(os.path.exists(first))
        self.doc.selected = selected(2, 2, 8, 8); self.bar.button.click()
        self.assertFalse(os.path.exists(first), 'replaced'); second = self.bar.pending['mask_path']
        self.bar.clear_button.click()
        self.assertFalse(os.path.exists(second), 'cleared'); self.assertIsNone(self.bar.pending)

    def test_the_chat_end_clears_the_area_on_every_document(self):
        self.chat(); self.doc.selected = selected(0, 0, 8, 8); self.bar.button.click()
        first = self.doc; state.document = Document(); state.document.selected = selected(0, 0, 4, 4); self.bar.button.click()
        self.panel.new_chat()
        self.assertIsNone(first.feature(SYSTEM)); self.assertIsNone(state.document.feature(SYSTEM))

    def test_new_chat_ends_the_area(self):
        self.chat(); self.doc.selected = selected(0, 0, 8, 8); self.bar.button.click()
        self.panel.new_chat()
        self.assertIsNone(self.doc.feature(SYSTEM)); self.assertFalse(self.bar.chip.isVisible())

    def question(self):
        self.chat()
        self.panel.handle_event({'type': 'question', 'id': 'q1', 'question': 'Select the sky with the Freehand Selection tool (or the Magnetic one, which snaps to edges), then press Paint only here.',
                                 'options': ['Select with Freehand', 'Use my selection', 'Paint everywhere'], 'select_area': {'part': 'the sky'}})
        app.processEvents()
        return {b.text(): b for b in self.panel.question_controls}

    def test_the_painter_asks_for_a_selection_with_three_buttons(self):
        buttons = self.question()
        self.assertEqual(list(buttons), ['Select with Freehand', 'Use my selection', 'Paint everywhere'])
        self.assertNotIn('You decide', [b.text() for b in self.panel.findChildren(QPushButton) if b.isVisible()])
        self.assertFalse(buttons['Use my selection'].isEnabled(), 'no selection yet')
        buttons['Select with Freehand'].click()
        self.assertEqual(Instance.tools, ['KisToolSelectOutline']); self.assertIn('Magnetic', self.bar.hint.text())
        self.doc.selected = selected(0, 0, W, 10); self.bar.watch_selection()
        self.assertTrue(buttons['Use my selection'].isEnabled())
        buttons['Use my selection'].click()
        prompt = self.sent('prompt')[-1]
        self.assertEqual(prompt['text'], 'Use my selection')
        self.assertEqual((prompt['paint_only_here']['name'], prompt['paint_only_here']['bounds']), ('the sky', [0, 0, W, 10]))
        self.assertEqual(self.bar.chip.text(), 'Painting only inside: the sky')
        self.assertFalse(any(b.isEnabled() for b in buttons.values()), 'answered once')

    def test_paint_everywhere_answers_without_an_area(self):
        buttons = self.question()
        buttons['Paint everywhere'].click()
        prompt = self.sent('prompt')[-1]
        self.assertEqual(prompt['text'], 'Paint everywhere'); self.assertNotIn('paint_only_here', prompt)
        self.assertIsNone(self.doc.feature(SYSTEM))

    def test_screenshot(self):
        shots = os.environ.get('PAINT_ONLY_SCREENSHOTS')
        if not shots: self.skipTest('PAINT_ONLY_SCREENSHOTS not set')
        os.makedirs(shots, exist_ok=True)
        original = module.QApplication.palette
        palette = module.QPalette(); palette.setColor(module.QPalette.ColorRole.Window, QColor('#141b25'))
        module.QApplication.palette = staticmethod(lambda: palette)
        try:
            self.panel.set_theme(0)
            self.panel.resize(360, 820)
            self.question()
            self.doc.selected = selected(0, 0, W, 10); self.bar.watch_selection()
            self.panel.question_controls[1].click()
            self.chat({'name': 'the sky', 'bounds': [0, 0, W, 10], 'mask_path': self.sent('prompt')[-1]['paint_only_here']['mask_path']})
            for _ in range(4): app.processEvents()
            self.panel.grab().save(os.path.join(shots, 'paint-only-here-toska-night-360.png'))
            self.panel.composer.grab().save(os.path.join(shots, 'paint-only-here-composer-toska-night-360.png'))
        finally:
            module.QApplication.palette = original


if __name__ == '__main__':
    unittest.main()

"""Following the artist, composition guides and canvas messages, with a fake Krita window. Files go to a temporary folder that is removed."""
import sys
import types
import unittest
import test_region_craft as region_tests

view_module = sys.modules['creative_test_package.canvas_view']


class Colour:
    def __init__(self, name): self.value = name
    def colorForCanvas(self, canvas): return types.SimpleNamespace(name=lambda: self.value)


class View:
    def __init__(self, doc, selected): self.doc, self.selected, self.messages = doc, selected, []
    def document(self): return self.doc
    def selectedNodes(self): return self.selected
    def canvas(self): return 'canvas'
    def foregroundColor(self): return Colour('#3a6ea5')
    def backgroundColor(self): return Colour('#ffffff')
    def showFloatingMessage(self, message, icon, timeout, priority): self.messages.append(message)


class Guides:
    def __init__(self, xml='<guides artist="yes"/>'): self.xml, self.horizontal, self.vertical, self.visible = xml, [], [], False
    def toXml(self): return self.xml
    def fromXml(self, xml): self.xml = xml; self.horizontal = self.vertical = []; return True
    def setHorizontalGuides(self, values): self.horizontal = values
    def setVerticalGuides(self, values): self.vertical = values
    def setVisible(self, value): self.visible = value
    def removeAllGuides(self): self.horizontal = self.vertical = []


class Document(region_tests.Document):
    def __init__(self):
        super().__init__(); self.guides = Guides(); self.guide_changes = []
    def guidesConfig(self): return self.guides
    def setGuidesConfig(self, config): self.guides = config; self.guide_changes.append((list(config.horizontal), list(config.vertical), config.xml))
    def width(self): return 300
    def height(self): return 150


class CanvasViewTests(region_tests.RegionSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.h.doc = Document()
        self.h._creative_session.update(document_id=region_tests.native.module.document_id(self.h.doc), width=300, height=150)
        self.figure = self.artist_layer('Figure')
        self.view = View(self.h.doc, [self.figure])
        window = types.SimpleNamespace(activeView=lambda: self.view, views=lambda: [self.view])
        previous = view_module.Krita
        view_module.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(activeWindow=lambda: window, windows=lambda: [window]))
        self.addCleanup(setattr, view_module, 'Krita', previous)
        previous_icon = sys.modules.get('PyQt5.QtGui').__dict__.get('QIcon')
        sys.modules['PyQt5.QtGui'].QIcon = lambda: None
        self.addCleanup(lambda: setattr(sys.modules['PyQt5.QtGui'], 'QIcon', previous_icon) if previous_icon else delattr(sys.modules['PyQt5.QtGui'], 'QIcon'))

    def test_every_observation_says_which_layer_and_colours_the_artist_has(self):
        focus = self.h._view_artist_focus(self.h.doc)            # added to every observation as artist_focus
        self.assertEqual(focus, {'selected_layers': [{'id': self.figure.id, 'name': 'Figure'}], 'foreground': '#3a6ea5', 'background': '#ffffff'})
        self.view.doc = Document()                                  # the artist looks at another painting
        self.assertIsNone(self.h._view_artist_focus(self.h.doc))

    def test_an_operation_shows_a_short_message_on_the_canvas(self):
        region_tests.run(self.h, 'create_layer', {'name': 'Sky flats', 'type': 'paint'}, 'sky')
        self.assertEqual(self.view.messages, ['Creative Agent · Sky flats'])

    def test_list_brushes_returns_the_whole_library_and_only_takes_a_filter(self):
        asked = []
        self.h.cmd_list_brushes = lambda params: asked.append(params) or {'status': 'ok', 'brushes': [], 'count': 0, 'total': 154}
        region_tests.run(self.h, 'list_brushes', {})
        self.assertEqual(asked, [{'filter': '', 'limit': 500}], 'all 154 presets, not the first 80')
        with self.assertRaisesRegex(Exception, 'Unknown parameters'):
            region_tests.run(self.h, 'list_brushes', {'limit': 10})

    def test_guides_are_a_view_aid_restored_when_the_chat_ends(self):
        result = region_tests.run(self.h, 'guides', {'preset': 'thirds', 'horizon': 90})
        self.assertEqual((result['horizontal'], result['vertical']), ([50.0, 90.0, 100.0], [100.0, 200.0]))
        self.assertTrue(self.h.doc.guides.visible)
        self.assertEqual(self.h._creative_session.get('passes', []), [], 'no pass: guides are not paint')
        region_tests.run(self.h, 'guides', {'clear': True})
        self.assertEqual(self.h._creative_session['guides_prior'], '<guides artist="yes"/>', "the artist's guides, saved once")
        self.h.get_active_document = lambda: self.h.doc
        region_tests.run(self.h, 'end', {})
        self.assertEqual(self.h.doc.guide_changes[-1][2], '<guides artist="yes"/>')
        for params, message in (({}, 'Give a preset'), ({'preset': 'golden'}, 'preset must be'), ({'preset': 'horizon'}, 'needs horizon'),
                                ({'vertical': [400]}, 'vertical must be between'), ({'clear': True, 'preset': 'thirds'}, 'clear takes no other')):
            with self.assertRaisesRegex(ValueError, message):
                self.h._guides_validate(self.h.doc, params)


if __name__ == '__main__':
    unittest.main()

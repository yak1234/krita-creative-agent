# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Toska's colour themes: the two .colors files, the new-install default and the panel's matching colours.

- krita/data/themes/ToskaNight.colors and ToskaDay.colors have every section and key KritaDarkOrange.colors has, are
  installed, are named 'Toska Night' and 'Toska Day', and keep their text readable (WCAG contrast ratios: normal text 7:1
  on its backgrounds, inactive and other text 4.5:1, selection text 4.5:1 on the selection, focus decorations 3:1).
- The build named Toska opens a new install with 'Toska Night' through one CMake value, KRITA_APP_DEFAULT_THEME
  (cmake/modules/KritaAppIdentity.cmake), which writes the identity's own copy of kritarc; stock Krita's kritarc is
  untouched ('Krita dark'). Evaluated with cmake in script mode (no build).
- The panel (kritamcp/panel_theme.py) uses Toska's colours under a Toska theme, made from the same files.
"""
import configparser
import importlib.util
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[3]
THEMES = REPO / 'krita/data/themes'
NIGHT = THEMES / 'ToskaNight.colors'
DAY = THEMES / 'ToskaDay.colors'
REFERENCE = THEMES / 'KritaDarkOrange.colors'
KRITARC = REPO / 'krita/data/kritarc'
IDENTITY_CMAKE = REPO / 'cmake/modules/KritaAppIdentity.cmake'
IDENTITY_HEADER_IN = REPO / 'libs/global/config-app-identity.h.cmake'
PLUGIN = REPO / 'creative-agent/krita-mcp/krita-plugin/kritamcp'
CMAKE = shutil.which('cmake')

_spec = importlib.util.spec_from_file_location('panel_theme_under_test', PLUGIN / 'panel_theme.py')
panel_theme = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(panel_theme)

COLOR_SECTIONS = ('Window', 'View', 'Button', 'Selection', 'Tooltip', 'Complementary')


def scheme(path):
    parser = configparser.RawConfigParser(interpolation=None, strict=True)
    parser.optionxform = str                      # KConfig keys are case sensitive
    parser.read(path, encoding='utf-8')
    return parser


def hex_of(value):
    parts = [int(part) for part in value.split(',')]
    assert len(parts) == 3 and all(0 <= part <= 255 for part in parts), value
    return '#%02x%02x%02x' % tuple(parts)


def luminance(color):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def colors(path, section):
    return {key: hex_of(value) for key, value in scheme(path)['Colors:' + section].items()}


def contrast_rows(path):
    """(section, foreground key, background key, foreground, background, ratio, required) for every text and focus
    colour of every colour section, on both of its backgrounds."""
    rows = []
    for section in COLOR_SECTIONS:
        values = colors(path, section)
        for key, color in sorted(values.items()):
            if key.startswith('Background'):
                continue
            if key.startswith('Decoration'):
                need = 3.0
            elif key == 'ForegroundNormal' and section != 'Selection':
                need = 7.0
            else:
                need = 4.5
            for background in ('BackgroundNormal', 'BackgroundAlternate'):
                rows.append((section, key, background, color, values[background],
                             contrast(color, values[background]), need))
    return rows


class SchemeFileTest(unittest.TestCase):
    def test_every_section_and_key_of_krita_dark_orange(self):
        reference = scheme(REFERENCE)
        for path in (NIGHT, DAY):
            with self.subTest(path=path.name):
                parsed = scheme(path)
                self.assertEqual(sorted(parsed.sections()), sorted(reference.sections()))
                for section in reference.sections():
                    self.assertEqual(sorted(parsed[section]), sorted(reference[section]), section)

    def test_names(self):
        for path, name in ((NIGHT, 'Toska Night'), (DAY, 'Toska Day')):
            general = scheme(path)['General']
            self.assertEqual(general['Name'], name)            # the theme menu's entry and the kritarc value
            self.assertEqual(general['ColorScheme'], name)
        names = {scheme(path)['General']['Name'] for path in THEMES.glob('*.colors')}
        self.assertEqual(len(names), len(list(THEMES.glob('*.colors'))), 'two schemes share a name')

    def test_colour_values_are_rgb_triples(self):
        for path in (NIGHT, DAY):
            for section in scheme(path).sections():
                if section.startswith(('Colors:', 'WM')):
                    for key, value in scheme(path)[section].items():
                        hex_of(value)

    def test_installed(self):
        text = (THEMES / 'CMakeLists.txt').read_text()
        install = text[text.rindex('install(FILES'):]
        self.assertIn('ToskaNight.colors', install)
        self.assertIn('ToskaDay.colors', install)
        self.assertNotIn('FOUNDATION_BUILD', install, 'Toska themes are installed in every build, not only Foundation ones')

    def test_licence_header(self):
        for path in (NIGHT, DAY):
            head = path.read_text().splitlines()[:2]
            self.assertEqual(head[0], '# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>')
            self.assertEqual(head[1], '# SPDX-License-Identifier: GPL-2.0-or-later')


class ContrastTest(unittest.TestCase):
    def test_every_text_colour_reaches_its_ratio(self):
        for path in (NIGHT, DAY):
            for section, key, background, fg, bg, ratio, need in contrast_rows(path):
                with self.subTest(theme=path.stem, section=section, key=key, background=background):
                    self.assertGreaterEqual(ratio, need, '%s on %s is %.2f:1' % (fg, bg, ratio))

    def test_the_proposed_roles_are_kept(self):
        # The roles agreed with the lead; a value changes only in lightness when a ratio fails (then this list too)
        night = {('Window', 'BackgroundNormal'): '#141b25', ('View', 'BackgroundNormal'): '#0e141c',
                 ('View', 'BackgroundAlternate'): '#1a2330', ('Button', 'BackgroundNormal'): '#1f2a38',
                 ('Window', 'ForegroundNormal'): '#e9e3d8', ('Window', 'ForegroundInactive'): '#8e9bab',
                 ('Window', 'DecorationFocus'): '#e4502f', ('Window', 'DecorationHover'): '#e4502f',
                 ('Selection', 'BackgroundNormal'): '#b8432a', ('Selection', 'ForegroundNormal'): '#fff4e6',
                 ('View', 'ForegroundLink'): '#f0b27a', ('View', 'ForegroundVisited'): '#b98a6a',
                 ('View', 'ForegroundNeutral'): '#e8a24a', ('View', 'ForegroundPositive'): '#7fb38a',
                 ('Tooltip', 'BackgroundNormal'): '#1f2a38', ('Tooltip', 'ForegroundNormal'): '#f5e6cc'}
        day = {('Window', 'BackgroundNormal'): '#efe8dc', ('View', 'BackgroundNormal'): '#f8f4ec',
               ('View', 'BackgroundAlternate'): '#e7dfd0', ('Button', 'BackgroundNormal'): '#e2d8c6',
               ('Window', 'ForegroundNormal'): '#1b2430', ('Window', 'DecorationFocus'): '#c4432a',
               ('Selection', 'BackgroundNormal'): '#c4432a', ('Selection', 'ForegroundNormal'): '#fff8ee',
               ('View', 'ForegroundLink'): '#a2481f'}
        for path, roles in ((NIGHT, night), (DAY, day)):
            for (section, key), value in roles.items():
                with self.subTest(theme=path.stem, section=section, key=key):
                    self.assertEqual(colors(path, section)[key], value)

    def test_day_inactive_text_was_darkened_not_recoloured(self):
        # The proposed #5d6b7c is 4.47:1 on the window: the file keeps its hue and saturation, only the lightness drops
        import colorsys
        def hls(color):
            return colorsys.rgb_to_hls(*(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)))
        proposed = hls('#5d6b7c')
        self.assertLess(contrast('#5d6b7c', '#efe8dc'), 4.5)
        for section in ('Window', 'View', 'Button'):
            got = hls(colors(DAY, section)['ForegroundInactive'])
            self.assertAlmostEqual(got[0], proposed[0], delta=0.01)
            self.assertAlmostEqual(got[2], proposed[2], delta=0.03)
            self.assertLess(got[1], proposed[1])


def configure(folder):
    """Runs KritaAppIdentity.cmake in script mode with a settings folder. Returns (KRITA_APP_DEFAULT_THEME, the qrc text or
    None, the kritarc the qrc names (text) or None, the header's define)."""
    with tempfile.TemporaryDirectory(prefix='toska-theme-') as out:
        out = pathlib.Path(out)
        (out / 'probe.cmake').write_text(
            'set(CMAKE_SCRIPT_MODE_FILE "")\n'
            'set(CMAKE_BINARY_DIR "${OUT}")\n'
            'include("${REPO}/cmake/modules/KritaAppIdentity.cmake")\n'
            'configure_file("${REPO}/libs/global/config-app-identity.h.cmake" "${OUT}/config-app-identity.h")\n'
            'message("RESULT|${KRITA_APP_DEFAULT_THEME}|${KRITA_APP_IDENTITY_QRC}")\n')
        run = subprocess.run([CMAKE, f'-DREPO={REPO}', f'-DOUT={out}', f'-DKRITA_APP_SETTINGS_FOLDER={folder}',
                              '-P', str(out / 'probe.cmake')], capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, run.stderr
        line = next(l for l in run.stderr.splitlines() if l.startswith('RESULT|'))
        _, theme, qrc_path = line.split('|')
        qrc = kritarc = None
        if qrc_path:
            qrc = pathlib.Path(qrc_path).read_text()
            kritarc = pathlib.Path(re.search(r'<file alias="kritarc">([^<]+)</file>', qrc).group(1)).read_text()
        define = re.search(r'#define KRITA_APP_DEFAULT_THEME "([^"]*)"', (out / 'config-app-identity.h').read_text())
        return theme, qrc, kritarc, define.group(1) if define else None


def theme_of(kritarc_text):
    match = re.search(r'(?m)^\[theme\]\nTheme=(.*)$', kritarc_text)
    return match.group(1) if match else None


class DefaultThemeTest(unittest.TestCase):
    def test_stock_kritarc_keeps_krita_dark(self):
        self.assertEqual(theme_of(KRITARC.read_text()), 'Krita dark')
        self.assertIn('"Krita dark"', (REPO / 'libs/ui/thememanager.cpp').read_text())   # the code's own fallback

    def test_one_value_decides_tied_to_the_toska_identity(self):
        text = IDENTITY_CMAKE.read_text()
        self.assertRegex(text, r'set\(KRITA_APP_DEFAULT_THEME ""\)\nif \(_identity_is_toska\)\n'
                               r'    set\(KRITA_APP_DEFAULT_THEME "Toska Night"\)\nendif\(\)')
        self.assertIn('#define KRITA_APP_DEFAULT_THEME "@KRITA_APP_DEFAULT_THEME@"', IDENTITY_HEADER_IN.read_text())
        # stock Krita's qrc still names the source kritarc
        self.assertIn('set(KRITARC_PATH "${CMAKE_CURRENT_SOURCE_DIR}/data/kritarc")', (REPO / 'krita/CMakeLists.txt').read_text())

    def test_the_default_names_an_installed_theme(self):
        names = {scheme(path)['General']['Name'] for path in THEMES.glob('*.colors')}
        self.assertIn('Toska Night', names)
        self.assertIn('Krita dark', names)

    def test_every_identity(self):
        if not CMAKE:
            self.skipTest('cmake is not installed')
        stock = KRITARC.read_text()
        cases = {'KritaAgent': 'Toska Night', '': None, 'Other': 'Krita dark', 'Off': None, 'No': None}
        for folder, expected in cases.items():
            with self.subTest(folder=folder):
                theme, qrc, kritarc, define = configure(folder)
                self.assertEqual(define, theme, 'config-app-identity.h disagrees with CMake')
                if expected is None:                    # no settings folder: stock Krita, no identity qrc at all
                    self.assertEqual((theme, qrc), ('', None))
                    continue
                self.assertEqual(theme_of(kritarc), expected)
                self.assertIn('prefix="/kconfig/%s"' % folder, qrc)
                if folder == 'KritaAgent':
                    self.assertEqual(theme, 'Toska Night')
                    # the copy differs from the shipped kritarc in that one line only
                    self.assertEqual(kritarc.replace('Theme=Toska Night\n', 'Theme=Krita dark\n', 1), stock)
                else:
                    self.assertEqual(theme, '')
                    self.assertIn('krita/data/kritarc</file>', qrc)
        self.assertEqual(KRITARC.read_text(), stock, 'configuring changed the source kritarc')


class LineEndingTest(unittest.TestCase):
    def test_a_crlf_kritarc_keeps_its_line_endings(self):
        if not CMAKE:
            self.skipTest('cmake is not installed')
        with tempfile.TemporaryDirectory(prefix='toska-theme-crlf-') as tree:
            tree = pathlib.Path(tree)
            (tree / 'cmake/modules').mkdir(parents=True)
            (tree / 'krita/data').mkdir(parents=True)
            shutil.copy(IDENTITY_CMAKE, tree / 'cmake/modules/KritaAppIdentity.cmake')
            crlf = KRITARC.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            (tree / 'krita/data/kritarc').write_bytes(crlf)
            out = tree / 'build'
            out.mkdir()
            (out / 'probe.cmake').write_text(
                'set(CMAKE_SCRIPT_MODE_FILE "")\n'
                'set(CMAKE_BINARY_DIR "${OUT}")\n'
                'include("${TREE}/cmake/modules/KritaAppIdentity.cmake")\n'
                'message("RESULT|${KRITA_APP_IDENTITY_KRITARC}")\n')
            run = subprocess.run([CMAKE, f'-DTREE={tree}', f'-DOUT={out}', '-DKRITA_APP_SETTINGS_FOLDER=KritaAgent',
                                  '-P', str(out / 'probe.cmake')], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            path = next(l for l in run.stderr.splitlines() if l.startswith('RESULT|')).split('|')[1]
            copy = pathlib.Path(path).read_bytes()
            self.assertIn(b'\r\n[theme]\r\nTheme=Toska Night\r\n', copy)
            self.assertEqual(copy.replace(b'Theme=Toska Night\r\n', b'Theme=Krita dark\r\n', 1), crlf)


class ThemeManagerFallbackTest(unittest.TestCase):
    def test_an_unknown_theme_name_falls_back_to_krita_dark(self):
        # A name with no installed scheme (a removed .colors file, a typo in kritarc) gets Krita dark, not an empty
        # KSharedConfig whose defaults are light
        code = (REPO / 'libs/ui/thememanager.cpp').read_text()
        self.assertIn('d->themeMap.value(theme, d->themeMap.value(QStringLiteral("Krita dark")))', code)
        self.assertNotIn('d->themeMap.value(theme);', code)


class PanelColoursTest(unittest.TestCase):
    MAP = {'bg': ('Window', 'BackgroundNormal'), 'surface': ('View', 'BackgroundNormal'),
           'raised': ('Button', 'BackgroundNormal'), 'text': ('Window', 'ForegroundNormal'),
           'muted': ('Button', 'ForegroundInactive'), 'hover': ('Button', 'BackgroundAlternate'),
           'accent': ('Window', 'ForegroundActive'), 'button': ('Selection', 'BackgroundNormal'),
           'buttonText': ('Selection', 'ForegroundNormal')}

    def test_built_from_the_scheme_files(self):
        for path, panel in ((NIGHT, panel_theme.TOSKA_NIGHT), (DAY, panel_theme.TOSKA_DAY)):
            self.assertEqual(set(panel), set(panel_theme.PANEL_KEYS))
            self.assertEqual(set(panel_theme.DARK), set(panel_theme.PANEL_KEYS))
            for key, (section, role) in self.MAP.items():
                with self.subTest(theme=path.stem, key=key):
                    self.assertEqual(panel[key], colors(path, section)[role])
            self.assertEqual(panel_theme.TOSKA_WINDOWS[colors(path, 'Window')['BackgroundNormal']],
                             scheme(path)['General']['Name'])

    def test_panel_contrast(self):
        for panel in (panel_theme.TOSKA_NIGHT, panel_theme.TOSKA_DAY):
            for fg, bg, need in (('text', 'bg', 7), ('text', 'surface', 7), ('text', 'raised', 7), ('text', 'hover', 7),
                                 ('muted', 'bg', 4.5), ('muted', 'surface', 4.5), ('muted', 'raised', 4.5),
                                 ('buttonText', 'button', 4.5), ('bg', 'accent', 4.5), ('accent', 'surface', 3)):
                with self.subTest(fg=fg, bg=bg, panel=panel['bg']):
                    self.assertGreaterEqual(contrast(panel[fg], panel[bg]), need)

    def test_match_follows_a_toska_palette(self):
        c, dark = panel_theme.panel_colors('system', '#141b25')
        self.assertEqual((c, dark), (panel_theme.TOSKA_NIGHT, True))
        c, dark = panel_theme.panel_colors('system', '#EFE8DC')
        self.assertEqual((c, dark), (panel_theme.TOSKA_DAY, False))

    def test_name_decides_only_without_a_palette(self):
        self.assertEqual(panel_theme.panel_colors('system', None, 'Toska Night'), (panel_theme.TOSKA_NIGHT, True))
        self.assertEqual(panel_theme.panel_colors('system', None, 'Toska Day'), (panel_theme.TOSKA_DAY, False))
        # Krita applies the palette before it saves the name: with a palette, a Toska name alone never decides
        self.assertEqual(panel_theme.panel_colors('system', '#202020', 'Toska Night'), (panel_theme.DARK, True))
        self.assertEqual(panel_theme.panel_colors('system', '#f0f0f0', 'Toska Night'), (panel_theme.LIGHT, False))
        self.assertEqual(panel_theme.panel_colors('system', '#202020', 'Toska Day'), (panel_theme.DARK, True))

    def test_switching_away_from_toska_while_the_old_name_is_saved(self):
        # Toska Night -> Krita dark (window #474747): both dark, the saved name is still the old one
        self.assertEqual(panel_theme.panel_colors('system', '#474747', 'Toska Night'), (panel_theme.DARK, True))
        # Toska Day -> Krita bright: both light
        self.assertEqual(panel_theme.panel_colors('system', '#e6e6e6', 'Toska Day'), (panel_theme.LIGHT, False))
        # and towards Toska while the old name is saved
        self.assertEqual(panel_theme.panel_colors('system', '#141b25', 'Krita dark'), (panel_theme.TOSKA_NIGHT, True))
        self.assertEqual(panel_theme.panel_colors('system', '#efe8dc', 'Krita bright'), (panel_theme.TOSKA_DAY, False))

    def test_other_themes_keep_dark_and_light_by_lightness(self):
        self.assertEqual(panel_theme.panel_colors('system', '#1f1f1f', 'Krita dark orange'), (panel_theme.DARK, True))
        self.assertEqual(panel_theme.panel_colors('system', '#e0e0e0', 'Krita bright'), (panel_theme.LIGHT, False))
        self.assertEqual(panel_theme.panel_colors('system', None, None), (panel_theme.DARK, True))
        self.assertEqual(panel_theme.panel_colors('system', 'not a colour', 42), (panel_theme.DARK, True))

    def test_dark_and_light_choices_are_unchanged(self):
        for window in ('#141b25', '#efe8dc', None):
            self.assertEqual(panel_theme.panel_colors('dark', window, 'Toska Day'), (panel_theme.DARK, True))
            self.assertEqual(panel_theme.panel_colors('light', window, 'Toska Night'), (panel_theme.LIGHT, False))

    def test_returns_copies(self):
        c, _ = panel_theme.panel_colors('system', '#141b25')
        c['chevron'] = 'x'
        self.assertNotIn('chevron', panel_theme.TOSKA_NIGHT)

    def test_qt_lightness_decides_when_given(self):
        # The panel passes QColor.lightness(); the module's own estimate is within one of it
        self.assertEqual(panel_theme.panel_colors('system', '#808080', None, 127), (panel_theme.DARK, True))
        self.assertEqual(panel_theme.panel_colors('system', '#7f7f7f', None, 128), (panel_theme.LIGHT, False))
        self.assertEqual(panel_theme.panel_colors('system', '#202020', 'Toska Night', 200), (panel_theme.LIGHT, False))
        self.assertEqual(panel_theme.panel_colors('system', '#141b25', None, 200), (panel_theme.TOSKA_NIGHT, True))
        self.assertEqual(panel_theme.panel_colors('system', None, None, True), (panel_theme.DARK, True))  # not a number
        try:
            from PyQt5.QtGui import QColor
        except ImportError:
            self.skipTest('PyQt5 is not importable')
        if not hasattr(QColor('#000000'), 'lightness'):
            self.skipTest('another test replaced PyQt5.QtGui with a stub')
        for color in ('#141b25', '#efe8dc', '#808080', '#7f8081', '#ff0000', '#000000', '#ffffff', '#7d7408', '#03052a'):
            self.assertLessEqual(abs(panel_theme.lightness(color) - QColor(color).lightness()), 1, color)

    def test_docker_uses_the_module(self):
        source = (PLUGIN / 'creative_docker.py').read_text()
        self.assertIn('from .panel_theme import panel_colors', source)
        body = source[source.index('    def apply_theme('):]
        body = body[:body.index('\n    def ', 10)]
        self.assertIn('panel_colors(', body)
        self.assertIn('.lightness()', body)
        self.assertNotIn("'#1e1f22'", body, 'the colour dicts live in panel_theme.py')
        self.assertIn("readSetting('theme', 'Theme', '')", source)
        # one apply per palette change: no deferred re-check (it ran before Krita saved the name anyway)
        handler = source[source.index('    def event(self, event):'):]
        handler = handler[:handler.index('\n    def ', 10)]
        self.assertIn('ApplicationPaletteChange', handler)
        self.assertEqual(handler.count('apply_theme('), 1)
        self.assertNotIn('singleShot', handler)


if __name__ == '__main__':
    unittest.main()

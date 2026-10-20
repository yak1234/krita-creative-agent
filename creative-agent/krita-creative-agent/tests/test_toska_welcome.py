# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Toska's welcome page background: the shipped files cannot rot, and only the build named Toska has them.

krita/data/welcome/welcome-toska.qrc gives Toska's painting the alias :/welcome/toska-welcome.jpg. One value decides
everything: KRITA_APP_OWN_WELCOME (cmake/modules/KritaAppIdentity.cmake), true only for the build named Toska and never
on Android, like KRITA_APP_OWN_SPLASH. krita/CMakeLists.txt compiles the qrc in by it (no :/welcome resource in any
other build), and the generated config-app-identity.h hands it to KisAppIdentity::hasOwnWelcome(), which
KisWelcomePageWidget reads. These tests parse the files and, with cmake installed, evaluate the CMake code in script
mode (no build). KisWelcomeBackgroundLayoutTest (C++) checks the layout and the decoded painting after a build.
"""
import pathlib
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

REPO = pathlib.Path(__file__).resolve().parents[3]
WELCOME = REPO / 'krita/data/welcome'
QRC = WELCOME / 'welcome-toska.qrc'
PAINTING = WELCOME / 'toska/toska-welcome.jpg'
SOURCE = REPO / 'creative-agent/docs/branding/toska-welcome-source.png'
KRITA_CMAKE = REPO / 'krita/CMakeLists.txt'
IDENTITY_CMAKE = REPO / 'cmake/modules/KritaAppIdentity.cmake'
IDENTITY_HEADER_IN = REPO / 'libs/global/config-app-identity.h.cmake'
IDENTITY_H = REPO / 'libs/global/KisAppIdentity.h'
IDENTITY_CPP = REPO / 'libs/global/KisAppIdentity.cpp'
WIDGET_CPP = REPO / 'libs/ui/KisWelcomePageWidget.cpp'
WIDGET_H = REPO / 'libs/ui/KisWelcomePageWidget.h'
LAYOUT_H = REPO / 'libs/ui/KisWelcomeBackgroundLayout.h'
LAYOUT_TEST = REPO / 'libs/ui/tests/KisWelcomeBackgroundLayoutTest.cpp'
UI_TESTS_CMAKE = REPO / 'libs/ui/tests/CMakeLists.txt'
CMAKE = shutil.which('cmake')
ALIAS = ':/welcome/toska-welcome.jpg'


def qrc_files(path):
    """{(prefix, alias): file path} of a .qrc file."""
    files = {}
    for resource in ET.parse(path).getroot().iter('qresource'):
        for entry in resource.iter('file'):
            files[(resource.get('prefix'), entry.get('alias') or entry.text)] = path.parent / entry.text
    return files


def jpeg_size(data):
    """(width, height) from a JPEG's first start-of-frame marker, or None."""
    if data[:2] != b'\xff\xd8':
        return None
    at = 2
    while at + 4 <= len(data):
        if data[at] != 0xff:
            return None
        marker = data[at + 1]
        length = struct.unpack('>H', data[at + 2:at + 4])[0]
        if marker in (0xc0, 0xc1, 0xc2):
            height, width = struct.unpack('>HH', data[at + 5:at + 9])
            return width, height
        at += 2 + length
    return None


def png_size(data):
    return struct.unpack('>II', data[16:24]) if data[:8] == b'\x89PNG\r\n\x1a\n' else None


def welcome_qrc_block():
    """The lines of krita/CMakeLists.txt that set krita_welcome_qrc: the empty default and the if() block after it."""
    lines = KRITA_CMAKE.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(r'set\(krita_welcome_qrc ""\)$', line))
    end = next(i for i in range(start, len(lines)) if re.match(r'endif\s*\(', lines[i]))
    return '\n'.join(lines[start:end + 1])


def configure(folder, android):
    """Runs KritaAppIdentity.cmake, configures config-app-identity.h and runs the krita_welcome_qrc lines in cmake's
    script mode. Returns (KRITA_APP_OWN_WELCOME, KRITA_APP_OWN_SPLASH, the header's define, krita_welcome_qrc)."""
    with tempfile.TemporaryDirectory(prefix='toska-welcome-') as out:
        out = pathlib.Path(out)
        (out / 'block.cmake').write_text(welcome_qrc_block() + '\n')
        (out / 'probe.cmake').write_text(
            'set(CMAKE_SCRIPT_MODE_FILE "")\n'
            'set(CMAKE_BINARY_DIR "${OUT}")\n'
            'set(CMAKE_SOURCE_DIR "${REPO}")\n'
            + ('set(ANDROID TRUE)\n' if android else '')
            + 'include("${REPO}/cmake/modules/KritaAppIdentity.cmake")\n'
              'configure_file("${REPO}/libs/global/config-app-identity.h.cmake" "${OUT}/config-app-identity.h")\n'
              'include("${OUT}/block.cmake")\n'
              'message("RESULT|${KRITA_APP_OWN_WELCOME}|${KRITA_APP_OWN_SPLASH}|${krita_welcome_qrc}")\n')
        run = subprocess.run([CMAKE, f'-DREPO={REPO}', f'-DOUT={out}', f'-DKRITA_APP_SETTINGS_FOLDER={folder}',
                              '-P', str(out / 'probe.cmake')], capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, run.stderr
        line = next(l for l in run.stderr.splitlines() if l.startswith('RESULT|'))
        _, own, splash, qrc = line.split('|')
        header = (out / 'config-app-identity.h').read_text()
        define = re.search(r'#define KRITA_APP_OWN_WELCOME (\S+)', header)
        return own, splash, define.group(1) if define else None, qrc


class WelcomeFilesTest(unittest.TestCase):
    def test_qrc_lists_the_painting_under_the_alias_the_code_loads(self):
        files = qrc_files(QRC)
        self.assertEqual(set(files), {('/welcome', 'toska-welcome.jpg')})
        self.assertEqual(files[('/welcome', 'toska-welcome.jpg')], PAINTING)
        self.assertTrue(PAINTING.is_file())
        self.assertIn('QStringLiteral("%s")' % ALIAS, WIDGET_CPP.read_text())

    def test_painting_is_a_web_sized_copy_of_the_kept_source(self):
        self.assertTrue(SOURCE.is_file(), 'the artist\'s source stays in docs/branding')
        source = png_size(SOURCE.read_bytes())
        data = PAINTING.read_bytes()
        self.assertEqual(jpeg_size(data), source, 'the copy keeps the source\'s pixels (1774 x 887)')
        self.assertAlmostEqual(source[0] / source[1], 2.0, places=2)
        self.assertLessEqual(len(data), 600 * 1024)
        self.assertNotIn(b'ICC_PROFILE', data[:4096], 'untagged: Qt reads it as sRGB, as the source is')

    def test_artwork_is_marked_as_the_artists_without_a_licence(self):
        readme = (PAINTING.parent / 'README.md').read_text()
        self.assertIn('owned by the artist', readme)
        self.assertIn('licence to be decided', readme)
        self.assertIn('SPDX-License-Identifier: GPL-3.0-or-later', (PAINTING.parent / 'make_welcome.py').read_text())

    def test_stock_has_no_welcome_art(self):
        # Only the Toska qrc mentions the painting; no other qrc in the tree ships it
        for qrc in REPO.glob('krita/**/*.qrc'):
            if qrc != QRC:
                self.assertNotIn('toska-welcome', qrc.read_text(errors='replace'), qrc)


class WelcomeSelectionTest(unittest.TestCase):
    def test_the_define_follows_the_splash_rule_and_reaches_the_header(self):
        text = IDENTITY_CMAKE.read_text()
        self.assertRegex(text, r'set\(KRITA_APP_OWN_WELCOME 0\)\nif \(_identity_is_toska AND NOT ANDROID\)\n'
                               r'    set\(KRITA_APP_OWN_WELCOME 1\)\nendif\(\)')
        self.assertIn('#define KRITA_APP_OWN_WELCOME @KRITA_APP_OWN_WELCOME@', IDENTITY_HEADER_IN.read_text())
        self.assertIn('bool hasOwnWelcome()', IDENTITY_H.read_text())
        self.assertRegex(IDENTITY_CPP.read_text(), r'return KRITA_APP_OWN_WELCOME != 0;')

    def test_krita_cmake_adds_the_qrc_only_by_the_define(self):
        block = welcome_qrc_block()
        self.assertIn('if(KRITA_APP_OWN_WELCOME)', block)
        self.assertNotIn('KRITA_APP_SETTINGS_FOLDER', block, 'the folder name must not decide the welcome page')
        text = KRITA_CMAKE.read_text()
        qrcs = text[text.index('set(krita_QRCS'):text.index('CACHE INTERNAL "krita_QRCS"')]
        self.assertIn('    ${krita_welcome_qrc}\n', qrcs)
        self.assertNotIn('welcome-toska.qrc', qrcs, 'listed only through the variable, empty in other builds')

    def test_cmake_and_the_header_agree_for_every_identity(self):
        if not CMAKE:
            self.skipTest('cmake is not installed')
        cases = {
            # folder, android: own welcome, qrc
            ('KritaAgent', False): ('1', str(QRC)),
            ('KritaAgent', True): ('0', ''),
            ('', False): ('0', ''),
            ('', True): ('0', ''),
            ('Other', False): ('0', ''),     # another identity keeps upstream's plain page
            ('Off', False): ('0', ''),       # folder names CMake reads as false
            ('No', False): ('0', ''),
        }
        for (folder, android), (own, qrc) in cases.items():
            with self.subTest(folder=folder, android=android):
                got_own, splash, define, got_qrc = configure(folder, android)
                self.assertEqual((got_own, got_qrc), (own, qrc))
                self.assertEqual(define, own, 'config-app-identity.h disagrees with CMake')
                self.assertEqual(got_own, splash, 'the welcome page and the splash follow one rule')


class WelcomeCodeTest(unittest.TestCase):
    def test_the_widget_loads_the_painting_only_for_the_own_welcome(self):
        code = WIDGET_CPP.read_text()
        self.assertNotIn('settingsFolder()', code, 'the welcome page must not decide by the folder name')
        constructor = code[code.index('KisWelcomePageWidget::KisWelcomePageWidget('):]
        constructor = constructor[:constructor.index('\n}\n')]
        guard = constructor.index('if (KisAppIdentity::hasOwnWelcome()) {')
        self.assertLess(guard, constructor.index(ALIAS))
        self.assertEqual(code.count('QStringLiteral("%s")' % ALIAS), 1)

    def test_the_includes_the_painting_needs_are_unconditional(self):
        # Every build compiles paintEvent(), so what it needs must not sit inside an #if block (an earlier version put
        # them inside #ifdef Q_OS_ANDROID, and kritaui failed to compile on every desktop build)
        needed = {'<KisAppIdentity.h>', '"KisWelcomeBackgroundLayout.h"', '<QPainter>', '<QLinearGradient>',
                  '<QPaintEvent>', '<QTimer>'}
        found = set()
        depth = 0
        for line in WIDGET_CPP.read_text().splitlines():
            directive = re.match(r'\s*#\s*(\w+)\s*(.*)', line)
            if not directive:
                continue
            word, rest = directive.groups()
            if word in ('if', 'ifdef', 'ifndef'):
                depth += 1
            elif word == 'endif':
                depth -= 1
            elif word == 'include' and depth == 0:
                found.add(rest.split('//')[0].strip())
        self.assertEqual(depth, 0)
        self.assertEqual(needed - found, set(), 'included only under a preprocessor condition, or not at all')

    def test_without_the_painting_the_page_paints_as_upstream(self):
        code = WIDGET_CPP.read_text()
        body = code[code.index('void KisWelcomePageWidget::paintEvent('):]
        body = body[:body.index('\n}\n')]
        self.assertRegex(body, r'if \(m_ownBackground\.isNull\(\)\) \{\n\s+QWidget::paintEvent\(event\);\n\s+return;')
        self.assertIn('KisWelcomeBackgroundLayout::coverSourceRect(', body)
        self.assertIn('void paintEvent(QPaintEvent *event) override;', WIDGET_H.read_text())

    def test_the_scaled_painting_is_dropped_when_hidden_and_smoothed_after_a_resize(self):
        code = WIDGET_CPP.read_text()
        hide = code[code.index('void KisWelcomePageWidget::hideEvent('):]
        hide = hide[:hide.index('\n}\n')]
        self.assertIn('m_ownBackgroundScaled = QPixmap();', hide)
        resize = code[code.index('void KisWelcomePageWidget::resizeEvent('):]
        resize = resize[:resize.index('\n}\n')]
        self.assertIn('m_ownBackgroundResizing = true;', resize)
        self.assertIn('m_ownBackgroundSmoothTimer->start();', resize)
        self.assertIn('m_ownBackgroundSmoothTimer->setSingleShot(true);', code)
        self.assertIn('m_ownBackgroundSmoothTimer->setInterval(150);', code)
        self.assertIn('m_ownBackgroundResizing ? Qt::FastTransformation : Qt::SmoothTransformation', code)
        header = WIDGET_H.read_text()
        self.assertIn('void hideEvent(QHideEvent *event) override;', header)
        self.assertIn('void resizeEvent(QResizeEvent *event) override;', header)

    def test_only_the_welcome_page_paints_the_painting(self):
        # never behind or around the canvas: no other source in libs/ or krita/ touches the alias or hasOwnWelcome()
        users = set()
        for path in list((REPO / 'libs').rglob('*.cpp')) + list((REPO / 'libs').rglob('*.h')) + \
                list((REPO / 'krita').rglob('*.cc')) + list((REPO / 'krita').rglob('*.cpp')):
            text = path.read_text(errors='replace')
            if 'hasOwnWelcome' in text or 'toska-welcome' in text or 'KisWelcomeBackgroundLayout' in text:
                users.add(path.relative_to(REPO).as_posix())
        self.assertEqual(users, {'libs/global/KisAppIdentity.h', 'libs/global/KisAppIdentity.cpp',
                                 'libs/ui/KisWelcomePageWidget.cpp', 'libs/ui/KisWelcomePageWidget.h',
                                 'libs/ui/KisWelcomeBackgroundLayout.h',
                                 'libs/ui/tests/KisWelcomeBackgroundLayoutTest.cpp',
                                 'libs/ui/tests/KisWelcomeBackgroundLayoutTest.h'})

    def test_layout_numbers_and_test_main(self):
        numbers = dict(re.findall(r'inline constexpr qreal (k\w+) = ([\d.]+);', LAYOUT_H.read_text()))
        self.assertEqual(numbers, {'kAnchorX': '1.0', 'kAnchorY': '0.25', 'kVeil': '0.30', 'kVeilLight': '0.62',
                                   'kLeftShade': '0.88', 'kLeftFadeEnd': '0.45'})
        self.assertNotIn('static constexpr', LAYOUT_H.read_text(), 'namespace-scope constants are inline constexpr')
        test = LAYOUT_TEST.read_text()
        self.assertIn('QTEST_MAIN(KisWelcomeBackgroundLayoutTest)', test)
        self.assertIn('QCOMPARE(KisAppIdentity::hasOwnWelcome(), toskaFolder);', test)
        self.assertIn('TOSKA_WELCOME_DIR="${CMAKE_SOURCE_DIR}/krita/data/welcome/toska"', UI_TESTS_CMAKE.read_text())


if __name__ == '__main__':
    unittest.main()

# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Toska's splash screen: the shipped files cannot rot, and only a build with its own identity uses them.

krita/data/splash/splash-toska.qrc gives Toska's painting and banner the aliases KisSplashScreen loads (:/splash/0.png,
:/splash/banner.svg). One value decides everything: KRITA_APP_OWN_SPLASH (cmake/modules/KritaAppIdentity.cmake), true
only for the build named Toska and never on Android. krita/CMakeLists.txt picks the qrc by it, and the generated
config-app-identity.h hands it to KisAppIdentity::hasOwnSplash(), which every splash branch in the C++ reads.
These tests parse the files and, with cmake installed, evaluate the CMake code in script mode (no build); with Qt
importable they also let QtSvg find the logo frame and decode the picture.
"""
import base64
import io
import os
import pathlib
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

REPO = pathlib.Path(__file__).resolve().parents[3]
SPLASH = REPO / 'krita/data/splash'
TOSKA_QRC = SPLASH / 'splash-toska.qrc'
STOCK_QRC = SPLASH / 'splash.qrc'
BANNER = SPLASH / 'toska/banner.svg'
KRITA_CMAKE = REPO / 'krita/CMakeLists.txt'
IDENTITY_CMAKE = REPO / 'cmake/modules/KritaAppIdentity.cmake'
LAYOUT_H = REPO / 'libs/ui/KisSplashBannerLayout.h'
SPLASH_CPP = REPO / 'libs/ui/kis_splash_screen.cpp'
IDENTITY_HEADER_IN = REPO / 'libs/global/config-app-identity.h.cmake'
IDENTITY_H = REPO / 'libs/global/KisAppIdentity.h'
IDENTITY_CPP = REPO / 'libs/global/KisAppIdentity.cpp'
LAYOUT_TEST = REPO / 'libs/ui/tests/KisSplashBannerLayoutTest.cpp'
TOSKA_DIR = SPLASH / 'toska'
AGENT_FORK = REPO / 'AGENT-FORK.md'
SVG = '{http://www.w3.org/2000/svg}'
XLINK = '{http://www.w3.org/1999/xlink}'
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def qrc_files(path):
    """{(prefix, alias): file path} of a .qrc file."""
    files = {}
    for resource in ET.parse(path).getroot().iter('qresource'):
        for entry in resource.iter('file'):
            files[(resource.get('prefix'), entry.get('alias') or entry.text)] = path.parent / entry.text
    return files


def png_size(data):
    if data[:8] != PNG_MAGIC or data[12:16] != b'IHDR':
        return None
    return struct.unpack('>II', data[16:24])


def banner_parts():
    root = ET.parse(BANNER).getroot()
    view_box = [float(v) for v in root.get('viewBox').split()]
    frame = next(e for e in root.iter() if e.get('id') == 'toska-logo')
    images = list(root.iter(SVG + 'image'))
    return root, view_box, frame, images


def splash_qrc_block():
    """The if()...endif() block of krita/CMakeLists.txt that sets krita_splash_qrc, found by the assignment."""
    lines = KRITA_CMAKE.read_text().splitlines()
    sets = [i for i, line in enumerate(lines) if re.match(r'\s*set\(krita_splash_qrc\b', line)]
    assert sets, 'krita/CMakeLists.txt no longer sets krita_splash_qrc'
    start = next(i for i in range(sets[0], -1, -1) if re.match(r'if\s*\(', lines[i]))
    end = next(i for i in range(sets[-1], len(lines)) if re.match(r'endif\s*\(', lines[i]))
    return '\n'.join(lines[start:end + 1])


def splash_qrc_for(android, own_splash):
    """Evaluates that block in Python (if/elseif/else on single variables) for one configuration."""
    values = {'ANDROID': android, 'KRITA_APP_OWN_SPLASH': own_splash}
    chosen = None
    taking = False
    done = False
    for line in splash_qrc_block().splitlines():
        line = line.strip()
        head = re.match(r'(if|elseif)\s*\((\w+)\)$', line)
        if head:
            if head.group(2) not in values:
                raise AssertionError(f'unexpected condition {line!r} in the krita_splash_qrc block')
            taking = not done and values[head.group(2)]
            done = done or taking
        elif re.match(r'else\s*\(\)$', line):
            taking = not done
            done = True
        elif taking:
            match = re.match(r'set\(krita_splash_qrc ([\w.-]+)\)', line)
            chosen = match.group(1) if match else chosen
    return chosen


CMAKE = shutil.which('cmake')


def configure(folder, android):
    """Runs KritaAppIdentity.cmake, configures config-app-identity.h and runs the krita_splash_qrc block in cmake's
    script mode. Returns (display name, KRITA_APP_OWN_SPLASH, the header's define, krita_splash_qrc)."""
    with tempfile.TemporaryDirectory(prefix='toska-splash-') as out:
        out = pathlib.Path(out)
        (out / 'block.cmake').write_text(splash_qrc_block() + '\n')
        (out / 'probe.cmake').write_text(
            'set(CMAKE_SCRIPT_MODE_FILE "")\n'
            'set(CMAKE_BINARY_DIR "${OUT}")\n'
            + ('set(ANDROID TRUE)\n' if android else '')
            + 'include("${REPO}/cmake/modules/KritaAppIdentity.cmake")\n'
              'configure_file("${REPO}/libs/global/config-app-identity.h.cmake" "${OUT}/config-app-identity.h")\n'
              'include("${OUT}/block.cmake")\n'
              'message("RESULT|${KRITA_APP_DISPLAY_NAME}|${KRITA_APP_OWN_SPLASH}|${krita_splash_qrc}")\n')
        run = subprocess.run([CMAKE, f'-DREPO={REPO}', f'-DOUT={out}', f'-DKRITA_APP_SETTINGS_FOLDER={folder}',
                              '-P', str(out / 'probe.cmake')], capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, run.stderr
        line = next(l for l in run.stderr.splitlines() if l.startswith('RESULT|'))
        _, name, own, qrc = line.split('|')
        header = (out / 'config-app-identity.h').read_text()
        define = re.search(r'#define KRITA_APP_OWN_SPLASH (\S+)', header)
        return name, own, define.group(1) if define else None, qrc


def png_chunks(data):
    chunks, at = [], 8
    while at < len(data):
        length, kind = struct.unpack('>I4s', data[at:at + 8])
        chunks.append((kind, data[at + 8:at + 8 + length]))
        at += 12 + length
    return chunks


class ToskaQrcTest(unittest.TestCase):
    def test_lists_existing_files_under_the_aliases_the_code_loads(self):
        files = qrc_files(TOSKA_QRC)
        self.assertEqual(set(files), {('/splash', '0.png'), ('/splash', 'banner.svg')})
        for key, path in files.items():
            self.assertTrue(path.is_file(), f'{key}: {path}')
        self.assertEqual(files[('/splash', 'banner.svg')], BANNER)
        # KisSplashScreen asks for exactly these two (and :/krita-branding.svgz, which it hides for an identity build)
        code = SPLASH_CPP.read_text()
        self.assertIn('":/splash/0.png"', code)
        self.assertIn('":/splash/banner.svg"', code)

    def test_painting_is_a_2_to_1_png_under_3_mb(self):
        painting = qrc_files(TOSKA_QRC)[('/splash', '0.png')]
        data = painting.read_bytes()
        size = png_size(data)
        self.assertIsNotNone(size, 'the alias 0.png must hold a PNG')
        width, height = size
        self.assertAlmostEqual(width / height, 2.0, places=2)
        self.assertGreaterEqual(height, 480, 'smaller than the splash KisSplashScreen(480) shows')
        self.assertLess(len(data), 3 * 1024 * 1024)

    def test_painting_is_tagged_srgb(self):
        chunks = png_chunks(qrc_files(TOSKA_QRC)[('/splash', '0.png')].read_bytes())
        kinds = [kind for kind, _ in chunks]
        self.assertIn(b'sRGB', kinds)
        self.assertLess(kinds.index(b'sRGB'), kinds.index(b'IDAT'))

    def test_artwork_is_marked_as_the_artists_without_a_licence(self):
        readme = (TOSKA_DIR / 'README.md').read_text()
        self.assertIn('owned by the artist', readme)
        self.assertIn('licence to be decided', readme)
        self.assertNotIn('SPDX-License-Identifier', BANNER.read_text())
        self.assertIn('SPDX-License-Identifier: GPL-3.0-or-later', (TOSKA_DIR / 'make_banner.py').read_text())
        fork = AGENT_FORK.read_text()
        self.assertIn('artwork owned by the artist, licence to be decided', fork)

    def test_stock_qrc_is_upstreams(self):
        files = qrc_files(STOCK_QRC)
        self.assertIn(('/splash', 'banner.svg'), files)
        self.assertRegex(files[('/splash', '0.png')].name, r'^electrichearts_.*_4K\.png$')
        self.assertNotIn('toska', STOCK_QRC.read_text().lower())
        self.assertNotIn('toska', (SPLASH / 'banner.svg').read_text().lower())


class ToskaBannerTest(unittest.TestCase):
    def test_parses_and_embeds_one_png_the_size_of_its_view_box(self):
        root, view_box, frame, images = banner_parts()
        self.assertEqual(root.tag, SVG + 'svg')
        self.assertEqual(view_box[:2], [0.0, 0.0])
        self.assertEqual(len(images), 1)
        href = images[0].get(XLINK + 'href') or images[0].get('href')
        self.assertTrue(href.startswith('data:image/png;base64,'), href[:40])
        data = base64.b64decode(href.split(',', 1)[1], validate=True)
        self.assertEqual(png_size(data), (int(view_box[2]), int(view_box[3])))
        kinds = [kind for kind, _ in png_chunks(data)]
        self.assertIn(b'sRGB', kinds, 'the logo is sRGB: tag the embedded PNG')
        self.assertLess(kinds.index(b'sRGB'), kinds.index(b'IDAT'))
        # no Krita lettering left over, nothing fetched from outside
        self.assertNotIn('KRITA', BANNER.read_text())
        self.assertEqual(sum(1 for e in root.iter() if (e.get(XLINK + 'href') or '').startswith('http')), 0)

    def test_logo_frame_is_inside_the_view_box_and_3_to_1(self):
        _, view_box, frame, _ = banner_parts()
        x, y, w, h = (float(frame.get(k)) for k in ('x', 'y', 'width', 'height'))
        self.assertEqual((frame.get('fill'), frame.get('stroke')), ('none', 'none'), 'the frame must not draw')
        self.assertTrue(0 <= x and 0 <= y and x + w <= view_box[2] and y + h <= view_box[3])
        self.assertAlmostEqual(w / h, 3.0, delta=0.05)

    def test_halo_is_light_and_fades_out_before_the_edge(self):
        from PIL import Image
        _, view_box, frame, images = banner_parts()
        href = images[0].get(XLINK + 'href') or images[0].get('href')
        image = Image.open(io.BytesIO(base64.b64decode(href.split(',', 1)[1]))).convert('RGBA')
        width, height = image.size
        edge = [image.getpixel((x, 0))[3] for x in range(width)] + [image.getpixel((x, height - 1))[3] for x in range(width)]
        edge += [image.getpixel((0, y))[3] for y in range(height)] + [image.getpixel((width - 1, y))[3] for y in range(height)]
        self.assertEqual(max(edge), 0, 'the halo is clipped at the banner edge')
        # just outside the logo's lettering the halo is light, faint and never opaque
        x, y = int(float(frame.get('x'))), int(float(frame.get('y')))
        halo = [image.getpixel((px, py)) for px in range(x - 20, x + int(float(frame.get('width'))) + 20, 7)
                for py in range(4, y - 4, 3)]
        lit = [p for p in halo if p[3] > 0]
        self.assertTrue(lit, 'no halo above the logo')
        self.assertLess(max(p[3] for p in lit), 160, 'the halo is not subtle')
        self.assertTrue(all(min(p[:3]) >= 180 for p in lit if p[3] > 8), 'the halo is not light')

    def test_qtsvg_finds_the_logo_frame_and_decodes_the_picture(self):
        try:
            from PyQt5.QtSvg import QSvgRenderer
            from PyQt5.QtGui import QImage, QPainter
        except ImportError:
            self.skipTest('PyQt5 with QtSvg is not importable')
        _, view_box, frame, _ = banner_parts()
        renderer = QSvgRenderer(str(BANNER))
        self.assertTrue(renderer.isValid())
        self.assertTrue(renderer.elementExists('toska-logo'))
        bounds = renderer.boundsOnElement('toska-logo')
        self.assertEqual((bounds.x(), bounds.y(), bounds.width(), bounds.height()),
                         tuple(float(frame.get(k)) for k in ('x', 'y', 'width', 'height')))
        image = QImage(int(view_box[2]) // 2, int(view_box[3]) // 2, QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        opaque = sum(1 for y in range(0, image.height(), 4) for x in range(0, image.width(), 4)
                     if (image.pixel(x, y) >> 24) & 0xff > 200)
        self.assertGreater(opaque, 100)


class ToskaSplashSelectionTest(unittest.TestCase):
    def test_krita_cmake_picks_the_qrc_by_the_one_define(self):
        self.assertEqual(splash_qrc_for(android=False, own_splash=True), 'splash-toska.qrc')
        self.assertEqual(splash_qrc_for(android=False, own_splash=False), 'splash.qrc')
        self.assertEqual(splash_qrc_for(android=True, own_splash=False), 'splash-android.qrc')
        block = splash_qrc_block()
        self.assertIn('KRITA_APP_OWN_SPLASH', block)
        self.assertNotIn('KRITA_APP_SETTINGS_FOLDER', block, 'the folder name must not decide the splash')
        self.assertIn('${CMAKE_SOURCE_DIR}/krita/data/splash/${krita_splash_qrc}', KRITA_CMAKE.read_text())

    def test_the_define_is_computed_with_strequal_and_reaches_the_header(self):
        text = IDENTITY_CMAKE.read_text()
        self.assertRegex(text, r'set\(KRITA_APP_OWN_SPLASH 0\)')
        self.assertRegex(text, r'STREQUAL "KritaAgent"')
        self.assertRegex(text, r'NOT ANDROID')
        self.assertIn('#define KRITA_APP_OWN_SPLASH @KRITA_APP_OWN_SPLASH@', IDENTITY_HEADER_IN.read_text())

    def test_cmake_and_the_header_agree_for_every_identity(self):
        if not CMAKE:
            self.skipTest('cmake is not installed')
        cases = {
            # folder, android: display name, own splash, qrc
            ('KritaAgent', False): ('Toska', '1', 'splash-toska.qrc'),
            ('KritaAgent', True): ('Toska', '0', 'splash-android.qrc'),
            ('', False): ('Krita', '0', 'splash.qrc'),
            ('', True): ('Krita', '0', 'splash-android.qrc'),
            ('Other', False): ('Other', '0', 'splash.qrc'),   # another identity keeps upstream's art
            ('Off', False): ('Krita', '0', 'splash.qrc'),     # a folder name CMake reads as false
            ('No', False): ('Krita', '0', 'splash.qrc'),
        }
        for (folder, android), (name, own, qrc) in cases.items():
            with self.subTest(folder=folder, android=android):
                got_name, got_own, define, got_qrc = configure(folder, android)
                self.assertEqual((got_name, got_own, got_qrc), (name, own, qrc))
                self.assertEqual(define, own, 'config-app-identity.h disagrees with CMake')

    def test_the_fork_configures_with_a_settings_folder(self):
        # Pins "KritaAgent": the later migration (AGENT-FORK.md, "Product name: Toska") renames it here too
        text = IDENTITY_CMAKE.read_text()
        match = re.search(r'set\(KRITA_APP_SETTINGS_FOLDER "([^"]*)" CACHE STRING', text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), 'KritaAgent')
        # krita/CMakeLists.txt reads the define after the identity module set it
        top = (REPO / 'CMakeLists.txt').read_text()
        self.assertLess(top.index('KritaAppIdentity'), top.index('add_subdirectory(krita)'))
        self.assertIn('test_the_fork_configures_with_a_settings_folder', AGENT_FORK.read_text())

    def test_every_cpp_splash_branch_reads_has_own_splash(self):
        self.assertIn('bool hasOwnSplash()', IDENTITY_H.read_text())
        self.assertRegex(IDENTITY_CPP.read_text(), r'return KRITA_APP_OWN_SPLASH != 0;')
        code = SPLASH_CPP.read_text()
        self.assertNotIn('settingsFolder()', code, 'the splash must not decide by the folder name')
        # the title, the layout and the credit (getImageSource) each ask
        self.assertGreaterEqual(code.count('KisAppIdentity::hasOwnSplash()'), 3)
        for function in ('KisSplashScreen::KisSplashScreen', 'void KisSplashScreen::updateSplashImage',
                         'KisSplashScreen::Source KisSplashScreen::getImageSource'):
            body = code[code.index(function):]
            body = body[:body.index('\n}\n')]
            self.assertIn('hasOwnSplash()', body, function)
        # Krita's logo is not even loaded for Toska
        self.assertRegex(code, r'ownSplash \? new QSvgWidget\(m_lblSplash\)\s*: new QSvgWidget\(QStringLiteral\(":/krita-branding.svgz"\)')

    def test_android_and_stock_stay_upstream(self):
        code = SPLASH_CPP.read_text()
        for upstream in ('addDropShadow(m_bannerSvg);', 'i18nc("Normal splash artist name", "Tyson Tan")',
                         'm_brandingSvg->move(m_bannerSvg->x() - m_brandingSvg->width(), marginTop);',
                         'QStringLiteral(":/splash/hd.jpg")', 'i18n("Krita")'):
            self.assertIn(upstream, code)
        self.assertEqual(splash_qrc_for(android=True, own_splash=False), 'splash-android.qrc')
        self.assertRegex(IDENTITY_CMAKE.read_text(), r'NOT ANDROID')

    def test_layout_numbers_and_test_main(self):
        layout = LAYOUT_H.read_text()
        numbers = dict(re.findall(r'constexpr qreal (k\w+) = ([\d.]+);', layout))
        self.assertEqual(numbers, {'kLeft': '0.035', 'kTop': '0.30', 'kWidth': '0.36'})
        self.assertIn('"toska-logo"', SPLASH_CPP.read_text())
        test = LAYOUT_TEST.read_text()
        self.assertIn('QTEST_MAIN(KisSplashBannerLayoutTest)', test)
        self.assertNotIn('QTEST_GUILESS_MAIN', test)


if __name__ == '__main__':
    unittest.main()

# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the packaged app says about itself: the build record (which commit, where the source is) and the licence notices.

Everything that can be read from the thing shipped is read from it (the FFmpeg libraries' own licence and configuration
strings, the wheels' METADATA and the libraries they carry, Qt's version): nothing here is a hand-written claim about what is
inside. Used by agent/package_app.py; Python 3.9 compatible, standard library only.
"""
import datetime
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_URL = 'https://github.com/yak1234/krita-creative-agent'
DEFAULT_BRANCH = 'main'
UPSTREAM_URL = 'https://invent.kde.org/graphics/krita.git'
NOT_PUBLISHED = 'not published yet'


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo)] + list(args), capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ''


# ------------------------------------------------------------------------------------------------------- the build record

def publish_map(repo):
    """{local commit: public commit} from <git-dir>/publish-map, if the checkout has one."""
    common = git(repo, 'rev-parse', '--git-common-dir')
    mapping = {}
    if not common:
        return mapping
    path = Path(common) if Path(common).is_absolute() else Path(repo) / common
    try:
        for line in (path / 'publish-map').read_text().splitlines():
            parts = line.split()
            if len(parts) == 2:
                mapping[parts[0]] = parts[1]
    except OSError:
        pass
    return mapping


def build_record(source, built_from, packaging_root=ROOT, source_url=DEFAULT_SOURCE_URL, allow_dirty=False,
                 allow_stale=False, allow_unpublished=False, remote='public', branch=DEFAULT_BRANCH):
    """(record, problems). `built_from` is the hash the Krita executable reports. A problem is a reason to refuse that the
    matching allow flag turns into a note in the record; the rest of the problems stay problems."""
    record = {'commit': '', 'public_commit': NOT_PUBLISHED, 'source': source_url, 'branch': branch, 'built_from': built_from or '',
              'head': '', 'notes': [], 'date': datetime.date.today().isoformat()}
    problems = []
    head = git(source, 'rev-parse', 'HEAD')
    if not head:
        return record, ['%s is not a git checkout: the build cannot be tied to a commit' % source]
    record['head'] = head
    full = git(source, 'rev-parse', '--verify', '--quiet', '%s^{commit}' % built_from) if built_from else ''
    if not full:
        if allow_stale:
            record['notes'].append('stale build: the executable reports %r, which is not in the checkout' % (built_from or 'nothing'))
            full = head
        else:
            problems.append('the executable reports commit %r, which is not in %s (use --allow-stale-build to package it anyway)'
                            % (built_from or 'none', source))
    record['commit'] = full
    if full and full != head:
        if allow_stale:
            record['notes'].append('stale build: binaries from %s, checkout HEAD %s' % (full[:12], head[:12]))
        else:
            problems.append('the build is not from HEAD: binaries from %s, checkout at %s (rebuild, or --allow-stale-build)'
                            % (full[:12], head[:12]))
    dirty = []
    for name, repo in (('source', source), ('packaging', packaging_root)):
        if git(repo, 'status', '--porcelain', '--untracked-files=no'):
            dirty.append(name)
    if dirty:
        if allow_dirty:
            record['notes'].append('dirty tree (uncommitted changes in: %s)' % ', '.join(dirty))
        else:
            problems.append('the %s tree has uncommitted changes (commit them, or use --allow-dirty)' % ' and '.join(dirty))
    public = publish_map(source).get(full, '') if full else ''
    published = False
    if public and git(source, 'cat-file', '-t', public) == 'commit':
        published = subprocess.run(['git', '-C', str(source), 'merge-base', '--is-ancestor', public, '%s/%s' % (remote, branch)],
                                   capture_output=True).returncode == 0
    if published:
        record['public_commit'] = public
    elif allow_unpublished:
        record['notes'].append('the commit is not in %s/%s yet: the source offer points at a commit that is not published' % (remote, branch))
    else:
        problems.append('commit %s is not in %s/%s (publish first, or use --allow-unpublished)' % (full[:12], remote, branch))
    return record, problems


def record_text(record):
    return ('Krita Agent\n'
            'build commit: %(commit)s\n'
            'public commit: %(public_commit)s\n'
            'source: %(source)s\n'
            'branch: %(branch)s\n'
            'program files built from: %(built_from)s\n'
            'packaged from checkout HEAD: %(head)s\n'
            'notes: %(notes)s\n'
            'date: %(date)s\n'
            'licences: Resources/LICENSES\n' % dict(record, notes='; '.join(record['notes']) or 'none'))


def parse_record(text):
    """The inverse of record_text (what the About box reads, in C++, with the same rule)."""
    found = {}
    for line in text.splitlines():
        key, sep, value = line.partition(':')
        if sep:
            found.setdefault(key.strip(), value.strip())
    return found


def plist_entries(record):
    return {'KritaAgentBuild': record['commit'], 'KritaAgentPublicCommit': record['public_commit'],
            'KritaAgentSource': record['source'], 'KritaAgentBinariesBuiltFrom': record['built_from'] or 'unknown',
            'KritaAgentPackagedHead': record['head'], 'KritaAgentNotes': '; '.join(record['notes']),
            'KritaAgentBuildDate': record['date']}


def source_statement(record):
    """One sentence for the source offer, from the record: the URL and the exact commit."""
    commit = record['public_commit'] if record['public_commit'] != NOT_PUBLISHED else record['commit']
    text = 'commit %s of %s (branch %s)' % (commit, record['source'], record['branch'])
    if record['public_commit'] != NOT_PUBLISHED and record['commit'] != record['public_commit']:
        text += '; in the local development repository the same tree is commit %s' % record['commit']
    if record['public_commit'] == NOT_PUBLISHED:
        text += ' (this commit is not published yet)'
    return text


# ----------------------------------------------------------------------------------------------- facts read from the shipped files

def strings_of(path):
    result = subprocess.run(['strings', '-a', str(path)], capture_output=True, text=True)
    return result.stdout.splitlines() if result.returncode == 0 else []


def ffmpeg_facts(libavutil):
    """The licence, version and configuration FFmpeg's libavutil reports about itself, from its own strings."""
    facts = {'license': '', 'version': '', 'configuration': ''}
    for line in strings_of(libavutil):
        match = re.search(r'(L?GPL version [0-9.]+( or later)?|Nonfree and unredistributable)\s*$', line)
        if not facts['license'] and match and len(line) < 80:
            facts['license'] = match.group(1)
        elif not facts['version'] and re.fullmatch(r'\d+\.\d+(\.\d+)?(-[\w.]+)?-g[0-9a-f]{7,40}', line):
            facts['version'] = line
        elif not facts['configuration'] and re.match(r'(--|-D)\w', line) and (' --enable-' in line or ' -Dlib' in line or '--enable-' in line[:40]):
            facts['configuration'] = line
    if not facts['version']:                      # a Homebrew build names its version in the install prefix
        match = re.search(r'/ffmpeg/(\d+\.\d+(?:\.\d+)?)', facts['configuration'])
        facts['version'] = match.group(1) if match else ''
    return facts


# libraries FFmpeg can be configured with: (name, licence, where the source is)
FFMPEG_LIBRARIES = {
    'libaom': ('libaom (AV1)', 'BSD-2-Clause with the AOMedia patent licence', 'https://aomedia.googlesource.com/aom'),
    'libwebp': ('libwebp', 'BSD-3-Clause', 'https://chromium.googlesource.com/webm/libwebp'),
    'libvpx': ('libvpx (VP8/VP9)', 'BSD-3-Clause', 'https://chromium.googlesource.com/webm/libvpx'),
    'libopenh264': ('OpenH264', 'BSD-2-Clause', 'https://github.com/cisco/openh264'),
    'libtheora': ('libtheora', 'BSD-3-Clause', 'https://xiph.org/theora/'),
    'libmp3lame': ('LAME (MP3)', 'LGPL-2.0-or-later', 'https://lame.sourceforge.io/ (source: https://sourceforge.net/projects/lame/files/lame/)'),
    'libopus': ('Opus', 'BSD-3-Clause', 'https://opus-codec.org/'),
    'libvorbis': ('libvorbis', 'BSD-3-Clause', 'https://xiph.org/vorbis/'),
    'libx264': ('x264', 'GPL-2.0-or-later', 'https://www.videolan.org/developers/x264.html'),
    'libx265': ('x265', 'GPL-2.0-only', 'https://bitbucket.org/multicoreware/x265_git'),
    'libdav1d': ('dav1d', 'BSD-2-Clause', 'https://code.videolan.org/videolan/dav1d'),
    'librav1e': ('rav1e', 'BSD-2-Clause', 'https://github.com/xiph/rav1e'),
    'libsvtav1': ('SVT-AV1', 'BSD-2-Clause with the AOMedia patent licence', 'https://gitlab.com/AOMediaCodec/SVT-AV1'),
    'libvidstab': ('vid.stab', 'GPL-2.0-or-later', 'https://github.com/georgmartius/vid.stab'),
    'libvmaf': ('libvmaf', 'BSD-2-Clause with a patent licence', 'https://github.com/Netflix/vmaf'),
    'libxvid': ('Xvid', 'GPL-2.0-or-later', 'https://www.xvid.com/'),
    'librubberband': ('Rubber Band', 'GPL-2.0-or-later', 'https://breakfastquay.com/rubberband/'),
    'libtesseract': ('Tesseract', 'Apache-2.0', 'https://github.com/tesseract-ocr/tesseract'),
    'libass': ('libass', 'ISC', 'https://github.com/libass/libass'),
    'libopenjpeg': ('OpenJPEG', 'BSD-2-Clause', 'https://www.openjpeg.org/'),
    'libspeex': ('Speex', 'BSD-3-Clause', 'https://www.speex.org/'),
    'libsoxr': ('SoX resampler', 'LGPL-2.1-or-later', 'https://sourceforge.net/projects/soxr/'),
    'libzmq': ('ZeroMQ', 'MPL-2.0', 'https://zeromq.org/'),
    'libzimg': ('zimg', 'WTFPL-2.0', 'https://github.com/sekrit-twc/zimg'),
    'libbluray': ('libbluray', 'LGPL-2.1-or-later', 'https://www.videolan.org/developers/libbluray.html'),
    'libjxl': ('libjxl (JPEG XL)', 'BSD-3-Clause', 'https://github.com/libjxl/libjxl'),
    'libsrt': ('SRT', 'MPL-2.0', 'https://github.com/Haivision/srt'),
    'librist': ('librist', 'BSD-2-Clause', 'https://code.videolan.org/rist/librist'),
    'libsnappy': ('Snappy', 'BSD-3-Clause', 'https://github.com/google/snappy'),
    'libssh': ('libssh', 'LGPL-2.1-or-later', 'https://www.libssh.org/'),
    'libaribb24': ('aribb24', 'LGPL-3.0-or-later', 'https://github.com/nkoriyama/aribb24'),
    'libopencore-amrnb': ('OpenCORE AMR-NB', 'Apache-2.0', 'https://opencore-amr.sourceforge.io/'),
    'libopencore-amrwb': ('OpenCORE AMR-WB', 'Apache-2.0', 'https://opencore-amr.sourceforge.io/'),
    'libharfbuzz': ('HarfBuzz', 'MIT', 'https://harfbuzz.github.io/'),
    'libxml2': ('libxml2', 'MIT', 'https://gitlab.gnome.org/GNOME/libxml2'),
    'libfontconfig': ('Fontconfig', 'MIT-style', 'https://www.freedesktop.org/wiki/Software/fontconfig/'),
    'libfreetype': ('FreeType', 'FreeType licence or GPL-2.0', 'https://freetype.org/'),
    'frei0r': ('frei0r', 'GPL-2.0-or-later', 'https://frei0r.dyne.org/'),
    'gnutls': ('GnuTLS', 'LGPL-2.1-or-later', 'https://www.gnutls.org/'),
    'sdl2': ('SDL2', 'Zlib', 'https://libsdl.org/'),
    'zlib': ('zlib', 'Zlib', 'https://zlib.net/'),
}


def ffmpeg_libraries(configuration):
    """Names of the external libraries a configuration string enables (meson -Dlibx=enabled or --enable-libx)."""
    names = [n for n in re.findall(r'--enable-([\w-]+)', configuration) if n in FFMPEG_LIBRARIES or n.startswith('lib')]
    names += [n for n in re.findall(r'-D(lib\w+)=enabled', configuration) if not n.endswith(('_encoder', '_decoder', '_muxer', '_demuxer'))]
    names += [n for n in ('sdl2', 'zlib') if re.search(r'-D%s=enabled' % n, configuration)]
    return sorted(set(names))


def ffmpeg_notice(libavutil, label='FFmpeg', recipe='the exact build recipe is ext_ffmpeg in krita-deps-management (see the Qt note for its address).'):
    facts = ffmpeg_facts(libavutil)
    release = facts['version'].split('-')[0]
    lines = ['%s %s (ffmpeg, ffprobe and the libav*/libsw* libraries)' % (label, facts['version'] or '(version unknown)'),
             '  licence reported by the shipped libavutil: %s' % (facts['license'] or 'not found: treat as GPL-3.0-or-later')]
    if facts['license'].startswith('LGPL'):
        lines.append('  configured without --enable-gpl, --enable-version3 or --enable-nonfree (the library says LGPL); FFmpeg itself stays under')
        lines.append('  the LGPL inside the GPL-3.0-or-later whole work.')
    else:
        lines.append('  This FFmpeg is configured with --enable-gpl%s: it is a GPL work, which the GPL-3.0-or-later whole work permits.' %
                     (' --enable-version3' if '--enable-version3' in facts['configuration'] else ''))
    libraries = ffmpeg_libraries(facts['configuration'])
    if libraries:
        lines.append('  codec and format libraries it is configured with (from its configuration string):')
        for name in libraries:
            info = FFMPEG_LIBRARIES.get(name)
            lines.append('    %-18s %s' % (name, ('%s: %s, source %s' % info) if info else 'see the FFmpeg configuration'))
    lines.append('  FFmpeg source: https://ffmpeg.org/download.html (release %s; tarball https://ffmpeg.org/releases/ffmpeg-%s.tar.xz);'
                 % (release or 'see version', release or 'VERSION'))
    if 'homebrew' in facts['configuration'].lower():
        lines.append('  built by Homebrew (formula ffmpeg): https://github.com/Homebrew/homebrew-core/blob/master/Formula/f/ffmpeg.rb')
    else:
        lines.append('  ' + recipe)
    return lines


def qt_facts(frameworks):
    plist = Path(frameworks) / 'QtCore.framework' / 'Versions' / 'A' / 'Resources' / 'Info.plist'
    try:
        import plistlib
        with open(plist, 'rb') as stream:
            return plistlib.load(stream).get('CFBundleShortVersionString', '')
    except (OSError, ValueError, ImportError):
        return ''


def deps_recipe(source):
    """(address, commit) of the krita-deps-management checkout the Qt and dependency builds came from, if it is there."""
    folder = Path(source) / 'krita-deps-management'
    commit = git(folder, 'rev-parse', 'HEAD')
    branch = git(folder, 'rev-parse', '--abbrev-ref', 'HEAD')
    remote = git(folder, 'remote', 'get-url', 'origin') or 'https://invent.kde.org/packaging/krita-deps-management.git'
    return remote, commit, branch


def qt_notice(frameworks, source, record):
    remote, commit, branch = deps_recipe(source)
    version = qt_facts(frameworks)
    return [
        'Qt %s (the Qt*.framework folders in Contents/Frameworks, and the Qt plugins in Contents/PlugIns) is used under the GNU' % (version or '6'),
        'Lesser General Public License, version 3 (LGPL-3.0-only.txt; the GPL-3.0 text next to it).',
        '  Your rights under the LGPL-3.0: you may replace these Qt frameworks with a modified or other build of the same Qt',
        '  version and use this application with it. To do so: put your frameworks in Contents/Frameworks (same names), then sign the',
        '  app again, because macOS refuses a changed bundle:  codesign --force --deep --sign - "Krita Agent.app"  (or with your',
        '  own identity; the entitlements are in packaging/macos/entitlements.plist of the source). You may also reverse engineer',
        '  this application as far as needed to debug such changes.',
        '  Corresponding Qt source: this Qt is built from the recipe and patches of krita-deps-management%s%s (%s), the dependency set the' %
        ((', branch ' + branch) if branch else '', (', commit ' + commit) if commit else '', remote),
        '  fork pins in agent/fetch-deps.sh of %s; the Qt patches are in its ext_qt folder. Upstream Qt: https://download.qt.io/' % source_statement(record),
    ]


def python_package_notices(packages_dir):
    """[(name, version, licence expression, [licence files], [libraries it carries])] for a pip --target folder."""
    found = []
    packages_dir = Path(packages_dir)
    for dist in sorted(packages_dir.glob('*.dist-info')):
        metadata = {}
        try:
            for line in (dist / 'METADATA').read_text(errors='replace').splitlines():
                if not line.strip():
                    break
                key, _, value = line.partition(': ')
                metadata.setdefault(key, value)
        except OSError:
            pass
        licence = (metadata.get('License-Expression') or metadata.get('License') or '').splitlines()
        licence = licence[0] if licence else 'see the licence files'
        files = [p for p in dist.rglob('*') if p.is_file() and re.match(r'(LICEN[CS]E|NOTICE|COPYING|AUTHORS)', p.name, re.I)]
        package_dirs = [packages_dir / name for name in (metadata.get('Name', '').replace('-', '_'), 'cv2' if 'opencv' in dist.name.lower() else '')
                        if name and (packages_dir / name).is_dir()]
        carried = sorted(str(p.relative_to(packages_dir)) for d in package_dirs for p in d.rglob('*')
                         if p.is_file() and any(part.endswith(('.dylibs', '.libs')) for part in p.relative_to(d).parts))
        found.append((metadata.get('Name', dist.name), metadata.get('Version', ''), licence, files, carried))
    return found


# What the libraries inside the wheels are (by file-name prefix), for the notice. Anything else: see the wheel's own licence file.
WHEEL_LIBRARY_LICENCES = (
    ('libscipy_openblas', 'OpenBLAS: BSD-3-Clause'), ('libopenblas', 'OpenBLAS: BSD-3-Clause'),
    ('libgfortran', 'GCC runtime: GPL-3.0-or-later WITH GCC-exception-3.1 (the runtime library exception)'),
    ('libgcc_s', 'GCC runtime: GPL-3.0-or-later WITH GCC-exception-3.1 (the runtime library exception)'),
    ('libquadmath', 'GCC libquadmath: LGPL-2.1-or-later'),
    ('libav', 'FFmpeg: licence as reported by the wheel\'s libavutil (see below)'), ('libsw', 'FFmpeg (libswscale/libswresample)'),
    ('libpng', 'libpng licence'), ('libjpeg', 'IJG / libjpeg-turbo: BSD-3-Clause-style'), ('libtiff', 'libtiff licence (BSD-style)'),
    ('libwebp', 'BSD-3-Clause'), ('libopenjp2', 'BSD-2-Clause'), ('libaom', 'BSD-2-Clause'), ('libdav1d', 'BSD-2-Clause'),
    ('libfreetype', 'FreeType licence / GPL-2.0'), ('libfontconfig', 'MIT-style'), ('libfribidi', 'LGPL-2.1-or-later'),
    ('libcrypto', 'OpenSSL / Apache-2.0'), ('libssl', 'OpenSSL / Apache-2.0'), ('libz', 'Zlib'), ('liblzma', 'public domain (xz)'),
    ('libbrotli', 'MIT'), ('libx264', 'GPL-2.0-or-later'), ('libx265', 'GPL-2.0-only'), ('libvpx', 'BSD-3-Clause'),
    ('libopus', 'BSD-3-Clause'), ('libvorbis', 'BSD-3-Clause'), ('libogg', 'BSD-3-Clause'), ('libmp3lame', 'LGPL-2.0-or-later'),
    ('libass', 'ISC'), ('libharfbuzz', 'MIT'), ('libxml2', 'MIT'), ('libbluray', 'LGPL-2.1-or-later'), ('libarchive', 'BSD-2-Clause'),
)


def wheel_library_licence(name):
    for prefix, text in WHEEL_LIBRARY_LICENCES:
        if name.startswith(prefix):
            return text
    return 'see the licence files of the wheel'

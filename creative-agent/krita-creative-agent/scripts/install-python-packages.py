"""Install the plugin's native Python packages (krita-mcp/krita-plugin/python-packages.txt) for Krita's own Python, into
the shared folder kritamcp/vendor.py reads: <Creative Agent>/python/<os>-<machine>-py<major><minor>/.

Krita's Python version is read from the installed app (Krita 5.3.3 bundles 3.13); give --python to target another
(the Qt6 fork). Uses uv. Installs into a new folder and swaps it in, so a failed install never leaves a half-filled one.

  python3 scripts/install-python-packages.py [--krita /Applications/krita.app] [--python 3.13] [--machine arm64]
"""
import argparse
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT.parent / 'krita-mcp/krita-plugin/python-packages.txt'
UV_PLATFORMS = {('darwin', 'arm64'): 'aarch64-apple-darwin', ('darwin', 'x86_64'): 'x86_64-apple-darwin'}


def krita_python(app):
    """The Python version Krita bundles, from its framework folder, or None."""
    versions = sorted(p.name for p in (Path(app) / 'Contents/Frameworks/Python.framework/Versions').glob('3.*'))
    return versions[-1] if versions else None


def target_folder(python, machine):
    sys.path.insert(0, str(ROOT.parent / 'krita-mcp/krita-plugin/kritamcp'))
    from node_runtime import default_root
    system = {'darwin': 'macos', 'win32': 'windows'}.get(sys.platform, 'linux')
    return default_root().parent / 'python' / ('%s-%s-py%s' % (system, machine, python.replace('.', '')))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--krita', default='/Applications/krita.app')
    parser.add_argument('--python')
    parser.add_argument('--machine', default=platform.machine().lower())
    args = parser.parse_args()
    python = args.python or krita_python(args.krita)
    if not python or not re.fullmatch(r'3\.\d+', python):
        raise SystemExit('Give --python: no Krita Python found at ' + args.krita)
    uv_platform = UV_PLATFORMS.get((sys.platform, args.machine))
    if not uv_platform:
        raise SystemExit('No wheel platform known for %s %s' % (sys.platform, args.machine))
    target = target_folder(python, args.machine)
    staging = target.with_name(target.name + '.installing')
    shutil.rmtree(staging, ignore_errors=True)
    subprocess.run(['uv', 'pip', 'install', '--quiet', '--target', str(staging), '--python-version', python,
                    '--python-platform', uv_platform, '--only-binary', ':all:', '-r', str(REQUIREMENTS)], check=True)
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    installed = sorted(p.name for p in target.glob('*.dist-info'))
    print('Installed for Python %s (%s) in %s:\n  %s' % (python, args.machine, target, '\n  '.join(installed)))


if __name__ == '__main__':
    main()

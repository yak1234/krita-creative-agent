"""Native Python packages for Krita's own Python, which bundles none (no numpy, OpenCV, psutil or xxhash).

They are installed once per machine, shared by releases like the Node runtime, in
`<Creative Agent>/python/<os>-<machine>-py<major><minor>/` beside `runtimes/` (node_runtime.default_root): an install
replaces the plugin folder and never this one, and the Python version in the name keeps a Krita with another Python (the
Qt6 fork) from loading packages built for this one. A plugin may also carry `_vendor/<os>-<machine>/` itself.
scripts/install-python-packages.py installs the pinned set (krita-mcp/krita-plugin/python-packages.txt).

Both folders are appended to sys.path, so Krita's own packages (PyQt5) always win. Krita.app allows native libraries
from outside the bundle (com.apple.security.cs.disable-library-validation). Plugin code imports a package where it is
used and keeps a working fallback when it is missing.
"""
import os
import platform
import sys


def platform_tag():
    system = {'darwin': 'macos', 'win32': 'windows'}.get(sys.platform, 'linux')
    return '%s-%s' % (system, platform.machine().lower())


def shared_root(runtimes_root=None):
    """This machine's shared package folder for the running Python."""
    if runtimes_root is None:
        from .node_runtime import default_root
        runtimes_root = default_root()
    return os.path.join(os.path.dirname(os.fspath(runtimes_root)), 'python', '%s-py%d%d' % ((platform_tag(),) + sys.version_info[:2]))


def add_vendor_path(root=os.path.dirname(os.path.abspath(__file__)), shared=None):
    """Append the plugin's own vendor folder and the shared one to sys.path, once each. Returns the last added, or None."""
    found = None
    for path in (os.path.join(root, '_vendor', platform_tag()), shared or shared_root()):
        if os.path.isdir(path):
            if path not in sys.path:
                sys.path.append(path)
            found = path
    return found


def versions():
    """The vendored packages the plugin can use, by name: a version, or None when missing."""
    add_vendor_path()                                    # a plugin reload may not rerun __init__
    found, errors = {}, {}
    for name, module in (('numpy', 'numpy'), ('opencv', 'cv2'), ('psutil', 'psutil'), ('xxhash', 'xxhash')):
        try:
            imported = __import__(module)
        except Exception as error:                       # a native package can fail with more than ImportError
            found[name] = None
            errors[name] = ('%s: %s' % (type(error).__name__, error))[:300]
            continue
        found[name] = getattr(imported, '__version__', None) or getattr(imported, 'VERSION', None)
    if errors:
        found['errors'] = errors
    return found


def numpy_version():
    return versions()['numpy']

"""The plugin's one way to Qt: PyQt6 on a Qt6 Krita (the fork on Krita master), PyQt5 on Krita 5.

Plugin code imports every Qt name from here (`from .qt_compat import QImage, Qt, pyqtSignal`), never from PyQt5 or
PyQt6 directly. Every name of QtCore, QtGui and QtWidgets is here, so a class that moved in Qt6 (QAction, QShortcut:
QtWidgets to QtGui) is found either way. Enum names are written scoped (`Qt.TransformationMode.SmoothTransformation`,
`QImage.Format.Format_Alpha8`): PyQt6 requires them, and the PyQt5 5.15.11 bundled with Krita 5.3.3 accepts them too.
Write `exec()` and `sizeInBytes()`: `exec_()` and `byteCount()` are gone in Qt6. krita-mcp/scripts/qt6_scoped_enums.py
rewrites old enum names. Decision: the fork moved to Qt 6 (openspec krita-fork).

The binding is the one the host already loaded (Krita imports its own before any plugin), so a PyQt6 installed into
a Qt5 Krita's Python is never mixed in. With none loaded (tests, tools): PyQt6 when installed, else PyQt5.
"""
import sys


def _binding():
    for name in ('PyQt6', 'PyQt5'):
        if name in sys.modules:
            return name
    try:
        import PyQt6.QtCore  # noqa: F401
        return 'PyQt6'
    except ImportError:
        return 'PyQt5'


QT6 = _binding() == 'PyQt6'
if QT6:
    from PyQt6 import QtCore, QtGui, QtWidgets, sip
    from PyQt6.QtCore import *  # noqa: F401,F403
    from PyQt6.QtGui import *  # noqa: F401,F403
    from PyQt6.QtWidgets import *  # noqa: F401,F403
else:
    from PyQt5 import QtCore, QtGui, QtWidgets, sip
    from PyQt5.QtCore import *  # noqa: F401,F403
    from PyQt5.QtGui import *  # noqa: F401,F403
    from PyQt5.QtWidgets import *  # noqa: F401,F403


def scoped(owner, enum, name):
    """An enum member of a class in Krita's own bindings (`scoped(DockWidgetFactoryBase, 'DockPosition', 'DockRight')`):
    Qt6 Krita's PyQt6 bindings only have it scoped under its enum; Krita 5's PyQt5 ones always have it on the class."""
    member = getattr(getattr(owner, enum, None), name, None)
    return member if member is not None else getattr(owner, name)


def enum_value(member):
    """An enum member as the int a Qt call takes: PyQt6 enums are Python Enums, PyQt5's are ints already."""
    return getattr(member, 'value', member)


def image_bytes(image):
    """An image's pixels as one contiguous bytes object, rows without their padding."""
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes())
    data = pointer.asstring()
    row = image.width() * image.depth() // 8
    if image.bytesPerLine() == row:
        return data
    stride = image.bytesPerLine()
    return b''.join(data[y * stride:y * stride + row] for y in range(image.height()))

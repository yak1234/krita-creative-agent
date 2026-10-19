"""Rewrite PyQt5-style enum names (`Qt.AlignCenter`, `QImage.Format_ARGB32`) to the scoped names PyQt6 requires
(`Qt.AlignmentFlag.AlignCenter`, `QImage.Format.Format_ARGB32`). PyQt5 5.15 accepts the scoped names too, so the
result runs on both. PyQt6 itself says which enum a name belongs to.

Run with PyQt6 and PyQt5 available:  uv run --with pyqt6 --with pyqt5 python krita-mcp/scripts/qt6_scoped_enums.py FILE...
Add --write to change the files; without it, it prints what it would change. Every new name is checked in PyQt5 too.
"""
import enum
import re
import subprocess
import sys

from PyQt6 import QtCore, QtGui, QtWidgets

MODULES = (QtCore, QtGui, QtWidgets)
NAME = re.compile(r'\b(Q[A-Za-z0-9]*|Qt)\.([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()')


def owner(class_name):
    return next((getattr(m, class_name) for m in MODULES if hasattr(m, class_name)), None)


def scoped(class_name, attr):
    """The scoped spelling of class_name.attr, or None when it needs none (or is not an enum member)."""
    cls = owner(class_name)
    if cls is None or attr in dir(cls):
        return None
    found = [name for name in dir(cls) if isinstance(getattr(cls, name, None), type)
             and issubclass(getattr(cls, name), enum.Enum) and attr in getattr(cls, name).__members__]
    return '%s.%s.%s' % (class_name, found[0], attr) if found else None


def rewrite(source):
    changes, unknown = [], set()
    def replace(match):
        new = scoped(match.group(1), match.group(2))
        if new:
            changes.append((match.group(0), new)); return new
        if owner(match.group(1)) is not None and match.group(2)[0].isupper() and match.group(2) not in dir(owner(match.group(1))):
            unknown.add(match.group(0))
        return match.group(0)
    lines = []
    for line in source.splitlines(keepends=True):
        code, hash_, comment = line.partition('#')
        lines.append(NAME.sub(replace, code) + hash_ + comment)       # comments keep their words
    return ''.join(lines), changes, unknown


def pyqt5_accepts(names):
    """Each scoped name, evaluated in PyQt5 (a child Python, so the two bindings never meet)."""
    script = ('from PyQt5.QtCore import *\nfrom PyQt5.QtGui import *\nfrom PyQt5.QtWidgets import *\nimport sys\n'
              'bad = []\nfor n in sys.argv[1:]:\n    try: eval(n)\n    except Exception: bad.append(n)\nprint("\\n".join(bad))\n')
    done = subprocess.run([sys.executable, '-c', script, *sorted(names)], capture_output=True, text=True)
    if done.returncode:
        raise SystemExit('PyQt5 check failed: ' + done.stderr[-400:])
    return [n for n in done.stdout.splitlines() if n]


def main(paths, write):
    every = set()
    for path in paths:
        with open(path) as handle:
            source = handle.read()
        result, changes, unknown = rewrite(source)
        every.update(new for _old, new in changes)
        print('%s: %d names scoped%s' % (path, len(changes), '; unresolved: ' + ', '.join(sorted(unknown)) if unknown else ''))
        if write and result != source:
            with open(path, 'w') as handle:
                handle.write(result)
    bad = pyqt5_accepts(every)
    if bad:
        raise SystemExit('PyQt5 does not accept: ' + ', '.join(bad))
    print('%d distinct scoped names, all accepted by PyQt5.' % len(every))


if __name__ == '__main__':
    args = sys.argv[1:]
    main([a for a in args if a != '--write'], '--write' in args)

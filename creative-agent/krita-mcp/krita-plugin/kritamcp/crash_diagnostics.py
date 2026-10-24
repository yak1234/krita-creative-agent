"""Persist uncaught Python errors before Krita opens its exception dialog.

This is diagnostic capture, not exception suppression or a crash recovery hook.
It deliberately delegates to Krita's existing exception handler.
"""
from datetime import datetime
import os
from pathlib import Path
import sys
import traceback


def log_path():
    return Path.home() / 'Library' / 'Logs' / 'Creative Agent' / 'krita-python-errors.log'


def _write(lines):
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
            path.replace(path.with_suffix('.previous.log'))
        with path.open('a', encoding='utf-8') as stream:
            stream.write('\n%s pid=%s\n' % (datetime.now().isoformat(), os.getpid()))
            stream.writelines(lines)
    except OSError:
        pass                                              # a logging failure must not replace the original exception


def record(where):
    """Log the exception being handled, with where it happened, and go on: for the panel's own catch-alls (one bad
    event or canvas poll must never stop the panel), which never reach the excepthook."""
    lines = ['Handled in %s:\n' % where] + traceback.format_exception(*sys.exc_info())
    _write(lines)
    try:
        sys.stderr.write(''.join(lines))
    except Exception:
        pass


def install():
    if getattr(sys.excepthook, '_creative_persistent_capture', False):
        return
    previous = sys.excepthook

    def capture(exc_type, exc_value, tb):
        _write(traceback.format_exception(exc_type, exc_value, tb))
        previous(exc_type, exc_value, tb)

    capture._creative_persistent_capture = True
    sys.excepthook = capture

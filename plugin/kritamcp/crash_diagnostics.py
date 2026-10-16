"""Persist uncaught Python errors before Krita opens its exception dialog.

This is diagnostic capture, not exception suppression or a crash recovery hook.
It deliberately delegates to Krita's existing exception handler.
"""
from datetime import datetime
import os
from pathlib import Path
import sys
import traceback


def install():
    if getattr(sys.excepthook, '_creative_persistent_capture', False):
        return
    previous = sys.excepthook
    log_path = Path.home() / 'Library' / 'Logs' / 'Creative Agent' / 'krita-python-errors.log'

    def capture(exc_type, exc_value, tb):
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            if log_path.exists() and log_path.stat().st_size > 2 * 1024 * 1024:
                log_path.replace(log_path.with_suffix('.previous.log'))
            with log_path.open('a', encoding='utf-8') as stream:
                stream.write('\n%s pid=%s\n' % (datetime.now().isoformat(), os.getpid()))
                traceback.print_exception(exc_type, exc_value, tb, file=stream)
        except OSError:
            # A logging failure must not replace the original exception.
            pass
        previous(exc_type, exc_value, tb)

    capture._creative_persistent_capture = True
    sys.excepthook = capture

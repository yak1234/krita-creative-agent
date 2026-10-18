"""Which windows an action opened, for the Krita action audit (native_craft.py).

A dialog is what would stop an unattended agent: Krita's modal window, or a new visible QDialog (QMessageBox and
QFileDialog are dialogs too). Krita also shows small top-level windows of its own that need no answer (on-canvas
notices, tooltips, floating dockers), so a new window alone is not a dialog.
"""
from PyQt5.QtWidgets import QApplication, QDialog


def visible_windows():
    """Identities of the visible top-level windows now: what was there before the action."""
    return set(id(widget) for widget in QApplication.topLevelWidgets() if widget.isVisible())


def new_dialogs(known):
    """The modal window and the visible dialogs that were not there before."""
    found = []
    modal = QApplication.activeModalWidget()
    if modal is not None:
        found.append(modal)
    for widget in QApplication.topLevelWidgets():
        if widget.isVisible() and id(widget) not in known and isinstance(widget, QDialog) and widget not in found:
            found.append(widget)
    return found


def describe(widget):
    return (type(widget).__name__ + ' ' + widget.objectName()).strip()

"""audit_dialogs with real Qt (offscreen). test_native.py replaces PyQt5 with stubs in this process, so the check
runs in a child Python with the plugin folder on its path. Writes no files."""
import json
import os
import pathlib
import subprocess
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / 'plugin/kritamcp'
CHECK = '''
import sys, json
sys.path.insert(0, %r)
from PyQt5.QtWidgets import QApplication, QDialog, QWidget, QMessageBox
from PyQt5.QtCore import Qt
app = QApplication.instance() or QApplication([])
import audit_dialogs as a
known = a.visible_windows()
notice = QWidget(None, Qt.ToolTip); notice.show()             # an on-canvas notice: a top-level window, not a dialog
dialog = QDialog(); dialog.setObjectName('DlgLayerSize'); dialog.show()
found = a.new_dialogs(known)
print(json.dumps({"found": [a.describe(w) for w in found]}))
''' % str(PLUGIN)


class AuditDialogTests(unittest.TestCase):
    def test_a_dialog_is_found_and_a_notice_is_not(self):
        done = subprocess.run([sys.executable, '-c', CHECK], capture_output=True, text=True, timeout=60,
                              env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
        if done.returncode:
            raise AssertionError(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else 'child failed')
        self.assertEqual(json.loads(done.stdout.strip().splitlines()[-1])['found'], ['QDialog DlgLayerSize'])


if __name__ == '__main__':
    unittest.main()

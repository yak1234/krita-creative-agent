"""Regression: a running QProcess must not update widgets during dock teardown."""
import importlib.util
import os
from pathlib import Path
import sys
import types
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['KRITA_CREATIVE_NO_AUTOSTART'] = '1'
from PyQt5 import sip
from PyQt5.QtCore import QProcess
from PyQt5.QtWidgets import QApplication, QDockWidget

root = Path(__file__).resolve().parents[2]
folder = root / 'plugin/kritamcp'
stub = types.ModuleType('krita')
stub.DockWidget = QDockWidget
stub.DockWidgetFactory = object
stub.DockWidgetFactoryBase = types.SimpleNamespace(DockRight=0)
stub.Krita = object
sys.modules['krita'] = stub
package = types.ModuleType('shutdown_test'); package.__path__ = [str(folder)]
sys.modules['shutdown_test'] = package
spec = importlib.util.spec_from_file_location('shutdown_test.creative_docker', folder / 'creative_docker.py')
ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(ui)
app = QApplication([])
errors = []
sys.excepthook = lambda *args: errors.append(args)

# Late queued callbacks, even when a child was already deleted.
panel = ui.CreativeAgentDocker()
panel.process_error(QProcess.FailedToStart)
assert 'could not start' in panel.status.text()
sip.delete(panel.status)
panel.process_error(QProcess.Crashed)
panel.process_finished()
panel.read_output()
sip.delete(panel)

# Reproduce Qt killing its live child process during dock destruction.
for _ in range(5):
    panel = ui.CreativeAgentDocker()
    process = QProcess(panel)
    panel.process = process
    process.errorOccurred.connect(panel.process_error)
    process.finished.connect(panel.process_finished)
    process.readyReadStandardOutput.connect(panel.read_output)
    panel.destroyed.connect(lambda _object=None, p=process: ui.disconnect_companion_callbacks(p))
    process.start('/bin/cat', [])
    assert process.waitForStarted(3000)
    sip.delete(panel)
    app.processEvents()
    assert sip.isdeleted(process)
assert not errors, [(str(e[1])) for e in errors]
print('PASS: late callbacks and five running-companion dock destructions; no uncaught Python errors')

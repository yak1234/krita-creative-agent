"""Run from Scripter after installation; preserves open canvases and restores chat."""
import importlib
import os
import kritamcp
from krita import Krita
from PyQt5.QtCore import Qt, QTimer, QProcess
from PyQt5.QtWidgets import QDockWidget

window = Krita.instance().activeWindow().qwindow()
old_panels = [d for d in window.findChildren(QDockWidget) if d.objectName() == 'krita_creative_agent']
if any(getattr(d, 'busy', False) for d in old_panels):
    raise RuntimeError('Stop the painting assistant before updating its panel.')
resume_id = next((d.study_id for d in old_panels if getattr(d, 'study_active', False) and getattr(d, 'study_id', None)), None)
for panel in old_panels:
    if getattr(panel, 'process', None) and panel.process.state() != QProcess.NotRunning:
        panel.send({'type': 'shutdown'})

# Never block Krita's UI while the old companion releases its native session.
timer = QTimer(window)
tries = [0]
def finish_reload():
    tries[0] += 1
    if any(getattr(d, 'process', None) and d.process.state() != QProcess.NotRunning for d in old_panels):
        if tries[0] > 100:
            timer.stop()
            print('Companion shutdown did not finish. The old panel remains available.')
        return
    timer.stop()
    import kritamcp.creative_validation as validation
    import kritamcp.creative_native_adapters as adapters
    import kritamcp.creative_tools as native
    import kritamcp.creative_docker as ui
    importlib.reload(validation)
    importlib.reload(adapters)
    importlib.reload(native)
    importlib.reload(ui)
    for name, method in native.CreativeTools.__dict__.items():
        if callable(method) and (name.startswith('_creative_') or name == 'cmd_creative'):
            setattr(kritamcp.KritaMCPExtension, name, method)
    replacement = ui.CreativeAgentDocker()
    replacement.setObjectName('krita_creative_agent')
    replacement.resume_on_ready = resume_id
    replacement.preserve_canvas_on_reload = True
    for old in old_panels:
        window.removeDockWidget(old)
        old.hide()
        old.deleteLater()
    window.addDockWidget(Qt.RightDockWidgetArea, replacement)
    kritamcp._creative_docker_instance = replacement
    replacement.show()
    print('Creative Agent updated. Open canvases preserved; restoring the conversation.', native.CREATIVE_BUILD)
timer.timeout.connect(finish_reload)
kritamcp._creative_reload_timer = timer
timer.start(100)

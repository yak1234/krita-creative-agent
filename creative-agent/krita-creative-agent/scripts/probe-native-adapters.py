"""Run in Krita Scripter; read-only probe for the currently open test document."""
import json
from pathlib import Path
from krita import Krita
import kritamcp
PLUGIN=Path(kritamcp.__file__).parent   # the installed plugin
PROJECT=Path(json.loads((PLUGIN/'creative-agent-config.json').read_text())['project_root'])
DIAGNOSTICS=PROJECT/'.creative-agent'/'diagnostics';DIAGNOSTICS.mkdir(parents=True,exist_ok=True)
from PyQt5.QtWidgets import QWidget,QToolButton
app=Krita.instance(); doc=app.activeDocument();view=app.activeWindow().activeView();win=app.activeWindow().qwindow()
report={'version':app.version(),'document':{'name':doc.name(),'width':doc.width(),'height':doc.height()},'methods':{n:hasattr(view,n) for n in ['flakeToCanvasTransform','flakeToImageTransform','foregroundColor','backgroundColor','setForeGroundColor','setBackGroundColor']},'tools':[(b.objectName(),b.metaObject().className(),b.isChecked()) for b in win.findChildren(QToolButton) if b.isCheckable()], 'canvas_widgets':[(w.objectName(),w.metaObject().className(),w.isVisible()) for w in win.findChildren(QWidget) if 'Canvas' in w.metaObject().className()], 'gradients':list(app.resources('gradient')),'actions':[a.objectName() for a in app.actions() if 'Gradient' in a.objectName() or 'Patch' in a.objectName()]}
(DIAGNOSTICS/'native-probe.json').write_text(json.dumps(report,indent=2))
print('Native adapter probe saved; canvas unchanged.')

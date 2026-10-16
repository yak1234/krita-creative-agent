"""Run in Scripter on the user's dedicated 600x600 blank test canvas only."""
import importlib.util,json,traceback
from pathlib import Path
from krita import Krita,Selection,InfoObject
from PyQt5.QtCore import QTimer
import sys
import kritamcp
PLUGIN=Path(kritamcp.__file__).parent   # the installed plugin
PROJECT=Path(json.loads((PLUGIN/'creative-agent-config.json').read_text())['project_root'])
DIAGNOSTICS=PROJECT/'.creative-agent'/'diagnostics';DIAGNOSTICS.mkdir(parents=True,exist_ok=True)
validation_spec=importlib.util.spec_from_file_location('kritamcp.native_adapter_validation',str(PLUGIN/'native_adapter_validation.py'))
validation=importlib.util.module_from_spec(validation_spec);validation_spec.loader.exec_module(validation);sys.modules['kritamcp.native_adapter_validation']=validation
spec=importlib.util.spec_from_file_location('kritamcp.native_adapter_candidate',str(PLUGIN/'creative_native_adapters.py'))
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
app=Krita.instance();doc=app.activeDocument();view=app.activeWindow().activeView()
assert doc.width()==600 and doc.height()==600, 'Use the dedicated 600x600 test document'
class Owner:
    def get_active_document(self):return app.activeDocument()
    def get_active_view(self):return app.activeWindow().activeView()
owner=Owner();report={'krita_version':app.version(),'adapter_version':adapter.ADAPTER_VERSION}
try:
    layer=doc.createNode('TypeSafe gradient test','paintlayer');doc.rootNode().addChildNode(layer,None);doc.setActiveNode(layer)
    selection=Selection();selection.select(40,40,520,200,255);doc.setSelection(selection)
    with adapter.NativeToolAdapter(owner,doc,'gradient') as tool:
        report['mapping']={str(pt):[tool.mapping.map(__import__('PyQt5.QtCore',fromlist=['QPointF']).QPointF(*pt)).x(),tool.mapping.map(__import__('PyQt5.QtCore',fromlist=['QPointF']).QPointF(*pt)).y()] for pt in [(0,0),(600,600)]}
        tool.run({'shape':'linear','start':[40,100],'end':[559,100],'foreground':'#153e80','background':'#efb958','opacity':1})
    doc.setSelection(None);doc.refreshProjection();doc.waitForDone()
    report['gradient_samples']={str(pt):list(bytes(layer.pixelData(*pt,1,1))) for pt in [(0,0),(50,100),(300,100),(550,100),(300,300)]}
    destination=DIAGNOSTICS/'gradient-live.png';doc.exportImage(str(destination),InfoObject())
    report['status']='executed'
except Exception:
    report['error']=traceback.format_exc()
finally:
    doc.setSelection(None)
    (DIAGNOSTICS/'gradient-live.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

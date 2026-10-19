"""Test native patch on a reversible fixture in the user-created test document."""
import importlib.util,json,traceback
from pathlib import Path
from krita import Krita,Selection
from PyQt5.QtCore import QByteArray
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
assert doc.width()==600 and doc.height()==600
class Owner:
    def get_active_document(self):return app.activeDocument()
    def get_active_view(self):return app.activeWindow().activeView()
report={'krita_version':app.version(),'adapter_version':adapter.ADAPTER_VERSION}
try:
    source=doc.createNode('Patch fixture original','paintlayer');doc.rootNode().addChildNode(source,None)
    source.setPixelData(QByteArray(bytes([160,180,190,255])*520*220),40,320,520,220)
    source.setPixelData(QByteArray(bytes([30,30,220,255])*20*20),290,420,20,20)
    before=bytes(source.pixelData(0,0,600,600))
    clone=source.clone();clone.setName('Smart Patch result');doc.rootNode().addChildNode(clone,source);doc.setActiveNode(clone);source.setVisible(False)
    sel=Selection();sel.select(280,410,40,40,255);doc.setSelection(sel);doc.refreshProjection();doc.waitForDone()
    with adapter.NativeToolAdapter(Owner(),doc,'smart_patch') as tool:
        tool.run({'paths':[[[295,425],[305,425],[305,435],[295,435],[295,425]]],'diameter':35,'accuracy':50,'patch_radius':4})
    after=bytes(clone.pixelData(0,0,600,600))
    changes=[i//4 for i in range(0,len(before),4) if before[i:i+4]!=after[i:i+4]]
    report.update(changed_pixels=len(changes),outside_selection_changes=sum(not (280<=i%600<320 and 410<=i//600<450) for i in changes),source_preserved=before==bytes(source.pixelData(0,0,600,600)),center=list(bytes(clone.pixelData(300,430,1,1))))
    report['passed']=bool(changes) and not report['outside_selection_changes'] and report['source_preserved'] and report['center']==[160,180,190,255]
except Exception:report['error']=traceback.format_exc()
finally:
    doc.setSelection(None);doc.refreshProjection();doc.waitForDone()
    doc.projection(0,0,600,600).save(str(DIAGNOSTICS/'patch-live.png'))
    (DIAGNOSTICS/'patch-live.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

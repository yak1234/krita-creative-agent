"""Real installed-adapter acceptance. Run in Krita Scripter on saved test.kra.
Creates retained, hidden fixture layers, never another document. Enables tools only
if all assertions pass. The full-agent gate is a separate test.
"""
import json,time,traceback,hashlib
from pathlib import Path
from krita import Krita,Selection
from PyQt5.QtCore import QByteArray
from PyQt5.QtWidgets import QToolButton, QApplication
from kritamcp.creative_native_adapters import NativeToolAdapter,ADAPTER_VERSION
from kritamcp.creative_tools import CREATIVE_BUILD
app=Krita.instance();doc=app.activeDocument();view=app.activeWindow().activeView()
import kritamcp
PLUGIN=Path(kritamcp.__file__).parent   # the installed plugin
PROJECT=Path(json.loads((PLUGIN/'creative-agent-config.json').read_text())['project_root'])
DIAGNOSTICS=PROJECT/'.creative-agent'/'diagnostics';DIAGNOSTICS.mkdir(parents=True,exist_ok=True)
assert doc and Path(doc.fileName()).resolve()==PROJECT/'test.kra' and (doc.width(),doc.height())==(600,600)
OUT=DIAGNOSTICS/('native-installed-'+str(int(time.time())))
OUT.mkdir();report={'build':CREATIVE_BUILD['build_id'],'status':'running','krita_version':app.version(),'adapter_version':ADAPTER_VERSION,'checks':[],'evidence':str(OUT)}
class Owner:
    def get_active_document(self):return app.activeDocument()
    def get_active_view(self):return app.activeWindow().activeView()
owner=Owner();saved_node=doc.activeNode();saved_selection=doc.selection();saved_zoom=view.canvas().zoomLevel();fixtures=[]
def data(layer):return bytes(layer.pixelData(0,0,600,600))
def state():
    win=app.activeWindow().qwindow()
    tool=[b.objectName() for b in win.findChildren(QToolButton) if b.isChecked() and b.metaObject().className()=='KoToolBoxButton']
    return {'tool':tool,'size':view.brushSize(),'opacity':view.paintingOpacity(),'gradient':view.currentGradient().name(),'fg':view.foregroundColor().components(),'bg':view.backgroundColor().components()}
def layer(name):
    n=doc.createNode(name,'paintlayer');doc.rootNode().addChildNode(n,None);doc.setActiveNode(n);fixtures.append(n);doc.refreshProjection();doc.waitForDone();QApplication.processEvents();return n
def select(x,y,w,h):
    sel=Selection();sel.select(x,y,w,h,255);doc.setSelection(sel)
def evidence(name):
    doc.refreshProjection();doc.waitForDone();doc.projection(0,0,600,600).save(str(OUT/(name+'.png')))
def check(name,passed,**detail):
    report['checks'].append(dict(name=name,passed=bool(passed),**detail))
    if not passed:raise AssertionError(name)
try:
    for shape,zoom in [('linear',saved_zoom),('radial',saved_zoom),('linear',0.8)]:
        view.canvas().setZoomLevel(zoom);n=layer('Acceptance '+shape+' '+str(zoom));select(80,80,300,120)
        before=state();p={'shape':shape,'start':[100,140],'end':[350,140] if shape=='linear' else [180,140],'foreground':'#153e80','background':'#efb958','opacity':1}
        with NativeToolAdapter(owner,doc,'gradient') as tool:tool.run(p)
        after=state();raw=data(n);painted=[i//4 for i in range(0,len(raw),4) if raw[i+3]]
        outside=sum(not(80<=i%600<380 and 80<=i//600<200) for i in painted)
        a=list(bytes(n.pixelData(105,140,1,1)));b=list(bytes(n.pixelData(345 if shape=='linear' else 190,140,1,1)))
        check('gradient_'+shape+'_'+str(zoom),len(painted)==36000 and outside==0 and a[0]>a[2]+40 and b[2]>b[0]+80 and before==after,painted=len(painted),outside=outside,start_bgra=a,end_bgra=b,state_restored=before==after,zoom=zoom)
        evidence('gradient-'+shape+'-'+str(zoom));n.setVisible(False)
    view.canvas().setZoomLevel(saved_zoom)
    src=layer('Acceptance patch original');src.setPixelData(QByteArray(bytes([160,180,190,255])*300*180),80,320,300,180);src.setPixelData(QByteArray(bytes([30,30,220,255])*20*20),190,400,20,20)
    original=data(src);clone=src.clone();clone.setName('Acceptance patch result');doc.rootNode().addChildNode(clone,src);fixtures.append(clone);doc.setActiveNode(clone);src.setVisible(False);select(180,390,40,40)
    evidence('patch-before');before=state()
    with NativeToolAdapter(owner,doc,'smart_patch') as tool:tool.run({'paths':[[[195,405],[205,405],[205,415],[195,415],[195,405]]],'diameter':35,'accuracy':50,'patch_radius':4})
    after=data(clone);changed=[i//4 for i in range(0,len(after),4) if original[i:i+4]!=after[i:i+4]]
    outside=sum(not(180<=i%600<220 and 390<=i//600<430) for i in changed)
    center=list(bytes(clone.pixelData(200,410,1,1)))
    check('smart_patch',len(changed)==400 and outside==0 and original==data(src) and center==[160,180,190,255] and before==state(),changed_pixels=len(changed),outside=outside,source_preserved=original==data(src),state_restored=before==state(),center_bgra=center)
    evidence('patch-after');clone.setVisible(False)
    # A real target change between preparation and execution must refuse input.
    doc.setActiveNode(clone)
    with NativeToolAdapter(owner,doc,'gradient') as tool:
        doc.setActiveNode(src)
        rejected=False
        try:tool.check_target()
        except RuntimeError:rejected=True
        finally:doc.setActiveNode(clone)
    check('active_layer_change_rejected',rejected and original==data(src))
    others=[v for v in app.activeWindow().views() if v.document()!=doc]
    assert len(others)==1, 'Open exactly one second test document'
    other=others[0]; other_doc=other.document()
    def projection_hash(d): return hashlib.sha256(bytes(d.pixelData(0,0,d.width(),d.height()))).hexdigest()
    first_hash=projection_hash(doc); second_hash=projection_hash(other_doc)
    doc.setActiveNode(clone)
    with NativeToolAdapter(owner,doc,'gradient') as tool:
        app.activeWindow().showView(other)
        rejected=False
        try:tool.run({'shape':'linear','start':[100,140],'end':[350,140],'foreground':'#153e80','background':'#efb958','opacity':1})
        except RuntimeError:rejected=True
        finally:app.activeWindow().showView(view)
    check('document_switch_before_dispatch_rejected',rejected and first_hash==projection_hash(doc) and second_hash==projection_hash(other_doc),both_documents_unchanged=first_hash==projection_hash(doc) and second_hash==projection_hash(other_doc))
    report['status']='passed'
    receipt={'adapter_version':ADAPTER_VERSION,'krita_version':app.version(),'gradient':True,'smart_patch':True,'evidence':str(OUT),'checked_at':time.time()}
    app.writeSetting('creative_agent_native_tools','acceptance',json.dumps(receipt))
except Exception:
    report['status']='failed';report['error']=traceback.format_exc()
finally:
    for n in fixtures:n.setVisible(False)
    view.canvas().setZoomLevel(saved_zoom);doc.setSelection(saved_selection);doc.setActiveNode(saved_node);doc.refreshProjection();doc.waitForDone()
    report['saved']=doc.save()
    (OUT/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

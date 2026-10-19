import json
from pathlib import Path
from krita import Krita
import kritamcp
PLUGIN=Path(kritamcp.__file__).parent   # the installed plugin
PROJECT=Path(json.loads((PLUGIN/'creative-agent-config.json').read_text())['project_root'])
DIAGNOSTICS=PROJECT/'.creative-agent'/'diagnostics';DIAGNOSTICS.mkdir(parents=True,exist_ok=True)
app=Krita.instance();doc=app.activeDocument();ids={
 'source':'{743cc0ee-c9a2-4167-8816-5538618db206}',
 'first':'{1d5900ae-3f36-45e3-8b41-92d0e51929e0}',
 'second':'{aa40c7fd-460a-469d-91d6-fa7c4eff0eaa}',
}
def walk(n):
 for c in n.childNodes():
  yield c
  yield from walk(c)
lookup={n.uniqueId().toString():n for n in walk(doc.rootNode())}
result={}
for name,id in ids.items():
 n=lookup[id]; raw=bytes(n.pixelData(180,390,40,40)); result[name]={'name':n.name(),'visible':n.visible(),'center_bgra':list(bytes(n.pixelData(200,410,1,1))),'top_bgra':list(bytes(n.pixelData(200,407,1,1))),'mask_sha':__import__('hashlib').sha256(raw).hexdigest(),'parent':n.parentNode().name()}
result['projection']={'center_bgra':list(bytes(doc.pixelData(200,410,1,1))),'top_bgra':list(bytes(doc.pixelData(200,407,1,1)))}
out=(DIAGNOSTICS/'patch-layer-diagnosis.json');out.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

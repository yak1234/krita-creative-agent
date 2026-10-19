"""Bounded Qt adapters for tools which are not exposed by Node.paintPath.

Disabled until a live acceptance receipt for this adapter and Krita version exists.
The test harness can instantiate NativeToolAdapter directly; public execution cannot
bypass the acceptance gate. No screen-coordinate constants or pixel substitutes.
"""
import json
import math
from krita import Krita, ManagedColor
from .qt_compat import Qt, QPointF, QEvent
from .qt_compat import QMouseEvent, QColor
from .qt_compat import QWidget, QToolButton, QComboBox, QCheckBox, QSlider, QSpinBox, QApplication, QMdiArea, QDialog

ADAPTER_VERSION = 'native-tools-v4'
TOOL_IDS = {'gradient': 'KritaFill/KisToolGradient', 'smart_patch': 'KritaShape/KisToolSmartPatch'}


from .native_adapter_validation import validated_parameters


def capabilities():
    app=Krita.instance()
    try: receipt=json.loads(app.readSetting('creative_agent_native_tools', 'acceptance', '{}'))
    except Exception: receipt={}
    valid=receipt.get('adapter_version')==ADAPTER_VERSION and receipt.get('krita_version')==app.version()
    return {name:{'available':bool(valid and receipt.get(name) is True),
                  'adapter_version':ADAPTER_VERSION,
                  'reason':None if valid and receipt.get(name) is True else 'Live adapter acceptance pending for this Krita version',
                  'selection':'Intersects explicit selection with stage region',
                  'prerequisites':['active verified canvas','native tool controls','reversible contribution'] + (['source paint layer','explicit repair selection'] if name=='smart_patch' else [])}
            for name in TOOL_IDS}


class NativeToolAdapter:
    def __init__(self, owner, doc, kind):
        self.owner,self.doc,self.kind=owner,doc,kind
        self.view=owner.get_active_view(); self.window=Krita.instance().activeWindow().qwindow()
        self.saved=[]; self.previous_tool=None

    def remember(self, getter, setter, value):
        old=getter(); self.saved.append(lambda: setter(old)); setter(value)
        if getter()!=value: raise RuntimeError('Krita rejected a tool option')

    def control(self, cls, name):
        matches=[w for w in self.window.findChildren(cls,name) if w is not None]
        if len(matches)!=1: raise RuntimeError('Native tool control unavailable: '+name)
        return matches[0]

    def __enter__(self):
        try:
            if QApplication.activeModalWidget() is not None or isinstance(QApplication.activeWindow(), QDialog):
                raise RuntimeError('Close the open Krita dialog before native painting')
            if self.owner.get_active_document()!=self.doc: raise RuntimeError('Painting target changed')
            canvas=self.view.canvas()
            if canvas.rotation()!=0 or canvas.mirror() or canvas.wrapAroundMode():
                raise ValueError('Native tool adapters require an unrotated, unmirrored canvas without wraparound')
            for name in ('flakeToCanvasTransform','flakeToImageTransform'):
                if not hasattr(self.view,name): raise RuntimeError('Krita coordinate transform binding unavailable')
            buttons=[b for b in self.window.findChildren(QToolButton) if b.isChecked() and b.metaObject().className()=='KoToolBoxButton']
            if len(buttons)!=1: raise RuntimeError('Cannot identify the current tool for restoration')
            self.previous_tool=buttons[0]
            action=Krita.instance().action(TOOL_IDS[self.kind])
            if action is not None: action.trigger()
            else:
                candidates=self.window.findChildren(QToolButton,TOOL_IDS[self.kind])
                if len(candidates)!=1: raise RuntimeError('Native tool unavailable')
                candidates[0].click()
            # Tool activation creates the option widget synchronously.
            areas=self.window.findChildren(QMdiArea)
            if len(areas)!=1: raise RuntimeError('Cannot resolve the document area')
            area=areas[0]
            candidates=[s for s in area.subWindowList() if s.isVisible()]
            title=self.doc.fileName().rsplit('/',1)[-1] if self.doc.fileName() else self.doc.name()
            matches=[s for s in candidates if s.windowTitle().startswith(title)]
            if len(matches)!=1: raise RuntimeError('Cannot resolve the active document subwindow')
            self.subwindow=matches[0]
            widgets=[w for w in self.subwindow.findChildren(QWidget) if w.isVisible() and w.metaObject().className() in ('KisOpenGLCanvas2','KisQPainterCanvas')]
            if len(widgets)!=1: raise RuntimeError('Cannot resolve a unique canvas input widget')
            self.widget=widgets[0]
            inv,ok=self.view.flakeToImageTransform().inverted()
            if not ok: raise RuntimeError('Invalid document coordinate transform')
            self.mapping=inv*self.view.flakeToCanvasTransform()
            self.target=self.doc.activeNode()
            return self
        except Exception:
            self.__exit__(None,None,None); raise

    def check_target(self):
        if self.owner.get_active_document()!=self.doc or self.owner.get_active_view()!=self.view or self.doc.activeNode()!=self.target:
            raise RuntimeError('Active native tool target changed')

    def drag(self, path):
        pts=[self.mapping.map(QPointF(*p)) for p in path]
        if any(not self.widget.rect().contains(p.toPoint()) for p in pts):
            raise ValueError('Native tool path is outside the visible canvas; fit the target region first')
        self.check_target()
        pressed=False
        try:
            for i,p in enumerate(pts):
                self.check_target()
                kind=QEvent.Type.MouseButtonPress if i==0 else QEvent.Type.MouseMove
                event=QMouseEvent(kind,p,Qt.MouseButton.LeftButton if i==0 else Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(self.widget,event); pressed=True
            self.check_target()
        finally:
            if pressed: QApplication.sendEvent(self.widget,QMouseEvent(QEvent.Type.MouseButtonRelease,pts[-1],Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
        self.doc.waitForDone()

    def preflight(self,p):
        validated_parameters(self.kind,p,self.doc.width(),self.doc.height())
        self.check_target()
        points=[p['start'],p['end']] if self.kind=='gradient' else [pt for path in p['paths'] for pt in path]
        if any(not self.widget.rect().contains(self.mapping.map(QPointF(*pt)).toPoint()) for pt in points):
            raise ValueError('Native tool path is outside the visible canvas')
        controls=[(QComboBox,'shape_combo'),(QComboBox,'repeat_combo'),(QCheckBox,'reverse_check'),(QCheckBox,'dither_check')] if self.kind=='gradient' else [(QSlider,'accuracySlider'),(QSpinBox,'patchRadius')]
        for cls,name in controls: self.control(cls,name)
        if self.kind=='gradient':
            if not any(k in Krita.instance().resources('gradient') for k in ('0. Foreground to Background','Foreground to Background','Foreground to background')):
                raise RuntimeError('Foreground-to-background gradient resource unavailable')

    def run(self,p):
        self.preflight(p)
        if self.kind=='gradient':
            shape=self.control(QComboBox,'shape_combo'); repeat=self.control(QComboBox,'repeat_combo')
            self.remember(shape.currentIndex,shape.setCurrentIndex,0 if p['shape']=='linear' else 2)
            self.remember(repeat.currentIndex,repeat.setCurrentIndex,0)
            for name in ('reverse_check','dither_check'):
                w=self.control(QCheckBox,name); self.remember(w.isChecked,w.setChecked,False)
            old_fg,old_bg=self.view.foregroundColor(),self.view.backgroundColor()
            old_gradient=self.view.currentGradient(); old_opacity=self.view.paintingOpacity()
            self.saved.append(lambda:self.view.setForeGroundColor(old_fg))
            self.saved.append(lambda:self.view.setBackGroundColor(old_bg))
            self.saved.append(lambda:self.view.setCurrentGradient(old_gradient))
            self.saved.append(lambda:self.view.setPaintingOpacity(old_opacity))
            gradients=Krita.instance().resources('gradient')
            candidates=[v for k,v in gradients.items() if k in ('0. Foreground to Background','Foreground to Background','Foreground to background')]
            if len(candidates)!=1: raise RuntimeError('Foreground-to-background gradient resource unavailable')
            self.view.setCurrentGradient(candidates[0])
            self.view.setForeGroundColor(ManagedColor.fromQColor(QColor(p['foreground']),self.view.canvas()))
            self.view.setBackGroundColor(ManagedColor.fromQColor(QColor(p['background']),self.view.canvas()))
            self.view.setPaintingOpacity(p['opacity'])
            self.drag([p['start'],p['end']])
        else:
            if self.doc.selection() is None: raise ValueError('Smart Patch requires an explicit repair selection')
            accuracy=self.control(QSlider,'accuracySlider'); radius=self.control(QSpinBox,'patchRadius')
            self.remember(accuracy.value,accuracy.setValue,p['accuracy']); self.remember(radius.value,radius.setValue,p['patch_radius'])
            self.remember(self.view.brushSize,self.view.setBrushSize,p['diameter'])
            for path in p['paths']: self.drag(path)
        self.doc.refreshProjection(); self.doc.waitForDone()

    def __exit__(self,*_):
        errors=[]
        for restore in reversed(self.saved):
            try: restore()
            except Exception as e: errors.append(str(e))
        if self.previous_tool:
            try: self.previous_tool.click()
            except Exception as e: errors.append(str(e))
        if errors: raise RuntimeError('Could not restore native tool state: '+'; '.join(errors))


def execute(owner,doc,kind,p):
    if not capabilities()[kind]['available']: raise ValueError('Native tool has not passed live acceptance on this Krita version')
    with NativeToolAdapter(owner,doc,kind) as adapter: adapter.run(p)

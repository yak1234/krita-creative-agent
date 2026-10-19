"""Selections, continuous native curves, and visual comparison exports."""
import os
from datetime import datetime
from krita import Krita, Selection
from .qt_compat import Qt, QPointF, QCoreApplication
from .qt_compat import QImage,QPainter,QPainterPath,QColor
from .geometry_data import bounds,curve,polygon
from .stroke_data import number
from .bridge_config import output_dir

class PrecisionTools:
    def cmd_duplicate_layer(self,p):
        doc,layer,err=self._require_layer()
        if err:return err
        if set(p)-{'name'}:raise ValueError('Supported parameter: name')
        name=p.get('name',layer.name()+' copy')
        if not isinstance(name,str) or not name.strip():raise ValueError('name must be nonempty text')
        doc.waitForDone()
        clone=layer.clone()
        if clone is None:raise RuntimeError('Layer clone failed')
        clone.setName(name)
        if not layer.parentNode().addChildNode(clone,layer):raise RuntimeError('Could not insert layer copy')
        doc.setActiveNode(clone);doc.refreshProjection();doc.waitForDone()
        return {'status':'ok','name':clone.name(),'id':clone.uniqueId().toString(),'active':True}

    def cmd_move_layer(self,p):
        doc,layer,err=self._require_layer()
        if err:return err
        if set(p)!={'dx','dy'}:raise ValueError('Supply dx and dy in canvas pixels')
        if layer.type()!='paintlayer' or layer.locked():raise ValueError('Movement requires an unlocked paint layer')
        values=[number(p[k],k,-100000,100000) for k in ('dx','dy')]
        if any(int(v)!=v for v in values):raise ValueError('Offsets must be integers')
        doc.waitForDone()
        # The fork's Node.move returns False when Krita refuses the move (a locked layer or group, a layer not in the
        # document, or a stroke the artist is still drawing holding it back past the wait limit).
        if layer.move(layer.position().x()+int(values[0]),layer.position().y()+int(values[1])) is False:
            raise RuntimeError('Krita refused the move: the layer or a group above it is locked, the layer is not in the document, or a stroke being drawn held it back')
        doc.refreshProjection();doc.waitForDone()
        r=layer.bounds()
        return {'status':'ok','bounds':[r.x(),r.y(),r.width(),r.height()], 'position':[layer.position().x(),layer.position().y()]}

    def cmd_modify_selection(self,p):
        doc,err=self._require_document()
        if err:return err
        if set(p)-{'operation','radius'}:raise ValueError('Supported parameters: operation, radius')
        operation=p.get('operation')
        if operation not in ('grow','shrink','feather','smooth'):raise ValueError('Use grow, shrink, feather, or smooth')
        radius=number(p.get('radius',1),'radius',1,128)
        if int(radius)!=radius:raise ValueError('radius must be an integer')
        if operation=='smooth' and 'radius' in p:raise ValueError('smooth does not accept radius')
        sel=doc.selection()
        if sel is None:raise ValueError('No active selection')
        sel=sel.duplicate();radius=int(radius)
        if operation=='grow':sel.grow(radius,radius)
        elif operation=='shrink':sel.shrink(radius,radius,False)
        elif operation=='feather':sel.feather(radius)
        else:sel.smooth()
        doc.setSelection(sel)
        return {'status':'ok','operation':operation,'bounds':[sel.x(),sel.y(),sel.width(),sel.height()]}

    def cmd_layer_settings(self,p):
        doc,layer,err=self._require_layer()
        if err:return err
        if set(p)-{'opacity','visible','alpha_locked','locked'}:raise ValueError('Supported layer settings: opacity, visible, alpha_locked, locked')
        opacity=number(p['opacity'],'opacity',0,1) if 'opacity' in p else None
        if 'visible' in p and not isinstance(p['visible'],bool):raise ValueError('visible must be boolean')
        for key in ('alpha_locked','locked'):
            if key in p and not isinstance(p[key],bool):raise ValueError(key+' must be boolean')
        if 'alpha_locked' in p and layer.type()!='paintlayer':raise ValueError('Alpha lock requires a paint layer')
        if opacity is not None:layer.setOpacity(round(opacity*255))
        if 'visible' in p:layer.setVisible(p['visible'])
        if 'alpha_locked' in p:layer.setAlphaLocked(p['alpha_locked'])
        if 'locked' in p:layer.setLocked(p['locked'])
        doc.refreshProjection();doc.waitForDone()
        return {'status':'ok','layer':layer.name(),'opacity':layer.opacity()/255,'visible':layer.visible(),'alpha_locked':layer.alphaLocked(),'locked':layer.locked()}

    def cmd_selection(self,p):
        doc,err=self._require_document()
        if err: return err
        mode=p.get('mode','replace')
        if mode=='clear':
            doc.setSelection(None)
            return {'status':'ok','selection':None}
        if mode not in ('replace','add','subtract','intersect'):
            raise ValueError('Invalid selection mode')
        shape=p.get('shape','rectangle')
        feather=number(p.get('feather',0),'feather',0,128)
        if int(feather)!=feather: raise ValueError('feather must be an integer')
        sel=Selection()
        if shape=='rectangle':
            x,y,w,h=bounds(p.get('bounds'),doc.width(),doc.height())
            sel.select(x,y,w,h,255)
        elif shape in ('ellipse','polygon'):
            from .region_raster import shape_mask
            points=None
            if shape=='ellipse':
                x,y,w,h=bounds(p.get('bounds'),doc.width(),doc.height())
            else:
                points,(x,y,w,h)=polygon(p.get('points',[]),doc.width(),doc.height())
            sel.setPixelData(shape_mask(shape,(x,y,w,h),points),x,y,w,h)
        else: raise ValueError('Unknown selection shape')
        if feather: sel.feather(int(feather))
        existing=doc.selection()
        if mode!='replace':
            if existing is None: raise ValueError('No existing selection to combine')
            existing=existing.duplicate()
            getattr(existing,mode)(sel);sel=existing
        doc.setSelection(sel)
        return {'status':'ok','mode':mode,'shape':shape,'feather':feather,'bounds':[sel.x(),sel.y(),sel.width(),sel.height()]}

    def cmd_curve_stroke(self,p,settle=True):
        """One native brush curve. settle=False leaves the wait and canvas refresh to the caller (paint_pass does both once per pass)."""
        if 'pressure' in p: raise ValueError('Continuous variable pressure is not exposed by this Krita binding; curve_stroke uses preset path dynamics')
        start,segments=curve(p.get('start'),p.get('segments'))
        doc,layer,err=self._require_layer()
        if err: return err
        if layer.locked() or not layer.visible() or layer.paintAbility()!='PAINT': raise ValueError('Layer is not paintable')
        size=number(p.get('size',self.current_brush_size),'size',.01,10000)
        opacity=number(p.get('opacity',self.current_opacity),'opacity',0,1)
        flow=number(p.get('flow',1),'flow',0,1)
        color=p.get('color')
        if color is not None and not QColor(color).isValid(): raise ValueError('Invalid color')
        view=self.get_active_view()
        path=QPainterPath();path.moveTo(*start)
        for segment in segments:path.cubicTo(*segment)
        self._apply_brush_state(view,size=size,opacity=opacity,flow=flow,color=color)
        layer.paintPath(path,'ForegroundColor','None')
        if settle: doc.refreshProjection();doc.waitForDone()
        return {'status':'ok','rendering':'single_native_path','segments':len(segments),'variable_pressure':False}

    def cmd_duplicate_document(self,p):
        doc,err=self._require_document()
        if err:return err
        doc.waitForDone();clone=doc.clone()
        if clone is None:raise RuntimeError('Could not clone document')
        clone.setFileName('');clone.setName(str(p.get('name','Painting practice copy')))
        window=Krita.instance().activeWindow();window.showView(window.addView(clone))
        return {'status':'ok','name':clone.name(),'source':doc.fileName(),'unsaved_copy':True}

    def cmd_compare_region(self,p):
        doc,err=self._require_document()
        if err:return err
        x,y,w,h=bounds(p.get('bounds'),doc.width(),doc.height())
        scale=number(p.get('scale',1),'scale',.25,4)
        ow,oh=round(w*scale),round(h*scale)
        if min(ow,oh)<1 or max(ow,oh)>2048:raise ValueError('Each comparison panel must be 1..2048 pixels')
        reference=QImage(os.path.expanduser(p.get('reference_path','')))
        if reference.isNull():raise ValueError('Reference image could not be read')
        rx,ry,rw,rh=bounds(p.get('reference_bounds'),reference.width(),reference.height())
        if abs(rw/rh-w/h)>.01:raise ValueError('Comparison crops must have matching aspect ratios')
        doc.refreshProjection();doc.waitForDone()
        current=doc.projection(x,y,w,h)
        reference=reference.copy(rx,ry,rw,rh)
        result=QImage(ow*2+24,oh+40,QImage.Format.Format_RGB32);result.fill(QColor('#252525'))
        painter=QPainter(result);painter.setPen(Qt.GlobalColor.white)
        painter.drawText(8,25,'Reference');painter.drawText(ow+24,25,'Painting')
        painter.drawImage(0,40,reference.scaled(ow,oh,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation))
        painter.drawImage(ow+24,40,current.scaled(ow,oh,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation));painter.end()
        folder=output_dir(os.environ,QCoreApplication.organizationName());os.makedirs(folder,exist_ok=True)
        path=os.path.join(folder,'comparison_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.png')
        if not result.save(path):raise RuntimeError('Comparison export failed')
        return {'status':'ok','canvas_path':path,'bounds':[x,y,w,h],'reference_bounds':[rx,ry,rw,rh],'scale':scale}

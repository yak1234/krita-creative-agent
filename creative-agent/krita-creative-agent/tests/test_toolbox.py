"""Reversible broad tool dispatch, using a real session journal and fake native paint."""
import json
import unittest
import test_native as native

native.qt.QPointF = lambda x,y:(x,y)
class Node(native.Layer):
    def __init__(self, identity, doc): super().__init__(identity); self.doc=doc
    def type(self): return 'paintlayer'
    def setLocked(self,value): self.is_locked=value
    def remove(self): self.doc.nodes.remove(self); return True
    def setBlendingMode(self, mode): self.pixels += mode.encode()
    def setPixelData(self, pixels, x, y, width, height): self.pixels=bytes(pixels); return True
class View:
    erasing=False
    def eraserMode(self): return self.erasing
    def setEraserMode(self, value): self.erasing=value
class Harness(native.Harness):
    def __init__(self): super().__init__(); self.view=View()
    def get_active_view(self): return self.view
    def cmd_new_layer(self,p):
        self.created_layers+=1
        node=Node('layer-'+str(self.created_layers),self.doc)
        self.doc.nodes.append(node);self.doc.active=node
        return {'id':node.identity}
    def cmd_duplicate_layer(self,p):
        source=self.doc.active; result=self.cmd_new_layer(p)
        self.doc.active.pixels=source.pixels
        return result
    def cmd_curve_stroke(self,p):
        if p.get('fail'): raise ValueError('Invalid curve')
        self.doc.active.pixels+=b'erase' if self.view.erasing else b'stroke'
        return {'status':'ok'}
    def cmd_brush_settings(self,p): return {'properties':{'CompositeOp':'normal','EraserMode':False}}
    def cmd_configure_brush(self,p): return {'status':'ok'}
    def _creative_progress(self,*args): pass

def call(h,commands,source=None,identifier='toolbox',projection=None):
    params={'name':'Broad edit','commands':[{'tool':name,'parameters_json':json.dumps(p)} for name,p in commands]}
    if source: params['source_layer_id']=source
    if projection: params['projection_region']=projection
    return h.cmd_creative({'operation':'painting_toolbox','session_id':'session','operation_id':identifier,'params':params})

class Mask:
    def __init__(self): self.data=None
    def select(self,x,y,w,h,value): self.data=bytes([value])*(w*h)
    def pixelData(self,x,y,w,h): return self.data
    def setPixelData(self,data,x,y,w,h): self.data=bytes(data); return True
    def intersect(self,other): self.data=bytes(min(a,b) for a,b in zip(self.data,other.data))
    def feather(self,radius): pass

class ProjectionDocument(native.Document):
    def width(self): return 4
    def height(self): return 4
    def colorModel(self): return 'RGBA'
    def colorDepth(self): return 'U8'
    def projectionPixelData(self,x,y,w,h): return bytes([20,40,60,255])*(w*h)
    def createNode(self,name,kind): return Node('projection-copy',self)
    def addChildNode(self,node,above): self.nodes.append(node);return True

class ToolboxTests(unittest.TestCase):
    def test_visible_projection_copy_is_masked_reversible_and_never_replayed(self):
        h=Harness();h.doc=ProjectionDocument()
        h._creative_session.update(document_id=native.module.document_id(h.doc),width=4,height=4)
        previous=native.module.Selection;native.module.Selection=Mask
        try:
            original=Mask();original.data=bytes([255,0,255,255])
            h.doc.setSelection(original)
            result=call(h,[('curve_stroke',{})],projection=[0,0,2,2])
            self.assertEqual(result['status'],'ok')
            self.assertEqual(result['projection_region'],[0,0,2,2])
            self.assertEqual(h.doc.nodes[0].pixels[3:16:4],bytes([255,0,255,255]))
            self.assertIs(h.doc.selection(),original)
            self.assertTrue(call(h,[('curve_stroke',{})],projection=[0,0,2,2])['replayed'])
            self.assertEqual(len(h.doc.nodes),1)
            h.cmd_creative({'operation':'review_pass','session_id':'session','operation_id':'reject','params':{'pass_id':'toolbox','action':'reject'}})
            self.assertFalse(h.doc.nodes[0].visible())
        finally: native.module.Selection=previous

    def test_projection_copy_rejects_cross_stage_and_unsupported_edits(self):
        h=Harness();h.doc=ProjectionDocument()
        params={'name':'Retouch','projection_region':[0,0,2,2],'region':[1,1,2,2],
                'commands':[{'tool':'curve_stroke','parameters_json':'{}'}]}
        with self.assertRaisesRegex(ValueError,'inside the protected stage'):
            h._creative_validate_toolbox(h.doc,params)
        params.pop('region');params['commands']=[{'tool':'draw_shape','parameters_json':'{}'}]
        with self.assertRaisesRegex(ValueError,'selection-aware'):
            h._creative_validate_toolbox(h.doc,params)
        params['commands']=[{'tool':'curve_stroke','parameters_json':'{}'}]
        params['source_layer_id']='missing'
        with self.assertRaises(ValueError): h._creative_validate_toolbox(h.doc,params)

    def test_edit_copy_replay_and_reject_preserve_original(self):
        h=Harness();h.cmd_new_layer({});original=h.doc.active
        result=call(h,[('eraser',{'enabled':True}),('curve_stroke',{})],original.identity)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(original.pixels,b'paint');self.assertFalse(original.visible())
        self.assertEqual(h.doc.nodes[1].pixels,b'painterase');self.assertFalse(h.view.erasing)
        self.assertTrue(call(h,[('eraser',{'enabled':True}),('curve_stroke',{})],original.identity)['replayed'])
        self.assertEqual(len(h.doc.nodes),2)
        h.cmd_creative({'operation':'review_pass','session_id':'session','operation_id':'reject','params':{'pass_id':'toolbox','action':'reject'}})
        self.assertTrue(original.visible());self.assertFalse(h.doc.nodes[1].visible())
    def test_locked_source_can_be_edited_on_an_unlocked_copy(self):
        h=Harness();h.cmd_new_layer({});original=h.doc.active;original.is_locked=True
        result=call(h,[('curve_stroke',{})],original.identity)
        self.assertEqual(result['status'],'ok')
        self.assertTrue(original.locked());self.assertFalse(h.doc.nodes[1].locked())
        self.assertEqual(original.pixels,b'paint')
    def test_invalid_command_rolls_back_without_uncertain_latch(self):
        h=Harness();h.cmd_new_layer({});original=h.doc.active
        result=call(h,[('curve_stroke',{'fail':True})],original.identity)
        self.assertEqual(result['error_code'],'validation_rejected')
        self.assertEqual(len(h.doc.nodes),1);self.assertTrue(original.visible())
        self.assertFalse(h._creative_unresolved(h._creative_session))
        self.assertEqual(h._creative_committed_count(h._creative_session),0)
    def test_reject_preserves_newer_manual_edits_on_source(self):
        h=Harness();h.cmd_new_layer({});original=h.doc.active
        call(h,[('curve_stroke',{})],original.identity)
        original.pixels=b'new manual work'
        with self.assertRaisesRegex(ValueError,'newer edits'):
            h.cmd_creative({'operation':'review_pass','session_id':'session','operation_id':'reject','params':{'pass_id':'toolbox','action':'reject'}})
        self.assertEqual(original.pixels,b'new manual work')

if __name__=='__main__':unittest.main()

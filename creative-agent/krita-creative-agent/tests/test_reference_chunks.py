"""Owned continuation layers and authoritative operation receipt lookup."""
import unittest
import types
from test_native import Harness, request, Document, module, krita
Journal = module.Journal

class Observing(Harness):
    """Records whether each canvas render was told the projection was already fresh."""
    def __init__(self):
        import time
        super().__init__(); self.renders=[]
        self._creative_session.update(saved_once=True, last_saved_at=time.monotonic())   # actions re-read, not save
    def _creative_observe(self, doc, session, region=None):
        self.renders.append(session.pop('projection_fresh', False))
        return {'status':'ok','document_id':'doc','image_path':'/tmp/view-%d.png' % len(self.renders),'layers':self._creative_layer_list(doc)}

class Smudging(Harness):
    """Two presets: a Color Smudge blender and a pixel brush; records preset changes."""
    PRESETS = {'k) Blender Basic': '<Preset paintopid="colorsmudge"><param name="MergedPaint">false</param><param name="SmudgeRateValue">1</param></Preset>',
               'b) Basic-1': '<Preset paintopid="paintbrush"><param name="Opacity">1</param></Preset>'}
    def __init__(self):
        super().__init__(); self.brush = []
        self._saved = (krita.Krita.instance, getattr(krita, 'Preset', None))
        krita.Krita.instance = lambda: types.SimpleNamespace(resources=lambda _kind: {name: name for name in self.PRESETS})
        krita.Preset = lambda name: types.SimpleNamespace(toXML=lambda: self.PRESETS[name])
    def close(self):
        krita.Krita.instance, preset = self._saved
        if preset is None: del krita.Preset
        else: krita.Preset = preset
    def cmd_configure_brush(self, params): self.brush.append(('configure', params['properties'])); return {'status': 'ok'}
    def cmd_restore_brush(self, params): self.brush.append(('restore',)); return {'status': 'ok'}

def smudge_request(preset='k) Blender Basic'):
    r = request(); r['params'].update(preset=preset, smudge_overlay=True); return r

class ReferenceChunksTests(unittest.TestCase):
    def test_smudge_overlay_turns_merged_paint_on_for_the_pass_and_always_restores_it(self):
        h = Smudging(); self.addCleanup(h.close)
        self.assertEqual(h.cmd_creative(smudge_request())['status'], 'ok')
        self.assertEqual(h.brush, [('configure', {'MergedPaint': True}), ('restore',)])
        plain = request(); plain['operation_id'] = 'plain'
        self.assertEqual(h.cmd_creative(plain)['status'], 'ok')
        self.assertEqual(len(h.brush), 2, 'a pass without smudge_overlay leaves the preset alone')
        r = smudge_request(); r['operation_id'] = 'half'; r['params']['smudge_rate'] = 0.5
        self.assertEqual(h.cmd_creative(r)['status'], 'ok')
        self.assertEqual(h.brush[2:], [('configure', {'MergedPaint': True, 'SmudgeRateValue': 0.5}), ('restore',)])
        failing = Smudging(); self.addCleanup(failing.close); failing.fail = True
        self.assertEqual(failing.cmd_creative(smudge_request())['status'], 'partial')
        self.assertEqual(failing.brush, [('configure', {'MergedPaint': True}), ('restore',)], 'restored after a failed stroke too')

    def test_smudge_overlay_needs_a_color_smudge_preset_and_a_boolean(self):
        h = Smudging(); self.addCleanup(h.close)
        with self.assertRaisesRegex(ValueError, 'Color Smudge'):
            h.cmd_creative(smudge_request('b) Basic-1'))
        r = smudge_request(); r['params']['smudge_overlay'] = 'yes'
        with self.assertRaisesRegex(ValueError, 'boolean'):
            h.cmd_creative(r)
        r = request(); r['params']['smudge_rate'] = 0.5
        with self.assertRaisesRegex(ValueError, 'needs smudge_overlay'):
            h.cmd_creative(r)
        self.assertEqual((h.paints, h.brush), (0, []), 'nothing painted or configured')

    def test_chunks_share_layer_and_review_row_and_restore_selection(self):
        h=Harness(); h.doc.selected=object(); selection=h.doc.selected
        a=request();a['operation_id']='reference-job-0';a['params']['stage_id']='stage-1-0'
        first=h.cmd_creative(a)
        b=request();b['operation_id']='reference-job-1';b['params'].update(stage_id='stage-1-0',continue_layer_id=first['layer_id'])
        second=h.cmd_creative(b)
        self.assertEqual(h.created_layers,1);self.assertEqual(h.paints,2)
        self.assertIs(h.doc.selected,selection)
        rows=[p for p in second['passes'] if p['kind']=='paint_pass']
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['continuation_chunks'],2)
        self.assertNotIn('passes',h._creative_session['operations']['reference-job-1'][1])
        status=h.cmd_creative({'operation':'operation_status','session_id':'session','params':{'id':'reference-job-1'}})
        self.assertTrue(status['found']);self.assertTrue(status['result']['replayed'])
        self.assertEqual(status['committed_stage_counts']['stage-1-0'],2)
        h.cmd_creative(b);self.assertEqual(h.paints,2)
        h.cmd_creative({'operation':'review_pass','session_id':'session','operation_id':'reject','params':{'pass_id':'reference-job-0','action':'reject'}})
        self.assertFalse(h.doc.nodes[0].shown)
        with self.assertRaises(ValueError):
            b['operation_id']='reference-job-2';h.cmd_creative(b)

    def test_continuation_rejects_changed_layer_stage_region_or_unowned_layer(self):
        for kind in ('pixels','stage','region','unowned'):
            with self.subTest(kind=kind):
                h=Harness();a=request();first=h.cmd_creative(a)
                b=request();b['operation_id']='next';b['params']['continue_layer_id']=first['layer_id']
                if kind=='pixels':h.doc.nodes[0].pixels=b'manual'
                if kind=='stage':b['params']['stage_id']='different'
                if kind=='region':b['params']['region']=[0,0,100,100]
                if kind=='unowned':h._creative_session['layers'].clear()
                with self.assertRaises(ValueError):h.cmd_creative(b)
                self.assertEqual(h.paints,1)

    def test_continuation_batches_skip_the_before_render_and_the_second_recomposite(self):
        h=Observing();a=request();a['operation_id']='reference-job-0'
        first=h.cmd_creative(a);self.assertEqual(h.renders,[False,True])        # before; after the pass (fresh)
        b=request();b['operation_id']='reference-job-1';b['params']['continue_layer_id']=first['layer_id']
        second=h.cmd_creative(b);self.assertEqual(h.renders,[False,True,True])  # only the after view
        entry=h._creative_session['passes'][-1]
        self.assertEqual(entry['before_path'],first['image_path']);self.assertEqual(entry['after_path'],second['image_path'])
        h.cmd_creative({'operation':'observe','session_id':'session','params':{}})
        self.assertEqual(h.renders[-1],False)                                     # a later observation recomposites

    def test_journal_keeps_receipts_without_layer_lists_and_replay_restores_them(self):
        import json,os,tempfile,shutil
        h=Observing();out=tempfile.mkdtemp();self.addCleanup(shutil.rmtree,out,True)
        h._creative_session['output']=out
        first=h.cmd_creative(request());self.assertTrue(first['layers'])
        stored=Journal(out).operations()['op-1'][1]                      # the journal database
        self.assertNotIn('layers',stored);self.assertNotIn('passes',stored);self.assertEqual(stored['layer_id'],first['layer_id'])
        self.assertNotIn('layers',h._creative_session['operations']['op-1'][1])
        replay=h.cmd_creative(request())
        self.assertTrue(replay['replayed']);self.assertEqual([l['id'] for l in replay['layers']],['layer-1'])

    def test_a_pass_takes_up_to_1024_curves(self):
        h=Harness();r=request();r['params']['strokes']=r['params']['strokes']*1024
        self.assertEqual(h.cmd_creative(r)['status'],'ok')
        r=request();r['operation_id']='more';r['params']['strokes']=r['params']['strokes']*1025
        with self.assertRaises(ValueError):h.cmd_creative(r)

    def test_lookup_cannot_follow_a_different_document(self):
        h=Harness();h.doc=Document()
        r=h.cmd_creative({'operation':'operation_status','session_id':'session','params':{'id':'absent'}})
        self.assertEqual(r['error_code'],'document_changed')

if __name__=='__main__':unittest.main()

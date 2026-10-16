import test from 'node:test';
import assert from 'node:assert/strict';
import { PaintingBridge } from '../src/bridge.mjs';

test('direct painting bridge restricts transport to loopback without credentials or redirects',async()=>{
  for(const bridge_url of ['https://127.0.0.1:5678','http://example.com','http://user:secret@localhost:5678'])
    await assert.rejects(new PaintingBridge('.', {bridge_url}).connect(),/locally/);
  const bridge=new PaintingBridge('.',{bridge_url:'http://127.0.0.1:5678'});
  const original=globalThis.fetch;
  try {
    globalThis.fetch=async(url,options)=>{
      assert.equal(url.hostname,'127.0.0.1');assert.equal(options.redirect,'error');
      assert.deepEqual(JSON.parse(options.body),{action:'creative',params:{operation:'peek',params:{output_dir:'/private/tmp/example'},session_id:'session'},timeout:120});
      return {ok:true,json:async()=>({status:'ok',document_id:'doc'})};
    };
    assert.equal((await bridge.call('peek',{output_dir:'/private/tmp/example'},'session')).document_id,'doc');
  } finally {globalThis.fetch=original;}
});

test('transport loss distinguishes unknown painting outcome from unavailable read-only context',async()=>{
  const bridge=new PaintingBridge('.',{}),original=globalThis.fetch;
  try {
    globalThis.fetch=async()=>{throw new Error('simulated lost response');};
    await assert.rejects(bridge.call('paint_pass',{},'session','operation'),error=>error.code==='outcome_unknown');
    await assert.rejects(bridge.call('peek',{},'session'),error=>error.code==='unavailable');
    globalThis.fetch=async()=>({ok:true,json:async()=>({error:'The painting changed.',error_code:'canvas_changed'})});
    await assert.rejects(bridge.call('paint_pass'),error=>error.code==='canvas_changed');
  } finally {globalThis.fetch=original;}
});

test('Krita HTTP 500 command results retain recoverable validation and genuine uncertainty',async()=>{
  const bridge=new PaintingBridge('.',{}), original=globalThis.fetch;
  try {
    for (const [result,code] of [
      [{error:'ValueError: Only layers made in this session can be adjusted',error_code:'internal'},'validation_rejected'],
      [{error:'The painting changed.',error_code:'canvas_changed'},'canvas_changed'],
      [{error:'Stroke partially applied.',error_code:'partial_change'},'partial_change'],
      [{error:'Command timed out.',error_code:'timeout'},'outcome_unknown'],
      [{error:'RuntimeError: unknown native failure',error_code:'internal'},'outcome_unknown'],
    ]) {
      globalThis.fetch=async()=>({ok:false,status:500,json:async()=>result});
      await assert.rejects(bridge.call('adjust_layer'),error=>error.code===code && error.result===result);
    }
  } finally {globalThis.fetch=original;}
});

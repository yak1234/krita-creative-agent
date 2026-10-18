import test from 'node:test';
import assert from 'node:assert/strict';
import {request} from 'node:http';
import {mkdtemp,mkdir,writeFile,readFile,stat,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {LiveDiagnostics} from '../src/live-diagnostics.mjs';

function query(socket,path,method='GET') {
  return new Promise((resolve,reject)=>{
    const req=request({socketPath:socket,path,method},res=>{
      let text='';res.on('data',chunk=>text+=chunk);res.on('end',()=>resolve({status:res.statusCode,body:JSON.parse(text)}));
    });req.on('error',reject);req.end();
  });
}
test('live socket reads existing runtime, correlates pending work, exports native evidence and cleans up',async()=>{
  const root=await mkdtemp(join(tmpdir(),'creative-diagnostics-test-'));
  const id='12345678-1234-1234-1234-123456789abc';let resolveNative,calls=0;
  const runtime={config:{output:root},study:{id},goal:{current_step:1,status:'active'},mode:'agent',busy:true,
    pendingTools:new Map([['tool-1',{name:'paint_pass',at:123}]]),emit(){},redact:s=>s.replaceAll('private-key','[redacted]'),
    bridge:{call:async()=>{calls++;return new Promise(resolve=>resolveNative=resolve);}}};
  const diagnostics=new LiveDiagnostics(runtime);diagnostics.attach();
  try {
    const directory=join(root,'studies',id);await mkdir(directory,{recursive:true});
    await writeFile(join(directory,'.operations.json'),JSON.stringify({'op-1':{status:'committed'}}));
    await writeFile(join(directory,'.passes.json'),'[{"id":"pass-1"}]');
    await diagnostics.start();
    if (process.platform!=='win32') assert.equal((await stat(diagnostics.socket)).mode & 0o777,0o600);   // a Windows named pipe has no file mode
    const pending=runtime.bridge.call('paint_pass',{},id,'op-1');
    const state=await query(diagnostics.socket,'/state');
    assert.equal(state.body.goal.current_step,1);assert.equal(state.body.pending_native[0].operation_id,'op-1');
    assert.deepEqual(state.body.pending_native[0].tool_call_ids,['tool-1']);assert.equal(calls,1);
    runtime.goal.current_step=2;assert.equal((await query(diagnostics.socket,'/state')).body.goal.current_step,2);
    resolveNative({checkpoint:'painting.kra'});await pending;
    runtime.emit({type:'error',message:'private-key'});
    const events=(await query(diagnostics.socket,'/events')).body.events;
    const dispatch=events.find(e=>e.type==='native_dispatch'),result=events.find(e=>e.type==='native_result');
    assert.equal(dispatch.request_id,result.request_id);assert.ok(result.at);assert.ok(events.some(e=>e.type==='save_receipt'));
    assert.ok(!JSON.stringify(events).includes('private-key'));
    assert.equal((await query(diagnostics.socket,'/events?limit=501')).status,400);
    assert.equal((await query(diagnostics.socket,'/paint','POST')).status,404);
    const reports=await Promise.all([query(diagnostics.socket,'/report','POST'),query(diagnostics.socket,'/report','POST')]);
    const report=JSON.parse(await readFile(reports[0].body.path,'utf8'));
    assert.equal(report.records['.operations.json']['op-1'].status,'committed');
    assert.equal(report.records['.passes.json'][0].id,'pass-1');assert.ok(report.records['diagnostic-events.jsonl'].length);
    assert.equal(calls,1); // Diagnostic reads/report never dispatch native work.
    const endpoint=diagnostics.descriptor;
    await diagnostics.close();await assert.rejects(stat(endpoint),{code:'ENOENT'});
  } finally {await diagnostics.close();await rm(root,{recursive:true,force:true});}
});

test('timeline reports eviction and preserves unknown native outcomes without retry',async()=>{
  let calls=0;
  const runtime={config:{},emit(){},redact:s=>s,pendingTools:new Map(),bridge:{call:async()=>{calls++;throw Object.assign(new Error('lost result'),{code:'outcome_unknown'});}}};
  const diagnostics=new LiveDiagnostics(runtime);diagnostics.attach();
  await assert.rejects(runtime.bridge.call('paint_pass',{},'session','operation'),{code:'outcome_unknown'});
  assert.equal(calls,1);assert.equal(diagnostics.pending.size,0);assert.equal(diagnostics.events.at(-1).error_code,'outcome_unknown');
  for(let i=0;i<600;i++)diagnostics.record({type:'test'});
  assert.equal(diagnostics.events.length,500);assert.equal(diagnostics.timeline(1).truncated,true);
});

test('a local agent can end the chat as the panel’s End does, never while it paints',async()=>{
  const root=await mkdtemp(join(tmpdir(),'creative-diagnostics-end-'));
  const ended=[];
  const runtime={config:{output:root},study:{id:'chat-1'},goal:null,mode:'agent',busy:true,pendingTools:new Map(),emit(){},redact:s=>s,bridge:{call:async()=>({})},
    async end(){ended.push(this.study.id);this.study=null;}};
  const diagnostics=new LiveDiagnostics(runtime);diagnostics.attach();
  try {
    await diagnostics.start();
    const busy=await query(diagnostics.socket,'/end','POST');
    assert.deepEqual([busy.status,busy.body.error_code,ended],[409,'busy',[]],'painting: refused, nothing ended');
    runtime.busy=false;
    assert.deepEqual((await query(diagnostics.socket,'/end','POST')).body,{status:'ok',ended:'chat-1'});
    assert.deepEqual(ended,['chat-1']);
    assert.deepEqual((await query(diagnostics.socket,'/end','POST')).body,{status:'ok',ended:null},'no chat: nothing to end');
    assert.equal((await query(diagnostics.socket,'/end')).status,404,'GET never ends a chat');
    assert.ok(diagnostics.timeline(0,500).events.some(e=>e.type==='chat_ended_by_agent' && e.study_id==='chat-1'));
  } finally {await diagnostics.close();await rm(root,{recursive:true,force:true});}
});

test('a native result’s step timings reach the timeline, for finding what is slow on a large painting',async()=>{
  const root=await mkdtemp(join(tmpdir(),'creative-diagnostics-timings-'));
  const runtime={config:{output:root},study:{id:'12345678-1234-1234-1234-123456789abc'},goal:null,mode:'agent',busy:false,pendingTools:new Map(),emit(){},redact:s=>s,
    bridge:{call:async()=>({status:'ok',timings_ms:{before:20000,apply:350000,total:414000}})}};
  const diagnostics=new LiveDiagnostics(runtime);diagnostics.attach();
  try {
    await runtime.bridge.call('create_layer',{},'12345678-1234-1234-1234-123456789abc','op-1');
    const event=diagnostics.timeline(0,50).events.find(e=>e.type==='native_result');
    assert.deepEqual(event.timings_ms,{before:20000,apply:350000,total:414000});
  } finally {await diagnostics.close();await rm(root,{recursive:true,force:true});}
});

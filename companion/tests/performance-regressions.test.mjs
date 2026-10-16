import { recordingTracing } from './fake-langfuse.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { IdleSleepGuard } from '../src/idle-sleep-guard.mjs';
import { StudioRuntime } from '../src/studio.mjs';
import { resultContent } from '../src/tools.mjs';

test('Agent idle-sleep hold exists only during an active run',()=>{
  const children=[];
  const guard=new IdleSleepGuard({enabled:true,pid:123,spawnProcess:(path,args,options)=>{
    assert.equal(path,'/usr/bin/caffeinate');assert.deepEqual(args,['-i','-w','123']);assert.deepEqual(options,{stdio:'ignore'});
    const child=new EventEmitter();child.exitCode=null;child.killed=false;
    child.kill=()=>{child.killed=true;return true;};children.push(child);return child;
  }});
  guard.start();guard.start();assert.equal(children.length,1);
  guard.stop();assert.equal(children[0].killed,true);
  guard.start();assert.equal(children.length,2);
  guard.stop();assert.equal(children[1].killed,true);
});

test('stage context sends a large observed layer tree once while preserving document revision',()=>{
  const layers=Array.from({length:158},(_,i)=>({id:'unique-layer-'+i,name:'Layer '+i,depth:0,visible:true,opacity:255,editable_by_agent:true,type:'paintlayer'}));
  const runtime=new StudioRuntime({config:{output:'/tmp/creative-performance-test',prevent_idle_sleep:false},tracing:recordingTracing(),emit:()=>{},models:{getModel:()=>({input:['image']})}});
  runtime.study={id:'study',provider:'test',model:'test',references:[]};
  runtime.goal={brief:null,current_step:0,stage_operations:0,character_records:[],revision:1,user_updates:[],locked_requirements:[],reviews:[],progress:[],messages:[]};
  runtime.decisionObservation={document_id:'doc',revision:'revision-123',content_id:'content-123',layers,width:600,height:600};
  const context=runtime.context('agent');
  assert.equal(context.split('unique-layer-157').length-1,1);
  assert.equal(context.split('revision-123').length-1,1);
  assert.equal(JSON.parse(context.slice(context.indexOf('{'))).canvas.layers.length,158);
});

test('paint receipt keeps full native details but sends a smaller searchable layer index to the model',async()=>{
  const layers=Array.from({length:158},(_,i)=>({id:'layer-'+i,name:'Layer '+i,depth:0,visible:true,opacity:255,editable_by_agent:true,type:'paintlayer'}));
  const result={status:'ok',layer_id:'layer-120',layers,revision:'new-revision'};
  const response=await resultContent({emit:()=>{}},result,{compactLayers:true,focusLayerIds:['layer-5']});
  const model=JSON.parse(response.content[0].text);
  assert.equal(model.layer_count,158);
  assert.equal(model.layer_index.length,158);
  assert.deepEqual(model.affected_layers.map(layer=>layer.id),['layer-5','layer-120']);
  assert.ok(!('layers' in model));
  assert.equal(response.details.layers.length,158);
  assert.ok(response.content[0].text.length < JSON.stringify(result).length*0.6);
});

test('the model never receives host bookkeeping, and long results stay valid JSON', async()=>{
  const {modelResultText,keepRecentImages}=await import('../src/tools.mjs');
  const passes=Array.from({length:170},(_,i)=>({id:'pass-'+i,title:'x'.repeat(80)}));
  const text=modelResultText({status:'ok',layer_id:'l1',passes,image_path:'/home/artist/view.png',checkpoint:'/home/artist/painting.kra',document_id:'doc',note:'n'.repeat(9000)},{compactLayers:true});
  const model=JSON.parse(text);
  for (const key of ['passes','image_path','checkpoint','document_id']) assert.ok(!(key in model),key+' is host-only');
  assert.ok(text.length<=2100,'capped: '+text.length); assert.equal(model.layer_id,'l1');
  const image={type:'image',data:'A',mimeType:'image/png'};
  const messages=[1,2,3].map(i=>({role:'toolResult',content:[{type:'text',text:'r'+i},image]}));
  assert.deepEqual(keepRecentImages(messages).map(m=>m.content.some(p=>p.type==='image')),[false,true,true]);
  assert.equal(messages[0].content[1].type,'image','the saved transcript is not changed');
});

test('paint_batch validates every action before painting, runs them in order and returns one image', async()=>{
  const {batchTool}=await import('../src/tools.mjs');
  const {Type}=await import('typebox');
  const calls=[];
  const image={type:'image',data:'A',mimeType:'image/png'};
  const fake=(name,fail)=>({name,parameters:Type.Object({n:Type.Number()},{additionalProperties:false}),
    execute:async(id,args)=>{calls.push([name,id,args.n]); if(fail===args.n) throw new Error('brush refused'); return {content:[{type:'text',text:'{}'},image],details:{status:'ok',layer_id:'layer-'+args.n}};}});
  const tool=batchTool([fake('paint_pass',3),fake('adjust_layer')]);
  // One invalid action rejects the whole batch before anything paints.
  await assert.rejects(tool.execute('call-1',{actions:[{tool:'paint_pass',arguments:{n:1}},{tool:'adjust_layer',arguments:{n:'x'}}]}),/Action 2 \(adjust_layer\).*Nothing was painted/);
  assert.equal(calls.length,0);
  const result=await tool.execute('call-2',{actions:[1,2,3,4].map(n=>({tool:n%2?'paint_pass':'adjust_layer',arguments:{n}}))});
  const summary=JSON.parse(result.content[0].text);
  assert.deepEqual(calls.map(c=>c[2]),[1,2,3],'stops at the first failure');
  assert.equal(summary.status,'stopped'); assert.equal(summary.not_run,1); assert.equal(summary.actions[2].error,'brush refused');
  assert.equal(result.content.filter(p=>p.type==='image').length,1,'one image per batch');
  assert.ok(calls.every(([,id])=>/^batch-[0-9a-f]{16}-\d$/.test(id) && id.length<=100),'operation ids fit the native 100-character limit');
});

test('painting runs have no fixed time cap; chat turns keep the 10-minute cap',()=>{
  const runtime=new StudioRuntime({config:{output:'/tmp/creative-deadline-test',prevent_idle_sleep:false},tracing:recordingTracing(),emit:()=>{},models:{getModel:()=>({input:['image']})}});
  for (const mode of ['autopilot','agent']) { runtime.mode=mode; runtime.executionPhase='agent'; assert.equal(runtime.runDeadlineMs(),null,mode+' painting is bounded by allowances, not a timer'); }
  runtime.mode='ask'; runtime.executionPhase='ask'; assert.equal(runtime.runDeadlineMs(),600000);
  runtime.mode='autopilot'; runtime.executionPhase='plan'; assert.equal(runtime.runDeadlineMs(),600000,'planning turns stay capped');
});

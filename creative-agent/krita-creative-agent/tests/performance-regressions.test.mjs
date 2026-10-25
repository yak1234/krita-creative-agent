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

test('with "Keep the screen awake", the hold also keeps the display on, and each hold is reported for the panel',()=>{
  let display=false; const calls=[], states=[];
  const guard=new IdleSleepGuard({enabled:true,pid:7,display:()=>display,onChange:state=>states.push(state),spawnProcess:(path,args)=>{
    calls.push(args); const child=new EventEmitter(); child.exitCode=null; child.killed=false; child.kill=()=>{child.killed=true;return true;}; return child;
  }});
  guard.start(); guard.stop();
  display=true; guard.start(); guard.stop();
  assert.deepEqual(calls,[['-i','-w','7'],['-d','-i','-w','7']],'the display is held only when the artist turned it on');
  assert.deepEqual(states,[{active:true,display:false},{active:false,display:false},{active:true,display:true},{active:false,display:false}]);
});

test('stage context sends a large observed layer tree once while preserving document revision',()=>{
  const layers=Array.from({length:158},(_,i)=>({id:'unique-layer-'+i,name:'Layer '+i,depth:0,visible:true,opacity:255,editable_by_agent:true,type:'paintlayer'}));
  const runtime=new StudioRuntime({defaultPlanner:null,sharpenModel:{download:async()=>{throw new Error('No model downloads in tests.');},service:{upscale:async()=>{throw new Error('No sharpening in tests.');}}},config:{output:'/tmp/creative-performance-test',prevent_idle_sleep:false},tracing:recordingTracing(),emit:()=>{},models:{getModel:()=>({input:['image']})}});
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

test('an observation over its limit keeps the layers and the revision, never the bare stub (eyes-and-history 6)', async()=>{
  const {modelResultText}=await import('../src/tools.mjs');
  // 60 layers with every field the plugin sends, as in a 46-81 layer chat: over the 6000-character limit.
  const layer=(i,depth=0)=>({id:'{'+String(i).padStart(8,'0')+'-aaaa-bbbb-cccc-dddddddddddd}',name:'Move '+i+' · Kremlin towers, warm light',depth,opacity:1,visible:i%3!==0,editable_by_agent:i!==0,type:'paintlayer'});
  const observation=(layers,extra={})=>({status:'ok',document_id:'doc-1',name:'New Moscow',width:6000,height:4000,image_path:'/p/view.jpg',path:'/p/view.jpg',
    revision:'rev-42',content_id:'c',region:null,image_width:1568,image_height:1045,scale:0.261,layers,weight:{level:'ok'},filename:'/p/painting.kra',modified:true,
    artist_focus:{selected_layers:[]},comic:null,protected_areas:[],...extra});
  const index=JSON.parse(modelResultText(observation(Array.from({length:60},(_,i)=>layer(i,i%4===0?0:1)))));
  assert.equal(index.result_truncated,undefined,'no stub');
  assert.equal(index.revision,'rev-42'); assert.deepEqual([index.width,index.height],[6000,4000]);
  assert.equal(index.layers.length,60,'every layer, compact');
  assert.deepEqual(index.layers[0],{id:layer(0).id,name:layer(0).name,hidden:true,locked:true},'id, name, and only the flags that are set');
  assert.deepEqual(index.layers[1],{id:layer(1).id,name:layer(1).name,depth:1});
  // So many layers that even the compact index is over: the top level and the counts.
  const many=JSON.parse(modelResultText(observation(Array.from({length:400},(_,i)=>layer(i,i%20===0?0:1)))));
  assert.equal(many.revision,'rev-42'); assert.equal(many.layer_count,400); assert.equal(many.top_level_layers,20);
  assert.equal(many.layers.length,20,'the top-level layers'); assert.ok(many.layers.every(l=>!l.depth));
  assert.equal(typeof many.hidden_layers,'number');
  assert.match(many.layers_note,/top-level/);
  // Whatever else is long, the revision and size survive and the text stays valid JSON within its limit.
  const long=modelResultText(observation(Array.from({length:4000},(_,i)=>layer(i,0)),{artist_focus:{selected_layers:Array.from({length:500},(_,i)=>({id:'x'+i,name:'y'.repeat(30)}))}}));
  const parsed=JSON.parse(long);
  assert.equal(parsed.revision,'rev-42'); assert.deepEqual([parsed.width,parsed.height],[6000,4000]); assert.equal(parsed.layer_count,4000);
  assert.ok(long.length<=6000+8000+200,'within its limit and the layers\u2019 budget: '+long.length);
});

test('close-ups count apart: the newest look keeps its view and crops, the look before keeps its view only (review b)', async()=>{
  const {keepRecentImages}=await import('../src/tools.mjs');
  const image=n=>({type:'image',data:n,mimeType:'image/jpeg'});
  const look=(n,crops)=>({role:'toolResult',content:[{type:'text',text:'{}'},image('view'+n),
    ...Array.from({length:crops},(_,i)=>[{type:'text',text:'CLOSE-UP '+(i+1)+' of the area you work in: canvas [0, 0, 10, 10]'},image('crop'+n+i)]).flat()]});
  const kept=keepRecentImages([look(1,0),look(2,2),look(3,2)]).map(m=>m.content.filter(p=>p.type==='image').map(p=>p.data));
  assert.deepEqual(kept,[[],['view2'],['view3','crop30','crop31']]);
});

test('one layer with a huge name never stalls the layer budget (eyes-and-history review a)',{timeout:5000},async()=>{
  const {modelResultText}=await import('../src/tools.mjs');
  const huge=[{id:'a',name:'n'.repeat(20000),depth:0,visible:true,editable_by_agent:true,type:'paintlayer'}];
  const compact=JSON.parse(modelResultText({status:'ok',layer_id:'a',layers:huge,revision:'r'},{compactLayers:true}));
  assert.equal(compact.layer_index.length,1); assert.ok(compact.layer_index[0].name.length<300); assert.equal(compact.layer_index[0].id,'a');
  const observed=JSON.parse(modelResultText({status:'ok',layers:huge,revision:'r',width:10,height:10}));
  assert.equal(observed.layers.length,1); assert.ok(observed.layers[0].name.length<300); assert.equal(observed.revision,'r');
});

test('every native result with a revision refreshes the revision the next change expects (eyes-and-history 8)', async()=>{
  const {nativeExecute}=await import('../src/tools.mjs');
  const runtime={decisionObservation:{revision:'r1',document_id:'doc',layers:[{id:'a'}]},emit(){},
    callNative:async()=>({status:'ok',layer_id:'a',revision:'r2'})};
  await nativeExecute(runtime,'set_layer')('call-1',{layer_id:'a',visible:false});
  assert.equal(runtime.decisionObservation.revision,'r2','a layer change without an image still moves the revision');
  assert.deepEqual(runtime.decisionObservation.layers,[{id:'a'}],'the rest of the last observation stays');
  runtime.callNative=async()=>({status:'ok',brushes:[]});
  await nativeExecute(runtime,'list_brushes')('call-2',{});
  assert.equal(runtime.decisionObservation.revision,'r2','a result without a revision changes nothing');
  // A read-only result reports the CURRENT revision: adopting it would hide the artist's edits since the painter looked.
  runtime.callNative=async()=>({status:'ok',colors:[],revision:'artist-edit'});
  await nativeExecute(runtime,'sample_colors')('call-3',{points:[[1,1]]});
  assert.equal(runtime.decisionObservation.revision,'r2','only a change the painter made moves the expected revision');
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
  const runtime=new StudioRuntime({defaultPlanner:null,sharpenModel:{download:async()=>{throw new Error('No model downloads in tests.');},service:{upscale:async()=>{throw new Error('No sharpening in tests.');}}},config:{output:'/tmp/creative-deadline-test',prevent_idle_sleep:false},tracing:recordingTracing(),emit:()=>{},models:{getModel:()=>({input:['image']})}});
  for (const mode of ['autopilot','agent']) { runtime.mode=mode; runtime.executionPhase='agent'; assert.equal(runtime.runDeadlineMs(),null,mode+' painting is bounded by allowances, not a timer'); }
  runtime.mode='ask'; runtime.executionPhase='ask'; assert.equal(runtime.runDeadlineMs(),600000);
  runtime.mode='autopilot'; runtime.executionPhase='plan'; assert.equal(runtime.runDeadlineMs(),600000,'planning turns stay capped');
});

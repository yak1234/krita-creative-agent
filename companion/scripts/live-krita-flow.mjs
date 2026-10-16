/** No provider or bridge mocks. Missing prerequisites are blocked, not passed. */
import {readFile,writeFile,mkdir,copyFile} from 'node:fs/promises';
import {join,resolve,dirname} from 'node:path';
import {homedir} from 'node:os';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const exec=promisify(execFile);
export async function runKritaFlow({companion,output,documentId,provider,model,python,patchSource,routingMode='guide'}) {
 const report={status:'blocked',checks:[],live_provider:false,live_bridge:false};
 let runtime,bridge;const mutations=[];const routes=[];
 const check=(name,status,evidence)=>report.checks.push({name,status,...evidence});
 const here=dirname(fileURLToPath(import.meta.url));
 const pixels=async(before,after,mode,...bounds)=>{
  try{const r=await exec(python,[join(here,'check-live-pixels.py'),before,after,mode,...bounds.map(String)]);return JSON.parse(r.stdout);}
  catch(e){if(e.stdout){try{return JSON.parse(e.stdout);}catch{}}throw new Error('Pixel checker unavailable or failed');}
 };
 try {
  if(!companion||!documentId||!provider||!model||!python)throw new Error('Provide companion, document ID, painter provider/model, and Python with Pillow.');
  const build=JSON.parse(await readFile(join(companion,'build-info.json'),'utf8'));report.build=build.build_id;
  const {PaintingBridge}=await import(pathToFileURL(join(companion,'src/bridge.mjs')));
  const config={project_root:output,paintings_dir:output,output:join(output,'.creative-agent'),bridge_url:'http://127.0.0.1:5678',model_idle_timeout_ms:60000};
  bridge=new PaintingBridge(companion,config);await bridge.connect();
  const health=await bridge.call('health');report.live_bridge=true;report.loaded_build=health.build?.build_id;
  if(health.build?.build_id!==build.build_id)throw new Error('Loaded Krita bridge and test companion builds differ.');
  if(health.session_active)throw new Error('Another Creative Agent session owns the canvas.');
  const source=await bridge.call('context');report.document=source;
  if(source.document_id!==documentId||source.width!==600||source.height!==600)throw new Error('Open the explicitly selected 600 x 600 test document.');
  if(!health.capabilities?.gradient?.available)throw new Error('Loaded native Gradient adapter has not passed its live acceptance gate.');
  check('preflight','passed',{krita_version:health.krita_version});
  const native=bridge.call.bind(bridge);
  bridge.call=async(operation,params={},...rest)=>{
   // Observe real traffic; never replace a provider response or native result.
   const mutating=['begin','painting_toolbox','paint_pass','adjust_layer','review_pass'].includes(operation);
   if(mutating && runtime?.mode!=='agent')throw new Error('Read-only mode attempted native mutation');
   if(operation==='begin' && params.mode!=='current')throw new Error('Acceptance uses only the user-selected test document');
   const receipt=await native(operation,params,...rest);
   if(mutating)mutations.push({operation,operation_id:rest[1],replayed:!!receipt.replayed,document_id:receipt.document_id,layer_id:receipt.layer_id,checkpoint:receipt.checkpoint,commands:params.commands?.map(c=>c.tool)});
   return receipt;
  };
  const {StudioRuntime}=await import(pathToFileURL(join(companion,'src/studio.mjs')));
  await mkdir(config.output,{recursive:true});
  try{await copyFile(join(homedir(),'.pi/agent/models-store.json'),join(config.output,'model-catalog.json'));}catch(e){if(e.code!=='ENOENT')throw e;}
  runtime=new StudioRuntime({root:companion,config,bridge,emit:e=>{if(e.type==='error')report.last_error=runtime.redact(e.message);}});
  await runtime.initialize();
  runtime.diagnostics={record:e=>{if(['routing','visual_check','review_progress'].includes(e.type))routes.push(e);}};
  if(!runtime.models.hasConfiguredAuth(provider))throw new Error('Painter provider credentials are unavailable.');
  if(!runtime.models.getModel(provider,model)?.input.includes('image'))throw new Error('Choose an available vision-capable painter.');
  if(!['off','evaluate','guide'].includes(routingMode))throw new Error('Unknown routing mode.');
  await runtime.setExecutionSettings({routing:routingMode});
  report.routing_mode=routingMode;
  report.live_provider=true;
  await runtime.start({provider,model,chat_mode:'ask',mode:'current',name:'Luna live acceptance',prompt:'Describe the visible test canvas in one sentence. Do not paint or save.'});
  if(runtime.runError)throw new Error('Real painter Ask request failed');
  const before=await native('peek',{output_dir:runtime.study.directory,document_id:documentId,region:[0,0,600,600]},runtime.study.id);
  await runtime.prompt('Would a blue-to-gold gradient fit in the blank horizontal strip? Answer only; do not change the picture.');
  const askAfter=await native('peek',{output_dir:runtime.study.directory,document_id:documentId,region:[0,0,600,600]},runtime.study.id);
  const readonly=await pixels(before.image_path,askAfter.image_path,'unchanged');
  check('real_painter_ask_readonly',readonly.passed&&!mutations.length?'passed':'failed',{pixels:readonly,native_mutations:mutations.length});
  if(!readonly.passed||mutations.length)throw new Error('Ask changed the live document');
  if(patchSource){
   await runtime.editPlan({title:'Native repair acceptance',objective:'Repair the red square on the observed source using native Smart Patch.',requirements:['Only change [180,390,40,40].','Use smart_patch on a reversible source copy.','Use rectangle selection bounds [180,390,40,40], not a polygon.','Use exactly paths [[[195,405],[205,405],[205,415],[195,415],[195,405]]], diameter 35, accuracy 50, patch_radius 4; do not substitute a line or change settings.'],freedom:[],steps:[{title:'Repair red square',region:[180,390,40,40],max_operations:1,stop_after:true,done_when:'The red square matches its beige surroundings.'}],completion:['Source pixels preserved.']});
  }else await runtime.editPlan({title:'Native gradient acceptance',objective:'Draw one native blue-to-gold gradient in the specified blank strip.',requirements:['Only change x40..559, y260..299.','Use painting_toolbox gradient, not brush strokes or raster imports.','Preserve every existing layer.'],freedom:[],steps:[{title:'Gradient strip',region:[40,260,520,40],max_operations:1,stop_after:true,done_when:'One blue-to-gold gradient is present inside the strip.'}],completion:['Outside pixels remain unchanged.']});
  await runtime.setLimits({minutes:2,passes:1});
  report.status='running';
  await runtime.prompt(patchSource ? `Repair the red defect using painting_toolbox on observed source_layer_id ${patchSource}. First read painting_tool_help and inspect layers. Use selection shape rectangle with exact bounds [180,390,40,40]; do not use a polygon selection. Then smart_patch with EXACT paths [[[195,405],[205,405],[205,415],[195,415],[195,405]]], diameter 35, accuracy 50, patch_radius 4. The path must close the defect; do not substitute or change these settings. Stop after one contribution.` : 'Execute the stage using painting_toolbox: create a new contribution, set a rectangular selection [40,260,520,40], then gradient shape linear, start [40,280], end [559,280], foreground #153e80, background #efb958, opacity 1. Read painting_tool_help first. Use the actual gradient command. Stop after one contribution.',{chat_mode:'agent',start_plan:true});
  const after=await native('observe',{region:[0,0,600,600]},runtime.study.id);
  const painted=await pixels(before.image_path,after.image_path,patchSource?'patch':'gradient',...(patchSource?[180,390,40,40]:[40,260,520,40]));
  const realRoutes=routes.filter(r=>r.model && r.operation && r.status==='recommended');
  const passes=mutations.filter(m=>m.operation==='painting_toolbox'&&!m.replayed);
  check(patchSource?'luna_to_painter_to_native_smart_patch':'luna_to_painter_to_native_gradient',painted.passed&&passes.length===1&&passes[0].commands?.includes(patchSource?'smart_patch':'gradient')&&(routingMode==='off'||realRoutes.some(r=>r.operation.choice===(patchSource?'repair':'gradient')))?'passed':'failed',{pixels:painted,routes:realRoutes,passes,before:before.image_path,after:after.image_path});
  const checkpoint=passes.at(-1)?.checkpoint;
  if(checkpoint){const saved=await pixels(after.image_path,checkpoint,'unchanged');check('saved_kra_receipt',saved.passed?'passed':'failed',{file:checkpoint,pixels:saved});}
  else check('saved_kra_receipt','failed',{reason:'No checkpoint returned by the painting operation'});
  // Actual Stop while a real model request is outstanding; no fake delayed server.
  await runtime.setMode('ask');
  const activityBefore=runtime.lastModelActivityAt;
  const pending=runtime.prompt('Inspect the gradient and explain its color transition in detail. Do not edit.');
  let stoppedDuringRequest=false;
  const timer=setInterval(()=>{if(runtime.busy && runtime.lastModelActivityAt!==activityBefore){stoppedDuringRequest=true;runtime.stop();clearInterval(timer);}},20);
  try{await pending;}finally{clearInterval(timer);}
  const stopAfter=await native('peek',{output_dir:runtime.study.directory,document_id:documentId,region:[0,0,600,600]},runtime.study.id);
  const stopped=await pixels(after.image_path,stopAfter.image_path,'unchanged');
  check('stop_real_request',!runtime.busy&&stopped.passed&&stoppedDuringRequest?'passed':'failed',{pixels:stopped,stopped_during_model_activity:stoppedDuringRequest});
  const studyId=runtime.study.id;await runtime.end();await runtime.resume(studyId);
  const resumed=await native('peek',{output_dir:runtime.study.directory,document_id:documentId,region:[0,0,600,600]},runtime.study.id);
  const retained=await pixels(stopAfter.image_path,resumed.image_path,'unchanged');
  check('restore_without_repainting',!runtime.busy&&retained.passed?'passed':'failed',{pixels:retained});
  check('document_switch_during_paint','blocked',{reason:'Requires a second explicitly selected test document and an interactive switch during a run; not simulated.'});
  if(!patchSource)check('smart_patch_full_agent_path','blocked',{reason:'Native fixture evidence is separate; full-agent repair scenario remains to run.'});
  report.status=report.checks.some(c=>c.status==='failed')?'failed':report.checks.some(c=>c.status==='blocked')?'blocked':'passed';
 } catch(e) {
  const reason=runtime?.redact(e.message)??e.message;
  if(report.status==='running'){report.status='failed';check('real_execution','failed',{reason});}
  else {report.status='blocked';check('prerequisite','blocked',{reason});}
 } finally {
  if(runtime){runtime.stop();if(!runtime.busy)await runtime.end().catch(()=>{});await runtime.releaseLock().catch(()=>{});}
  await bridge?.close().catch(()=>{});
  report.mutations=mutations;report.routing_events=routes;report.finished_at=new Date().toISOString();
  await writeFile(join(output,'krita-flow.json'),JSON.stringify(report,null,2)+'\n');
 }
 return report;
}

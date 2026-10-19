/** Coordinate an actual UI tab switch while a real StudioRuntime owns test.kra. */
import {readFile,writeFile,mkdir,copyFile,access} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {homedir} from 'node:os';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {dirname} from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const exec=promisify(execFile);
const [outputArg,companionArg,targetId,otherId,python]=process.argv.slice(2);
if(!outputArg||!companionArg||!targetId||!otherId||!python)throw new Error('Provide output, installed companion, target and other document IDs.');
const output=resolve(outputArg),companion=resolve(companionArg);await mkdir(output,{recursive:false});
const report={status:'blocked',build:null,checks:[],mutations:[]};let runtime,bridge;
const check=(name,status,detail={})=>report.checks.push({name,status,...detail});
const waitFile=async name=>{for(let i=0;i<1200;i++){try{await access(join(output,name));return;}catch{}await new Promise(r=>setTimeout(r,100));}throw new Error('Timed out waiting for UI tab switch');};
try{
 const {PaintingBridge}=await import(pathToFileURL(join(companion,'src/bridge.mjs')));
 const {StudioRuntime}=await import(pathToFileURL(join(companion,'src/studio.mjs')));
 const info=JSON.parse(await readFile(join(companion,'build-info.json')));report.build=info.build_id;
 const config={project_root:output,paintings_dir:output,output:join(output,'.creative-agent'),bridge_url:'http://127.0.0.1:5678',model_idle_timeout_ms:60000};
 bridge=new PaintingBridge(companion,config);await bridge.connect();const health=await bridge.call('health');if(health.build?.build_id!==info.build_id)throw new Error('Bridge/companion build mismatch');
 const context=await bridge.call('context');if(context.document_id!==targetId||!context.documents.some(d=>d.document_id===otherId))throw new Error('Expected target active and second test document open');
 const native=bridge.call.bind(bridge);bridge.call=async(op,p={},...rest)=>{const r=await native(op,p,...rest);if(['begin','painting_toolbox','paint_pass','adjust_layer','review_pass'].includes(op))report.mutations.push(op);return r;};
 await mkdir(config.output,{recursive:true});try{await copyFile(join(homedir(),'.pi/agent/models-store.json'),join(config.output,'model-catalog.json'));}catch(e){if(e.code!=='ENOENT')throw e;}
 runtime=new StudioRuntime({root:companion,config,bridge,emit:()=>{}});await runtime.initialize();await runtime.setExecutionSettings({routing:'off'});
 const provider='openrouter',model='deepseek/deepseek-v4.1-flash';if(!runtime.models.hasConfiguredAuth(provider))throw new Error('No real painter connection');
 await runtime.start({provider,model,chat_mode:'ask',mode:'current',name:'Live document-switch guard',prompt:'Describe this canvas briefly without editing.'});
 const directory=runtime.study.directory;const studyId=runtime.study.id;
 const beforeTarget=await native('peek',{output_dir:directory,document_id:targetId,region:[0,0,600,600]},studyId);
 const beforeOther=await native('peek',{output_dir:directory,document_id:otherId,region:[0,0,600,600]},studyId);
 await writeFile(join(output,'switch-now.json'),JSON.stringify({targetId,otherId}));await waitFile('switched.json');
 const switched=await native('context');check('other_document_active',switched.document_id===otherId?'passed':'failed',{observed:switched.document_id});
 await runtime.editPlan({title:'Document-switch guard',objective:'Draw a native gradient in the bound test document.',requirements:['Never paint another open document.'],freedom:[],steps:[{title:'Gradient',region:[40,260,520,40],max_operations:1,stop_after:true,done_when:'A new gradient exists.'}],completion:['Only the bound document changed.']});
 await runtime.setLimits({minutes:1,passes:1});
 try{await runtime.prompt('Paint one linear gradient in the target test document using painting_toolbox.',{chat_mode:'agent',start_plan:true});}catch(e){report.model_error=runtime.redact(e.message);}
 const afterOther=await native('peek',{output_dir:directory,document_id:otherId,region:[0,0,600,600]},studyId);
 report.beforeOther=beforeOther.image_path;report.afterOther=afterOther.image_path;report.beforeTarget=beforeTarget.image_path;
 await writeFile(join(output,'switch-back-now.json'),'{}');await waitFile('switched-back.json');
 const back=await native('context');check('target_restored',back.document_id===targetId?'passed':'failed',{observed:back.document_id});
 const afterTarget=await native('peek',{output_dir:directory,document_id:targetId,region:[0,0,600,600]},studyId);report.afterTarget=afterTarget.image_path;
 check('no_native_mutation_after_switch',report.mutations.length===0?'passed':'failed',{mutations:report.mutations});
 for(const key of ['Target','Other']){
  const result=await exec(python,[join(dirname(fileURLToPath(import.meta.url)),'check-live-pixels.py'),report['before'+key],report['after'+key],'unchanged']);
  const pixels=JSON.parse(result.stdout);check(key.toLowerCase()+'_pixels_unchanged',pixels.passed?'passed':'failed',{pixels});
 }
 report.status=report.checks.every(c=>c.status==='passed')?'passed':'failed';
}catch(e){report.error=runtime?.redact(e.message)??e.message;check('execution','blocked',{reason:report.error});}
finally{if(runtime){runtime.stop();await runtime.end().catch(()=>{});await runtime.releaseLock().catch(()=>{});}await bridge?.close().catch(()=>{});await writeFile(join(output,'switch-report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,checks:report.checks,report:join(output,'switch-report.json')}));process.exitCode=report.status==='passed'?0:report.status==='failed'?1:2;}

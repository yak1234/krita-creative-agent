/** Reject a real saved agent Smart Patch pass, then restore the prior accepted result. */
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {homedir} from 'node:os';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {dirname} from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const exec=promisify(execFile);
const [outputArg,companionArg,studyOutputArg,studyId,passId,sourceId,acceptedId,python]=process.argv.slice(2);
if([outputArg,companionArg,studyOutputArg,studyId,passId,sourceId,acceptedId,python].some(x=>!x))throw new Error('Provide output, installed companion, study output/id/pass, source/accepted layer IDs, and Pillow Python.');
const output=resolve(outputArg),companion=resolve(companionArg),studyOutput=resolve(studyOutputArg);await mkdir(output,{recursive:false});
const report={status:'blocked',checks:[]},check=(name,status,detail={})=>report.checks.push({name,status,...detail});let runtime,bridge;
try{
 const {PaintingBridge}=await import(pathToFileURL(join(companion,'src/bridge.mjs')));
 const {StudioRuntime}=await import(pathToFileURL(join(companion,'src/studio.mjs')));
 const info=JSON.parse(await readFile(join(companion,'build-info.json')));report.build=info.build_id;
 const config={project_root:studyOutput,paintings_dir:studyOutput,output:join(studyOutput,'.creative-agent'),bridge_url:'http://127.0.0.1:5678'};
 bridge=new PaintingBridge(companion,config);await bridge.connect();const health=await bridge.call('health');if(info.build_id!==health.build?.build_id)throw new Error('Loaded build mismatch');
 runtime=new StudioRuntime({root:companion,config,bridge,emit:()=>{}});await runtime.initialize();await runtime.resume(studyId);
 const target=runtime.study.target_document_id;const native=bridge.call.bind(bridge);
 const before=await native('peek',{output_dir:runtime.study.directory,document_id:target,region:[0,0,600,600]},studyId);
 await runtime.reviewPass({pass_id:passId,action:'reject'});
 const rejected=await native('peek',{output_dir:runtime.study.directory,document_id:target,region:[0,0,600,600]},studyId);
 const pixels=JSON.parse((await exec(python,[join(dirname(fileURLToPath(import.meta.url)),'check-live-pixels.py'),before.image_path,rejected.image_path,'reject_patch','180','390','40','40'])).stdout);
 check('native_review_reject',pixels.passed?'passed':'failed',{pixels,before:before.image_path,after:rejected.image_path});
 // Restore the previously accepted contribution so the test canvas ends repaired.
 await runtime.end();runtime=null;
 const url='http://127.0.0.1:5678';
 for(const [action,params] of [['select_layer',{id:sourceId}],['layer_settings',{visible:false}],['select_layer',{id:acceptedId}],['layer_settings',{visible:true}]]){
  const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,params})});const body=await response.json();if(!response.ok||body.error)throw new Error('Could not restore the accepted test contribution');
 }
 const restored=await native('peek',{output_dir:join(studyOutput,'.creative-agent','studies',studyId),document_id:target,region:[0,0,600,600]},studyId).catch(()=>null);
 if(restored){const same=JSON.parse((await exec(python,[join(dirname(fileURLToPath(import.meta.url)),'check-live-pixels.py'),before.image_path,restored.image_path,'unchanged'])).stdout);check('accepted_result_restored',same.passed?'passed':'failed',{pixels:same});}
 report.status=report.checks.every(c=>c.status==='passed')?'passed':'failed';
}catch(e){report.error=e.message;check('execution','blocked',{reason:e.message});}
finally{if(runtime){runtime.stop();await runtime.end().catch(()=>{});await runtime.releaseLock().catch(()=>{});}await bridge?.close().catch(()=>{});await writeFile(join(output,'result.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,checks:report.checks.map(x=>({name:x.name,status:x.status})),report:join(output,'result.json')}));process.exitCode=report.status==='passed'?0:report.status==='failed'?1:2;}

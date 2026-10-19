/** Live acceptance entry point. Exit 0 passed, 1 failed, 2 blocked. No mock transports. */
import {parseArgs,promisify} from 'node:util';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {execFile} from 'node:child_process';
import {LunaRouter} from '../src/routing.mjs';
import {LunaClient} from '../src/luna-decisions.ts';
import {routingKey} from './evaluate-routing.mjs';
import {runKritaFlow} from './live-krita-flow.mjs';
const exec=promisify(execFile);
// Solid 64x64 PNGs: upper half blue, lower half orange or green.
async function controlImage(lower) {
 const {deflateSync,crc32}=await import('node:zlib');
 const w=64,h=64,raw=Buffer.alloc((w*3+1)*h);
 for(let y=0;y<h;y++)for(let x=0;x<w;x++)raw.set(y<h/2?[40,70,160]:lower,y*(w*3+1)+1+x*3);
 const chunk=(type,data)=>{const len=Buffer.alloc(4);len.writeUInt32BE(data.length);const td=Buffer.concat([Buffer.from(type),data]);const crc=Buffer.alloc(4);crc.writeUInt32BE(crc32(td));return Buffer.concat([len,td,crc]);};
 const ihdr=Buffer.alloc(13);ihdr.writeUInt32BE(w,0);ihdr.writeUInt32BE(h,4);ihdr.set([8,2,0,0,0],8);
 return {type:'image',mimeType:'image/png',data:Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',ihdr),chunk('IDAT',deflateSync(raw)),chunk('IEND',Buffer.alloc(0))]).toString('base64')};
}
async function imageControl(client) {
 const questions={lower_warm:{type:'noul',instructions:'Is the lower half of the image warm orange?',criteria:{true:'Lower half is warm orange.',false:'Lower half is not orange.'}}};
 const probability={};
 for(const [name,rgb] of [['orange',[235,140,60]],['green',[60,170,80]]]) {
  const r=await client.decide({parts:['Synthetic test image.',await controlImage(rgb)],questions});
  if(r.fallback)return {name:'luna_image_control',status:'blocked',reason:r.fallback};
  probability[name]=r.answers.lower_warm.noul;
 }
 return {name:'luna_image_control',status:probability.orange>.8&&probability.green<.2?'passed':'failed',probability};
}
const {values}=parseArgs({options:{output:{type:'string'},'patch-source':{type:'string'},companion:{type:'string'},document:{type:'string'},provider:{type:'string'},model:{type:'string'},python:{type:'string'},'routing-only':{type:'boolean'},'routing-mode':{type:'string'},'doppler-project':{type:'string'},'doppler-config':{type:'string'}}});
if(!values.output)throw new Error('Provide a new --output directory for retained live evidence.');
const output=resolve(values.output);await mkdir(output,{recursive:false});
const report={schema:1,started_at:new Date().toISOString(),test_kind:'live_acceptance',mocks_used:false,status:'blocked',checks:[]};
let key=await routingKey();
if(!key&&values['doppler-project']&&values['doppler-config']){
 try{const r=await exec('doppler',['secrets','get','OPENROUTER_API_KEY','--project',values['doppler-project'],'--config',values['doppler-config'],'--plain'],{timeout:15000});key=r.stdout.trim();report.credential_source='doppler';}catch{report.credential_error='Doppler credential unavailable';}
}else if(key)report.credential_source='environment_or_pi_openrouter';
try{
 if(!key){report.checks.push({name:'real_luna_routing',status:'blocked',reason:'No OpenRouter credential available; no requests were made.'});}
 else{
  // Child/runtime clients receive only the named key; other Doppler secrets are never fetched.
  process.env.OPENROUTER_API_KEY=key;
  // The image must actually reach the model: two controls differing only in colour.
  const control=await imageControl(new LunaClient({apiKey:key}));
  report.checks.push(control);await writeFile(join(output,'image-control.json'),JSON.stringify(control,null,2)+'\n');
  const router=new LunaRouter({apiKey:key});
  const cases=JSON.parse(await readFile(new URL('../tests/fixtures/routing-heldout-v1.json',import.meta.url),'utf8'));
  const results=[];
  for(const item of cases){
   const state={direction:item.text,mode:'agent',references:item.reference?[{id:'reference-1',purpose:'likeness'}]:[],reference_jobs:item.job?[{id:'job-1',status:'painting'}]:[],capabilities:{gradient:{available:true},smart_patch:{available:true}},note:'Synthetic scenario metadata for intent classification only; no claim of a connected document or tool execution.'};
   const decision=await router.evaluate(state);results.push({request:item.text,expected:item.route,...decision,correct:decision.operation?.choice===item.route});
  }
  const responded=results.filter(r=>r.operation&&r.model).length;
  const accuracy=results.filter(r=>r.correct).length/results.length;
  const routing={name:'real_luna_routing',status:responded<results.length?'blocked':accuracy>=.9?'passed':'failed',fixture:'routing-heldout-v1',cases:results.length,api_responses:responded,accuracy,results};
  report.checks.push(routing);await writeFile(join(output,'routing.json'),JSON.stringify(routing,null,2)+'\n');
 }
 if(values['routing-only'])report.checks.push({name:'full_krita_acceptance',status:'blocked',reason:'Routing-only run: painter and Krita were not tested.'});
 else if(!key)report.checks.push({name:'full_krita_acceptance',status:'blocked',reason:'OpenRouter key required for the full path.'});
 else{
  const flow=await runKritaFlow({companion:values.companion&&resolve(values.companion),output,documentId:values.document,provider:values.provider,model:values.model,python:values.python,patchSource:values['patch-source'],routingMode:values['routing-mode']||'guide'});
  report.checks.push({name:'full_krita_acceptance',status:flow.status,report:'krita-flow.json',checks:flow.checks});
 }
}catch(error){report.checks.push({name:'runner',status:'failed',reason:String(error.message).split(key||'\0').join('[redacted]')});}
finally{
 report.status=report.checks.some(c=>c.status==='failed')?'failed':report.checks.some(c=>c.status==='blocked')?'blocked':'passed';
 report.finished_at=new Date().toISOString();await writeFile(join(output,'acceptance.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({status:report.status,report:join(output,'acceptance.json'),checks:report.checks.map(({name,status,accuracy,cases,api_responses})=>({name,status,accuracy,cases,api_responses}))},null,2));
 process.exitCode=report.status==='passed'?0:report.status==='failed'?1:2;
}

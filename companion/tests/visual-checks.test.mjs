import test from 'node:test';
import assert from 'node:assert/strict';
import {passCheck,progressCheck,artifactFindings,QUESTIONS} from '../src/visual-checks.mjs';
const before={type:'image',data:'YmVmb3Jl',mimeType:'image/png'}, after={type:'image',data:'YWZ0ZXI=',mimeType:'image/png'};
const FAILURES=Object.keys(QUESTIONS.pass.failures);
function client(answer) {
 const requests=[];
 return {requests,async decide(request){requests.push(request);return {elapsed_ms:2,usage:{cost:.0001,input_tokens:1000},...answer(request,requests.length)};}};
}
const ORDINARY=FAILURES.filter(id=>!QUESTIONS.pass.failures[id].reference_only);
const nouls=values=>({answers:Object.fromEntries([...FAILURES,'established'].map(id=>[id,{type:'noul',noul:values[id] ?? (id==='established' ? .99 : .01)}]))});

test('a clean pass costs one request and reports no findings',async()=>{
 const c=client(()=>nouls({}));
 const r=await passCheck({client:c,before,after});
 assert.equal(c.requests.length,1);assert.deepEqual(r.findings,[]);
 assert.deepEqual(Object.keys(c.requests[0].questions),[...ORDINARY,'established'],'hard join and duplicated band only for reference chunks');
 assert.deepEqual(ORDINARY,['flat_block','stripes','ellipses','hard_graphic']);
 assert.ok(ORDINARY.every(id=>c.requests[0].questions[id].type==='noul' && /not present in BEFORE/.test(c.requests[0].questions[id].instructions)));
 assert.deepEqual(c.requests[0].parts,['BEFORE (canvas before this paint pass):',before,'AFTER (canvas after this paint pass):',after]);
});
test('a flagged pass is located in a second request on AFTER only',async()=>{
 const c=client((request,n)=>n===1 ? nouls({stripes:.93,splice:.75,duplicate:.69})
  : {answers:{stripes:{type:'choice',choice:'bottom_center'},splice:{type:'choice',choice:'middle_left'}}});
 const r=await passCheck({client:c,before,after,reference:true});
 assert.equal(c.requests.length,2);
 assert.deepEqual(Object.keys(c.requests[1].questions),['splice','stripes'],'below-threshold duplicate (0.69) is ignored');
 assert.deepEqual(c.requests[1].parts,['AFTER (canvas after this paint pass):',after]);
 assert.deepEqual(r.findings.map(f=>[f.type,f.location]),[['splice','middle_left'],['stripes','bottom_center']]);
 assert.equal(r.usage.cost,.0002);
});
test('location failure keeps findings without locations; malformed answers fall back',async()=>{
 const located=await passCheck({client:client((r,n)=>n===1?nouls({ellipses:.9}):{fallback:'timeout'}),before,after});
 assert.deepEqual(located.findings.map(f=>[f.type,f.location]),[['ellipses',null]]);assert.equal(located.location_fallback,'timeout');
 const bad=await passCheck({client:client(()=>({answers:{splice:{type:'noul',noul:2}}})),before,after});
 assert.equal(bad.fallback,'service_or_response_error');
 const refused=await passCheck({client:client(()=>({fallback:'refused'})),before,after});
 assert.equal(refused.fallback,'refused');
});
test('before the painting is established, flat shapes are not flagged; severe means sure damage to an established painting',async()=>{
 const c=client(()=>nouls({flat_block:.95,stripes:.8,established:.3}));
 const r=await passCheck({client:c,before,after});
 assert.deepEqual(r.findings.map(f=>f.type),['stripes'],'flat block ignored on a block-in, stripes kept');
 const established={probabilities:{flat_block:.95,ellipses:.8,hard_graphic:.9,stripes:.99},established:.99};
 assert.deepEqual(artifactFindings(established).map(f=>[f.type,f.severe]),[['flat_block',true],['ellipses',false],['hard_graphic',false],['stripes',false]],'hard graphic alone is reported, never undone');
 assert.ok(artifactFindings({...established,established:null}).every(f=>!f.severe),'unknown stage: report, never undo');
 const malformed=await passCheck({client:client(()=>({answers:{...nouls({}).answers,established:{type:'noul',noul:3}}})),before,after});
 assert.equal(malformed.fallback,'service_or_response_error');
});
test('progress scores each repeated failing check and averages them',async()=>{
 const checks=[{id:'check-1',text:'Porch reads as recessed.'},{id:'check-2',text:'Windows have sills.'}];
 const c=client(()=>({answers:{check_0:{type:'score',score:.4},check_1:{type:'score',score:2.2}}}));
 const r=await progressCheck({client:c,previous:before,current:after,checks});
 assert.deepEqual(r.scores,{'check-1':.4,'check-2':2.2});assert.equal(r.mean,1.3);
 const q=c.requests[0].questions.check_0;
 assert.equal(q.type,'score');assert.deepEqual(q.criteria,QUESTIONS.progress.scale);assert.match(q.instructions,/Porch reads as recessed/);
 assert.deepEqual(c.requests[0].parts,['PREVIOUS (canvas at the previous review):',before,'CURRENT (canvas now):',after]);
});
test('progress caps checks, rejects out-of-range scores and passes through fallbacks',async()=>{
 const many=Array.from({length:12},(_,i)=>({id:'c'+i,text:'Check '+i}));
 const c=client(({questions})=>({answers:Object.fromEntries(Object.keys(questions).map(k=>[k,{type:'score',score:1}]))}));
 const r=await progressCheck({client:c,previous:before,current:after,checks:many});
 assert.equal(Object.keys(c.requests[0].questions).length,QUESTIONS.progress.max_checks);assert.equal(r.mean,1);
 assert.equal((await progressCheck({client:client(()=>({answers:{check_0:{type:'score',score:7}}})),previous:before,current:after,checks:many.slice(0,1)})).fallback,'service_or_response_error');
 assert.equal((await progressCheck({client:client(()=>({fallback:'timeout'})),previous:before,current:after,checks:many.slice(0,1)})).fallback,'timeout');
 assert.equal((await progressCheck({client:client(()=>({})),previous:before,current:after,checks:[]})).fallback,'no_checks');
});

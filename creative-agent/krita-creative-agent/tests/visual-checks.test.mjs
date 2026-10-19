import test from 'node:test';
import assert from 'node:assert/strict';
import {passCheck,progressCheck,moveCheck,MAX_FEATURES,artifactFindings,QUESTIONS} from '../src/visual-checks.ts';
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

// moveCheck: one batch of an Agent move, with focal features by name.
const moveAnswers=values=>({answers:Object.fromEntries(Object.entries(values).map(([id,p])=>[id,{type:'noul',noul:p}]))});
const moveClient=(values,locate={})=>client((request,n)=>n===1
 ? moveAnswers(Object.fromEntries(Object.keys(request.questions).map(id=>[id,values[id] ?? (id==='established' ? .95 : .1)])))
 : {answers:Object.fromEntries(Object.entries(locate).map(([id,choice])=>[id,{type:'choice',choice}]))});
test('moveCheck asks the artifact questions, texture over forms and one question per feature',async()=>{
 const c=moveClient({});
 await moveCheck({client:c,before,after,features:['Moon','Lit window']});
 const keys=Object.keys(c.requests[0].questions);
 for (const id of ['flat_block','established','texture_over_forms','feature_0','feature_1']) assert.ok(keys.includes(id),id);
 assert.ok(!keys.includes('splice') && !keys.includes('any_feature'));
 assert.match(c.requests[0].questions.feature_0.instructions,/Is the Moon that BEFORE shows/);
 assert.equal(c.requests[0].purpose,'detect-move-failures');
});
test('with no features it asks the generic object question',async()=>{
 const c=moveClient({});
 await moveCheck({client:c,before,after,features:[]});
 const keys=Object.keys(c.requests[0].questions);
 assert.ok(keys.includes('any_feature')); assert.ok(!keys.includes('feature_0'));
});
test('a covered moon is a located finding naming the feature',async()=>{
 const c=moveClient({feature_0:.9},{feature_0:'top_right'});
 const r=await moveCheck({client:c,before,after,features:['Moon']});
 assert.deepEqual(r.findings,[{type:'covered_feature',feature:'Moon',label:'Moon covered',probability:.9,location:'top_right'}]);
 assert.equal(c.requests[1].purpose,'locate-move-failures');
});
test('texture over forms on a block-in is exempt',async()=>{
 const r=await moveCheck({client:moveClient({texture_over_forms:.9,established:.3}),before,after,features:[]});
 assert.deepEqual(r.findings,[]);
});
test('features past MAX_FEATURES are dropped',async()=>{
 const c=moveClient({});
 await moveCheck({client:c,before,after,features:['a','b','c','d','e','f']});
 assert.equal(MAX_FEATURES,4);
 assert.deepEqual(Object.keys(c.requests[0].questions).filter(k=>k.startsWith('feature_')),['feature_0','feature_1','feature_2','feature_3']);
});
test('a move check fallback is returned, not findings',async()=>{
 const r=await moveCheck({client:client(()=>({fallback:'timeout',elapsed_ms:5})),before,after,features:['Moon']});
 assert.deepEqual(r,{fallback:'timeout',elapsed_ms:5});
});

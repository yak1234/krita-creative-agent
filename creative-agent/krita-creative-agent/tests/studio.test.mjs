import { recordingTracing } from './fake-langfuse.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, rm, writeFile, readFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { crc32, deflateSync } from 'node:zlib';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { Value } from 'typebox/value';
import { scanFolder } from '../src/project-folder.ts';
import { StudioRuntime, freshGoal, validateReview, normalizeBrief, repeatedReviewFailures, progressStalled, approvedReviewScope, restoredReviewStart, agentMoveInstructions } from '../src/studio.mjs';

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=', 'base64');
const brief = { title:'Two characters', objective:'A quiet portrait of two people.', requirements:['Mara wears a red coat.','Ivo has green eyes.'],
  freedom:['Choose the background.'], steps:[{title:'Establish figures',done_when:'Two correctly placed silhouettes.'}], completion:['Both people are visible.'] };
const pass = {name:'Figure silhouettes',preset:'Test brush',strokes:[{start:[20,20],segments:[[30,30,40,40,50,50]],size:70,opacity:0.2,flow:0.5,color:'#c0422a'}]};
const call = (name,args) => ({tool_calls:[{index:0,id:'call-'+Math.random().toString(36).slice(2),type:'function',function:{name,arguments:JSON.stringify(args)}}]});

test('review plateau counts repeated failing checks across changed passes and resets on progress',()=>{
  const review=(pass,ids,revision=1)=>({verdict:'continue',revision,stage:0,pass_count:pass,
    checks:ids.map(id=>({id,met:false}))});
  assert.equal(repeatedReviewFailures([review(1,['window']),review(2,['window']),review(3,['window'])]),3);
  assert.equal(repeatedReviewFailures([review(1,['window']),review(2,['window']),review(3,['porch'])]),1);
  assert.equal(repeatedReviewFailures([review(1,['window']),review(1,['window'])]),1);
  assert.equal(repeatedReviewFailures([review(1,['window']),review(2,['window'],2)]),1);
  assert.deepEqual(approvedReviewScope([{original:'Move the rail down',replacement:'Keep the rail here'}]),
    [{superseded:'Move the rail down',current:'Keep the rail here'}]);
  assert.equal(restoredReviewStart({reviews:[review(1,['window']),review(2,['window'])]}),2,
    'old saved studies begin a fresh plateau window');
  assert.equal(restoredReviewStart({review_start_index:1,reviews:[review(1,['window']),review(2,['window'])]}),1);
});

async function harness(respond, bridgeHook) {
  const output = await mkdtemp(join(tmpdir(),'creative-studio-'));
  const requests=[]; const calls=[]; const events=[];
  const server = createServer(async(req,res)=>{
    let body=''; for await(const chunk of req) body+=chunk;
    const request=JSON.parse(body); requests.push(request);
    let delta;
    try { delta=await respond(request,requests.length); } catch(error) { res.writeHead(500); res.end(error.message); return; }
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    for(const choice of [{delta:{role:'assistant',...delta},finish_reason:null},{delta:{},finish_reason:delta.tool_calls?'tool_calls':'stop'}])
      res.write('data: '+JSON.stringify({id:'reply',object:'chat.completion.chunk',created:1,model:'vision-test',choices:[{index:0,...choice}]})+'\n\n');
    res.end('data: [DONE]\n\n');
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  const models=await ModelRuntime.create({authPath:join(output,'auth.json'),modelsPath:null,refreshOnCreate:false});
  models.registerProvider('local-test',{api:'openai-completions',baseUrl:`http://127.0.0.1:${server.address().port}/v1`,models:[{id:'vision-test',name:'Test',reasoning:false,input:['text','image'],
    cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:128000,maxTokens:4096}]});     // the painter's tool schemas (60k characters) leave little of 64k before compaction (at 47k) starts mid-test
  await models.setRuntimeApiKey('local-test','test-only');
  let observation;
  const bridge={async call(operation,params,id,operationId){
    calls.push({operation,params}); const override = await bridgeHook?.(operation,params,id,operationId); if(override !== undefined) return override;
    if (operation==='context') return {document_id:'doc',active_document_id:'doc',name:'Untitled',filename:'',width:768,height:1024,modified:true,revision:'revision-0'};
    if(['begin','peek'].includes(operation)){
      const path=join(params.output_dir,'view.png'); await writeFile(path,png);
      observation={status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:path,layers:[],revision:'revision-0',content_id:'content-0',captured_at:new Date().toISOString(),
        ...(operation==='begin'?{checkpoint:params.painting_path ?? join(params.output_dir,'painting.kra')}:{})};
      if (operation === 'begin') await writeFile(observation.checkpoint, 'test painting');
    }
    return operation==='end'?{status:'ok'}:observation;
  }};
  const capabilities={async initialize(){},status(){return {status:'verified',route_verified:true,images_supported:true,tools_supported:true};},async verify(){return {route_verified:true,cached:true};},async invalidate(){}};
  const runtime=new StudioRuntime({root:output,config:{output},models,bridge,capabilities,tracing:recordingTracing(),emit:e=>events.push(e)});
  return {runtime,requests,calls,events,output,start:(mode,prompt='Help me plan',extra={})=>runtime.start({provider:'local-test',model:'vision-test',chat_mode:mode,prompt,mode:'copy',...extra}),
    async close(){if(runtime.busy) runtime.stop(); await runtime.writeQueue; await runtime.end().catch(()=>{}); runtime.dispose(); server.closeAllConnections(); await new Promise(r=>server.close(r)); await rm(output,{recursive:true,force:true});}};
}

test('Ask and Plan are read-only; questions and user-edited character rules persist through resume', {timeout:20000}, async()=>{
  let planning=0;
  const h=await harness(req=>{
    const names=req.tools.map(t=>t.function.name);
    assert.ok(!names.includes('paint_pass'));
    assert.ok(!names.includes('painting_toolbox'));
    if(!names.includes('propose_plan')) return {content:'We can discuss the painting without changing it.'};
    if(!planning++) return call('ask_question',{question:'How should the surface look?',options:['Subtle tooth','Visibly chalky']});
    return call('propose_plan',brief);
  });
  try{
    await h.start('ask'); assert.ok(h.calls.every(c=>['context','peek'].includes(c.operation)));
    await h.runtime.setMode('plan'); await h.runtime.prompt('Plan two characters.');
    assert.equal(h.runtime.goal.status,'needs_input'); assert.equal(h.runtime.busy,false);
    await h.runtime.prompt('You decide.'); assert.equal(h.runtime.goal.status,'ready');
    assert.ok(h.calls.every(c=>['context','peek'].includes(c.operation)),'discussion and planning never create or save a canvas');
    const revised={...brief,requirements:[...brief.requirements,'Keep Mara seated on the left.']};
    await h.runtime.editPlan(revised);
    const id=h.runtime.study.id; const count=h.requests.length;
    await h.runtime.end(); await h.runtime.resume(id);
    assert.equal(h.requests.length,count,'resume makes no model request');
    assert.deepEqual(h.runtime.goal.brief.requirements,revised.requirements);
    await h.runtime.prompt('Make the plan clearer.');
    assert.ok(h.runtime.goal.brief.requirements.includes('Keep Mara seated on the left.'),'model cannot silently drop manually locked rules');
    await assert.rejects(h.runtime.callNative('paint_pass',pass,'forbidden'),/disabled/);
    await assert.rejects(h.runtime.callNative('painting_toolbox',{},'forbidden-toolbox'),/disabled/);
    const saved=(await h.runtime.store.load(h.runtime.study.id)).goal;   // records live in SQLite
    assert.equal(saved.revision,3);
  }finally{await h.close();}
});

test('a temporary provider failure after painting retries without replaying the completed pass', {timeout:20000}, async()=>{
  let painted=false, failed=false;
  const h=await harness(req=>{
    const names=req.tools.map(t=>t.function.name);
    if(names.includes('propose_plan')) return call('propose_plan',brief);
    if(names.includes('submit_review')) return call('submit_review',{verdict:'complete',summary:'All checks passed.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Observed.'}))});
    if(!painted){painted=true;return call('paint_pass',pass);}
    if(!failed){failed=true;throw new Error('503 temporarily unavailable');}
    return call('request_review',{reason:'Review the existing pass.'});
  });
  try {
    await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});
    assert.ok(failed);assert.equal(h.runtime.goal.status,'complete');assert.equal(h.runtime.goal.passes,1);
    assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,1);
    assert.ok(h.events.some(e=>e.phase==='retrying'));
  } finally {await h.close();}
});

test('Plan discussion never paints; in Autopilot a reply without a question continues painting', {timeout:20000}, async()=>{
  let painted=false;
  const h=await harness(req=>{
    const names=req.tools.map(t=>t.function.name);
    if(names.includes('submit_review')) return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
    if(names.includes('paint_pass')) {
      if(!painted){painted=true;return call('paint_pass',pass);}
      return call('request_review',{reason:'Painting finished.'});
    }
    if(names.includes('start_painting')) return {content:'The surface still needs texture.'};
    if(h.runtime.mode==='plan' && h.runtime.goal.brief) return {content:'The surface still needs texture.'};
    return call('propose_plan',brief);
  });
  try {
    await h.start('plan');
    await h.runtime.prompt('What still needs work? Do not paint.');
    assert.equal(h.runtime.goal.passes,0); assert.ok(!h.calls.some(c=>c.operation==='begin'));
    await h.runtime.setMode('autopilot'); await h.runtime.prompt('What still needs work?');
    assert.equal(h.runtime.goal.passes,1);assert.ok(painted);
    assert.equal(h.calls.filter(c=>c.operation==='begin').length,1);
  } finally {await h.close();}
});

test('legacy canvas-based plans bind the current canvas instead of creating a blank target', async()=>{
  let painted=false;
  const h=await harness(req=>{
    const names=req.tools.map(t=>t.function.name);
    if(names.includes('propose_plan'))return call('propose_plan',brief);
    if(names.includes('submit_review'))return call('submit_review',{verdict:'complete',summary:'Done.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
    if(!painted){painted=true;return call('paint_pass',pass);}
    return call('request_review',{reason:'Stage finished.'});
  });
  try {
    await h.start('plan','Finish the painting',{mode:'new'});delete h.runtime.study.explicit_new_canvas;
    await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});
    assert.equal(h.calls.find(c=>c.operation==='begin').params.mode,'current');
    assert.equal(h.runtime.goal.status,'complete');
    assert.equal(h.runtime.goal.limits.minutes,0);assert.equal(h.runtime.goal.limits.passes,0);
    h.runtime.goal.used_ms=86400000;h.runtime.goal.passes=1000;
    assert.equal(h.runtime.allowanceExceeded(),false);
  } finally {await h.close();}
});

test('Use this canvas rebinds a zero-pass conversation without saving or painting', async()=>{
  const h=await harness(()=>call('propose_plan',brief));
  try {
    await h.start('plan');const path=join(h.output,'Existing painting.kra');await writeFile(path,'original');
    const originalCapture=h.runtime.captureCanvas.bind(h.runtime);
    h.runtime.captureCanvas=async()=>{const result=await originalCapture();result.snapshot.filename=path;return result;};
    await h.runtime.useAttachedCanvas();
    assert.equal(h.runtime.study.painting_file,'Existing painting.kra');
    assert.equal(h.runtime.study.needs_resume,true);assert.equal(h.runtime.goal.status,'paused');
    assert.ok(!h.calls.some(c=>['begin','paint_pass','adjust_layer'].includes(c.operation)));
    assert.equal(await readFile(path,'utf8'),'original');
    h.runtime.goal.passes=1;await assert.rejects(h.runtime.useAttachedCanvas(),/already has painting changes/);
  } finally {await h.close();}
});

test('Agent continues after failed independent visual review and stops only after every criterion passes', {timeout:20000}, async()=>{
  let painted=0,reviewed=0,agentCalls=0;
  const h=await harness(req=>{
    const names=req.tools.map(t=>t.function.name);
    if(names.includes('propose_plan')) return call('propose_plan',brief);
    if(names.includes('submit_review')){
      assert.deepEqual(names,['submit_review']);
      assert.match(JSON.stringify(req.messages),/technical_evidence/);
      assert.match(JSON.stringify(req.messages),/Native Krita document and persisted operation journal/);
      const images=req.messages.filter(m=>m.role==='user').flatMap(m=>Array.isArray(m.content)?m.content:[]).filter(c=>c.type==='image_url');
      assert.ok(images.length,'reviewer actually receives the canvas');
      reviewed++;
      return call('submit_review',{verdict:reviewed===1?'continue':'complete',summary:reviewed===1?'Coat color needs correction.':'All visible requirements met.',
        issues:reviewed===1?['Coat too orange.']:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:reviewed>1||i!==0,evidence:i===0?'Checked the coat color.':'Checked the visible character.'}))});
    }
    assert.ok(names.includes('paint_pass')); agentCalls++;
    const text=JSON.stringify(req.messages);
    assert.ok(text.includes('Mara wears a red coat.')); assert.ok(text.includes('Ivo has green eyes.'));
    if(agentCalls%2===1){painted++;return call('paint_pass',pass);}
    return call('request_review',{reason:'Compare the figures.'});
  });
  try{
    await h.start('plan'); assert.ok(h.calls.every(c=>['context','peek'].includes(c.operation)));
    await h.runtime.setMode('autopilot'); await h.runtime.prompt('',{start_plan:true});
    assert.equal(painted,2); assert.equal(reviewed,2); assert.equal(h.runtime.goal.status,'complete');
    assert.equal(h.calls.filter(c=>c.operation==='begin').length,1);
    assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,2);
    assert.equal(h.runtime.goal.passes,2); assert.equal(h.runtime.busy,false);
    const file=join(h.output,h.runtime.study.painting_file);
    assert.equal(h.runtime.study.painting_file,'Creative painting.kra','painting filename is relative and outside internal state');
    await h.runtime.end(); await h.runtime.resumeFile(file);
    assert.equal(h.runtime.goal.status,'paused'); assert.equal(h.runtime.goal.reviews.length,2);
  }finally{await h.close();}
});

test('Pause waits for an in-flight brush pass, prevents further work, and resumes without duplicating it', {timeout:20000}, async()=>{
  let entered,settle;
  const painting=new Promise(r=>entered=r); const release=new Promise(r=>settle=r);
  const h=await harness(req=>req.tools.some(t=>t.function.name==='propose_plan')?call('propose_plan',brief):call('paint_pass',pass),
    async op=>{if(op==='paint_pass'){entered();await release;}});
  try{
    await h.start('plan'); await h.runtime.setMode('autopilot');
    const running=h.runtime.prompt('',{start_plan:true});
    await painting; h.runtime.stop(); settle(); await running;
    assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,1);
    assert.equal(h.runtime.goal.status,'paused'); assert.equal(h.runtime.goal.passes,1);
    const count=h.requests.length, id=h.runtime.study.id;
    await h.runtime.end(); await h.runtime.resume(id);
    assert.equal(h.requests.length,count); assert.equal(h.runtime.goal.status,'paused');
  }finally{settle();await h.close();}
});

test('paint budget and mode are enforced before native dispatch', async()=>{
  const h=await harness(()=>call('propose_plan',brief));
  try{
    await h.start('plan'); await h.runtime.setMode('autopilot');
    h.runtime.goal.status='active'; h.runtime.goal.approved_revision=h.runtime.goal.revision; h.runtime.executionPhase='agent';
    h.runtime.goal.limits.passes=1; h.runtime.goal.passes=1;
    await assert.rejects(h.runtime.callNative('paint_pass',pass,'limit'),/allowance/);
    assert.ok(h.calls.every(c=>['context','peek'].includes(c.operation)));
    h.runtime.goal=freshGoal('ask'); h.runtime.mode='ask';
    await assert.rejects(h.runtime.callNative('adjust_layer',{},'ask'),/disabled/);
  }finally{await h.close();}
});

const imagesInLatestMessage = req => {
  const user = req.messages.filter(m=>m.role==='user').at(-1);
  return (Array.isArray(user?.content)?user.content:[]).filter(c=>c.type==='image_url');
};

test('references go to the model reduced, once per chat, and again after a resume', {timeout:20000}, async()=>{
  const reduced='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';   // a different valid PNG
  let resizes=0;
  const h=await harness(()=>({content:'Noted.'}),async(op,params)=>{
    if(op==='model_image'){resizes++;assert.equal(params.max_side,1568);return {status:'ok',scaled:true,width:1568,height:1000,mime_type:'image/png',image_base64:reduced};}
  });
  const text=req=>JSON.stringify(req.messages.filter(m=>m.role==='user').at(-1).content);
  try {
    const path=join(h.output,'reference.png');await writeFile(path,png);
    await h.start('ask','What do you see?',{references:[{path}]});
    let images=imagesInLatestMessage(h.requests.at(-1));   // the reference, then the attached canvas
    assert.equal(images.length,2);assert.ok(images[0].image_url.url.endsWith(reduced),'the reduced copy, not the original');
    assert.match(text(h.requests.at(-1)),/attached to this message/);
    await h.runtime.canvas({action:'detach'});
    await h.runtime.prompt('And the colours?');
    assert.equal(imagesInLatestMessage(h.requests.at(-1)).length,0,'not attached again');
    assert.match(text(h.requests.at(-1)),/attached earlier in this chat/);
    const id=h.runtime.study.id;await h.runtime.end();await h.runtime.resume(id);
    await h.runtime.prompt('Still there?');
    images=imagesInLatestMessage(h.requests.at(-1));
    assert.equal(images.length,1,'a resumed chat gets the references again');assert.ok(images[0].image_url.url.endsWith(reduced));
    assert.equal(resizes,1,'Krita resizes each reference once; later turns use the cached copy');
  }finally{await h.close();}
});

test('a reference goes unchanged when Krita cannot resize it', {timeout:20000}, async()=>{
  const h=await harness(()=>({content:'Noted.'}),async op=>{ if(op==='model_image') throw new Error('bridge offline'); });
  try {
    const path=join(h.output,'reference.png');await writeFile(path,png);
    await h.start('ask','What do you see?',{references:[{path}]});
    const images=imagesInLatestMessage(h.requests.at(-1));
    assert.equal(images.length,2);assert.ok(images[0].image_url.url.endsWith(png.toString('base64')));
  }finally{await h.close();}
});

test('new Ask deterministically includes live unsaved canvas bytes and an exact snapshot receipt; detach survives messages', {timeout:20000}, async()=>{
  const h=await harness(()=>({content:'I can see the painting.'}));
  try {
    await h.start('ask','Do you see this painting?',{mode:'new'});
    assert.equal(imagesInLatestMessage(h.requests.at(-1)).length,1);
    assert.ok(imagesInLatestMessage(h.requests.at(-1))[0].image_url.url.endsWith(png.toString('base64')));
    const receipt=h.events.find(e=>e.type==='message_context');
    assert.equal(receipt.status,'included'); assert.equal(receipt.canvas.modified,true);
    assert.equal(receipt.canvas.document_id,'doc'); assert.equal(receipt.canvas.name,'Untitled');
    assert.equal(h.runtime.goal.messages[0].canvas.content_id,receipt.canvas.content_id);
    const peekCount=h.calls.filter(c=>c.operation==='peek').length;
    await h.runtime.canvas({action:'detach'});
    await h.runtime.prompt('Discuss the idea without the canvas.');
    assert.equal(imagesInLatestMessage(h.requests.at(-1)).length,0);
    assert.equal(h.calls.filter(c=>c.operation==='peek').length,peekCount);
    await assert.rejects(h.runtime.callNative('observe'),/Canvas not included/);
    const id=h.runtime.study.id; await h.runtime.end(); await h.runtime.resume(id);
    assert.equal(h.runtime.canvasSelection.selected,false);
    assert.ok(h.calls.every(c=>['peek','context'].includes(c.operation)));
  } finally {await h.close();}
});

test('capture failure prevents a false included receipt and prevents the provider request', {timeout:20000}, async()=>{
  let fail=false;
  const h=await harness(()=>({content:'Canvas observed.'}),op=>{if(op==='peek'&&fail) throw new Error('Canvas capture failed.');});
  try {
    await h.start('ask'); const requests=h.requests.length;
    const receipts=h.events.filter(e=>e.type==='message_context').length;
    fail=true; await assert.rejects(h.runtime.prompt('Look again.'),/capture failed/);
    assert.equal(h.requests.length,requests);
    assert.equal(h.events.filter(e=>e.type==='message_context').length,receipts);
    assert.equal(h.events.filter(e=>e.type==='context').at(-1).state,'error');
    assert.equal(h.runtime.busy,false);
  } finally {await h.close();}
});

const latestUserText = req => {
  const user = req.messages.filter(m=>m.role==='user').at(-1);
  return Array.isArray(user?.content) ? user.content.filter(c=>c.type==='text').map(c=>c.text).join('\n') : String(user?.content ?? '');
};

test('Ask is teacher mode: it gets the Krita lesson guide and no painting tools; Plan does not', {timeout:20000}, async()=>{
  const h=await harness(()=>({content:'Here is how a painter would build it.'}));
  try {
    await h.start('ask','How would I recreate this in Krita?');
    const asked=h.requests.at(-1);
    assert.match(latestUserText(asked),/Ask mode is teacher mode/);
    assert.match(latestUserText(asked),/message the artist could send in Agent mode/);
    const guide=latestUserText(asked);
    for (const requirement of [
      /Label it "Agent prompt".*fenced text block/,
      /copying that prompt alone.*must supply the stage's artistic direction/,
      /Repeat the relevant subject, style, composition and palette/,
      /Scope and starting state:/, /Visible result:/, /Construction:/, /Preservation:/,
      /Finish and stop:.*stop after this stage without starting the next one/,
      /split it into smaller stages with separate prompts/,
      /2 or 3 practice problems under the label "Practice"/, /never on their artwork/, /Every step, without exception, ends with its own Practice block/,
      /Goal:/, /Setup:/, /Do:/, /Check:/, /Common mistake:/, /build from easy to harder/,
      /outside its fenced block, so copying the prompt never copies the exercises/,
      /request a correction of that same stage before proceeding/,
    ]) assert.match(guide,requirement,'Ask supplies the standalone stage-prompt contract');
    const names=asked.tools?.map(t=>t.function.name) ?? [];
    assert.deepEqual(names.sort(),['list_reference_paintings','observe_canvas','sample_canvas_colors','view_reference'],'Ask only looks');
    assert.ok(h.calls.every(c=>['context','peek'].includes(c.operation)),'the canvas is only read');
    await h.runtime.setMode('plan'); await h.runtime.prompt('Plan a winter river scene.');
    assert.doesNotMatch(latestUserText(h.requests.at(-1)),/teacher mode/);
  } finally {await h.close();}
});

test('a lesson from Ask is saved for the artist in every mode and never sent to the painter', {timeout:20000}, async()=>{
  const lesson='# Lesson: Winter river at night\n\n1. Block in the sky.\n2. Glow the lamps.';
  let reply='Here is how a painter would build it.\n\n'+lesson;
  const h=await harness(()=>({content:reply}));
  try {
    await h.start('ask','How would I recreate this in Krita?');
    assert.equal(h.runtime.goal.lesson.title,'Winter river at night');
    assert.equal(h.runtime.goal.lesson.markdown,lesson,'the lesson starts at its heading');
    assert.equal(h.events.filter(e=>e.type==='goal').at(-1).goal.lesson.title,'Winter river at night','the panel receives it');
    reply='Use Multiply for shadow.'; await h.runtime.prompt('Which blend mode darkens?');
    assert.equal(h.runtime.goal.lesson.title,'Winter river at night','a quick answer keeps the lesson');
    reply='# Lesson: Not from Ask'; await h.runtime.setMode('plan'); await h.runtime.prompt('Plan it.');
    assert.equal(h.runtime.goal.lesson.title,'Winter river at night','only Ask writes lessons');
    assert.doesNotMatch(h.runtime.context('agent'),/Winter river at night|Glow the lamps/,'the painter context leaves the lesson out');
    assert.doesNotMatch(latestUserText(h.requests.at(-1)),/Glow the lamps/);
  } finally {await h.close();}
});

test('pinned visual context targets its selected document without taking painting ownership', {timeout:20000}, async()=>{
  const h=await harness(()=>({content:'Pinned context received.'}));
  try {
    await h.runtime.canvas({action:'attach',follow_active:false,document_id:'doc'});
    await h.start('ask','Describe this canvas.');
    assert.ok(h.calls.filter(c=>c.operation==='peek').every(c=>c.params.document_id==='doc'));
    assert.ok(h.calls.every(c=>['context','peek'].includes(c.operation)));
    await h.runtime.canvas({action:'detach'}); await h.runtime.canvas({action:'inspect'});
    assert.equal(h.runtime.canvasSelection.selected,false,'metadata changes do not silently reattach');
  } finally {await h.close();}
});

test('plan steps are an order: the run paints through every step to one final review without stopping', {timeout:20000}, async()=>{
  const plan={...brief,steps:[{title:'Block in',done_when:'Masses placed.',scope:'Upper field first'},{title:'Refine',done_when:'Edges resolved.'}]};
  let painted=0, reviewed=0, retired=null;
  const h=await harness(req=>{
    const names=req.tools.map(t=>t.function.name);
    if(names.includes('propose_plan')) return call('propose_plan',plan);
    if(names.includes('submit_review')) {
      reviewed++;
      const text=req.messages.filter(m=>m.role==='user').at(-1).content.filter(c=>c.type==='text').map(c=>c.text).join('\n');
      const data=JSON.parse(text.slice(text.indexOf('{')));
      assert.equal(data.current_stage,undefined); assert.equal(data.final_stage,undefined);
      assert.equal(data.checks.length,brief.requirements.length+brief.completion.length,'one review of the final requirements, not a step done_when');
      return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:data.checks.map(c=>({id:c.id,met:true,evidence:'Visible.'}))});
    }
    if(painted<2) {painted++; return call('paint_pass',pass);}
    return call('request_review',{reason:'The whole painting meets the completion criteria.'});
  });
  try {
    await h.start('plan'); await h.runtime.setMode('autopilot'); await h.runtime.prompt('',{start_plan:true});
    assert.equal(h.runtime.goal.status,'complete'); assert.equal(reviewed,1); assert.equal(h.runtime.goal.passes,2);
    const merges=h.calls.filter(c=>c.operation==='merge_passes');
    assert.deepEqual(merges.map(c=>[c.params.stage_id,c.params.name]),[['stage-1-0','Step 1 · Block in'],['stage-1-1','Step 2 · Refine']],'a passed review merges each step\u2019s kept strokes');
    assert.ok(h.calls.filter(c=>c.operation==='paint_pass').every(c=>!c.params.region),'no stage region clips painting');
    retired=h.runtime.buildTools().find(t=>t.name==='propose_plan');
    assert.ok(!Value.Check(retired.parameters,{...plan,steps:[{title:'Calibrate',done_when:'Mark visible.',stop_after:true,max_operations:1}]}),'stage stops and limits are no longer plan fields');
  } finally {await h.close();}
});

test('a suggested locked-rule change waits for acceptance and preserves unrelated character requirements', {timeout:20000}, async()=>{
  let proposed=false;
  const h=await harness(req=>{
    if(!proposed) {proposed=true;return call('propose_plan',brief);}
    if(JSON.stringify(req.messages).includes('Apply this requirement change')) return call('propose_plan',{...brief,requirements:['Mara wears a blue coat.','Ivo has green eyes.']});
    return call('revise_requirement',{original:'Mara wears a red coat.',replacement:'Mara wears a blue coat.',user_quote:'Make the coat blue'});
  });
  try {
    await h.start('plan'); await h.runtime.editPlan(brief);
    await h.runtime.prompt('Make the coat blue; keep Ivo unchanged.');
    assert.equal(h.runtime.goal.status,'needs_input');
    assert.ok(h.runtime.goal.locked_requirements.includes('Mara wears a red coat.'));
    assert.equal(h.runtime.goal.pending_requirement.replacement,'Mara wears a blue coat.');
    await h.runtime.prompt('Apply this requirement change');
    assert.deepEqual(h.runtime.goal.locked_requirements,['Mara wears a blue coat.','Ivo has green eyes.']);
    assert.deepEqual(approvedReviewScope(h.runtime.goal.accepted_requirement_changes),
      [{superseded:'Mara wears a red coat.',current:'Mara wears a blue coat.'}]);
  } finally {await h.close();}
});

test('a native revision mismatch pauses instead of painting again', {timeout:20000}, async()=>{
  const h=await harness(req=>req.tools.some(t=>t.function.name==='propose_plan')?call('propose_plan',brief):call('paint_pass',pass),
    op=>{if(op==='paint_pass') throw Object.assign(new Error('The painting changed since observation.'),{code:'canvas_changed'});});
  try {
    await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});
    assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,1);
    assert.equal(h.runtime.goal.status,'paused'); assert.equal(h.runtime.goal.passes,0);
    assert.match(h.runtime.goal.pause_reason,/changed/);
  } finally {await h.close();}
});

test('model changes keep the same SDK session, plan, character records and messages', {timeout:20000}, async()=>{
  const h=await harness(()=>call('propose_plan',brief));
  try {
    await h.start('plan'); const session=h.runtime.session; const goal=structuredClone(h.runtime.goal); const count=h.requests.length;
    await h.runtime.setModel('local-test','vision-test');
    assert.equal(h.runtime.session,session); assert.equal(h.requests.length,count);
    assert.deepEqual(h.runtime.goal.brief,goal.brief); assert.deepEqual(h.runtime.goal.messages,goal.messages);
  } finally {await h.close();}
});

test('restart uncertainty quarantines Agent, restores operation counts, and requires inspected revision acknowledgement', {timeout:20000}, async()=>{
  const h=await harness(()=>call('propose_plan',brief),async(op,params)=>{
    if(op==='begin' && params.mode==='resume') {
      const path=join(params.output_dir,'recovery.png');await writeFile(path,png);
      return {document_id:'doc',revision:'recovery-revision',image_path:path,width:768,height:1024,layers:[],
        unresolved_operations:['interrupted-op'],committed_operation_count:3,passes:[{stage_id:'stage-1-0'}]};
    }
    if(op==='reconcile') {
      assert.equal(params.expected_revision,'revision-0');
      return {unresolved_operations:[],committed_operation_count:3};
    }
  });
  try {
    await h.start('plan');
    h.runtime.study.painting_file='recovered.kra';h.runtime.study.needs_resume=true;
    await writeFile(join(h.output,'recovered.kra'),'existing painting');
    await h.runtime.setMode('autopilot'); const count=h.requests.length;
    await assert.rejects(h.runtime.prompt('',{start_plan:true}),/Inspect and acknowledge/);
    assert.equal(h.runtime.faulted,true); assert.equal(h.runtime.goal.passes,3); assert.equal(h.runtime.goal.stage_operations,1);
    assert.equal(h.requests.length,count,'uncertain native history prevents any Agent model continuation');
    await assert.rejects(h.runtime.reconcile(),/Inspect result/);
    await h.runtime.inspectResult(); await h.runtime.reconcile();
    assert.equal(h.runtime.faulted,false);assert.equal(h.runtime.goal.status,'paused');
    assert.ok(h.events.some(e=>e.type==='inspected_result'));assert.ok(h.events.some(e=>e.type==='reconciled'));
    assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,0);
  }finally {await h.close();}
});

test('explicit pass review is serialized and user messages wait until the native action settles', {timeout:20000}, async()=>{
  let entered,settle;
  const action=new Promise(r=>entered=r),release=new Promise(r=>settle=r);
  const h=await harness(req=>req.tools.some(t=>t.function.name==='propose_plan')?call('propose_plan',brief):({content:'I will discuss the updated pass.'}),
    async op=>{if(op==='review_pass'){entered();await release;}});
  try {
    await h.start('plan'); h.runtime.study.bound=true;h.runtime.study.target_document_id='doc';
    const reviewing=h.runtime.reviewPass({action:'strength',pass_id:'test-pass',value:0.5});
    await action;assert.equal(h.runtime.busy,true);
    await assert.rejects(h.runtime.reviewPass({action:'reject',pass_id:'test-pass'}),/Pause/);
    const count=h.requests.length;
    await h.runtime.prompt('Explain this pass.',{chat_mode:'ask'});
    assert.equal(h.requests.length,count,'a pending native change and model prompt cannot overlap');
    settle();await reviewing;
    assert.equal(h.requests.length,count+1);assert.equal(h.runtime.busy,false);
    assert.equal(h.calls.filter(c=>c.operation==='review_pass').length,1);
  }finally {settle();await h.close();}
});

test('UI snapshot refresh cannot replace the revision actually seen by a pending Agent decision', {timeout:20000}, async()=>{
  let waiting,release;
  const pending=new Promise(r=>waiting=r),answer=new Promise(r=>release=r);
  let manualEdit=false;
  const h=await harness(async req=>{
    if(req.tools.some(t=>t.function.name==='propose_plan')) return call('propose_plan',brief);
    waiting();await answer;return call('paint_pass',pass);
  },async(op,params)=>{
    if(op==='peek' && manualEdit) {
      const path=join(params.output_dir,'manual-edit.png');await writeFile(path,png);
      return {document_id:'doc',name:'Untitled',width:768,height:1024,image_path:path,revision:'artist-new-revision',content_id:'artist-new-content',layers:[]};
    }
    if(op==='paint_pass') {
      assert.equal(params.expected_revision,'revision-0','mutation precondition must describe the canvas the pending model actually received');
      throw Object.assign(new Error('Artist edits changed the painting.'),{code:'canvas_changed'});
    }
  });
  try {
    await h.start('plan');await h.runtime.setMode('autopilot');
    const running=h.runtime.prompt('',{start_plan:true});await pending;
    manualEdit=true;await h.runtime.canvas({action:'refresh'});
    assert.equal(h.runtime.canvasContext.canvas.revision,'artist-new-revision');
    assert.equal(h.runtime.decisionObservation.revision,'revision-0');
    release();await running;
    assert.equal(h.runtime.goal.status,'paused');assert.equal(h.runtime.goal.passes,0);
    assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,1);
  }finally{release();await h.close();}
});

test('exact global paint ceiling still permits the final review and cannot allow a third pass', {timeout:20000}, async()=>{
  for (const verdict of ['complete','continue']) {
    const plan={...brief,steps:[{title:'Calibrate two brushes',done_when:'Both trials can be judged.'}]};
    let reviewed=0;
    const h=await harness(req=>{
      const names=req.tools.map(t=>t.function.name);
      if(names.includes('propose_plan'))return call('propose_plan',plan);
      if(names.includes('submit_review')){
        reviewed++;
        return call('submit_review',{verdict,summary:verdict==='complete'?'Both trials are ready.':'The material still reads too smooth.',
          issues:verdict==='complete'?[]:['Insufficient granular breakup.'],checks:[0,1,2].map(i=>({id:'check-'+i,met:verdict==='complete'||i!==2,evidence:'Compared the visible trials and protected properties.'}))});
      }
      return call('paint_pass',pass);
    });
    try{
      await h.start('plan');await h.runtime.setLimits({minutes:8,passes:2});await h.runtime.setMode('autopilot');
      await h.runtime.prompt('',{start_plan:true});
      const autopilot=h.requests.map(r=>JSON.stringify(r.messages)).filter(m=>m.includes('HOST MODE: AUTOPILOT. CURRENT PHASE: AGENT'));
      assert.ok(autopilot.length && autopilot.every(m=>m.includes('AI images are off for this chat (allowance 0)') && m.includes('do not call make_asset')),'Autopilot is told its AI image allowance');
      assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,2);
      assert.equal(h.runtime.goal.passes,2);assert.equal(reviewed,1,'the final allowed brush pass is always visually reviewed');
      assert.equal(h.runtime.goal.reviews.length,1);
      assert.equal(h.runtime.goal.status,verdict==='complete'?'complete':'limited');
      assert.equal(h.runtime.busy,false);
    }finally{await h.close();}
  }
});

test('conversation starts and restores acquire their transition before the first await', {timeout:20000}, async()=>{
  const h=await harness(()=>({content:'Ready.'}));
  try{
    const first=h.start('ask');
    await assert.rejects(h.start('ask'),/current action/);
    await first;assert.equal(h.requests.length,1);
    const id=h.runtime.study.id;await h.runtime.end();
    let entered,release;const pending=new Promise(r=>entered=r),settle=new Promise(r=>release=r);
    const load=h.runtime.store.load.bind(h.runtime.store);
    h.runtime.store.load=async key=>{entered();await settle;return load(key);};
    const restoring=h.runtime.resume(id);await pending;
    await assert.rejects(h.start('ask'),/current action/);
    await assert.rejects(h.runtime.resume(id),/current action/);
    h.runtime.stop();release();await restoring;
    assert.equal(h.requests.length,1);assert.equal(h.runtime.study.id,id);assert.equal(h.runtime.busy,false);
    assert.ok(h.runtime.session);assert.ok(!h.runtime.transition);
  }finally{await h.close();}
});

test('Stop or New chat during session preparation cannot launch a phantom model request', {timeout:20000}, async()=>{
  const h=await harness(()=>({content:'This must not be requested.'}));
  let release;
  try{
    let entered;const pending=new Promise(r=>entered=r),settle=new Promise(r=>release=r);
    const open=h.runtime.openSession.bind(h.runtime);
    h.runtime.openSession=async(...args)=>{entered();await settle;return open(...args);};
    const starting=h.start('ask','Remember my painting idea.');await pending;
    const id=h.runtime.study.id;h.runtime.stop();const ending=h.runtime.end();release();
    await Promise.all([starting,ending]);
    assert.equal(h.requests.length,0);assert.equal(h.runtime.busy,false);
    assert.equal(h.runtime.study,undefined);assert.equal(h.runtime.session,undefined);assert.ok(!h.runtime.transition);
    const record=await h.runtime.store.load(id);
    assert.equal(record.goal.status,'paused');assert.equal(record.goal.messages[0].text,'Remember my painting idea.');
  }finally{release?.();await h.close();}
});

test('older context responses cannot overwrite newer pin or detach actions', {timeout:20000}, async()=>{
  let releaseA,enteredA;
  const pendingA=new Promise(r=>enteredA=r),settleA=new Promise(r=>releaseA=r);
  const h=await harness(()=>({content:'Ready.'}),async(op,params)=>{
    if(op==='context'&&params.document_id==='doc-a'){enteredA();await settleA;return {document_id:'doc-a',active_document_id:'doc-a',width:768,height:1024};}
    if(op==='context'&&params.document_id==='doc-b')return {document_id:'doc-b',active_document_id:'doc-b',width:768,height:1024};
    if(op==='peek'){
      const path=join(params.output_dir,'context-'+params.document_id+'.png');await writeFile(path,png);
      return {document_id:params.document_id,width:768,height:1024,image_path:path,revision:'r-'+params.document_id};
    }
  });
  try{
    const old=h.runtime.canvas({action:'attach',follow_active:false,document_id:'doc-a'});await pendingA;
    await h.runtime.canvas({action:'attach',follow_active:false,document_id:'doc-b'});
    releaseA();await old;
    assert.equal(h.runtime.canvasContext.canvas.document_id,'doc-b');assert.equal(h.runtime.canvasSelection.document_id,'doc-b');
    await h.runtime.canvas({action:'detach'});await h.runtime.canvas({action:'inspect'});
    assert.equal(h.runtime.canvasContext.state,'detached');assert.equal(h.runtime.canvasSelection.selected,false);
  }finally{releaseA();await h.close();}
});

test('selected area sends a matching whole-canvas and actual crop receipt, and never applies to another document', {timeout:20000}, async()=>{
  const h=await harness(()=>({content:'The selection is included.'}));
  try{
    await h.runtime.canvas({action:'region',region:{document_id:'doc',bounds:[100,150,580,330],name:'Upper-field core'}});
    assert.equal(h.runtime.canvasSelection.follow_active,false);
    await h.start('ask');
    assert.equal(imagesInLatestMessage(h.requests.at(-1)).length,2);
    const receipt=h.events.filter(e=>e.type==='message_context').at(-1);
    assert.deepEqual(receipt.region.bounds,[100,150,580,330]);assert.equal(receipt.region.revision,receipt.canvas.revision);
    await h.runtime.canvas({action:'region',region:{document_id:'another-doc',bounds:[1,2,30,40]}});
    // The test bridge still reports doc: never send that other document's coordinates.
    await h.runtime.prompt('Discuss the visible canvas.');
    assert.equal(imagesInLatestMessage(h.requests.at(-1)).length,1);
    assert.equal(h.events.filter(e=>e.type==='message_context').at(-1).region,null);
    const id=h.runtime.study.id;await h.runtime.end();await h.runtime.resume(id);
    assert.equal(h.runtime.regionSelection.document_id,'another-doc');
  }finally{await h.close();}
});

test('canvas edits between whole-canvas and crop capture prevent a mixed-revision request', {timeout:20000}, async()=>{
  let changed=false;
  const h=await harness(()=>({content:'Unmixed image.'}),async(op,params)=>{
    if(op==='peek'&&params.region&&changed){const path=join(params.output_dir,'new-crop.png');await writeFile(path,png);return {document_id:'doc',image_path:path,width:768,height:1024,revision:'changed'};}
  });
  try{
    await h.runtime.canvas({action:'region',region:{document_id:'doc',bounds:[1,2,30,40]}});await h.start('ask');
    const count=h.requests.length;changed=true;
    await assert.rejects(h.runtime.prompt('Read the selected area.'),/changed while capturing/);
    assert.equal(h.requests.length,count);assert.equal(h.runtime.busy,false);
  }finally{await h.close();}
});

test('time ceiling still stops a pending independent review after the last allowed paint', {timeout:20000}, async()=>{
  let entered,release;const pending=new Promise(r=>entered=r),settle=new Promise(r=>release=r);
  const h=await harness(async req=>{
    const names=req.tools.map(t=>t.function.name);
    if(names.includes('propose_plan'))return call('propose_plan',{...brief,steps:[{title:'One pass',done_when:'Ready for review.'}]});
    if(names.includes('submit_review')){entered();await settle;return {content:'The request was interrupted.'};}
    return call('paint_pass',pass);
  });
  try{
    await h.start('plan');await h.runtime.setLimits({minutes:1,passes:1});await h.runtime.setMode('autopilot');
    const running=h.runtime.prompt('',{start_plan:true});await pending;h.runtime.goal.used_ms=60000;
    await assert.rejects(running);
    assert.equal(h.runtime.goal.status,'limited');assert.equal(h.runtime.busy,false);
    assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,1);
  }finally{release();await h.close();}
});

test('an authoritative native restart permits ending the old chat and reconnects a saved conversation paused', {timeout:20000}, async()=>{
  let restarted=false;
  const h=await harness(()=>({content:'Ready.'}),op=>{
    if(op==='end'&&restarted)throw new Error('This painting session does not own the document');
    if(op==='health')return {status:'ok',protocol_version:2,session_active:!restarted};
  });
  try{
    await h.start('ask');h.runtime.study.bound=true;h.runtime.study.painting_file='saved.kra';
    await writeFile(join(h.output,'saved.kra'),'painting');
    const id=h.runtime.study.id;restarted=true;await h.runtime.end();
    assert.equal(h.runtime.study,undefined);assert.equal(h.runtime.busy,false);
    await h.runtime.resume(id);h.runtime.study.bound=true;h.runtime.bridge.connect=async()=>{};
    const count=h.requests.length;await h.runtime.reconnect();
    assert.equal(h.runtime.study.bound,false);assert.equal(h.runtime.study.needs_resume,true);assert.equal(h.runtime.goal.status,'paused');
    assert.equal(h.requests.length,count);
  }finally{await h.close();}
});

test('capability failure or Stop during the probe prevents native document creation', {timeout:20000}, async()=>{
  const h=await harness(()=>call('propose_plan',brief));
  try{
    await h.start('plan');await h.runtime.setMode('autopilot');
    const tokens=h.runtime.goal.tokens;
    h.runtime.capabilities.verify=async()=>{throw Object.assign(new Error('Image route failed its probe.'),{code:'image_unverified',usage:{total:7}});};
    await assert.rejects(h.runtime.prompt('',{start_plan:true}),/Image route/);
    assert.ok(!h.calls.some(c=>c.operation==='begin'));assert.equal(h.runtime.goal.status,'paused');
    assert.equal(h.runtime.goal.tokens,tokens+7,'failed probe usage is counted exactly once');
    let entered;const pending=new Promise(r=>entered=r);
    h.runtime.capabilities.verify=async(_model,{signal})=>new Promise((_resolve,reject)=>{entered();signal.addEventListener('abort',()=>reject(new Error('Probe cancelled.')),{once:true});});
    const running=h.runtime.prompt('',{start_plan:true});await pending;h.runtime.stop();
    await assert.rejects(running,/cancelled/);
    assert.equal(h.runtime.busy,false);assert.ok(!h.calls.some(c=>c.operation==='begin'));
  }finally{await h.close();}
});

test('configuring a provider while idle preserves the current model and invalidates the new route cache', {timeout:20000}, async()=>{
  const h=await harness(()=>({content:'Ready.'}));
  try{
    await h.start('ask');const session=h.runtime.session;const invalidated=[];
    h.runtime.capabilities.invalidate=async model=>invalidated.push(model.id);
    await h.runtime.configureProvider({provider:'another-local-test',model:'another-vision',base_url:'http://127.0.0.1:4444/v1',api_key:'test-only'});
    assert.equal(h.runtime.session,session);assert.equal(h.runtime.study.model,'vision-test');assert.equal(h.runtime.busy,false);
    assert.deepEqual(invalidated,['another-vision']);
    assert.deepEqual(h.events.filter(e=>e.type==='models'&&e.selected).at(-1).selected,{provider:'local-test',id:'vision-test'});
    await assert.rejects(h.runtime.configureProvider({provider:'bad',model:'model-batch',base_url:'http://127.0.0.1',api_key:'test-only'}),/batch/);
  }finally{await h.close();}
});

test('text-only Pi models support detached Ask and Plan but cannot receive images or enter Agent', {timeout:20000}, async()=>{
  const h=await harness(req=>{
    assert.ok(!req.tools.some(t=>['observe_canvas','view_reference'].includes(t.function.name)));
    return req.tools.some(t=>t.function.name==='propose_plan')?call('propose_plan',brief):{content:'Text-only discussion.'};
  });
  try{
    const base=h.runtime.models.getModel('local-test','vision-test');
    h.runtime.models.registerProvider('text-test',{api:base.api,baseUrl:base.baseUrl,models:[{...base,id:'text-only',name:'Text only',input:['text']}]});
    await h.runtime.models.setRuntimeApiKey('text-test','test-only');
    await h.start('ask','Discuss a painting idea.',{provider:'text-test',model:'text-only',canvas:{selected:false,follow_active:true}});
    assert.ok(h.runtime.listModels().some(m=>m.provider==='text-test'&&!m.declared_images_supported));
    await h.runtime.setMode('plan');await h.runtime.prompt('Plan two people.');assert.ok(h.runtime.goal.brief);
    const count=h.requests.length;await assert.rejects(h.runtime.setMode('autopilot'),/vision model/);
    await h.runtime.canvas({action:'attach',follow_active:true});
    await assert.rejects(h.runtime.prompt('See the painting.'),/text only/);assert.equal(h.requests.length,count);
    await h.runtime.canvas({action:'detach'});
    const path=join(h.output,'reference.png');await writeFile(path,png);
    await assert.rejects(h.runtime.prompt('See the reference.',{references:[{path}]}),/text only/);assert.equal(h.requests.length,count);
    await h.runtime.removeReference({path});await h.runtime.prompt('Continue planning in text.');
    assert.ok(h.calls.every(c=>['context','peek'].includes(c.operation)));
  }finally{await h.close();}
});

test('draft plan requirements and character facts survive model omissions and restart before explicit correction acceptance', {timeout:20000}, async()=>{
  let turn=0;
  const first={...brief,characters:[{name:'Mara',requirements:['Mara wears a red coat.','Mara remains seated on the left.']},{name:'Ivo',requirements:['Ivo has green eyes.']}]};
  const omitted={...brief,requirements:[],characters:[]};
  const h=await harness(()=>{
    turn++;
    if(turn===1)return call('propose_plan',first);
    if(turn===3)return call('revise_requirement',{original:'Mara remains seated on the left.',replacement:'Mara stands on the left.',user_quote:'Make Mara stand on the left.'});
    return call('propose_plan',omitted);
  });
  try{
    await h.start('plan','Mara wears a red coat and remains seated on the left. Ivo has green eyes.');
    assert.equal(h.runtime.goal.approved_revision,null);
    await h.runtime.prompt('Simplify the background without changing the people.');
    assert.ok(h.runtime.goal.brief.requirements.includes('Mara wears a red coat.'));
    assert.ok(h.runtime.goal.brief.characters.some(c=>c.name==='Ivo'&&c.requirements.includes('Ivo has green eyes.')));
    assert.ok(h.runtime.goal.character_records.find(c=>c.name==='Mara').requirements.includes('Mara remains seated on the left.'));
    const id=h.runtime.study.id;await h.runtime.end();await h.runtime.resume(id);
    await h.runtime.prompt('Make Mara stand on the left.');
    assert.equal(h.runtime.goal.status,'needs_input');
    assert.ok(h.runtime.goal.brief.characters.find(c=>c.name==='Mara').requirements.includes('Mara remains seated on the left.'));
    await h.runtime.prompt('Apply this requirement change');
    assert.ok(!h.runtime.goal.brief.characters.find(c=>c.name==='Mara').requirements.includes('Mara remains seated on the left.'));
    assert.ok(h.runtime.goal.brief.characters.find(c=>c.name==='Mara').requirements.includes('Mara stands on the left.'));
    assert.ok(h.runtime.goal.brief.requirements.includes('Ivo has green eyes.'));
    assert.equal(h.runtime.goal.approved_revision,null);assert.ok(h.calls.every(c=>['context','peek'].includes(c.operation)));
  }finally{await h.close();}
});

test('reference purpose changes are persistent, invalidate approval and preserve prior message receipts', {timeout:20000}, async()=>{
  const h=await harness(()=>call('propose_plan',brief));
  try{
    const path=join(h.output,'reference.png');await writeFile(path,png);
    await h.start('plan','Plan from this image.',{references:[{path,name:'Pasted reference',purpose:'composition',notes:'Use the arrangement.'}]});
    const receipt=h.runtime.goal.messages.find(m=>m.role==='user').references[0];
    const reference=h.runtime.study.references[0];assert.equal(reference.name,'Pasted reference');assert.equal(receipt.name,'Pasted reference');
    await h.runtime.setReferencePurpose({id:reference.id,purpose:'material',notes:'Only the dry texture.'});
    assert.equal(receipt.purpose,'composition');assert.equal(reference.purpose,'material');assert.equal(h.runtime.goal.approved_revision,null);
    assert.match(h.runtime.context('plan'),/Only the dry texture/);
    const id=h.runtime.study.id;await h.runtime.end();await h.runtime.resume(id);
    assert.equal(h.runtime.study.references[0].purpose,'material');
  }finally{await h.close();}
});

test('color sampling uses the observed document and cannot replace model image revision or bypass detached context', {timeout:20000}, async()=>{
  const h=await harness(()=>({content:'Ready.'}),(operation,params)=>{
    if(operation==='sample_colors')return {document_id:params.document_id,revision:'newer-color-revision',samples:[{position:[200,220],hex:'#c0422a',rgba:[192,66,42,255]}]};
  });
  try{
    await h.start('ask');
    const result=await h.runtime.callNative('sample_colors',{points:[[200,220]]});
    assert.equal(result.document_id,'doc');assert.equal(result.samples[0].hex,'#c0422a');
    assert.equal(h.runtime.decisionObservation.revision,'revision-0');
    await h.runtime.canvas({action:'detach'});await assert.rejects(h.runtime.callNative('sample_colors',{points:[[200,220]]}),/Canvas not included/);
    assert.ok(!h.calls.some(c=>['begin','paint_pass','adjust_layer'].includes(c.operation)));
  }finally{await h.close();}
});

test('a detach while a sent message is capturing applies to future messages without changing its receipt', {timeout:20000}, async()=>{
  let hold=false,entered,release;const pending=new Promise(r=>entered=r),settle=new Promise(r=>release=r);
  const h=await harness(()=>({content:'Ready.'}),async operation=>{if(operation==='peek'&&hold){entered();await settle;}});
  try{
    await h.start('ask');hold=true;const request=h.runtime.prompt('Describe the canvas that is attached.');await pending;
    await h.runtime.canvas({action:'detach'});release();await request;
    assert.equal(imagesInLatestMessage(h.requests.at(-1)).length,1);
    assert.equal(h.runtime.canvasSelection.selected,false);assert.equal(h.runtime.canvasContext.state,'detached');
    await h.runtime.prompt('Now discuss without an attachment.');
    assert.equal(imagesInLatestMessage(h.requests.at(-1)).length,0);
  }finally{release();await h.close();}
});

test('restored plan accepts reopened same file but rejects another document or changed dimensions', async()=>{
  const h=await harness(()=>({content:'Ready.'}));
  try {
    const path=join(h.output,'painting.kra'); await writeFile(path,'test');
    h.runtime.study={needs_resume:true,painting_file:'painting.kra'};
    h.runtime.store.resolvePainting=()=>path;
    h.runtime.goal={plan_target:{document_id:'old-process-id',width:768,height:1024},target_needs_review:true};
    h.runtime.canvasContext={canvas:{document_id:'new-process-id',filename:path,width:768,height:1024}};
    await h.runtime.refreshPlanIdentity();
    assert.equal(h.runtime.goal.target_needs_review,false);
    assert.equal(h.runtime.study.target_document_id,'new-process-id');
    h.runtime.canvasContext.canvas.width=1000;
    await h.runtime.refreshPlanIdentity(); assert.equal(h.runtime.goal.target_needs_review,true);
    h.runtime.canvasContext.canvas.width=768; h.runtime.canvasContext.canvas.filename=join(h.output,'other.kra');
    await writeFile(h.runtime.canvasContext.canvas.filename,'other');
    await h.runtime.refreshPlanIdentity(); assert.equal(h.runtime.goal.target_needs_review,true);
    h.runtime.study=undefined;
  } finally {await h.close();}
});

test('Agent builds multiple batches without the former three-pass audit interruption', {timeout:20000}, async()=>{
  let painted=0,reviewed=0;
  const h=await harness(req=>{
    const names=req.tools.map(t=>t.function.name);
    if(names.includes('propose_plan'))return call('propose_plan',brief);
    if(names.includes('submit_review')) {
      reviewed++;assert.equal(painted,6,'review must wait for the completed stage');
      return call('submit_review',{verdict:'complete',summary:'Stage finished.',issues:[],checks:[...[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'})),{id:'extra-layer-metadata',met:true,evidence:'Layer record available.'}]});
    }
    if(painted<6){painted++;return call('paint_pass',pass);}
    return call('request_review',{reason:'All construction batches for this stage are complete.'});
  });
  try {
    await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});
    assert.equal(h.runtime.goal.status,'complete');assert.equal(painted,6);assert.equal(reviewed,1);
  }finally{await h.close();}
});

test('an unchanged failed painting cannot trigger another paid review without painting', async()=>{
 const h=await harness(()=>call('propose_plan',brief));
 try {
  await h.start('plan');h.runtime.executionPhase='agent';
  h.runtime.goal.reviews.push({verdict:'continue',review_contract_version:2,revision:h.runtime.goal.revision,stage:0,pass_count:h.runtime.goal.passes});
  const review=h.runtime.buildTools().find(t=>t.name==='request_review');
  await assert.rejects(review.execute('duplicate',{reason:'Please reconsider.'}),/unchanged painting/);
  h.runtime.goal.passes++;
  await review.execute('after-paint',{reason:'The reported defects have been corrected.'});
  assert.equal(h.runtime.yieldRequested,true);
 }finally{await h.close();}
});

test('ordinary progress replies do not trigger stage audits', {timeout:20000}, async()=>{
 let turn=0,painted=0,reviewed=0;
 const h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',brief);
  if(names.includes('submit_review')) {
   reviewed++;assert.equal(painted,3);
   return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  }
  turn++;
  if(turn%2===0 && painted<3)return {content:'Construction is progressing; continuing the stage.'};
  if(painted<3){painted++;return call('paint_pass',pass);}
  return call('request_review',{reason:'Whole stage finished.'});
 });
 try {await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});assert.equal(h.runtime.goal.status,'complete');assert.equal(reviewed,1);}
 finally {await h.close();}
});

test('a continue verdict with every required check met completes the painting in one review', {timeout:20000}, async()=>{
 let reviews=0;
 const h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',brief);
  if(names.includes('submit_review')){
   reviews++;
   return call('submit_review',{verdict:reviews===1?'continue':'complete',summary:'All criteria visible.',issues:reviews===1?['Optional future refinement.']:[],checks:[0,1,2].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  }
  return call('request_review',{reason:'Painting ready.'});
 });
 try {await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});assert.equal(h.runtime.goal.status,'complete');assert.equal(reviews,1);assert.equal(h.runtime.goal.reviews.length,1);
  // The verdict is scored on the review trace, in the chat's session.
  const {scores,observations}=h.runtime.tracing.recorded, review=observations.find(o=>o.name==='review-canvas');
  assert.deepEqual(scores.map(s=>[s.name,s.value]),[['review-passed',1],['review-checks-met',1]]);
  assert.ok(scores.every(s=>s.traceId===review.traceId && !('sessionId' in s)),'one target: the review trace, which is in the chat session');
  assert.equal(review.trace.sessionId,h.runtime.study.id);}
 finally {await h.close();}
});

test('the host derives completion from the final checks; nothing can be deferred or handed to the artist',()=>{
 const criteria=[{id:'check-0'},{id:'check-1'}];
 const met={id:'check-0',met:true,evidence:'Visible.'}, unmet={id:'check-1',met:false,evidence:'Edges missing.'};
 assert.equal(validateReview({verdict:'continue',summary:'s',issues:['minor note'],checks:[met,{...unmet,met:true}]},{criteria}).verdict,'complete');
 assert.equal(validateReview({verdict:'complete',summary:'s',issues:[],checks:[met,unmet]},{criteria}).verdict,'continue');
 assert.throws(()=>validateReview({verdict:'needs_input',summary:'s',issues:[],checks:[met,unmet]},{criteria}),/Invalid review/);
 assert.throws(()=>validateReview({verdict:'continue',summary:'s',issues:[],checks:[met,{...unmet,deferred_to_stage:2,preserved:true}]},{criteria}),/Invalid review/);
 assert.throws(()=>validateReview({verdict:'continue',summary:'s',issues:[],checks:[met]},{criteria}),/every required check/);
});

test('saved plans drop retired stage controls when loaded', ()=>{
 const plan={...brief,steps:[{title:'Block in',done_when:'Masses placed.',scope:'Whole canvas',region:[0,0,10,10],stop_after:true,max_operations:3}]};
 assert.deepEqual(normalizeBrief(plan).steps,[{title:'Block in',done_when:'Masses placed.',scope:'Whole canvas'}]);
 const checked={...brief,steps:[{title:'Block in',done_when:'Masses placed.',checks:['The car sits in the lower half']}]};
 assert.deepEqual(normalizeBrief(checked).steps[0].checks,['The car sits in the lower half'],'the visible checks Luna paces with are kept');
});

test('a legacy unversioned review is re-reviewed once under the final contract, then painting continues', {timeout:20000}, async()=>{
 let reviews=0,painted=false;
 const plan={...brief,steps:[{title:'Interiors',done_when:'Interiors resolved.'},{title:'Edges',done_when:'Edges resolved.'}]};
 const h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',plan);
  if(names.includes('submit_review')){
   reviews++;
   return call('submit_review',{verdict:reviews===1?'continue':'complete',summary:reviews===1?'Edges still pending.':'Painting complete.',issues:reviews===1?['Edges pending.']:[],
    checks:[0,1,2].map(i=>({id:'check-'+i,met:reviews>1||i!==2,evidence:'Visible.'}))});
  }
  assert.equal(reviews,1,'the legacy review is replaced before more painting');
  if(!painted){painted=true;return call('paint_pass',pass);}
  return call('request_review',{reason:'Edges finished.'});
 });
 try{
  await h.start('plan');h.runtime.goal.reviews.push({verdict:'continue',revision:h.runtime.goal.revision,stage:0,pass_count:0});
  await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.goal.status,'complete');assert.equal(h.runtime.goal.passes,1);assert.equal(reviews,2);
 }finally{await h.close();}
});

test('idle Agent replies recover internally and finish without user Resume', {timeout:20000}, async()=>{
 let idle=0,painted=false;
 const h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',brief);
  if(names.includes('submit_review'))return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  if(idle++<3)return {content:'I have not taken an action.'};
  assert.ok(h.runtime.goal.execution_recovery);
  if(!painted){painted=true;return call('paint_pass',pass);}
  return call('request_review',{reason:'Finished stage.'});
 });
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.goal.status,'complete');assert.equal(h.runtime.goal.passes,1);
  assert.equal(h.runtime.goal.execution_recovery.attempt,1);
  assert.deepEqual(h.runtime.goal.brief.requirements,brief.requirements);
  assert.equal(h.calls.filter(c=>c.operation==='begin').length,1);
 }finally{await h.close();}
});

test('parallel preparation runs two isolated model requests beside one painter that does not wait for them', {timeout:20000}, async()=>{
  let active=0, peak=0, proposals=0, release, go;
  const together=new Promise(r=>{release=r;}), painterStarted=new Promise(r=>{go=r;}); let painted=false;
  const h=await harness(async req=>{
    const names=req.tools.map(t=>t.function.name);
    if(names.includes('propose_plan')) return call('propose_plan',brief);
    if(names.includes('submit_batch_proposal')) {
      assert.deepEqual(names,['submit_batch_proposal'],'workers cannot call painting tools');
      active++;peak=Math.max(peak,active);if(active===2)release();await together;await painterStarted;
      active--;proposals++;
      return call('submit_batch_proposal',{summary:'Build broad silhouettes.',batches:[{tool:'paint_pass',arguments_json:JSON.stringify(pass)}]});
    }
    if(names.includes('submit_review')) return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
    if(!painted){
      // The painter starts while both workers are still thinking; their suggestions reach it in this action's result.
      assert.equal(proposals,0);go();
      while(!h.runtime.parallelPreparation) await new Promise(r=>setTimeout(r,5));
      painted=true;return call('paint_pass',pass);
    }
    const results=req.messages.filter(m=>m.role==='tool').map(m=>JSON.stringify(m.content));
    assert.equal(results.filter(r=>r.includes('parallel_preparation')).length,1,'suggestions arrive once, in a painting result');
    return call('request_review',{reason:'Stage complete.'});
  });
  try {
    await h.start('plan');await h.runtime.setExecutionSettings({concurrency:2,reasoning:'high',routing:'off',decisions:{endpoint:'openrouter',model:'openai/gpt-6-luna-decisions'}});
    assert.equal(h.runtime.session.thinkingLevel,'off','nonreasoning model does not pretend to think');
    await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});
    assert.equal(peak,2);assert.equal(proposals,2);assert.equal(h.runtime.goal.status,'complete');
    assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,1);
    const id=h.runtime.study.id;await h.runtime.end();await h.runtime.resume(id);
    assert.deepEqual(h.runtime.executionSettings,{concurrency:2,reasoning:'high',routing:'off',native_craft:true,move_size:'subject',merge_kept:true,guides:true,reference_first:true,assets:'codex',ai_images:0,keep_screen_awake:false,decisions:{endpoint:'openrouter',model:'openai/gpt-6-luna-decisions'}});
    assert.equal(h.runtime.session.thinkingLevel,'off');
    assert.equal(h.runtime.goal.status,'paused');
  } finally {await h.close();}
});

test('Stop cancels background preparation together with the painter', {timeout:10000}, async()=>{
  let workers=0, painter=false, started;
  const ready=new Promise(r=>{started=r;});
  const h=await harness(async req=>{
    const names=req.tools.map(t=>t.function.name);
    if(names.includes('propose_plan'))return call('propose_plan',brief);
    if(names.includes('submit_batch_proposal')) {if(++workers===2 && painter)started();await new Promise(()=>{});}
    painter=true;if(workers===2)started();await new Promise(()=>{});
  });
  try {
    await h.start('plan');await h.runtime.setExecutionSettings({concurrency:2,reasoning:'auto'});await h.runtime.setMode('autopilot');
    const run=h.runtime.prompt('',{start_plan:true});await ready;
    await assert.rejects(h.runtime.setExecutionSettings({concurrency:1,reasoning:'off'}),/settle/);
    h.runtime.stop();await run;
    assert.equal(h.runtime.parallelWorkers.size,0);
    assert.ok(!h.calls.some(c=>['paint_pass','painting_toolbox'].includes(c.operation)));
    assert.equal(h.runtime.goal.status,'paused');
  } finally {await h.close();}
});

test('parallel proposals for a step the plan has left are discarded; worker failures leave nothing to deliver', async()=>{
  const runtime=new StudioRuntime({config:{output:'/tmp/creative-store-placeholder'},tracing:recordingTracing(),emit:()=>{}});
  runtime.study={id:'study',provider:'test',model:'model'};runtime.goal={revision:1,current_step:0};
  runtime.executionSettings={concurrency:2,reasoning:'auto'};
  runtime.bridge={call:async()=>({brushes:[]})};
  runtime.prepareWorker=async()=>{runtime.goal.current_step=1;return {summary:'for step 1'};};   // the painter moved on meanwhile
  assert.equal(await runtime.prepareStageConcurrently({revision:'old'}),false);
  assert.equal(runtime.parallelPreparation,undefined);
  runtime.prepareWorker=async()=>({summary:'for step 2'});
  assert.equal(await runtime.prepareStageConcurrently({revision:'old'}),true,'a canvas painted since is expected, not stale');
  assert.equal(runtime.parallelPreparation.proposals.length,2);assert.equal(runtime.parallelPreparation.delivered,false);
  runtime.parallelPreparation=undefined;runtime.prepareWorker=async()=>{throw new Error('Provider unavailable');};
  assert.equal(await runtime.prepareStageConcurrently({revision:'new'}),true);
  assert.deepEqual(runtime.parallelPreparation.proposals,[]);assert.equal(runtime.parallelPreparation.delivered,true);
});

test('Agent invokes compact recipe, runs five chunks without review, and keeps the recipe clip', {timeout:20000}, async()=>{
 let painted=false;
 const recipe={name:'Generated scumble',preset:'Test brush',region:[40,50,600,450],palette:['#ef8d76','#ee8973'],stroke_count:1200,size:[20,45],opacity:[.15,.3],direction:'horizontal',irregularity:.8,seed:42};
 const planned=brief;
 const h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan')){assert.ok(!names.includes('paint_recipe'));return call('propose_plan',planned);}
  if(names.includes('submit_review')){assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,5);return call('submit_review',{verdict:'complete',summary:'Painting ready.',issues:[],checks:[0,1,2].map(i=>({id:'check-'+i,met:true,evidence:'Observed.'}))});}
  assert.ok(names.includes('paint_recipe'));
  if(!painted){painted=true;return call('paint_recipe',recipe);}
  return call('request_review',{reason:'Whole stage complete.'});
 });
 try{
  await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.goal.status,'complete');assert.equal(h.runtime.goal.passes,5);assert.equal(h.runtime.goal.reviews.length,1);
  const batches=h.calls.filter(c=>c.operation==='paint_pass');assert.deepEqual(batches.map(c=>c.params.strokes.length),[256,256,256,256,176]);
  assert.ok(batches.every(c=>JSON.stringify(c.params.region)===JSON.stringify(recipe.region)),'the recipe region is the clipping mask');
 }finally{await h.close();}
});

test('Pi Agent discovers reference tools, refines three scales and carries native revisions across chunks', {timeout:20000}, async()=>{
 let started=false,revision='revision-0',painted=0;
 const h=await harness(async req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan')){assert.ok(!names.includes('paint_from_reference'));return call('propose_plan',brief);}
  if(names.includes('submit_review'))return call('submit_review',{verdict:'complete',summary:'Fixture rendered.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Fixture.'}))});
  assert.ok(names.includes('paint_from_reference'));assert.ok(names.includes('continue_reference_painting'));
  if(!started){started=true;return call('paint_from_reference',{name:'Sampled fixture',reference_id:h.runtime.study.references[0].id,preset:'Test brush',source:[0,0,24,24],target:[10,10,48,48],steps:[6,2,1],focal_regions:[[4,4,8,8]]});}
  const folder=join(h.runtime.study.directory,'reference-paintings');const file=(await readdir(folder)).find(n=>/^[a-f0-9]{32}\.json$/.test(n));const job=JSON.parse(await readFile(join(folder,file)));
  return job.status==='complete'?call('request_review',{reason:'All three scales finished.'}):call('continue_reference_painting',{job_id:job.id});
 },async(op,params)=>{
  if(op==='decode_reference')return {width:24,height:24,sha256:params.sha256,rgba_base64:Buffer.alloc(24*24*4,255).toString('base64')};
  if(op==='paint_pass'){assert.equal(params.expected_revision,revision);painted++;revision='paint-'+painted;return {status:'ok',width:768,height:1024,revision,layer_id:params.continue_layer_id??'layer-'+painted,image_path:join(h.runtime.study.directory,'view.png'),layers:[]};}
  if(op==='observe')return {status:'ok',width:768,height:1024,revision,image_path:join(h.runtime.study.directory,'view.png'),layers:[]};
 });
 try{h.runtime.config.reference_batch=128;   // small batches so the fine pass spans two chunks
  const path=join(h.output,'reference.png');await writeFile(path,png);await h.start('plan','Plan reconstruction',{references:[{path}]});await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.goal.status,'complete');assert.equal(painted,4);assert.equal(h.runtime.goal.passes,4);
  const batches=h.calls.filter(c=>c.operation==='paint_pass');assert.equal(batches[2].params.continue_layer_id,'layer-2');assert.equal(h.runtime.goal.reviews.length,1);
 }finally{await h.close();}
});

test('Luna guide and evaluate modes preserve Pi tool permissions and read-only Ask',async()=>{
 for(const routing of ['guide','evaluate']) {
  const h=await harness(()=>({content:'I can discuss the gradient.'}));
  try {
   await h.start('ask');
   let count=0;
   h.runtime.lunaRouter={evaluate:async(_state,{identity})=>{count++;return {status:'recommended',context_identity:identity,operation:{choice:'gradient',confidence:.98},brush:{choice:'none',confidence:.95},elapsed_ms:1};}};
   await h.runtime.setExecutionSettings({routing});
   await h.runtime.prompt('What gradient would suit this?');
   assert.equal(count,1);
   assert.ok(h.calls.every(c=>['context','peek'].includes(c.operation)));
   const sent=JSON.stringify(h.requests.at(-1));
   assert.equal(sent.includes('Optional routing advice'),routing==='guide');
   assert.ok(!h.requests.at(-1).tools.some(t=>t.function.name==='painting_toolbox'));
  } finally {await h.close();}
 }
});

test('Agent consumes an inspect route once and paints after a preliminary inspection', {timeout:20000}, async()=>{
 let agentTurns=0;
 const h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',brief);
  if(names.includes('submit_review'))return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  agentTurns++;
  if(agentTurns===1)return {content:'I inspected the supplied canvas and identified the next correction.'};
  if(agentTurns===2)return call('paint_pass',pass);
  return call('request_review',{reason:'The stage is ready.'});
 });
 try {
  await h.start('plan','Make this painting stronger.');
  await h.runtime.setMode('autopilot');
  h.runtime.lunaRouter={evaluate:async(_state,{identity})=>({status:'recommended',context_identity:identity,operation:{choice:'inspect',confidence:.95},brush:{choice:'none',confidence:.95},elapsed_ms:1})};
  await h.runtime.setExecutionSettings({routing:'guide'});
  await h.runtime.prompt('',{start_plan:true});
  const painterRequests=h.requests.filter(req=>req.tools.some(t=>t.function.name==='paint_pass'));
  assert.ok(painterRequests.length>=3);
  assert.match(JSON.stringify(painterRequests[0]),/continue painting in this turn/);
  assert.ok(!JSON.stringify(painterRequests[1]).includes('"operation":"inspect"'));
  assert.equal(h.runtime.goal.passes,1);
  assert.equal(h.runtime.goal.status,'complete');
 } finally {await h.close();}
});

test('Luna late results are discarded when paused or the target revision changes',async()=>{
 const h=await harness(()=>({content:'Ready.'}));
 try {
  await h.start('ask');await h.runtime.setExecutionSettings({routing:'guide'});
  for(const change of ['revision','stop']) {
   h.runtime.cancelRequested=false;
   let resolve,entered;
   const started=new Promise(r=>{entered=r;});
   h.runtime.lunaRouter={evaluate:(_state,{identity})=>new Promise(r=>{resolve=()=>r({status:'recommended',context_identity:identity,operation:{choice:'move',confidence:1},brush:{choice:'none',confidence:1}});entered();})};
   const pending=h.runtime.routeDirection('Move the selected layer');await started;
   if(change==='stop')h.runtime.stop();else h.runtime.decisionObservation={document_id:'other',revision:'changed'};
   resolve();await pending;assert.equal(h.runtime.routingDecision,null);
  }
 } finally {await h.close();}
});

// A fake Luna client records what it was asked and answers per question type.
function fakeLuna(answer=()=>({fallback:'service_or_response_error'})) {
 const requests=[];
 return {requests,async decide(request){requests.push(request);return {elapsed_ms:1,usage:{cost:0,input_tokens:0},...answer(request)};}};
}
const hasImage=parts=>parts.some(part=>typeof part==='object');

test('Luna routing sends the canvas image while attached and is text-only when detached',async()=>{
 const h=await harness(()=>({content:'Ready.'}));
 try {
  await h.start('ask');
  const luna=fakeLuna();h.runtime.lunaClient=luna;
  await h.runtime.setExecutionSettings({routing:'evaluate'});
  await h.runtime.prompt('Move the boat to the right.');
  assert.equal(luna.requests.length,1);assert.ok(hasImage(luna.requests[0].parts),'attached canvas is sent');
  await h.runtime.canvas({action:'detach'});
  await h.runtime.prompt('Now soften the sky.');
  assert.equal(luna.requests.length,2);assert.ok(!hasImage(luna.requests[1].parts),'detached canvas is not sent');
  assert.ok(!JSON.stringify(h.events).includes('base64'),'no image data in events');
 } finally {await h.close();}
});

test('Luna layer need: Off asks nothing, Evaluate logs beside what the painter did, Guide advises the painter',{timeout:30000},async()=>{
 const texture={name:'Coat fur',preset:'b) Basic-1',strokes:[{start:[50,100],segments:[[60,110,70,120,80,130]],size:8,opacity:1,flow:1,color:'#302018'}],clip_to:'base',blend_mode:'overlay'};
 const prompts=[]; let h;
 h=await harness(req=>{
  if(!req.tools.some(t=>t.function.name==='paint_batch')) return {content:'Hello.'};
  const text=latestUserText(req), turn=/HOST MODE/.test(text) && req.messages.at(-1).role==='user';
  if(turn) prompts.push(text);
  return turn ? call('paint_pass',texture) : call('finish_move',{summary:'Coat texture'});
 },async(operation,params,_study,id)=>{
  if(operation!=='paint_pass')return undefined;
  // A new file per view, as the plugin writes: rewriting one view.png raced the background Luna read.
  const dir=h.runtime.study.directory, view=join(dir,'view-'+id+'.png'); await writeFile(view,png);
  return {status:'ok',layer_id:'fur-'+id,document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:view,layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};
 });
 const luna=fakeLuna(r=>r.purpose==='choose-next-layer' ? {answers:{need:{type:'choice',choice:'texture',confidence:0.8}}} : {fallback:'service_or_response_error'});
 const asked=()=>luna.requests.filter(r=>r.purpose==='choose-next-layer');
 try {
  await h.start('ask','Hello'); h.runtime.lunaClient=luna; await h.runtime.setMode('agent');
  await h.runtime.prompt('Paint her coat.');
  assert.equal(asked().length,0,'Off asks nothing');
  await h.runtime.setExecutionSettings({routing:'evaluate'});
  await h.runtime.prompt('Give the coat fur.');
  // The Evaluate question runs in the background: wait for it (a fixed 20 ms flaked under load).
  for(const until=Date.now()+3000; asked().length<1 && Date.now()<until;) await new Promise(r=>setTimeout(r,10));
  assert.equal(asked().length,1); assert.match(asked()[0].questions.need.instructions,/Give the coat fur/);
  assert.doesNotMatch(prompts.at(-1),/layer_need/,'Evaluate never changes what the painter sees');
  assert.deepEqual(['mode','need','painted'].map(k=>h.runtime.goal.layer_needs.at(-1)[k]),['evaluate','texture','texture'],'Luna’s choice is logged beside the painter’s');
  await h.runtime.setExecutionSettings({routing:'guide'});
  await h.runtime.prompt('More fur on the collar.');
  assert.match(prompts.at(-1),/"layer_need":\{"area":"More fur on the collar.","need":"texture","hint":"Add surface texture clipped to the flat/);
  await h.runtime.setExecutionSettings({native_craft:false}); const before=asked().length;
  await h.runtime.prompt('Strokes only now.');
  assert.equal(asked().length,before,'no layer advice with Strokes only');
 } finally {await h.close();}
});

test('One unify pass: after a whole-picture underpainting a chat gets one whole-canvas softening pass; more must be scoped',{timeout:30000},async()=>{
 // after-the-underpainting goal 3: a traced chat ran four whole-canvas smudge transfers and a filter over its underpainting.
 const whole={name:'Fuse dabs',preset:'k) Blender Basic',strokes:[{start:[0,0],segments:[[300,400,500,700,768,1024]],size:60,opacity:1,flow:1,color:'#808080'}]};
 const calls={'Fuse':['paint_pass',whole],'Again':['paint_pass',{...whole,name:'Soften every mass'}],'Blur':['apply_filter',{target:'under-1',filter:'blur',mode:'copy'}],
  'Hair':['paint_pass',{...whole,name:'Soften the hair',region:[100,100,200,200]}],'Bloom':['apply_filter',{target:'lamp-copy',filter:'blur',mode:'copy'}],
  'Broken':['paint_batch',{actions:[{tool:'paint_pass',arguments:{...whole,name:'Dot',strokes:[{...whole.strokes[0],segments:[[1,1,2,2,3,3]]}]}},{tool:'paint_pass',arguments:{...whole,name:'Broken smudge'}}]}]};
 const results=[]; let h;
 h=await harness(req=>{
  if(!req.tools.some(t=>t.function.name==='paint_batch')) return {content:'Hello.'};
  const text=latestUserText(req);
  if(!(/HOST MODE/.test(text) && req.messages.at(-1).role==='user')){
   const result=req.messages.filter(m=>m.role==='tool').at(-1);
   results.push(typeof result?.content==='string' ? result.content : JSON.stringify(result?.content)); return {content:'Done.'};
  }
  const key=Object.keys(calls).find(k=>text.endsWith(k+'.'));
  return call(...calls[key]);
 },async(operation,params,_study,id)=>{
  if(!['paint_pass','apply_filter'].includes(operation))return undefined;
  if(params.name==='Broken smudge') throw Object.assign(new Error('Use an exact installed preset name from list_brushes'),{code:'invalid_params'});
  const dir=h.runtime.study.directory, view=join(dir,'view-'+id+'.png'); await writeFile(view,png);
  return {status:'ok',layer_id:'soft-'+id,document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:view,layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('ask','Hello'); await h.runtime.setMode('agent');
  await h.runtime.prompt('Fuse.');
  assert.equal(h.runtime.goal.unify_pass,undefined,'before any underpainting the rule does not apply');
  // The whole-picture underpainting: a painted transfer job over the whole canvas, as reference-tool.mjs saves it.
  const jobs=join(h.runtime.study.directory,'reference-paintings'); await mkdir(jobs,{recursive:true});
  await writeFile(join(jobs,'a'.repeat(32)+'.json'),JSON.stringify({id:'a'.repeat(32),completed:5000,layer_id:'under-1',recipe:{name:'Underpainting',target:[0,0,768,1024]},scope:JSON.stringify([h.runtime.goal.revision])}));
  await h.runtime.prompt('Broken.');
  assert.match(results.at(-1),/"status":"failed"/,'the batch\u2019s smudge failed');
  assert.equal(h.runtime.goal.unify_pass,undefined,'a smudge that failed does not spend the pass');
  await h.runtime.prompt('Bloom.');
  assert.equal(h.calls.filter(c=>c.operation==='apply_filter').length,1,'a bloom blur of a small layer runs');
  assert.equal(h.runtime.goal.unify_pass,undefined,'and does not spend the pass');
  await h.runtime.prompt('Again.');
  assert.match(h.runtime.goal.unify_pass?.what ?? '',/smudge pass "Soften every mass"/,'the one unify pass is remembered for the chat');
  const painted=h.calls.filter(c=>c.operation==='apply_filter').length;
  await h.runtime.prompt('Blur.');
  assert.match(results.at(-1),/One unify pass per chat: smudge pass "Soften every mass" already softened the whole canvas.*blur filter covers 100%.*one element or region/);
  assert.equal(h.calls.filter(c=>c.operation==='apply_filter').length,painted,'nothing ran');
  await h.runtime.prompt('Again.');
  assert.match(results.at(-1),/One unify pass per chat/,'a second whole-canvas smudge too');
  const passes=h.calls.filter(c=>c.operation==='paint_pass').length;
  await h.runtime.prompt('Hair.');
  assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,passes+1,'softening scoped to one element still runs');
  assert.doesNotMatch(results.at(-1),/One unify pass/);
 } finally {await h.close();}
});

test('Undone work does not count: the underpainting and the transfer rules read the moves the artist kept, across the chat’s plan revisions',{timeout:30000},async()=>{
 const h=await harness(()=>({content:'Hello.'}));
 try {
  await h.start('ask','Hello'); await h.runtime.setMode('agent');
  const canvas={width:768,height:1024,layers:[]}, jobs=join(h.runtime.study.directory,'reference-paintings'); await mkdir(jobs,{recursive:true});
  const id='b'.repeat(32);
  await writeFile(join(jobs,id+'.json'),JSON.stringify({id,completed:5000,recipe:{name:'Underpainting',target:[0,0,768,1024]},scope:JSON.stringify([h.runtime.goal.revision])}));
  assert.equal(await h.runtime.underpainted(canvas),true);
  h.runtime.goal.revision=(h.runtime.goal.revision ?? 0)+1;
  assert.equal(await h.runtime.underpainted(canvas),true,'an underpainting from an earlier plan revision of the chat');
  h.runtime.goal.revision-=1;
  assert.equal(await h.runtime.wholeTransferAvailable(canvas),false,'a kept transfer: no second whole one');
  h.runtime.goal.moves=[{number:1,status:'undone'}]; h.runtime.goal.reference_jobs={[id]:[1]};
  assert.deepEqual([...h.runtime.undoneReferenceJobs()],[id]);
  assert.equal(await h.runtime.underpainted(canvas),false,'its move was undone');
  assert.equal(await h.runtime.wholeTransferAvailable(canvas),true,'the whole underpainting may be retried');
 } finally {await h.close();}
});

test('Ask when it may be done offers the folder elements whose steps are still open',{timeout:20000},async()=>{
 const h=await harness(()=>({content:'Hello.'}));
 try {
  await h.start('ask','Hello');
  h.runtime.study.folder={root:'/tmp/x',guesses:{}};
  h.runtime.folderIndex={root:'/tmp/x',elements:[{name:'01-sky.png',guess:'Sky'},{name:'02-towers.png',guess:'Towers'},{name:'03-woman.png',guess:'Woman'}]};
  h.runtime.goal.brief={steps:[{title:'Sky',scope:'01-sky.png'},{title:'Towers',scope:'02-towers.png'},{title:'Woman',scope:'03-woman.png'}]};
  h.runtime.goal.done_steps=[0,2];
  assert.deepEqual(h.runtime.elementsToOffer(),['Towers']);
 } finally {await h.close();}
});

test('Ask when it may be done: an unsure or done-leaning next-layer decision ends the move after one call and asks the artist',{timeout:30000},async()=>{
 // after-the-underpainting goal 4: two traced chats invented strokes for 20-30 minutes once the decision was spread thin.
 const texture={name:'Coat fur',preset:'b) Basic-1',strokes:[{start:[50,100],segments:[[60,110,70,120,80,130]],size:8,opacity:1,flow:1,color:'#302018'}],clip_to:'base',blend_mode:'overlay'};
 const prompts=[]; let paints=0, h;
 h=await harness(req=>{
  if(!req.tools.some(t=>t.function.name==='paint_batch')) return {content:'Hello.'};
  const text=latestUserText(req), turn=/HOST MODE/.test(text) && req.messages.at(-1).role==='user';
  if(turn) prompts.push(text);
  return call('paint_pass',{...texture,name:'Fur '+(++paints)});      // a painter that would keep inventing strokes
 },async(operation,params,_study,id)=>{
  if(operation!=='paint_pass')return undefined;
  const dir=h.runtime.study.directory, view=join(dir,'view-'+id+'.png'); await writeFile(view,png);
  return {status:'ok',layer_id:'fur-'+id,document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:view,layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};
 });
 let answer={type:'choice',choice:'texture',confidence:0.22,probabilities:{texture:0.22,accents:0.21,done:0.2,light:0.19,shadow:0.18}};
 const luna=fakeLuna(r=>r.purpose==='choose-next-layer' ? {answers:{need:answer}} : {fallback:'service_or_response_error'});
 try {
  await h.start('ask','Hello'); h.runtime.lunaClient=luna; await h.runtime.setMode('agent');
  await h.runtime.setExecutionSettings({routing:'guide'});
  h.runtime.goal.brief={steps:[{title:'Sky'},{title:'Kremlin towers'},{title:'Woman'}]}; h.runtime.goal.done_steps=[0];
  await h.runtime.prompt('Fur first.');
  assert.doesNotMatch(prompts.at(-1),/ASK WHEN IT MAY BE DONE/,'before the underpainting a thin decision is no reason to stop');
  assert.ok(paints>1,'the move goes on'); paints=0;
  const jobs=join(h.runtime.study.directory,'reference-paintings'); await mkdir(jobs,{recursive:true});
  await writeFile(join(jobs,'a'.repeat(32)+'.json'),JSON.stringify({id:'a'.repeat(32),completed:5000,recipe:{name:'Underpainting',target:[0,0,768,1024]},scope:JSON.stringify([h.runtime.goal.revision])}));
  await h.runtime.prompt('More fur on the collar.');
  assert.match(prompts.at(-1),/ASK WHEN IT MAY BE DONE: .*unsure what "More fur on the collar\." needs next/);
  assert.match(prompts.at(-1),/ask the artist what to work on next, offering the elements still lacking detail \(Kremlin towers, Woman\)/,'the plan’s open steps are offered');
  assert.equal(paints,1,'the move ended after one painting call');
  const move=h.runtime.goal.moves.at(-1);
  assert.deepEqual(move.ask_next,{reason:'unsure',elements:['Kremlin towers','Woman']});
  assert.match(h.events.filter(e=>e.type==='status' && e.phase==='idle').at(-1).message,/What should come next\? Kremlin towers or Woman/);
  answer={type:'choice',choice:'accents',confidence:0.4,probabilities:{accents:0.4,done:0.32,texture:0.28}};
  await h.runtime.prompt('Polish her head.');
  assert.match(prompts.at(-1),/ranks "done" among its top two choices/);
  answer={type:'choice',choice:'texture',confidence:0.8,probabilities:{texture:0.8,done:0.1,accents:0.1}};
  const before=paints;
  await h.runtime.prompt('Fur on the hem.');
  assert.doesNotMatch(prompts.at(-1),/ASK WHEN IT MAY BE DONE/,'a clear next layer: no nudge');
  assert.ok(paints-before>1,'and the move goes on as usual');
  assert.equal(h.runtime.goal.moves.at(-1).ask_next,undefined);
 } finally {await h.close();}
});

test('Luna artifact check: Off makes no call, Evaluate records each pass, Guide asks it in the one pacing request and names the painted area',{timeout:20000},async()=>{
 for(const mode of ['off','evaluate','guide']) {
  let h;
  h=await harness(req=>{
   const names=req.tools.map(t=>t.function.name);
   if(names.includes('propose_plan'))return call('propose_plan',brief);
   if(names.includes('submit_review'))return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
   return h.calls.some(c=>c.operation==='paint_pass') ? call('request_review',{reason:'Ready.'}) : call('paint_pass',pass);
  },async(operation,params,_study,id)=>{
   if(operation!=='paint_pass')return undefined;
   const dir=h.runtime.study.directory;
   await writeFile(join(dir,'before.png'),png);await writeFile(join(dir,'after.png'),png);await writeFile(join(dir,'view.png'),png);
   return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'revision-1',content_id:'content-1',
    passes:[{id,kind:'paint',title:'Pass',before_path:join(dir,'before.png'),after_path:join(dir,'after.png')}]};
  });
  try {
   await h.start('plan');await h.runtime.setMode('autopilot');
   const luna=fakeLuna(({questions})=>Object.values(questions)[0].type==='noul'
    ? {answers:Object.fromEntries(Object.keys(questions).map(k=>[k,{type:'noul',noul:['stripes','mistake_stripes'].includes(k)?.93:.02}]))}
    : Object.values(questions)[0].type==='choice' && 'stripes' in questions ? {answers:{stripes:{type:'choice',choice:'bottom_center',confidence:.9,probabilities:{}}}}
    : {fallback:'service_or_response_error'});
   h.runtime.lunaClient=luna;h.runtime.lunaRouter={evaluate:async(_s,{identity})=>({status:'fallback',reason:'test',context_identity:identity})};
   await h.runtime.setExecutionSettings({routing:mode});
   await h.runtime.prompt('',{start_plan:true});
   await new Promise(r=>setTimeout(r,50));
   const passChecks=luna.requests.filter(r=>r.parts.includes('BEFORE (canvas before this paint pass):'));
   const paced=luna.requests.filter(r=>r.purpose==='pace-run' && r.parts.includes('BEFORE (canvas before this painting call):'));
   const event=h.events.find(e=>e.type==='visual_check');
   const painterSaw=JSON.stringify(h.requests).includes('mechanical stripes');
   if(mode==='off'){assert.equal(passChecks.length+paced.length,0);assert.equal(event,undefined);}
   else if(mode==='evaluate') {
    assert.equal(passChecks.length,1);assert.equal(paced.length,0);
    assert.deepEqual(event.findings.map(f=>[f.type,f.location]),[['stripes','bottom_center']]);
    assert.equal(painterSaw,false,'Evaluate only records');
   } else {
    assert.equal(passChecks.length,0,'no separate per-pass request');
    assert.equal(paced.length,1,'asked once, inside the pacing request');
    assert.ok(Object.keys(paced[0].questions).some(k=>k.startsWith('s0_c')) && 'mistake_stripes' in paced[0].questions);
    assert.ok(!luna.requests.some(r=>r.purpose==='locate-pass-failures'),'no guessed location request');
    assert.deepEqual(event.findings.map(f=>f.type),['stripes']);
    assert.ok(painterSaw);
    assert.ok(JSON.stringify(h.requests).includes('area\\":[20,20,30,30]'),'the painter is told the area its strokes covered');
   }
   assert.equal(h.runtime.goal.passes,1);
  } finally {await h.close();}
 }
});

test('Guide undoes a painting call Luna is sure pasted a flat block over an established painting, and tells the painter',{timeout:20000},async()=>{
 let h, painted=0;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',brief);
  if(names.includes('submit_review'))return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  return painted>=AUTO_UNDO_CALLS ? call('request_review',{reason:'Ready.'}) : (painted++, call('paint_pass',pass));
 },async(operation,params,_study,id)=>{
  const dir=h.runtime.study.directory;
  if(operation==='review_pass') {
   await writeFile(join(dir,'undone.png'),png);
   return {status:'ok',document_id:'doc',width:768,height:1024,image_path:join(dir,'undone.png'),layers:[],revision:'revision-undone-'+params.pass_id,affected_pass_ids:[params.pass_id],passes:[]};
  }
  if(operation!=='paint_pass')return undefined;
  await writeFile(join(dir,'before.png'),png);await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'revision-'+id,content_id:'content-1',
   passes:[{id,kind:'paint',title:'Pass',layer_id:'layer-'+id,before_path:join(dir,'before.png'),after_path:join(dir,'view.png')}]};
 });
 const AUTO_UNDO_CALLS=4;
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');
  const luna=fakeLuna(({questions})=>({answers:Object.fromEntries(Object.keys(questions).map(k=>[k,{type:'noul',noul:k==='mistake_flat_block'?.96:k==='mistake_established'?.99:.05}]))}));
  h.runtime.lunaClient=luna;h.runtime.lunaRouter={evaluate:async(_s,{identity})=>({status:'fallback',reason:'test',context_identity:identity})};
  await h.runtime.setExecutionSettings({routing:'guide'});
  await h.runtime.prompt('',{start_plan:true});
  const rejects=h.calls.filter(c=>c.operation==='review_pass');
  assert.equal(rejects.length,3,'at most three automatic undos per plan step; then the flag is only reported');
  assert.ok(rejects.every(c=>c.params.action==='reject' && /^revision-/.test(c.params.expected_revision)));
  assert.deepEqual(h.runtime.goal.auto_rejects,{0:3});
  const told=JSON.stringify(h.requests);
  assert.ok(told.includes('host_undo') && told.includes('flat block'),'the painter is told what was undone and why');
  assert.ok(told.includes('visual_check'),'past the limit the finding is reported, not undone');
  assert.ok(h.events.some(e=>e.type==='action' && /Undid a painting call/.test(e.message)));
 } finally {await h.close();}
});

test('Luna progress makes stall rules evidence-based in Guide mode',()=>{
 const review=(pass_count,progress)=>({verdict:'continue',revision:1,stage:0,pass_count,checks:[{id:'check-1',met:false}],...(progress!==undefined?{progress}:{})});
 const stalled=[review(1),review(2,{mean:.2}),review(3,{mean:.4})];
 assert.equal(repeatedReviewFailures(stalled,{progress:true}),3);
 assert.equal(progressStalled(stalled,3),true,'no real improvement: change strategy');
 const slight=[review(1),review(2,{mean:1.2}),review(3,{mean:.4})];
 assert.equal(progressStalled(slight,3),false,'slight measured progress defers the strategy change');
 const missing=[review(1),review(2,{fallback:'timeout'}),review(3,{mean:.1})];
 assert.equal(progressStalled(missing,3),null,'missing progress keeps the check-ID rule');
 const clear=[review(1),review(2,{mean:.3}),review(3,{mean:2.4})];
 assert.equal(repeatedReviewFailures(clear,{progress:true}),0,'clear progress ends the repeated run');
 assert.equal(repeatedReviewFailures(clear),3,'without Guide, progress is ignored');
});

test('Luna progress check scores repeated failures from the previous and current review images',async()=>{
 const h=await harness(()=>({content:'Ready.'}));
 try {
  await h.start('ask');
  const dir=h.runtime.study.directory;await writeFile(join(dir,'r1.png'),png);await writeFile(join(dir,'r2.png'),png);
  const luna=fakeLuna(({questions})=>({answers:Object.fromEntries(Object.keys(questions).map(k=>[k,{type:'score',score:.5,confidence:.9,probabilities:{}}]))}));
  h.runtime.lunaClient=luna;await h.runtime.setExecutionSettings({routing:'evaluate'});
  const failed={id:'check-1',met:false,evidence:'Porch stripes remain.'};
  h.runtime.goal.reviews=[{verdict:'continue',revision:h.runtime.goal.revision,stage:0,pass_count:1,image:join(dir,'r1.png'),checks:[failed],criteria_text:{'check-1':'The porch reads as a recessed porch.'}},
   {verdict:'continue',revision:h.runtime.goal.revision,stage:0,pass_count:2,image:join(dir,'r2.png'),checks:[failed],criteria_text:{'check-1':'The porch reads as a recessed porch.'}}];
  await h.runtime.reviewProgress();
  assert.equal(luna.requests.length,1);
  assert.match(Object.values(luna.requests[0].questions)[0].instructions,/recessed porch/);
  assert.deepEqual(h.runtime.goal.reviews.at(-1).progress,{scores:{'check-1':.5},mean:.5,region:'canvas'});
  await h.runtime.setExecutionSettings({routing:'off'});h.runtime.goal.reviews.at(-1).progress=undefined;
  await h.runtime.reviewProgress();assert.equal(luna.requests.length,1,'Off makes no call');
 } finally {await h.close();}
});

test('Luna reuses the painter OpenRouter key, then OPENROUTER_API_KEY, else falls back not_connected',async()=>{
 const h=await harness(()=>({content:'Ready.'}));
 const saved=process.env.OPENROUTER_API_KEY;
 try {
  await h.start('ask');
  h.runtime.models.getAuth=async provider=>provider==='openrouter'?{auth:{apiKey:'sk-or-pi'},source:'auth.json'}:undefined; // Pi's real shape
  assert.equal((await h.runtime.luna()).apiKey,'sk-or-pi');assert.ok(h.runtime.secrets.includes('sk-or-pi'),'key is redacted');
  h.runtime.lunaClient=undefined;h.runtime.models.getAuth=async()=>undefined;process.env.OPENROUTER_API_KEY='sk-or-env';
  assert.equal((await h.runtime.luna()).apiKey,'sk-or-env');
  h.runtime.lunaClient=undefined;delete process.env.OPENROUTER_API_KEY;
  const client=await h.runtime.luna();assert.equal(client.apiKey,null);
  assert.equal((await client.decide({parts:['x'],questions:{}})).fallback,'not_connected');
 } finally {if(saved===undefined)delete process.env.OPENROUTER_API_KEY;else process.env.OPENROUTER_API_KEY=saved;await h.close();}
});

test('a failed Luna pass check leaves the pass result unchanged',async()=>{
 const h=await harness(()=>({content:'Ready.'}));
 try {
  await h.start('ask');await h.runtime.setExecutionSettings({routing:'guide'});
  const dir=h.runtime.study.directory;await writeFile(join(dir,'b.png'),png);await writeFile(join(dir,'a.png'),png);
  h.runtime.lunaClient=fakeLuna(()=>({fallback:'refused'}));
  const result={passes:[{id:'op-1',kind:'paint',before_path:join(dir,'b.png'),after_path:join(dir,'a.png')}]};
  const before=JSON.stringify(result);
  await h.runtime.visualPassCheck(result,'op-1');
  assert.equal(JSON.stringify(result),before);assert.equal(h.runtime.lunaClient.requests.length,1);
  assert.ok(!h.events.some(e=>e.type==='visual_check'));
 } finally {await h.close();}
});

// Paint passes fail natively with an uncertain outcome; observe/reconcile succeed unless told otherwise.
function uncertainBridge(get,{failObserve=false}={}) {
 return async(operation,params,_study,id)=>{
  const h=get();
  if(operation==='paint_pass'){h.failedPass=true;const e=new Error('Smart Patch could not sample the source');e.code='partial_change';throw e;}
  if(operation==='observe'&&failObserve&&h.failedPass){throw Object.assign(new Error('Krita did not respond'),{code:'unavailable'});}
  if(operation==='reconcile'||operation==='observe'){
   const dir=h.runtime.study.directory;await writeFile(join(dir,'now.png'),png);
   return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'now.png'),layers:[],
    revision:'revision-r',content_id:'content-r',unresolved_operations:[],committed_operation_count:0};
  }
  return undefined;
 };
}

test('an uncertain action recovers automatically and the run continues without pausing for inspection',{timeout:20000},async()=>{
 let h,painted=0;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',brief);
  if(names.includes('submit_review'))return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  return painted++ ? call('request_review',{reason:'Ready.'}) : call('paint_pass',pass);
 },uncertainBridge(()=>h));
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.setExecutionSettings({routing:'off'});
  await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.faulted,false,'not faulted');
  assert.equal(h.runtime.goal.status,'complete','the run continued to review and completion');
  assert.ok(h.calls.some(c=>c.operation==='reconcile'),'native uncertain state acknowledged');
  const toolResult=JSON.stringify(h.requests.find(r=>JSON.stringify(r).includes('uncertain_action')));
  assert.match(toolResult,/Smart Patch could not sample the source/);assert.match(toolResult,/never repeat the action blindly/);
  assert.ok(!JSON.stringify(h.events).includes('Paused for inspection'));
 } finally {await h.close();}
});

test('if recovery cannot observe the canvas, the run pauses for inspection as before',{timeout:20000},async()=>{
 let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',brief);
  return call('paint_pass',pass);
 },uncertainBridge(()=>h,{failObserve:true}));
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');
  await h.runtime.prompt('',{start_plan:true}).catch(()=>{});
  assert.equal(h.runtime.faulted,true);assert.equal(h.runtime.goal.status,'paused');
 } finally {await h.close();}
});

test('repeated uncertain actions change strategy every third in a row and never pause the run',{timeout:30000},async()=>{
 let h;
 const reasons=[];
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',brief);
  const reason=h.runtime.goal.execution_recovery?.reason;
  if(reason && reasons.at(-1)!==reason) reasons.push(reason);
  // Only the artist's Stop ends this run.
  if((h.runtime.goal.uncertain_strategy_at ?? 0)>=6){h.runtime.stop();return {content:'Stopped.'};}
  return call('paint_pass',{...pass,name:'Attempt '+Math.random()});
 },uncertainBridge(()=>h));
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.setExecutionSettings({routing:'off'});
  await h.runtime.prompt('',{start_plan:true});
  assert.equal(reasons.length,2,'a strategy change at three and again at six');
  assert.match(reasons[0],/^3 painting actions in a row/);assert.match(reasons[1],/^6 painting actions in a row/);
  assert.equal(h.runtime.goal.pause_reason,undefined,'no runaway pause');
  assert.equal(h.runtime.faulted,false);assert.equal(h.runtime.goal.status,'paused','paused only by Stop');
 } finally {await h.close();}
});

test('no mid-run stops: outside canvas edits and repeated failed reviews keep the run going', {timeout:30000}, async()=>{
 let reviews=0, observes=0, turn=0;
 const h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',brief);
  if(names.includes('submit_review')){
   reviews++;
   return call('submit_review',{verdict:'continue',summary:'Edges still soft.',issues:reviews<7?['Edges soft.']:[],
    checks:[0,1,2].map(i=>({id:'check-'+i,met:reviews>=7||i!==2,evidence:'Visible.'}))});
  }
  // Alternate one paint pass and one review request.
  return (turn++)%2 ? call('request_review',{reason:'Painting ready.'}) : call('paint_pass',{...pass,name:'Pass '+Math.random()});
 },(operation)=>{
  // The artist edits the canvas once mid-run.
  if(operation==='observe' && ++observes===3) return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,
   image_path:h.runtime.lastObservation?.image_path,layers:[],revision:'revision-artist',content_id:'content-artist',captured_at:new Date().toISOString()};
 });
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.setExecutionSettings({routing:'off'});
  await h.runtime.prompt('',{start_plan:true});
  assert.ok(h.runtime.goal.user_updates.some(u=>/artist edited the canvas/.test(u)),'outside edits become a direction to keep');
  assert.equal(reviews,7,'five or more repeated failed reviews do not pause the run');
  assert.equal(h.runtime.goal.status,'complete');assert.equal(h.runtime.goal.pause_reason,undefined);
 } finally {await h.close();}
});

test('Resume acknowledges a leftover uncertain action instead of requiring inspection',{timeout:20000},async()=>{
 let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',brief);
  if(names.includes('submit_review'))return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  return call('request_review',{reason:'Ready.'});
 },uncertainBridge(()=>h));
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');
  h.runtime.study.bound=true;h.runtime.study.target_document_id='doc';h.runtime.faulted=true;h.runtime.study.unresolved_operations=[{error:'earlier'}];
  await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.faulted,false);assert.ok(h.calls.some(c=>c.operation==='reconcile'));
  assert.notEqual(h.runtime.goal.status,'paused');
 } finally {await h.close();}
});

test('In Agent mode the artist\u2019s next message acknowledges a leftover uncertain action, as Resume does',{timeout:20000},async()=>{
 let h, painted=0;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('paint_batch'))painted++;               // a move asks the model with the painting tools
  return {content:'ok'};
 },uncertainBridge(()=>h));
 try {
  await h.start('ask','Hi');await h.runtime.setMode('agent');
  h.runtime.study.bound=true;h.runtime.study.target_document_id='doc';h.runtime.faulted=true;h.runtime.study.unresolved_operations=[{error:'timed out'}];
  await h.runtime.prompt('Go on, fix the seam.');
  assert.equal(h.runtime.faulted,false,'the message is the go-ahead, not refused');
  assert.ok(h.calls.some(c=>c.operation==='reconcile'),'the canvas is confirmed first');
  assert.ok(painted>=1,'and the move runs');
 } finally {await h.close();}
});

test('Keep and Undo also acknowledge a leftover uncertain action, as a typed message does',{timeout:20000},async()=>{
 let h;
 const uncertain=uncertainBridge(()=>h);
 h=await harness(()=>({content:'ok'}),async(operation,params,study,id)=>operation==='review_pass'?{status:'ok',layers:[]}:uncertain(operation,params,study,id));
 try {
  await h.start('ask','Hi');await h.runtime.setMode('agent');
  h.runtime.goal.moves=[{number:1,status:'ready',title:'Clouds'}];
  h.runtime.study.bound=true;h.runtime.study.target_document_id='doc';h.runtime.faulted=true;h.runtime.study.unresolved_operations=[{error:'checkpoint failed'}];
  await h.runtime.moveAction({action:'undo',move:1}).catch(error=>assert.doesNotMatch(error.message,/Inspect and acknowledge/));
  assert.equal(h.runtime.faulted,false,'the artist\u2019s Undo is the go-ahead');
  assert.ok(h.calls.some(c=>c.operation==='reconcile'));
 } finally {await h.close();}
});

test('after Undo the retry keeps what already works and is told what the undone move did',{timeout:20000},async()=>{
 const h=await harness(()=>({content:'ok'}),async operation=>operation==='review_pass'?{status:'ok',layers:[]}:undefined);
 try {
  await h.start('ask','Hi');await h.runtime.setMode('agent');
  h.runtime.goal.moves=[{number:1,status:'ready',title:'Clouds',summary:'Seed-selected the sky and filled it flat, then strokes'}];
  let sent; h.runtime.prompt=async text=>{sent=text;}; h.runtime.reviewPass=async()=>{};   // the layers' reject is tested elsewhere
  await h.runtime.moveAction({action:'undo',move:1});
  assert.match(sent,/undid move 1/);
  assert.match(sent,/seed-selected the sky and filled it flat/i,'what the undone move did');
  assert.match(sent,/keep what already works/i);
  assert.doesNotMatch(sent,/clearly different approach/,'"clearly different" threw away what worked');
 } finally {await h.close();}
});

test('tracing is optional: without Langfuse a chat runs untraced; with it one session runs until New chat', {timeout:20000}, async()=>{
  const h=await harness(()=>({content:'Happy to discuss it.'}));
  try {
    const tracing=h.runtime.tracing; h.runtime.tracing=null;
    let attempts=0;
    h.runtime.connectTracing=async()=>{attempts++; throw new Error('No Langfuse keys. Add LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL to .env.');};
    await h.start('ask','Untraced chat');
    assert.ok(h.runtime.study,'the chat starts'); assert.ok(h.requests.length>0,'the model is called');
    assert.ok(h.events.some(e=>e.type==='status' && e.message==='Tracing off (no Langfuse keys).'));
    assert.equal(h.events.filter(e=>e.type==='tracing').length,0);
    await h.runtime.end();
    await h.start('ask','Another untraced chat'); await h.runtime.end();
    assert.equal(attempts,1,'a failed connection is not retried on every chat start');
    h.runtime.tracingAttemptAt=-Infinity;
    h.runtime.connectTracing=async()=>tracing;
    await h.start('ask','First chat');
    const first=h.runtime.study.id;
    assert.deepEqual(h.events.filter(e=>e.type==='tracing').map(e=>e.url),['https://langfuse.test/project/project-test/sessions/'+first]);
    await h.runtime.prompt('Second message, same chat');
    await h.runtime.end();
    await h.start('ask','Second chat');
    const second=h.runtime.study.id; assert.notEqual(first,second);
    const roots=tracing.recorded.observations.filter(o=>!o.parent);
    const sessions=roots.map(o=>[o.name,o.trace.sessionId]);
    assert.deepEqual(sessions,[['answer-artist',first],['answer-artist',first],['end-chat',first],['answer-artist',second]],'only chats after the connection are traced');
    assert.ok(tracing.recorded.observations.filter(o=>o.parent).every(o=>o.trace.sessionId===o.parent.trace.sessionId));
    assert.ok(roots.slice(0,2).every(o=>o.ended),'runs end before New chat'); assert.equal(roots[2].options.asType,'event');
  } finally {await h.close();}
});

test('Luna pacing advances plan steps and calls the review, so the painter spends no turns on bookkeeping',{timeout:30000},async()=>{
 const twoSteps={...brief,steps:[{title:'Establish figures',done_when:'Two placed silhouettes.'},{title:'Refine faces',done_when:'Readable faces.'}]};
 let paceCalls=0, toolLists=[];
 const pace=req=>{
  if(req.purpose!=='pace-run')return {fallback:'service_or_response_error'};
  paceCalls++;
  // Call 1: step 1's checks are visible (next step). Call 3: the whole painting looks finished (review).
  return {answers:Object.fromEntries(Object.keys(req.questions).map(k=>[k,{type:'noul',noul:k.startsWith('s0_') || (k==='finished' && paceCalls>=3) ? .9 : .1}]))};
 };
 let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',twoSteps);
  if(names.includes('submit_review'))return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  toolLists.push(names);
  return call('paint_pass',pass);
 },async(operation,params,_study,id)=>{
  if(operation!=='paint_pass')return undefined;
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'revision-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');
  h.runtime.lunaClient=fakeLuna(pace);await h.runtime.setExecutionSettings({routing:'guide'});
  await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.goal.status,'complete','the host-called review completed the painting');
  assert.equal(h.runtime.goal.current_step,1,'the host moved to the next step');
  assert.ok(toolLists.every(n=>!n.includes('record_progress') && n.includes('request_review')),'record_progress is hidden; request_review stays as a backstop');
  assert.ok(h.requests.some(r=>JSON.stringify(r.messages).includes('host_pacing')),'the painter is told in the tool result');
  assert.ok(h.runtime.goal.pace_history.length>=3);
 } finally {await h.close();}
});

test('a Stop that Krita heard first pauses the run: a shortened pass or a refused action',{timeout:20000},async()=>{
 for (const answer of [{stopped:'Stopped by the artist.',stopped_after_strokes:2,strokes_total:6}, {error:'Stopped by the artist before this action ran; nothing was painted.',error_code:'stopped_by_artist'}]) {
  let h, paints=0;
  h=await harness(req=>{
   const names=req.tools.map(t=>t.function.name);
   if(names.includes('propose_plan'))return call('propose_plan',brief);
   assert.ok(++paints<=3,'the run does not keep painting after Krita reported the Stop');
   return call('paint_pass',pass);
  },async(operation,params,_study,id)=>{
   if(operation!=='paint_pass')return undefined;
   if(answer.error_code){const error=new Error(answer.error);error.code=answer.error_code;throw error;}
   const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
   return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'revision-'+id,content_id:'c-'+id,passes:[],...answer};
  });
  try {
   await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.prompt('',{start_plan:true});
   assert.equal(h.runtime.goal.status,'paused');assert.ok(h.runtime.cancelRequested);
   assert.ok(!h.runtime.faulted,'a Stop is never an uncertain result');
   assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,1);
  } finally {await h.close();}
 }
});

test('Luna pacing moves on when its score stops rising instead of continuing one step forever',{timeout:30000},async()=>{
 const twoSteps={...brief,steps:[{title:'Construction map',done_when:'Guide lines at exact positions.'},{title:'Block-in',done_when:'Flat masses.'}]};
 const pace=req=>req.purpose!=='pace-run' ? {fallback:'service_or_response_error'}
  : {answers:Object.fromEntries(Object.keys(req.questions).map(k=>[k,{type:'noul',noul:k==='finished' ? .1 : .53}]))};   // every check at 1.6 of 3, flat
 let h, paints=0;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',twoSteps);
  if(names.includes('submit_review'))return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  assert.ok(++paints<=20,'the run does not paint one step forever');
  return call('paint_pass',pass);
 },async(operation,params,_study,id)=>{
  if(operation!=='paint_pass')return undefined;
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'revision-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');
  h.runtime.lunaClient=fakeLuna(pace);await h.runtime.setExecutionSettings({routing:'guide'});
  await h.runtime.prompt('',{start_plan:true});
  const history=h.runtime.goal.pace_history;
  assert.equal(history.filter(p=>p.step===0).length,8,'step 1 levels off after eight flat scores');
  assert.equal(history.find(p=>p.step===0 && p.action==='next_step'),history.filter(p=>p.step===0).at(-1));
  assert.equal(h.runtime.goal.current_step,1);
  assert.ok(h.requests.some(r=>JSON.stringify(r.messages).includes('progress stopped rising')),'the painter is told why it moved on');
  assert.equal(history.filter(p=>p.step===1).at(-1).action,'request_review','the last step levels off into the review');
  assert.equal(h.runtime.goal.status,'complete');
 } finally {await h.close();}
});

test('a blur that twice fails to move the step is refused for the rest of the step, and the painter is told to paint instead',{timeout:30000},async()=>{
 const twoSteps={...brief,steps:[{title:'Big shapes',done_when:'Masses.'},{title:'Materials',done_when:'Distinct materials.'}]};
 let blurs=0, painted=false;
 // Blurs leave the step flat at 1.2 of 3 (below 1 would be a stall that moves on); the first painted pass makes the painting look finished.
 const pace=req=>req.purpose!=='pace-run' ? {fallback:'service_or_response_error'}
  : {answers:Object.fromEntries(Object.keys(req.questions).map(k=>[k,{type:'noul',noul:k==='finished' ? (painted ? .9 : .1) : .4}]))};
 let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan'))return call('propose_plan',twoSteps);
  if(names.includes('submit_review'))return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:[0,1,2].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  if(++blurs<=4)return call('apply_filter',{target:'layer-1',filter:'gaussian blur'});
  painted=true; return call('paint_pass',pass);
 },async(operation,params,_study,id)=>{
  if(!['paint_pass','apply_filter'].includes(operation))return undefined;
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',layer_id:'layer-'+id,document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'revision-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');
  h.runtime.lunaClient=fakeLuna(pace);await h.runtime.setExecutionSettings({routing:'guide'});
  await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.calls.filter(c=>c.operation==='apply_filter').length,3,'the fourth blur never reached Krita');
  const told=h.requests.map(r=>JSON.stringify(r.messages));
  assert.ok(told.some(m=>m.includes('smoothing filter ran twice on this step')),'the painter is told why, with authored tools to use instead');
  assert.deepEqual(h.runtime.goal.pace_history.filter(p=>p.method).map(p=>p.method),['smoothing filter','smoothing filter','smoothing filter']);
  assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,1,'painting by hand is never refused');
  assert.equal(h.runtime.goal.status,'complete');
 } finally {await h.close();}
});

test('OAuth sign-ins (e.g. Codex) are offered after key models; a lapsed sign-in pauses with how to sign in again and keeps the model',{timeout:20000},async()=>{
 const h=await harness(()=>({content:'Hello.'}));
 try {
  await h.start('ask','Before the login lapses');
  h.runtime.models.listCredentials=async()=>[{providerId:'local-test',type:'oauth'}];
  await h.runtime.refreshKeyProviders();
  const listed=h.runtime.listModels().filter(m=>m.provider==='local-test');
  assert.ok(listed.length && listed.every(m=>m.auth==='oauth' && m.configured),'OAuth models are listed and usable');
  assert.equal(h.runtime.listProviders().find(p=>p.id==='local-test')?.auth,'oauth');
  await h.runtime.prompt('Continue');
  assert.ok(h.runtime.goal.messages.some(m=>m.role==='assistant' && /Hello/.test(m.text)),'a chat runs on the signed-in model');
  // The sign-in lapses mid-run: the model request fails with an auth error.
  h.runtime.onEvent({type:'message_end',message:{role:'assistant',stopReason:'error',errorMessage:'401 Unauthorized: token expired'}});
  assert.match(h.runtime.runError,/sign-in has lapsed, so the run is paused.*\/login.*same model/);
  h.runtime.onEvent({type:'message_end',message:{role:'assistant',stopReason:'error',errorMessage:'500 upstream overloaded'}});
  assert.doesNotMatch(h.runtime.runError,/sign-in/,'other errors are reported as they are');
  // Signed out: the chat keeps its model and says how to sign in; signing in again lets it continue.
  const configured=h.runtime.models.hasConfiguredAuth.bind(h.runtime.models);
  let signedIn=false, rechecked=0;
  h.runtime.models.hasConfiguredAuth=id=>id==='local-test' ? signedIn : configured(id);
  const refresh=h.runtime.models.refresh.bind(h.runtime.models);
  h.runtime.models.refresh=async options=>{ if(options?.providers?.includes('local-test')) rechecked++; return refresh(options); };
  await assert.rejects(h.runtime.prompt('Continue'),/not signed in.*\/login/);
  assert.ok(rechecked>0,'the sign-in is re-read before refusing');
  assert.equal(h.runtime.study.provider,'local-test','the chat keeps its model');
  signedIn=true;
  await h.runtime.prompt('Continue after signing in');
 } finally {await h.close();}
});

test('a Quick Agent move is one painting call; Keep continues, Undo rejects the whole move and retries',{timeout:30000},async()=>{
 const batch=n=>call('paint_batch',{summary:'Night sky block-in '+n,actions:[{tool:'paint_pass',arguments:pass},{tool:'paint_pass',arguments:{...pass,name:'Swirls'}}]});
 let painterCalls=0, toolNames=[];
 let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(!names.includes('paint_batch')) return {content:'Hello.'};
  toolNames.push(names); painterCalls++;
  return batch(painterCalls);
 },async(operation,params,_study,id)=>{
  if(!['paint_pass','review_pass'].includes(operation))return undefined;
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('ask','Hello'); await h.runtime.setExecutionSettings({move_size:'quick'}); await h.runtime.setMode('agent');
  await h.runtime.prompt('Paint the swirling night sky.');
  assert.equal(painterCalls,1,'one model call made the move; the turn ended after it');
  const [first]=h.runtime.goal.moves;
  assert.deepEqual([first.number,first.status,first.actions,first.strokes,first.title],[1,'ready',2,2,'Night sky block-in 1']);
  assert.equal(h.runtime.goal.status,'move_ready');
  const painted=h.calls.filter(c=>c.operation==='paint_pass');
  assert.equal(painted.length,2); assert.ok(painted.every(c=>c.params.stage_id==='move-1'),'a move is one pass group');
  assert.ok(toolNames[0].includes('paint_batch') && !toolNames[0].includes('request_review') && !toolNames[0].includes('record_progress'));
  assert.ok(h.events.some(e=>e.type==='move' && e.move.number===1));
  await h.runtime.moveAction({action:'keep',move:1});
  assert.equal(h.runtime.goal.moves[0].status,'kept'); assert.equal(h.runtime.goal.moves[1].status,'ready');
  await h.runtime.moveAction({action:'undo',move:2});
  const undo=h.calls.find(c=>c.operation==='review_pass');
  assert.deepEqual([undo.params.pass_id,undo.params.action],['stage:move-2','reject'],'Undo rejects every pass of the move');
  assert.equal(h.runtime.goal.moves[1].status,'undone');
  assert.equal(h.runtime.goal.moves[2].kind,'retry'); assert.equal(h.runtime.goal.reviews.length,0,'Agent never runs the review on its own');
  await assert.rejects(h.runtime.moveAction({action:'keep',move:1}),/no painted move/);
 } finally {await h.close();}
});

test('a Subject Agent move works the subject through several batches, then one card and one Undo',{timeout:30000},async()=>{
 const stages=['Kremlin block-in','Towers and walls','Light and windows'];
 let painterCalls=0, prompts=[];
 let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(!names.includes('paint_batch')) return {content:'Hello.'};
  prompts.push(latestUserText(req));
  painterCalls++;
  if(painterCalls<=stages.length) return call('paint_batch',{summary:stages[painterCalls-1],actions:[{tool:'paint_pass',arguments:{...pass,name:stages[painterCalls-1]}}]});
  return call('finish_move',{summary:'Kremlin: red walls, five towers with green spires, lit windows'});
 },async(operation,params,_study,id)=>{
  if(!['paint_pass','review_pass'].includes(operation))return undefined;
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('ask','Hello'); await h.runtime.setMode('agent');
  await h.runtime.prompt('Paint the Kremlin.');
  assert.match(prompts[0],/finishes ONE subject/); assert.match(prompts[0],/up to 8 painting calls/);
  assert.equal(painterCalls,4,'three batches, looking at each result, then finish_move');
  const painted=h.calls.filter(c=>c.operation==='paint_pass');
  assert.equal(painted.length,3); assert.ok(painted.every(c=>c.params.stage_id==='move-1'),'the whole subject is one pass group');
  const [move]=h.runtime.goal.moves;
  assert.deepEqual([move.number,move.status,move.calls,move.actions,move.title],[1,'ready',3,3,'Kremlin: red walls, five towers with green spires, lit windows']);
  assert.equal(h.events.filter(e=>e.type==='move').length,1,'one card for the subject');
  assert.ok(h.events.some(e=>e.type==='status' && /Move 1 · Kremlin block-in · 2 batches/.test(e.message ?? '')),'progress shows while it works');
  await h.runtime.moveAction({action:'undo',move:1});
  assert.equal(h.calls.find(c=>c.operation==='review_pass').params.pass_id,'stage:move-1','one Undo removes the whole subject');
 } finally {await h.close();}
});

test('Keep after a move that finished the whole request ends it instead of asking for another move',{timeout:30000},async()=>{
 let painterCalls=0; let h;
 h=await harness(req=>{
  if(!req.tools.some(t=>t.function.name==='paint_batch')) return {content:'Hello.'};
  painterCalls++;
  if(painterCalls===1) return call('paint_batch',{summary:'Fields',actions:[{tool:'paint_pass',arguments:{...pass,name:'Fields'}}]});
  if(painterCalls===2) return call('finish_move',{summary:'Rothko: yellow over red-orange on an orange ground',request_done:true});
  return call('paint_batch',{summary:'Polish',actions:[{tool:'paint_pass',arguments:{...pass,name:'Polish'}}]});
 },async(operation,params,_study,id)=>{
  if(!['paint_pass','review_pass'].includes(operation))return undefined;
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('ask','Hello'); await h.runtime.setMode('agent');
  await h.runtime.prompt('Paint the Rothko.');
  const [move]=h.runtime.goal.moves;
  assert.equal(move.request_done,true);
  await h.runtime.moveAction({action:'keep',move:1});
  assert.equal(painterCalls,2,'no further move was asked for');
  assert.equal(h.runtime.goal.moves.length,1); assert.equal(h.runtime.goal.moves[0].status,'kept');
  assert.equal(h.runtime.goal.status,'complete','the panel shows Finished');
  assert.ok(h.events.some(e=>e.type==='status' && /finished your request/.test(e.message ?? '')));
  await h.runtime.prompt('Now add a thin dark frame.');
  assert.equal(h.runtime.goal.moves.length,2,'a new message starts the next request');
 } finally {await h.close();}
});

test('the painter can propose a protected area while painting; the proposal reaches the panel and waits',{timeout:30000},async()=>{
 const area={id:'mask-1',name:'Woman and car',state:'pending',by:'agent',bounds:[0,500,400,500]};
 let calls=0, offered=[]; let h;
 h=await harness(req=>{
  if(!req.tools.some(t=>t.function.name==='paint_batch')) { offered.push(req.tools.map(t=>t.function.name)); return {content:'Hello.'}; }
  offered.push(req.tools.map(t=>t.function.name)); calls++;
  if(calls===1) return call('propose_protection',{name:'Woman and car',area:[{shape:'polygon',points:[[0,500],[400,500],[400,1000]]}]});
  return {content:'Marked. Keep it if it looks right.'};
 },async(operation)=>operation==='propose_protection' ? {status:'ok',area,message:'Shown in red. You keep out of it from now on; the artist keeps or discards it.'} : undefined);
 try {
  await h.start('ask','Hello');
  assert.ok(!offered[0].includes('propose_protection'),'not in Ask: there is no painting session');
  await h.runtime.setMode('agent');
  await h.runtime.prompt('Protect the woman and the car.');
  assert.ok(offered.at(-1).includes('propose_protection'),'offered while painting');
  assert.deepEqual(h.calls.filter(c=>c.operation==='propose_protection').map(c=>c.params.name),['Woman and car']);
  assert.deepEqual(h.events.find(e=>e.type==='protection_proposed')?.area,area);
 } finally {await h.close();}
});

test('a protected-area hit reaches the chat right away and the painter; the third one tells it to leave the area alone',{timeout:30000},async()=>{
 let calls=0, results=[]; let h;
 h=await harness(req=>{
  if(!req.tools.some(t=>t.function.name==='paint_batch')) return {content:'Hello.'};
  const last=req.messages.findLast(m=>m.role==='tool'); if(last) results.push(typeof last.content==='string'?last.content:JSON.stringify(last.content));
  calls++;
  if(calls<=3) return call('paint_pass',{...pass,name:'Street '+calls});
  return call('finish_move',{summary:'Street'});
 },async(operation,params,_study,id)=>{
  if(operation!=='paint_pass')return undefined;
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[],
   protected:[{name:'Woman and car',pixels:900,share:0.4}]};
 });
 try {
  await h.start('ask','Hello'); await h.runtime.setMode('agent');
  await h.runtime.prompt('Repaint the street.');
  const hits=h.events.filter(e=>e.type==='protection_hit');
  assert.equal(hits.length,3,'one line per hit, as it happens');
  assert.equal(hits[0].message,"Move 1 reached into 'Woman and car'. I kept it untouched (about 40% of it was in the way).");
  assert.match(results[0],/Woman and car/,'the painter is told in the result');
  assert.doesNotMatch(results[1],/Leave it alone/);
  assert.match(results[2],/You keep painting into 'Woman and car'. Leave it alone./);
 } finally {await h.close();}
});

test('a reference part reaches the painter as a part of its original, with where it sits; a crop of a part names the part',{timeout:30000},async()=>{
 const h=await harness(()=>({content:'Hello.'}));
 try {
  await h.start('ask','Hello');
  const dir=h.runtime.study.directory, original=join(dir,'moscow-source.png'), sky=join(dir,'sky-source.png'), cloud=join(dir,'cloud-source.png');
  for (const file of [original,sky,cloud]) await writeFile(file,png);
  await h.runtime.addReferences([{path:original,name:'New Moscow',role:'reference'},
   {path:sky,name:'Sky (part)',role:'reference',part_of:original,part_kind:'part',bounds:[0,0,1448,362]}]);
  await h.runtime.addReferences([{path:cloud,name:'Cloud (crop)',role:'reference',part_of:sky,part_kind:'crop',bounds:[600,40,200,120]}]);
  const [moscow,part,crop]=h.runtime.study.references;
  assert.deepEqual([part.part_of,part.part_kind,part.bounds],[moscow.id,'part',[0,0,1448,362]]);
  assert.equal(crop.part_of,part.id,'a crop of a part names the part');
  assert.equal(moscow.part_of,undefined);
  const lone=join(dir,'lone-source.png'); await writeFile(lone,png);
  await h.runtime.addReferences([{path:lone,name:'Lone (part)',role:'reference',part_of:join(dir,'removed.png'),part_kind:'part',bounds:[0,0,10,10]}]);
  const orphan=h.runtime.study.references.at(-1);
  assert.deepEqual([orphan.part_of,orphan.part_kind,orphan.bounds],[null,'part',[0,0,10,10]],'a part whose original is gone is still a part');
  const context=h.runtime.context('agent');
  assert.match(context,new RegExp('"id":"'+part.id+'"[^}]*"part_of":"'+moscow.id+'","part_kind":"part","bounds":\\[0,0,1448,362\\]'));
 } finally {await h.close();}
});

test('masses painted with plain strokes get a craft hint in the result; clipped texture strokes do not',{timeout:30000},async()=>{
 const big={name:'Coat mass',preset:'b) Basic-1',strokes:[{start:[50,100],segments:[[200,150,400,500,700,900]],size:40,opacity:1,flow:1,color:'#302018'}]};
 const texture={...big,name:'Coat fur',clip_to:'$1',blend_mode:'overlay',layer_opacity:0.4};
 let calls=0, results=[]; let h;
 h=await harness(req=>{
  if(!req.tools.some(t=>t.function.name==='paint_batch')) return {content:'Hello.'};
  const last=req.messages.findLast(m=>m.role==='tool'); if(last) results.push(typeof last.content==='string'?last.content:JSON.stringify(last.content));
  calls++;
  if(calls===1) return call('paint_pass',big);
  if(calls===2) return call('paint_batch',{summary:'Coat',actions:[{tool:'fill_region',arguments:{name:'Coat',area:[{shape:'rectangle',bounds:[50,100,650,800]}],color:'#302018',clip_base:true}},{tool:'paint_pass',arguments:texture}]});
  return call('finish_move',{summary:'Coat'});
 },async(operation,params,_study,id)=>{
  if(!['paint_pass','fill_region'].includes(operation))return undefined;
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',layer_id:operation+'-'+id,document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('ask','Hello'); await h.runtime.setMode('agent'); await h.runtime.prompt('Paint her coat.');
  assert.match(results[0],/craft_hint/); assert.match(results[0],/Coat mass.*covered about \d+% of the canvas with plain strokes/);
  assert.doesNotMatch(results[1],/craft_hint/,'flats with clipped overlay texture are the intended craft');
  const fur=h.calls.find(c=>c.operation==='paint_pass' && c.params.name==='Coat fur');
  assert.equal(fur.params.blend_mode,'overlay','texture strokes keep their blend mode');
  assert.match(fur.params.clip_to,/^fill_region-/,'"$1" became the flat');
 } finally {await h.close();}
});

test('a run that starts with nothing unresolved clears any leftover inspection button in the panel',{timeout:20000},async()=>{
 let h;
 h=await harness(req=>req.tools.some(t=>t.function.name==='paint_batch') ? call('finish_move',{summary:'x'}) : {content:'Hello.'});
 try {
  await h.start('ask','Hello'); await h.runtime.setMode('agent');
  await h.runtime.prompt('Look first.');
  const clear=h.events.filter(e=>e.type==='uncertain_operations');
  assert.ok(clear.length && clear.every(e=>e.operations.length===0),'an all-clear, never a new warning');
 } finally {await h.close();}
});

test('Keep merges the kept move into one layer before the next move; the setting can turn it off',{timeout:30000},async()=>{
 let painted=0, runs=2; let h;
 h=await harness(req=>{
  if(!req.tools.some(t=>t.function.name==='paint_batch')) return {content:'Hello.'};
  return /HOST MODE/.test(latestUserText(req)) && req.messages.at(-1).role==='user' ? call('paint_pass',{...pass,name:'Towers '+(++painted)}) : call('finish_move',{summary:'Towers'});
 },async(operation,params,_study,id)=>{
  const dir=h.runtime.study.directory;
  if(operation==='merge_passes') { const left=--runs; return {status:'ok',merged_layers:runs>=0?3:0,remaining_runs:Math.max(left,0),passes:[]}; }
  if(operation!=='paint_pass') return undefined;
  await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('ask','Hello'); await h.runtime.setMode('agent');
  await h.runtime.prompt('Paint the Kremlin towers.');
  await h.runtime.moveAction({action:'keep',move:1});
  const merges=h.calls.filter(c=>c.operation==='merge_passes');
  assert.equal(merges.length,2,'merges run by run until none remain');
  assert.ok(merges.every(c=>c.params.stage_id==='move-1' && c.params.name==='Move 1 · Towers'));
  assert.ok(h.calls.indexOf(merges[0])<h.calls.findIndex(c=>c.operation==='paint_pass' && c.params.name==='Towers 2'),'before the next move paints');
  assert.ok(h.events.some(e=>e.type==='action' && /Merged kept passes: 4 fewer layers/.test(e.message)));
  const tidy=h.calls.find(c=>c.operation==='tidy_kept');
  assert.equal(tidy?.params.stage_id,'move-1','Keep also removes the stage\u2019s hidden leftovers');
  assert.ok(h.calls.indexOf(tidy)>h.calls.indexOf(merges.at(-1)) && h.calls.indexOf(tidy)<h.calls.findIndex(c=>c.operation==='paint_pass' && c.params.name==='Towers 2'),'after the merge, before the next move paints');
  await h.runtime.setExecutionSettings({merge_kept:false}); runs=2;
  await h.runtime.moveAction({action:'keep',move:2});
  assert.equal(h.calls.filter(c=>c.operation==='merge_passes').length,2,'Keep every pass leaves the layers alone');
  assert.equal(h.calls.filter(c=>c.operation==='tidy_kept').length,2,'but the hidden leftovers still go: tidying changes nothing the artist sees');
 } finally {await h.close();}
});

test('a Subject move that reaches its limit stops for the artist and says so',{timeout:30000},async()=>{
 let painterCalls=0; let h;
 h=await harness(req=>{
  if(!req.tools.some(t=>t.function.name==='paint_batch')) return {content:'Hello.'};
  painterCalls++; return call('paint_batch',{summary:'More towers',actions:[{tool:'paint_pass',arguments:pass}]});
 },async(operation,params,_study,id)=>{
  if(operation!=='paint_pass')return undefined;
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('ask','Hello'); await h.runtime.setMode('agent');
  await assert.rejects(h.runtime.buildTools().find(t=>t.name==='finish_move').execute('x',{summary:'Nothing yet'}),/no move in progress/);
  await h.runtime.prompt('Paint the whole city.');
  assert.equal(painterCalls,8,'Subject moves stop at 8 painting calls');
  assert.equal(h.runtime.goal.moves[0].limited,true);
  assert.equal(h.runtime.goal.moves[0].title,'Paint the whole city.','an unfinished move is titled with the request');
  assert.match(h.events.filter(e=>e.type==='status').at(-1).message,/reached its size limit/);
 } finally {await h.close();}
});

test('an Agent move made of craft is one card: fill, clipped Multiply layer and a baked filter, and Undo rejects them together',{timeout:30000},async()=>{
 const area=[{shape:'ellipse',bounds:[100,100,300,300]}];
 const move=call('paint_batch',{summary:'Lit sphere',actions:[
  {tool:'fill_region',arguments:{name:'Sphere',area,color:'#3a6ea5',clip_base:true}},
  {tool:'create_layer',arguments:{name:'Shadow',type:'paint',blend_mode:'multiply',clip_to:'$1'}},
  {tool:'apply_filter',arguments:{target:'$2',filter:'gaussian blur',mode:'copy'}}]});
 let h, layer=0;
 h=await harness(req=>req.tools.some(t=>t.function.name==='paint_batch') ? move : {content:'Hello.'},async(operation,_params,_study,id)=>{
  if(!['fill_region','create_layer','apply_filter','review_pass'].includes(operation))return undefined;
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',layer_id:'layer-'+(++layer),document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('ask','Hello'); await h.runtime.setExecutionSettings({move_size:'quick'}); await h.runtime.setMode('agent');
  await h.runtime.prompt('Paint a lit sphere.');
  const craft=h.calls.filter(c=>['fill_region','create_layer','apply_filter'].includes(c.operation));
  assert.deepEqual(craft.map(c=>c.operation),['fill_region','create_layer','apply_filter']);
  assert.ok(craft.every(c=>c.params.stage_id==='move-1'),'every craft result belongs to the move');
  assert.deepEqual([craft[1].params.clip_to,craft[2].params.target],['layer-1','layer-2']);
  const [card]=h.runtime.goal.moves;
  assert.deepEqual([card.number,card.status,card.actions,card.title],[1,'ready',3,'Lit sphere'],'one move card');
  assert.equal(h.runtime.goal.passes,3,'each craft action counts toward the pass allowance');
  assert.equal(h.requests.filter(r=>r.tools.some(t=>t.function.name==='paint_batch')).length,1,'one painter call ran the whole batch');
  await h.runtime.moveAction({action:'undo',move:1});
  const undo=h.calls.find(c=>c.operation==='review_pass');
  assert.deepEqual([undo.params.pass_id,undo.params.action],['stage:move-1','reject']);
 } finally {await h.close();}
});

const comicPanels=['P1','P2','P3','P4'].map((id,i)=>({id,bounds:[40+(i%2)*360,40+Math.floor(i/2)*480,340,460],order:i+1}));
const comicSetting={layout:{preset:'grid-2x2'},panels:comicPanels};
const comicBridge=(h,log)=>async(operation,params,_study,id)=>{
  if(!['comic_page','fill_region','letter','review_pass'].includes(operation))return undefined;
  log.push({operation,params});
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',layer_id:operation+'-'+id,document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[],
    ...(operation==='comic_page'?{comic:{page_id:'page',panels:comicPanels.map(p=>({...p,group_id:'group-'+p.id}))}}:{})};
};

test('Comic is a setting: Ask and Plan never lay out the page; the first Agent move does, outside the move, and Undo keeps it',{timeout:30000},async()=>{
  const log=[]; let h, seen=[];
  h=await harness(req=>{
    const names=req.tools.map(t=>t.function.name); seen.push({names,text:latestUserText(req)});
    if(!names.includes('paint_batch')) return {content:'Here is how a comic page works.'};
    return call('paint_batch',{summary:'Panel 1 sky',actions:[{tool:'fill_region',arguments:{name:'Sky',panel:'P1',area:[{shape:'rectangle',bounds:[40,40,340,200]}],color:'#c9a46a'}},
      {tool:'letter',arguments:{panel:'P1',kind:'caption',text:'The forest recedes.',at:[60,60]}}]});
  },(...args)=>comicBridge(h,log)(...args));
  try {
    await h.start('ask','I want a comic page.');
    assert.ok(!seen.at(-1).names.includes('letter'),'letter is offered only with Comic on');
    await h.runtime.setComic(comicSetting);
    assert.equal(h.events.filter(e=>e.type==='goal').at(-1).goal.comic.panels.length,4,'the panel receives the setting');
    await h.runtime.prompt('How should I pace it?');
    assert.match(seen.at(-1).text,/COMIC PAGE ON/); assert.match(seen.at(-1).text,/"comic":\{"built":false/);
    await h.runtime.setMode('plan'); await h.runtime.prompt('Plan it.');
    assert.equal(log.filter(c=>c.operation==='comic_page').length,0,'Ask and Plan never build the page');
    await h.runtime.setExecutionSettings({move_size:'quick'}); await h.runtime.setMode('agent'); await h.runtime.prompt('Paint panel 1.');
    const page=log.find(c=>c.operation==='comic_page');
    assert.deepEqual([page.params.preset,page.params.stage_id],['grid-2x2','comic-page'],'the host lays out the page, outside the move');
    assert.ok(log.indexOf(page)<log.findIndex(c=>c.operation==='fill_region'),'before the painter paints');
    const fill=log.find(c=>c.operation==='fill_region'); const letter=log.find(c=>c.operation==='letter');
    assert.deepEqual([fill.params.panel,fill.params.stage_id,letter.params.stage_id],['P1','move-1','move-1']);
    assert.ok(seen.at(-1).names.includes('letter'));
    assert.match(seen.at(-1).text,/"comic":\{"built":true/); assert.doesNotMatch(seen.at(-1).text,/group-P1/,'host ids stay out of the context');
    assert.equal(h.runtime.goal.comic.built,true);
    await h.runtime.moveAction({action:'undo',move:1});
    assert.equal(log.find(c=>c.operation==='review_pass').params.pass_id,'stage:move-1','Undo rejects the move, not the page');
    await assert.rejects(h.runtime.setComic(null),/already laid out/);
  } finally {await h.close();}
});

test('with Comic on a plan must tell every panel and paint every panel',{timeout:20000},async()=>{
  const story={logline:'Seeker leads the troop to the kill.',panels:comicPanels.map(p=>({panel:p.id,beat:'Beat '+p.id,shot:'wide',characters:['Seeker']}))};
  let attempt=0;
  const h=await harness(req=>{
    const names=req.tools.map(t=>t.function.name);
    if(!names.includes('propose_plan')) return {content:'ok'};
    if(req.messages.at(-1).role==='tool') return {content:'Revised.'};
    attempt++;
    return call('propose_plan',attempt===1?brief:{...brief,story,steps:[{title:'Panels',done_when:'All four painted.',panels:['P1','P2','P3','P4']},{title:'Lettering',done_when:'Captions lettered.'}]});
  });
  try {
    await h.start('ask','Hi'); await h.runtime.setComic(comicSetting); await h.runtime.setMode('plan');
    await h.runtime.prompt('Plan the page.');
    assert.equal(h.runtime.goal.brief,null,'a plan without a story is refused');
    const refusal=h.requests.at(-1).messages.findLast(m=>m.role==='tool');
    assert.match(String(refusal.content),/needs a story/);
    await h.runtime.prompt('Try again with the story.');
    assert.equal(h.runtime.goal.brief.story.panels.length,4);
    await assert.rejects(h.runtime.editPlan({...h.runtime.goal.brief,story:{...story,panels:story.panels.slice(0,3)}}),/P4 has no beat/);
  } finally {await h.close();}
});

test('Autopilot with Comic on lays out the page before the first painting turn and reviews it as a comic',{timeout:30000},async()=>{
  const story={logline:'The troop reaches the kill.',panels:comicPanels.map(p=>({panel:p.id,beat:'Beat '+p.id,shot:'medium',characters:['Seeker']}))};
  const plan={...brief,story,steps:[{title:'Panels',done_when:'Painted.',panels:['P1','P2','P3','P4']},{title:'Lettering',done_when:'Lettered.'}]};
  const log=[]; let h, painted=0, reviewText='';
  h=await harness(req=>{
    const names=req.tools.map(t=>t.function.name);
    if(names.includes('propose_plan')) return call('propose_plan',plan);
    if(names.includes('submit_review')) {
      reviewText=latestUserText(req);
      const data=JSON.parse(reviewText.slice(reviewText.indexOf('{')));
      return call('submit_review',{verdict:'complete',summary:'Finished.',issues:[],checks:data.checks.map(c=>({id:c.id,met:true,evidence:'Visible.'}))});
    }
    if(!painted++) return call('fill_region',{name:'Plain',panel:'P1',area:[{shape:'rectangle',bounds:[40,40,340,460]}],color:'#b08850'});
    return call('request_review',{reason:'Every panel is painted and lettered.'});
  },(...args)=>comicBridge(h,log)(...args));
  try {
    await h.start('plan'); await h.runtime.setComic(comicSetting); await h.runtime.prompt('Plan the page.');
    await h.runtime.setMode('autopilot'); await h.runtime.prompt('',{start_plan:true});
    assert.deepEqual(log.slice(0,2).map(c=>c.operation),['comic_page','fill_region'],'the page comes first');
    assert.equal(log.filter(c=>c.operation==='comic_page').length,1,'laid out once');
    assert.equal(h.runtime.goal.status,'complete');
    assert.match(reviewText,/This is a comic page/); assert.match(reviewText,/"panels":\[\{"id":"P1"/);
  } finally {await h.close();}
});

test('a chat saved in the former self-driving Agent mode reopens in Autopilot',{timeout:20000},async()=>{
 const h=await harness(()=>({content:'Hello.'}));
 try {
  await h.start('ask','Old chat'); const id=h.runtime.study.id;
  h.runtime.goal.mode='agent'; delete h.runtime.goal.modes_version; await h.runtime.persist(); await h.runtime.end();
  await h.runtime.resume(id);
  assert.equal(h.runtime.mode,'autopilot'); assert.equal(h.runtime.goal.modes_version,2);
 } finally {await h.close();}
});

test('Autopilot pauses for a blocking question mid-run and the answer resumes painting directly', {timeout:30000}, async()=>{
 let asks=0, painted=0, planningAfterStart=0, started=false;
 const h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('submit_review')) return call('submit_review',{verdict:'complete',summary:'Done.',issues:[],checks:[0,1,2].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  if(names.includes('propose_plan')) { if(started) planningAfterStart++; return call('propose_plan',brief); }
  started=true;
  const last=req.messages.at(-1), result=last?.role==='tool' ? JSON.stringify(last.content):'';
  if(/Question displayed/.test(result)) return {content:'Waiting for the artist.'};
  if(/already asked the artist/.test(result) || painted>=3) return painted>=4 ? call('request_review',{reason:'Painting ready.'}) : (painted++, call('paint_pass',{...pass,name:'Pass '+painted}));
  if(painted===asks) { asks++; return call('ask_question',{question:'Question '+asks+': which reading did you mean?',options:['First','Second']}); }
  painted++; return call('paint_pass',{...pass,name:'Pass '+painted});
 });
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.setExecutionSettings({routing:'off'});
  await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.goal.status,'needs_input'); assert.equal(h.runtime.goal.question.asked_in,'agent');
  assert.equal(h.runtime.busy,false,'the run waits for the artist');
  await h.runtime.prompt('First');
  assert.equal(h.runtime.goal.status,'needs_input','painting resumed, then the second question paused it');
  assert.ok(h.runtime.goal.user_updates.includes('Answer to Question 1: which reading did you mean?: First'));
  await h.runtime.prompt('Second');
  assert.equal(asks,3,'a third question was attempted'); assert.equal(h.runtime.goal.question,null,'and refused: the painter decided');
  assert.equal(h.runtime.goal.status,'complete');
  assert.equal(planningAfterStart,0,'answers go straight back to painting, without a planning turn');
 } finally {await h.close();}
});

test('a steering message during an Autopilot run continues it; discussing a finished painting does not repaint it', {timeout:30000}, async()=>{
 let painted=0, steered=false, release;
 const gate=new Promise(r=>release=r);
 const h=await harness(async req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('submit_review')) return call('submit_review',{verdict:'complete',summary:'Done.',issues:[],checks:[0,1,2].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  if(names.includes('start_painting')) return {content:'Noted.'};
  if(names.includes('propose_plan')) return call('propose_plan',brief);
  if(!painted){painted++; await gate; return call('paint_pass',{...pass,name:'Pass 1'});}
  if(h.runtime.goal.user_updates.includes('Make the sky warmer.')) steered=true;
  return painted++<2 ? call('paint_pass',{...pass,name:'Pass '+painted}) : call('request_review',{reason:'Painting ready.'});
 });
 try {
  await h.start('plan');await h.runtime.setMode('autopilot');await h.runtime.setExecutionSettings({routing:'off'});
  const run=h.runtime.prompt('',{start_plan:true});
  while(!painted) await new Promise(r=>setTimeout(r,5));
  const steer=h.runtime.prompt('Make the sky warmer.');
  release(); await run; await steer;
  assert.ok(steered,'the painter received the steering message'); assert.equal(h.runtime.goal.status,'complete','and finished the run');
  const passes=h.runtime.goal.passes, requests=h.requests.length;
  await h.runtime.prompt('What did you change in the sky?');
  assert.equal(h.runtime.goal.passes,passes,'discussing a finished painting does not paint');
  assert.ok(!h.requests.slice(requests).some(r=>r.tools.some(t=>t.function.name==='paint_pass')),'nor enables the painting tools');
 } finally {await h.close();}
});

test('pacing close-up: an actual-pixel crop of where the call painted, only of the canvas just observed', async () => {
  const directory=await mkdtemp(join(tmpdir(),'close-up-'));
  try {
    await writeFile(join(directory,'crop.png'),png);
    const calls=[]; let revision='r1';
    const host={guidesView:true,study:{directory,id:'study'},callPasses:()=>[],bridge:{call:async(op,params)=>{calls.push({op,params});return {revision,image_path:join(directory,'crop.png')};}}};
    const closeUp=(call,details)=>StudioRuntime.prototype.paceCloseUp.call(host,call,{details});
    const details={width:6000,height:4500,revision:'r1',document_id:'doc'};
    const surface={tool:'paint_reference_surface',args:{target:[600,60,5000,1740]}};
    const found=await closeUp(surface,details);
    assert.deepEqual(found.region,[2316,146,1568,1568]);
    assert.equal(found.content.type,'image');
    assert.deepEqual(calls[0],{op:'peek',params:{output_dir:directory,region:[2316,146,1568,1568],refresh:false,guides:false,document_id:'doc'}},'Luna\u2019s close-up leaves the guide lines out');
    host.guidesView=false; await closeUp(surface,details);
    assert.ok(!('guides' in calls.at(-1).params),'an older plugin is never sent the flag');
    revision='r2';
    assert.equal(await closeUp(surface,details),null,'a crop of another revision is dropped');
    assert.equal(await closeUp(surface,{...details,width:768,height:1024}),null,'a small canvas is already seen at actual pixels');
    assert.equal(await closeUp({tool:'observe_canvas',args:{}},details),null,'nothing says where it painted');
    host.bridge.call=async()=>{throw new Error('Krita went away');};
    assert.equal(await closeUp(surface,{...details,revision:'r2'}),null,'a failed crop never stops pacing');
  } finally { await rm(directory,{recursive:true,force:true}); }
});

test('a chat\'s AI image allowance starts from Settings, survives an older saved chat, and is validated', {timeout:20000}, async()=>{
  const h=await harness(()=>({content:'Noted.'}));
  try {
    assert.deepEqual(freshGoal('ask').limits,{minutes:0,passes:0,ai_images:0});
    await h.start('ask','Hello');
    assert.equal(h.runtime.goal.limits.ai_images,0,'a new install starts with no AI images');
    assert.equal(h.runtime.goal.ai_images_used,0);
    await h.runtime.setLimits({minutes:5,passes:3,ai_images:2});
    assert.deepEqual(h.runtime.goal.limits,{minutes:5,passes:3,ai_images:2});
    await h.runtime.setLimits({minutes:5,passes:4});
    assert.equal(h.runtime.goal.limits.ai_images,2,'leaving ai_images out keeps the chat\'s allowance');
    await h.runtime.setLimits({minutes:0,passes:0,ai_images:null});
    await h.runtime.setLimits({minutes:0,passes:0});
    assert.equal(h.runtime.goal.limits.ai_images,null,'no limit survives a change to the other allowances');
    for (const bad of [-1,21,1.5,'3']) await assert.rejects(h.runtime.setLimits({minutes:0,passes:0,ai_images:bad}),/AI images/);
    // A chat saved before allowances existed takes the Settings default when it is restored.
    delete h.runtime.goal.limits.ai_images; await h.runtime.persist();
    const id=h.runtime.study.id; await h.runtime.end();
    await h.runtime.setExecutionSettings({ai_images:'unlimited'});
    await h.runtime.resume(id);
    assert.equal(h.runtime.goal.limits.ai_images,null,'Settings "No limit" becomes no limit');
    await h.runtime.end();
    await h.runtime.setExecutionSettings({ai_images:3});
    await h.start('ask','A new chat');
    assert.equal(h.runtime.goal.limits.ai_images,3,'a new chat takes the current default');
  } finally { await h.close(); }
});

// Luna move review (extensions/luna-review.ts through studio.reviewHost): each batch of an Agent move.
async function lunaMove({batches=1, flagged=()=>false, areas=[{id:'a1',name:'Moon',state:'pending',by:'agent'}]}={}) {
 let painterCalls=0;
 let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(!names.includes('paint_batch')) return {content:'Hello.'};
  painterCalls++;
  if(painterCalls<=batches) return call('paint_batch',{summary:'Clouds '+painterCalls,actions:[{tool:'paint_pass',arguments:{...pass,name:'Clouds '+painterCalls}}]});
  return call('finish_move',{summary:'Clouds finished'});
 },async(operation,params,_study,id)=>{
  const dir=h.runtime.study.directory;
  if(operation==='protection_list') return {status:'ok',areas};
  if(!['paint_pass','review_pass'].includes(operation))return undefined;
  await writeFile(join(dir,'before.png'),png); await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,
   passes:operation==='paint_pass' ? [{id,kind:'paint',title:'Clouds',layer_id:'layer-'+id,before_path:join(dir,'before.png'),after_path:join(dir,'view.png')}] : [],
   ...(operation==='review_pass' ? {affected_pass_ids:[params.pass_id]} : {})};
 });
 let detect=0;
 const luna=fakeLuna(({purpose,questions})=>{
  if(purpose==='locate-move-failures') return {answers:Object.fromEntries(Object.keys(questions).map(k=>[k,{type:'choice',choice:'top_right'}]))};
  if(purpose!=='detect-move-failures') return {fallback:'service_or_response_error'};
  const bad=flagged(++detect);
  return {answers:Object.fromEntries(Object.keys(questions).map(k=>[k,{type:'noul',noul:k==='established' ? .95 : bad && k==='feature_0' ? .9 : .05}]))};
 });
 await h.start('ask','Hello'); h.runtime.lunaClient=luna;
 await h.runtime.setExecutionSettings({routing:'guide'}); await h.runtime.setMode('agent');
 return {h,luna};
}

test('an Agent batch that covers the moon is undone and the move carries the verdict',{timeout:30000},async()=>{
 const {h,luna}=await lunaMove({flagged:n=>n===1});
 try {
  await h.runtime.prompt('Finish the clouds.');
  const rejects=h.calls.filter(c=>c.operation==='review_pass');
  assert.equal(rejects.length,1); assert.equal(rejects[0].params.action,'reject'); assert.match(rejects[0].params.pass_id,/-0$/);
  const detect=luna.requests.find(r=>r.purpose==='detect-move-failures');
  assert.match(detect.questions.feature_0.instructions,/Is the Moon that BEFORE shows/);
  const [move]=h.runtime.goal.moves;
  assert.equal(move.review.verdict,'undone'); assert.equal(move.review.undone_batches,1); assert.equal(move.review.batches,1);
  assert.match(move.review_line,/Luna undid 1 of 1 batch.*Moon covered/);
  assert.ok(JSON.stringify(h.requests).includes('Luna undid this batch: Moon covered (top_right)'),'the painter is told');
 } finally {await h.close();}
});

test('an Agent move does not also run the per-pass check',{timeout:30000},async()=>{
 const {h,luna}=await lunaMove();
 try {
  await h.runtime.prompt('Finish the clouds.');
  assert.equal(luna.requests.filter(r=>r.purpose==='detect-pass-failures').length,0);
  assert.equal(luna.requests.filter(r=>r.purpose==='detect-move-failures').length,1);
  const [move]=h.runtime.goal.moves;
  assert.equal(move.review.verdict,'kept'); assert.equal(move.review_line,'Luna: no regressions in 1 batch');
 } finally {await h.close();}
});

test('a move Luna stops tells the artist why',{timeout:30000},async()=>{
 const {h}=await lunaMove({batches:4,flagged:()=>true});
 try {
  await h.runtime.prompt('Finish the clouds.');
  assert.equal(h.calls.filter(c=>c.operation==='review_pass').length,2,'two undos, then the third is reported');
  const [move]=h.runtime.goal.moves;
  assert.equal(move.review.verdict,'undone'); assert.match(move.luna_stopped,/Luna undid 2 batches/);
  assert.equal(move.calls,3,'the move ends after the batch Luna stopped');
  assert.ok(h.events.some(e=>e.type==='status' && /Luna undid 2 batches/.test(e.message ?? '')));
 } finally {await h.close();}
});

test('Luna checks kept and proposed areas by name, not locked layers or removed areas',{timeout:30000},async()=>{
 const {h}=await lunaMove({areas:[{id:'a',name:'Moon',state:'active'},{id:'b',name:'Rim',state:'pending'},{id:'locked-layers',name:'Locked layers',state:'active'},{id:'c',name:'Old',state:'removed'}]});
 try {
  assert.deepEqual(await h.runtime.reviewHost().features(),['Moon','Rim']);
 } finally {await h.close();}
});

test('a late verdict from another chat is dropped, not written into this chat’s move',{timeout:30000},async()=>{
 const {h}=await lunaMove();
 try {
  await h.runtime.prompt('Finish the clouds.');
  const [move]=h.runtime.goal.moves, before=JSON.stringify(move.review);
  const host=h.runtime.reviewHost();
  assert.equal(host.scope(),h.runtime.study);
  host.record({move:1,call_id:'late',status:'warned',findings:[{type:'covered_feature',label:'Moon covered'}],scope:{id:'another chat'}});
  assert.equal(JSON.stringify(h.runtime.goal.moves[0].review),before);
 } finally {await h.close();}
});

test('after Luna stops a move, a later painting call in the same message is refused',{timeout:30000},async()=>{
 let painterCalls=0, h;
 const tc=(i,name,args)=>({index:i,id:'call-'+Math.random().toString(36).slice(2),type:'function',function:{name,arguments:JSON.stringify(args)}});
 const batch=n=>({tool:'paint_batch',args:{summary:'Clouds '+n,actions:[{tool:'paint_pass',arguments:{...pass,name:'Clouds '+n}}]}});
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(!names.includes('paint_batch')) return {content:'Hello.'};
  painterCalls++;
  if(painterCalls<=2) return call('paint_batch',batch(painterCalls).args);
  if(painterCalls===3) return {tool_calls:[tc(0,'paint_batch',batch(3).args),tc(1,'paint_batch',batch(4).args)]};
  return call('finish_move',{summary:'Clouds finished'});
 },async(operation,params,_study,id)=>{
  const dir=h.runtime.study.directory;
  if(operation==='protection_list') return {status:'ok',areas:[{id:'a',name:'Moon',state:'pending'}]};
  if(!['paint_pass','review_pass'].includes(operation))return undefined;
  await writeFile(join(dir,'before.png'),png); await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,
   passes:operation==='paint_pass' ? [{id,kind:'paint',title:'Clouds',layer_id:'layer-'+id,before_path:join(dir,'before.png'),after_path:join(dir,'view.png')}] : [],
   ...(operation==='review_pass' ? {affected_pass_ids:[params.pass_id]} : {})};
 });
 try {
  await h.start('ask','Hello');
  h.runtime.lunaClient=fakeLuna(({purpose,questions})=>purpose==='detect-move-failures'
   ? {answers:Object.fromEntries(Object.keys(questions).map(k=>[k,{type:'noul',noul:k==='established' ? .95 : k==='feature_0' ? .9 : .05}]))}
   : {answers:Object.fromEntries(Object.keys(questions).map(k=>[k,{type:'choice',choice:'top_right'}]))});
  await h.runtime.setExecutionSettings({routing:'guide'}); await h.runtime.setMode('agent');
  await h.runtime.prompt('Finish the clouds.');
  assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,3,'the fourth batch, after the stop, never painted');
  assert.match(h.runtime.goal.moves[0].luna_stopped,/Luna undid 2 batches/);
 } finally {await h.close();}
});

test('a batch that painted and then stopped on a failed action is still reviewed, recipe chunks included',{timeout:30000},async()=>{
 let painterCalls=0, h, passes=[];
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(!names.includes('paint_batch')) return {content:'Hello.'};
  painterCalls++;
  if(painterCalls===1) return call('paint_batch',{summary:'Clouds',actions:[{tool:'paint_pass',arguments:{...pass,name:'Clouds'}},{tool:'paint_pass',arguments:{...pass,name:'Fails'}}]});
  return call('finish_move',{summary:'Clouds finished'});
 },async(operation,params,_study,id)=>{
  const dir=h.runtime.study.directory;
  if(operation==='protection_list') return {status:'ok',areas:[]};
  if(operation==='list_passes') return {status:'ok',passes};                    // as the plugin answers: the chat's passes so far
  if(operation!=='paint_pass')return undefined;
  if(params.name==='Fails') throw new Error('Action 2: target "$3" must name an earlier action in this batch that created a layer.');
  await writeFile(join(dir,'before.png'),png); await writeFile(join(dir,'view.png'),png);
  passes=[...passes,{id:'recipe-abc-0',kind:'paint_pass',title:'Clouds',layer_id:'layer-1',before_path:join(dir,'before.png'),after_path:join(dir,'view.png')}];
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes};
 });
 try {
  await h.start('ask','Hello');
  const luna=fakeLuna(({purpose,questions})=>purpose==='detect-move-failures'
   ? {answers:Object.fromEntries(Object.keys(questions).map(k=>[k,{type:'noul',noul:k==='established' ? .95 : .05}]))} : {fallback:'service_or_response_error'});
  h.runtime.lunaClient=luna;
  await h.runtime.setExecutionSettings({routing:'guide'}); await h.runtime.setMode('agent');
  await h.runtime.prompt('Finish the clouds.');
  assert.equal(luna.requests.filter(r=>r.purpose==='detect-move-failures').length,1,'the stopped batch was reviewed');
  assert.equal(h.runtime.goal.moves[0].review.batches,1);
 } finally {await h.close();}
});

test('the artist hears once per chat what makes the painting heavy, with the fixes; the painting is not changed',{timeout:30000},async()=>{
 const weight={level:'too_heavy',reasons:['10 live filter masks (wavelet noise reducer) recompute on every refresh','147 groups each cache a projection (about 15876 MB)'],fixes:['bake_filters','merge_kept']};
 const h=await harness(()=>({content:'Hello.'}),async(operation)=>operation==='peek' ? undefined : undefined);
 try {
  await h.start('ask','Hello');
  h.runtime.noteWeight({weight}); h.runtime.noteWeight({weight});
  const notes=h.events.filter(e=>e.type==='action' && /heavy for Krita/.test(e.message ?? ''));
  assert.equal(notes.length,1,'once per chat');
  assert.match(notes[0].message,/wavelet noise reducer/);
  assert.match(notes[0].message,/bake the filter masks/); assert.match(notes[0].message,/merge kept moves/);
  h.runtime.noteWeight({weight:{level:'ok',reasons:[],fixes:[]}});
  assert.equal(h.events.filter(e=>e.type==='action' && /heavy for Krita/.test(e.message ?? '')).length,1);
 } finally {await h.close();}
});

test('an Agent move never adds a live filter mask or filter layer: they recompute on every refresh, so the filter is baked with mode copy',async()=>{
 const h=await harness(()=>({content:'Hello.'}),async()=>undefined);
 try {
  await h.start('ask','Hello'); await h.runtime.setMode('agent');
  for (const params of [{target:'l',filter:'blur'},{target:'l',filter:'blur',mode:'mask'},{target:'l',filter:'blur',mode:'layer'}])
   await assert.rejects(h.runtime.callNative('apply_filter',params),/no live filter masks or filter layers.*mode copy/);
  await assert.rejects(h.runtime.callNative('apply_filter',{target:'l',filter:'blur',mode:'copy'}),e=>!/filter mask/.test(e.message),'copy is the way to filter');
  await h.runtime.setMode('autopilot');
  await assert.rejects(h.runtime.callNative('apply_filter',{target:'l',filter:'blur'}),e=>!/filter mask/.test(e.message),'other modes keep masks');
 } finally {await h.close();}
});

test('a stamp in an Agent move is one paced painting call: revision and move stage sent, Luna reviews its pass, the tips sheet shown',{timeout:30000},async()=>{
 let painterCalls=0, h, sheetSeen=false;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(!names.includes('paint_batch')) return {content:'Hello.'};
  assert.ok(names.includes('make_material') && names.includes('stamp_material'),'offered in an Agent move');
  sheetSeen ||= JSON.stringify(req.messages).includes('image');
  painterCalls++;
  if(painterCalls===1) return call('make_material',{name:'Clouds',source:{area:[{shape:'rectangle',bounds:[0,0,768,300]}]}});
  if(painterCalls===2) return call('stamp_material',{name:'Cloud volume',material:'Clouds',area:[{seed:[10,10]}],count:50,size:[100,300]});
  return call('finish_move',{summary:'Clouds stamped'});
 },async(operation,params,_study,id)=>{
  const dir=h.runtime.study.directory;
  if(operation==='protection_list') return {status:'ok',areas:[]};
  if(operation==='make_material') { await writeFile(join(dir,'sheet.png'),png);
   return {status:'ok',material:params.name,kind:'light',tips:6,size:200,sheet_path:join(dir,'sheet.png')}; }
  if(!['stamp','review_pass'].includes(operation))return undefined;
  await writeFile(join(dir,'before.png'),png); await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,
   dabs_placed:params.dabs?.length,passes:operation==='stamp' ? [{id,kind:'stamp',title:'Cloud volume',layer_id:'layer-'+id,before_path:join(dir,'before.png'),after_path:join(dir,'view.png')}] : []};
 });
 try {
  await h.start('ask','Hello');
  let reviewed=0;
  h.runtime.lunaClient=fakeLuna(({purpose,questions})=>{ if(purpose==='detect-move-failures') reviewed++;
   return purpose==='detect-move-failures' ? {answers:Object.fromEntries(Object.keys(questions).map(k=>[k,{type:'noul',noul:k==='established' ? .95 : .05}]))} : {fallback:'service_or_response_error'}; });
  await h.runtime.setExecutionSettings({routing:'guide'}); await h.runtime.setMode('agent');
  await h.runtime.prompt('Give the clouds volume.');
  const stamp=h.calls.find(c=>c.operation==='stamp');
  assert.ok(stamp,'the stamp reached Krita');
  assert.equal(stamp.params.stage_id,'move-1'); assert.ok(stamp.params.expected_revision);
  assert.equal(stamp.params.dabs.length,50);
  assert.equal(reviewed,1,'Luna reviewed the stamp’s batch');
  assert.ok(sheetSeen,'the painter saw the tips sheet');
  assert.equal(h.runtime.goal.moves[0].actions,1,'one painting action: make_material is not one');
 } finally {await h.close();}
});

test('the painting is saved during the model’s turn, after Luna review has settled each batch',async()=>{
 const h=await harness(()=>({content:'Hello.'}),async()=>undefined);
 try {
  await h.start('ask','Hello');
  const names=h.runtime.extensionFactories().map(e=>e.name);
  assert.ok(names.includes('save-timing'));
  assert.ok(names.indexOf('save-timing')>names.indexOf('luna-review'),'it sees the batch after any undo');
  let flushed=0; h.runtime.flushCheckpoint=async()=>{flushed++;};
  await h.runtime.saveHost().checkpoint();
  assert.equal(flushed,1,'the studio’s own checkpoint, as at review and run end');
  assert.equal(h.runtime.saveHost().painting('paint_batch'),true);
 } finally {await h.close();}
});

// Guided trace (project-folder A3): Luna and the reviewer judge the painting without the agent's guide lines; the painter
// sees them. The plugin's looks carry unguided_path (the view without guides) while guides show, and observe
// {guides:false} is the painting without them (test_guide_craft.py). Three distinct images tell them apart here.
// A valid 1x1 grey PNG of the given value (Pi decodes the images of a prompt, so they must be real images).
function greyPng(value) {
 const chunk=(type,data)=>{const length=Buffer.alloc(4);length.writeUInt32BE(data.length);const body=Buffer.concat([Buffer.from(type),data]);
  const crc=Buffer.alloc(4);crc.writeUInt32BE(crc32(body));return Buffer.concat([length,body,crc]);};
 return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',Buffer.from([0,0,0,1,0,0,0,1,8,0,0,0,0])),
  chunk('IDAT',deflateSync(Buffer.from([0,value]))),chunk('IEND',Buffer.alloc(0))]);
}
const guidesPng=greyPng(80);      // the painting with its guide lines showing
const cleanPng=greyPng(160);      // the same painting without them
const lunaImages=luna=>luna.requests.flatMap(r=>(r.parts ?? []).filter(p=>typeof p==='object')).map(p=>p.data);
async function guideViews(h,operation,params,id,extra={}) {
 const dir=h.runtime.study.directory;
 await writeFile(join(dir,'guides.png'),guidesPng); await writeFile(join(dir,'clean.png'),cleanPng);
 const hidden=operation==='observe' && params.guides===false;
 return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,layers:[],revision:'r-1',content_id:'c-'+id,
  image_path:join(dir,hidden ? 'clean.png' : 'guides.png'),...(hidden ? {guides_hidden:true} : {unguided_path:join(dir,'clean.png')}),...extra};
}

test('review and pass checks observe without guides',{timeout:30000},async()=>{
 let painted=false; let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan')) return call('propose_plan',brief);
  if(names.includes('submit_review')) return call('submit_review',{verdict:'complete',summary:'Done.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  if(!painted){painted=true;return call('paint_pass',pass);}
  return call('request_review',{reason:'Finished.'});
 },async(operation,params,_study,id)=>{
  if(!['observe','paint_pass'].includes(operation)) return undefined;
  const dir=h.runtime.study.directory;
  return guideViews(h,operation,params,id,operation==='paint_pass' ? {passes:[{id,kind:'paint_pass',title:'Figure silhouettes',layer_id:'L1',before_path:join(dir,'clean.png'),after_path:join(dir,'clean.png')}]} : {});
 });
 try {
  await h.start('plan'); h.runtime.guidesView=true;
  const luna=fakeLuna(); h.runtime.lunaClient=luna;
  await h.runtime.setExecutionSettings({routing:'guide'});
  await h.runtime.setMode('autopilot'); await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.goal.status,'complete');
  assert.ok(h.calls.some(c=>c.operation==='observe' && c.params.guides===false),'the final review looks without guides');
  const views=h.calls.filter(c=>c.operation==='view_options');
  assert.ok(views.length && views.at(-1).params.unguided_views===true,'with Luna on, every look also saves the view without guides');
  const hide=h.calls.findIndex(c=>c.operation==='hide_guides'), review=h.calls.findLastIndex(c=>c.operation==='observe' && c.params.guides===false);
  assert.ok(hide>review,'a completed run hides every guide: none reaches the finished painting');
  assert.ok(h.calls.findIndex(c=>c.operation==='merge_passes')<0 || hide<h.calls.findIndex(c=>c.operation==='merge_passes'),'before the kept work is merged');
  assert.ok(h.calls.filter(c=>c.operation==='observe').every(c=>c.params.guides===false || !('guides' in c.params)));
  const reviewer=JSON.stringify(h.requests.find(req=>req.tools.some(t=>t.function.name==='submit_review')));
  assert.ok(reviewer.includes(cleanPng.toString('base64')) && !reviewer.includes(guidesPng.toString('base64')),'the reviewer sees the painting without guides');
  assert.ok(lunaImages(luna).includes(cleanPng.toString('base64')),'Luna paced the run on the painting');
  assert.ok(!lunaImages(luna).includes(guidesPng.toString('base64')),'Luna never sees a guide');
 } finally {await h.close();}
});

test('the painter’s own observe still shows guides; a move with a guide: Keep merges the paint and leaves the guide',{timeout:30000},async()=>{
 let turn=0; let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(!names.includes('paint_batch')) return {content:'Hello.'};
  assert.ok(names.includes('draw_guide') && names.includes('finish_guide'),'offered in an Agent move');
  turn++;
  if(turn===1) return call('observe_canvas',{});
  if(turn===2) return call('draw_guide',{element:'Towers',lines:[{points:[[100,500],[100,200],[160,200],[160,500]]}]});
  if(turn===3) return call('paint_batch',{summary:'Towers',actions:[{tool:'paint_pass',arguments:{...pass,name:'Towers'}}]});
  if(turn===4) return call('finish_guide',{element:'Towers'});
  return call('finish_move',{summary:'Towers'});
 },async(operation,params,_study,id)=>{
  if(operation==='protection_list') return {status:'ok',areas:[]};
  if(operation==='merge_passes') return {status:'ok',merged_layers:0,remaining_runs:0,passes:[]};
  if(!['observe','paint_pass','draw_guide','finish_guide'].includes(operation)) return undefined;
  const dir=h.runtime.study.directory, entry=kind=>({id,kind,title:'Towers',layer_id:kind==='guide' ? 'guide-layer' : 'L-'+id,before_path:join(dir,'clean.png'),after_path:join(dir,'clean.png')});
  return guideViews(h,operation,params,id,{revision:'r-'+id,...(operation==='draw_guide' ? {layer_id:'guide-layer',passes:[entry('guide')]} : operation==='paint_pass' ? {passes:[entry('paint_pass')]} : {})});
 });
 try {
  await h.start('ask','Hello'); h.runtime.guidesView=true; h.runtime.forkTools=true;
  const luna=fakeLuna(); h.runtime.lunaClient=luna;
  await h.runtime.setExecutionSettings({routing:'guide'}); await h.runtime.setMode('agent');
  await h.runtime.prompt('Paint the Kremlin towers.');
  const observes=h.calls.filter(c=>c.operation==='observe');
  assert.ok(observes.length>=2 && observes.every(c=>!('guides' in c.params)),'the painter (and the move start) look with the guides showing');
  const guide=h.calls.find(c=>c.operation==='draw_guide');
  assert.equal(guide.params.stage_id,'move-1','the guide belongs to the move: Undo of the move rejects it');
  assert.ok(guide.params.expected_revision);
  assert.deepEqual(guide.params.strokes[0].start,[100,500]);
  assert.ok(h.calls.some(c=>c.operation==='finish_guide' && c.params.element==='Towers'));
  assert.equal(luna.requests.filter(r=>r.purpose==='detect-move-failures').length,1,'the guide is not reviewed as a painted batch');
  assert.ok(lunaImages(luna).length && !lunaImages(luna).includes(guidesPng.toString('base64')),'Luna judges the move without its guide');
  const painter=JSON.stringify(h.requests.at(-1));
  assert.ok(painter.includes(guidesPng.toString('base64')),'the painter sees its guide');
  assert.ok(!painter.includes('unguided_path'),'host bookkeeping stays out of the painter’s results');
  await h.runtime.moveAction({action:'keep',move:1});
  const merges=h.calls.filter(c=>c.operation==='merge_passes');
  assert.ok(merges.length && merges.every(c=>Object.keys(c.params).sort().join()==='name,stage_id' && !JSON.stringify(c.params).includes('guide-layer')),
   'Keep merges the move’s stroke passes by stage; the plugin never takes the guide (test_guide_craft.py)');
  assert.ok(!h.calls.some(c=>c.operation==='review_pass'),'Keep hides nothing');
 } finally {await h.close();}
});

test('ending a chat hides its guides first; finish_guide waits like any painting call',{timeout:30000},async()=>{
 const h=await harness(()=>({content:'Hello.'}));
 try {
  await h.start('ask','Hello'); h.runtime.guidesView=true;
  await assert.rejects(h.runtime.callNative('finish_guide',{element:'Towers'}),/Painting is disabled/,'not in Ask, Plan or a paused run');
  assert.ok(!h.calls.some(c=>c.operation==='finish_guide'));
  await h.runtime.setMode('agent'); h.runtime.executionPhase='agent'; h.runtime.goal.status='active';
  await h.runtime.bindCanvas();
  h.runtime.goal.question={question:'Which?'};
  await assert.rejects(h.runtime.callNative('finish_guide',{element:'Towers'}),/Painting is disabled/,'not while a question waits');
  await h.runtime.end();
  const hide=h.calls.findIndex(c=>c.operation==='hide_guides'), end=h.calls.findIndex(c=>c.operation==='end');
  assert.ok(hide>=0 && hide<end,'no guide is left showing when the chat ends');
 } finally {await h.close();}
});

test('an older plugin without views without guides: the review still runs, and says guides may show',{timeout:30000},async()=>{
 let painted=false; let h; let refuse=false;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan')) return call('propose_plan',brief);
  if(names.includes('submit_review')) return call('submit_review',{verdict:'complete',summary:'Done.',issues:[],checks:[0,1,2,3].map(i=>({id:'check-'+i,met:true,evidence:'Visible.'}))});
  if(!painted){painted=true;return call('paint_pass',pass);}
  return call('request_review',{reason:'Finished.'});
 },async(operation,params)=>{
  if(['observe','peek'].includes(operation) && 'guides' in params && refuse) { const error=new Error('ValueError: Unknown parameters: guides'); error.code='validation_rejected'; throw error; }
  if(['hide_guides','view_options'].includes(operation) && !h.runtime.guidesView) throw new Error('Unsupported creative operation');
  return undefined;
 });
 try {
  const diagnostics=[];
  await h.start('plan'); h.runtime.diagnostics={record:event=>diagnostics.push(event)};
  await h.runtime.setMode('autopilot'); await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.goal.status,'complete','an older plugin is never asked for guides: false');
  assert.ok(!h.calls.some(c=>'guides' in (c.params ?? {})));
  assert.ok(!h.calls.some(c=>['hide_guides','view_options'].includes(c.operation)));
  // A plugin that said it could, then refused: the review looks again without the flag and says so.
  h.runtime.guidesView=true; refuse=true;
  const review=await h.runtime.reviewCanvas();
  assert.equal(review.verdict,'complete');
  assert.ok(diagnostics.some(e=>e.type==='guides_view_refused'),'logged: the reviewed image may show guides');
  assert.equal(h.runtime.guidesView,false,'not asked again');
 } finally {await h.close();}
});

test('Paint this plan in Agent mode starts one move on the plan\'s current step, not a new plan',{timeout:30000},async()=>{
 const asked=[];
 let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan')) return call('propose_plan',brief);
  if(!names.includes('paint_batch')) return {content:'Hello.'};
  asked.push(JSON.stringify(req.messages.at(-1)));
  return call('paint_batch',{summary:'Figures blocked in',actions:[{tool:'paint_pass',arguments:pass}]});
 },async(operation,params,_study,id)=>{
  if(!['paint_pass','review_pass'].includes(operation))return undefined;
  const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
  return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};
 });
 try {
  await h.start('plan'); await h.runtime.setExecutionSettings({move_size:'quick'}); await h.runtime.setMode('agent');
  await h.runtime.prompt('',{start_plan:true});
  const [move]=h.runtime.goal.moves;
  assert.equal(move.request,'Paint step 1 of the plan: Establish figures.');
  assert.ok(asked.some(text=>text.includes('Paint step 1 of the plan: Establish figures.')),'the painter is told which step');
  assert.equal(h.runtime.mode,'agent','the plan is painted in Agent mode, one move at a time');
  assert.equal(h.runtime.goal.reviews.length,0);
 } finally {await h.close();}
});

/** Agent mode with a canvas the artist switches to: `paints` decides whether the first move painted anything. */
async function canvasSwitchHarness(paints) {
 let active='doc';
 const h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(!names.includes('paint_batch')) return {content:'Hello.'};
  return paints ? call('paint_batch',{summary:'Sky block-in',actions:[{tool:'paint_pass',arguments:pass}]}) : {content:'I looked at the canvas first.'};
 },async(operation,params)=>{
  if(operation==='context') return {document_id:active,active_document_id:active,name:active==='doc'?'Untitled':'Unnamed',filename:'',width:768,height:1024,modified:true,revision:'revision-'+active};
  if(['begin','peek','paint_pass','observe','review_pass'].includes(operation) && active!=='doc'){
   const dir=params.output_dir ?? h.runtime.study.directory, path=join(dir,'view-'+active+'.png'); await writeFile(path,png);
   const checkpoint=operation==='begin' ? (params.painting_path ?? join(dir,'painting.kra')) : undefined;
   if(checkpoint) await writeFile(checkpoint,'test painting');
   return {status:'ok',document_id:active,name:'Unnamed',filename:'',modified:true,width:768,height:1024,image_path:path,layers:[],revision:'r-'+active,content_id:'c-'+active,passes:[],...(checkpoint?{checkpoint}:{})};
  }
  if(['paint_pass','review_pass'].includes(operation)){
   const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
   return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-paint',content_id:'c-paint',passes:[]};
  }
  return undefined;
 });
 await h.start('ask','Hello'); await h.runtime.setExecutionSettings({move_size:'quick'}); await h.runtime.setMode('agent');
 await h.runtime.prompt('Start with the sky.');
 return {h, switchTo:id=>{active=id;}};
}

test('a new canvas the artist switches to before anything was painted becomes the chat\'s painting',{timeout:30000},async()=>{
 const {h,switchTo}=await canvasSwitchHarness(false);
 try {
  assert.equal(h.runtime.study.target_document_id,'doc');
  switchTo('doc2');
  await h.runtime.prompt('I created a new canvas, trace the outline first.');
  assert.equal(h.runtime.study.target_document_id,'doc2','the chat now paints the active canvas');
  const ends=h.calls.filter(c=>c.operation==='end'), begins=h.calls.filter(c=>c.operation==='begin');
  assert.equal(begins.length,2); assert.ok(ends.length>=1,'the first canvas is released before the new one is taken');
  assert.equal(begins[1].params.mode,'current');
  assert.ok(!('source_document_id' in begins[1].params) || begins[1].params.source_document_id==='doc2','nothing is copied from the old canvas');
  assert.ok(h.events.some(e=>e.type==='action' && /new canvas/i.test(e.message)),'the panel says it switched');
 } finally {await h.close();}
});

test('after painting, a different active canvas is refused with what to do, and the chat keeps its painting',{timeout:30000},async()=>{
 const {h,switchTo}=await canvasSwitchHarness(true);
 try {
  assert.ok(h.runtime.goal.passes>0);
  switchTo('doc2');
  await assert.rejects(h.runtime.prompt('Paint on this one now.'),/Switch back to it to continue, or start a new chat/);
  assert.equal(h.runtime.study.target_document_id,'doc');
  assert.equal(h.calls.filter(c=>c.operation==='begin').length,1);
 } finally {await h.close();}
});

// Reference first (reference-first.ts): a goal reference's chat starts from the reference's colours. A live chat with
// final_goal.png and "trace the outline" drew guides, then flat-filled them grey and never used the reference tools.
async function referenceFirstMove({settings={}, references=[{purpose:'general'}], colourPass=null, text='Trace the outline.', respond}={}) {
 const painted=[];
 const h=await harness((req,n)=>{
  if(!req.tools.some(t=>t.function.name==='paint_batch')) return {content:'Hello.'};
  painted.push(req);
  return respond?.(req,painted.length) ?? {content:'Done.'};
 });
 const path=join(h.output,'final_goal.png'); await writeFile(path,png);
 await h.start('ask','Hello',references.length ? {references:references.map(r=>({path,...r}))} : {});
 await h.runtime.setExecutionSettings({move_size:'quick',...settings}); await h.runtime.setMode('agent');
 if(colourPass){
  const folder=join(h.runtime.study.directory,'reference-paintings'); await mkdir(folder,{recursive:true});
  await writeFile(join(folder,'a'.repeat(32)+'.json'),JSON.stringify({id:'a'.repeat(32),recipe:{name:'Goal',...(colourPass==='transfer'?{}:{mode:colourPass})},completed:400,total:400,status:'complete',scope:JSON.stringify([h.runtime.goal.revision])}));
 }
 await h.runtime.prompt(text);
 const moveText=painted.length ? JSON.stringify(painted[0].messages.at(-1)) : '';
 return {h,painted,moveText};
}
const skillCount=(text,name)=>text.split('<skill name=\\"'+name+'\\"').length-1;

test('reference first: with a goal reference and no colour pass yet, the move\'s context carries the reference-transfer skill once, and no guides by default',{timeout:30000},async()=>{
 const {h,moveText}=await referenceFirstMove();
 try {
  assert.equal(skillCount(moveText,'reference-transfer'),1);
  assert.equal(skillCount(moveText,'guided-trace'),0,'guides only when the artist asks (the artist, 2026-10-23: traces are distracting next to the underpainting)');
  assert.match(moveText,/guides only when the artist asks/i);
  assert.match(moveText,/Trace the outline\./,'the artist\'s request is still there');
  const system=JSON.stringify(h.requests.at(-1).messages[0]);
  assert.equal(skillCount(system,'reference-transfer'),0,'the skills are per-move context, not system prompt');
 } finally {await h.close();}
});

test('reference first: no skills are injected with the setting off, with no reference, with only a palette reference, or after a reference colour pass',{timeout:60000},async()=>{
 for (const [label,options] of [['setting off',{settings:{reference_first:false}}],['no reference',{references:[]}],
   ['a palette reference only',{references:[{purpose:'palette'}]}],
   ['after a transfer',{colourPass:'transfer'}]]) {
  const {h,moveText}=await referenceFirstMove(options);
  try {
   assert.ok(moveText,label+': the move ran');
   assert.equal(skillCount(moveText,'reference-transfer')+skillCount(moveText,'guided-trace'),0,label);
  } finally {await h.close();}
 }
 for (const mode of ['edges','surface']) {
  const {h,moveText}=await referenceFirstMove({colourPass:mode});
  try { assert.equal(skillCount(moveText,'reference-transfer'),1,'a '+mode+' pass lays no reference colours: still injected'); } finally {await h.close();}
 }
});

const flatFill={name:'Moon',area:[{shape:'ellipse',bounds:[100,100,200,200]}],color:'#808080'};
const twoFills=(req,n)=>n<=2 ? call('fill_region',flatFill) : {content:'Done.'};
const toolResults=painted=>painted.flatMap(r=>r.messages.filter(m=>m.role==='tool').map(m=>JSON.stringify(m.content)));

test('reference first: a move\'s first fill_region is nudged toward the reference tools without running; a repeated fill runs',{timeout:30000},async()=>{
 const {h,painted}=await referenceFirstMove({respond:twoFills});
 try {
  assert.ok(painted.length>=2);
  const nudge=toolResults(painted.slice(1,2)).join();
  assert.match(nudge,/This painting has a reference\. Lay its colours first with paint_from_reference/);
  assert.doesNotMatch(nudge,/paint_reference_surface/,'a surface pass smudges paint already there: not on a fresh canvas');
  assert.equal(h.calls.filter(c=>c.operation==='fill_region').length,1,'the nudged fill made no native call; the repeat ran');
  assert.equal(h.runtime.goal.moves[0].actions,1);
 } finally {await h.close();}
});

test('reference first: no nudge with the setting off, with no reference, or after a reference colour pass',{timeout:60000},async()=>{
 for (const [label,options] of [['setting off',{settings:{reference_first:false}}],['no reference',{references:[]}],['after a transfer',{colourPass:'transfer'}]]) {
  const {h,painted}=await referenceFirstMove({...options,respond:twoFills});
  try {
   assert.ok(!toolResults(painted).join().includes('This painting has a reference'),label);
   assert.equal(h.calls.filter(c=>c.operation==='fill_region').length,1,label+': the first fill ran (a quick move ends there)');
  } finally {await h.close();}
 }
});

test('reference first: a flat fill inside a paint_batch is nudged too',{timeout:30000},async()=>{
 const {h,painted}=await referenceFirstMove({respond:(req,n)=>n===1 ? call('paint_batch',{summary:'Flats',actions:[{tool:'fill_region',arguments:flatFill}]}) : {content:'Done.'}});
 try {
  assert.match(toolResults(painted).join(),/This painting has a reference/);
  assert.equal(h.calls.filter(c=>c.operation==='fill_region').length,0);
 } finally {await h.close();}
});

test('reference first: the move\'s batch guidance lays masses from the reference instead of flat fills; without a reference it is unchanged',{timeout:60000},async()=>{
 for (const size of ['quick','subject']) {
  const plain=agentMoveInstructions(size), reference=agentMoveInstructions(size,{referenceFirst:{transfer:true}}),
   established=agentMoveInstructions(size,{referenceFirst:{transfer:false}});
  assert.match(plain,/lay it in with fill_region or a fill layer/,size);
  assert.doesNotMatch(reference,/lay it in with fill_region or a fill layer/,size);
  assert.match(reference,/paint_from_reference/); assert.doesNotMatch(reference,/paint_reference_surface/);
  assert.match(reference,/fill_region only for flat design areas/);
  assert.doesNotMatch(established,/paint_from_reference/,'no second whole transfer where one would be refused');
  assert.match(established,/paint_reference_surface and paint_reference_edges over the paint already there/);
  assert.match(established,/fill_region only for flat design areas/);
 }
 const withRef=await referenceFirstMove(), without=await referenceFirstMove({references:[]});
 try {
  assert.match(withRef.moveText,/fill_region only for flat design areas/);
  assert.doesNotMatch(withRef.moveText,/lay it in with fill_region or a fill layer/);
  assert.match(without.moveText,/lay it in with fill_region or a fill layer/);
  assert.doesNotMatch(without.moveText,/fill_region only for flat design areas/);
 } finally {await withRef.h.close(); await without.h.close();}
});

test('the move instructions say a guides-only request draws guides, paints nothing and finishes the move',()=>{
 for (const size of ['quick','subject','large'])
  assert.match(agentMoveInstructions(size),/asks only for guides, an outline or a tracing, draw the guides and call finish_move, painting nothing/,size);
});

// /trace starts a guide-only move: "trace the outline first" drew 7 guides, then 21 fills and passes in the same move.
async function traceMove(respond, {size='subject', text='/trace the moon and the towers'}={}) {
 let h; const offered=[], reqs=[];
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(!names.includes('finish_guide')) return {content:'Hello.'};
  offered.push(names); reqs.push(req);
  return respond(offered.length);
 },async(operation,params,_study,id)=>{
  if(operation==='protection_list') return {status:'ok',areas:[]};
  if(operation==='merge_passes') return {status:'ok',merged_layers:0,remaining_runs:0,passes:[]};
  if(operation==='hide_guides') return {status:'ok',hidden:1};
  if(!['observe','draw_guide','finish_guide'].includes(operation)) return undefined;
  return guideViews(h,operation,params,id,{revision:'r-'+id,...(operation==='draw_guide' ? {layer_id:'guide-layer',passes:[{id,kind:'guide',title:'Moon',layer_id:'guide-layer'}]} : {})});
 });
 const path=join(h.output,'final_goal.png'); await writeFile(path,png);
 await h.start('ask','Hello',{references:[{path}]}); h.runtime.forkTools=true;
 await h.runtime.setExecutionSettings({move_size:size}); await h.runtime.setMode('agent');
 if (text) await h.runtime.prompt(text);
 return {h,offered,reqs};
}
const guide=n=>call('draw_guide',{element:'Moon '+n,lines:[{points:[[100,100],[200,100],[200,200]]}]});

test('/trace starts a guide-only move: only guide and look tools are offered, and finish_move ends it with a guides card',{timeout:30000},async()=>{
 const {h,offered}=await traceMove(n=>n===1 ? guide(1) : n===2 ? call('finish_move',{summary:'Moon and towers'}) : {content:'Done.'});
 try {
  assert.equal(offered.length,2,'the move ended at finish_move');
  for (const names of offered) {
   for (const name of ['draw_guide','finish_guide','observe_canvas','finish_move']) assert.ok(names.includes(name),name);
   for (const name of ['paint_batch','paint_pass','fill_region','paint_recipe','paint_contours','paint_from_reference','paint_reference_surface','painting_toolbox','create_layer'])
    assert.ok(!names.includes(name),name+' is not offered in a guide-only move');
  }
  const [move]=h.runtime.goal.moves;
  assert.deepEqual([move.kind,move.status,move.guides],['guides','ready',1]);
  assert.match(move.title,/^Drew guides: Moon and towers/);
  assert.match(h.events.filter(e=>e.type==='status').at(-1)?.message ?? '',/drew guides/);
  assert.equal(h.runtime.goal.messages.filter(m=>m.role==='user').at(-1).text,'/trace the moon and the towers','the transcript shows what the artist typed');
  assert.ok(!h.calls.some(c=>['paint_pass','fill_region'].includes(c.operation)));
 } finally {await h.close();}
});

test('a guide-only move ends after its guide calls even without finish_move',{timeout:60000},async()=>{
 const {h,offered}=await traceMove(n=>guide(n));
 try {
  assert.equal(h.calls.filter(c=>c.operation==='draw_guide').length,8,'a subject move\'s 8 calls, counted in guides');
  assert.equal(offered.length,8);
  assert.equal(h.runtime.goal.moves[0].status,'ready');
  assert.match(h.runtime.goal.moves[0].title,/^Drew guides/);
 } finally {await h.close();}
});

test('the next move after a guide-only move offers the painting tools again',{timeout:30000},async()=>{
 const {h}=await traceMove(n=>n===1 ? guide(1) : call('finish_move',{summary:'Moon'}));
 try {
  await h.runtime.moveAction({action:'keep',move:1}).catch(()=>{});
  assert.ok(h.runtime.toolOffered('paint_batch'),'outside a guide-only move the painting tools are back');
 } finally {await h.close();}
});

// Review fixes (agent/reference-defaults).
test('reference first: a flat fill anywhere in a batch refuses the whole batch before anything paints, and it is not counted',{timeout:30000},async()=>{
 const batch=call('paint_batch',{summary:'Sky then flats',actions:[{tool:'paint_pass',arguments:pass},{tool:'fill_region',arguments:flatFill}]});
 const {h,painted}=await referenceFirstMove({respond:(req,n)=>n<=2 ? batch : {content:'Done.'}});
 try {
  const first=toolResults(painted.slice(1,2)).join();
  assert.match(first,/Nothing was painted: This painting has a reference/);
  assert.equal(painted.length,2,'the Quick move went on to the repeated batch: the refused one was not its one call');
  assert.equal(h.calls.filter(c=>c.operation==='paint_pass').length,1,'only the repeated batch painted');
  assert.equal(h.calls.filter(c=>c.operation==='fill_region').length,1);
  assert.equal(h.runtime.goal.moves[0].calls,1);
 } finally {await h.close();}
});

test('reference first: the nudge shows calmly in the panel, not as a failed action',{timeout:30000},async()=>{
 const {h}=await referenceFirstMove({respond:twoFills});
 try {
  assert.ok(h.events.some(e=>e.type==='action' && e.message==='Reference first: suggested laying the reference colours before a flat fill.' && !e.error));
  assert.equal(h.events.filter(e=>e.type==='action' && e.message==='Painting action needs attention').length,0);
 } finally {await h.close();}
});

test('a /trace move with a reference gets only guide-only instructions: no reference-transfer, transfer or subject-move text',{timeout:30000},async()=>{
 const {h,reqs}=await traceMove(n=>n===1 ? guide(1) : call('finish_move',{summary:'Moon'}));
 try {
  const text=JSON.stringify(reqs[0].messages.at(-1)).replace(/<skill name=\\"guided-trace\\"[\s\S]*?<\/skill>/,'');
  assert.equal(skillCount(JSON.stringify(reqs[0].messages.at(-1)),'guided-trace'),1,'the /trace skill itself');
  assert.equal(skillCount(text,'reference-transfer'),0);
  assert.doesNotMatch(text,/paint_from_reference|REFERENCE FIRST|work the subject through|Work the subject through/);
  assert.match(text,/GUIDE-ONLY MOVE/); assert.match(text,/finish_move/);
 } finally {await h.close();}
});

test('/trace where guides are unavailable tells the artist and leaves /trace out of the menu',{timeout:60000},async()=>{
 for (const [label,setup] of [['stock Krita',h=>{h.runtime.forkTools=false;}],['Guides off',async h=>{await h.runtime.setExecutionSettings({guides:false});}]]) {
  const {h}=await traceMove(()=>({content:'Done.'}),{text:null});
  try {
   await setup(h);
   await assert.rejects(h.runtime.prompt('/trace the moon'),/Tracing needs the Guides setting on \(Settings › Guides\) in Toska\./,label);
   assert.equal(h.runtime.goal.moves?.length ?? 0,0,label+': no move started');
   h.runtime.emitSkills();
   const menu=h.events.filter(e=>e.type==='skills').at(-1);
   assert.ok(!menu.commands.some(c=>c.command==='/trace'),label);
   assert.ok(menu.commands.some(c=>c.command==='/colour'),label);
  } finally {await h.close();}
 }
 const {h}=await traceMove(()=>({content:'Done.'}),{text:null});
 try { h.runtime.emitSkills(); assert.ok(h.events.filter(e=>e.type==='skills').at(-1).commands.some(c=>c.command==='/trace'),'available: listed'); }
 finally {await h.close();}
});

test('Keep of a guides move waits for the artist; with request_done its guides stay showing; Undo retries a guides move',{timeout:60000},async()=>{
 {
  const {h,offered}=await traceMove(n=>n===1 ? guide(1) : call('finish_move',{summary:'Moon'}));
  try {
   await h.runtime.moveAction({action:'keep',move:1});
   assert.equal(h.runtime.goal.moves.length,1,'no painting move starts by itself');
   assert.equal(offered.length,2);
   assert.equal(h.events.filter(e=>e.type==='status').at(-1).message,'Guides kept. Tell me what to paint next.');
  } finally {await h.close();}
 }
 {
  const {h}=await traceMove(n=>n===1 ? guide(1) : call('finish_move',{summary:'Moon',request_done:true}));
  try {
   await h.runtime.moveAction({action:'keep',move:1});
   assert.equal(h.calls.filter(c=>c.operation==='hide_guides').length,0,'the guides just kept stay showing');
   assert.equal(h.runtime.goal.status,'complete');
  } finally {await h.close();}
 }
 {
  const {h,offered}=await traceMove(n=>n%2 ? guide(n) : call('finish_move',{summary:'Moon'}));
  try {
   await h.runtime.moveAction({action:'undo',move:1});
   assert.equal(h.runtime.goal.moves[1].kind,'guides','the retry is a guides move');
   assert.ok(!offered.at(-1).includes('paint_batch'));
  } finally {await h.close();}
 }
});

test('a guide-only move honours the move\'s minutes and its card gets an image at finish_move',{timeout:30000},async()=>{
 const {h}=await traceMove(n=>n===1 ? guide(1) : call('finish_move',{summary:'Moon'}));
 try {
  const [move]=h.runtime.goal.moves;
  assert.match(move.canvas ?? '',/guides\.png$/,'the card shows the guides');
  const finish=h.calls.findLastIndex(c=>c.operation==='observe'), drew=h.calls.findLastIndex(c=>c.operation==='draw_guide');
  assert.ok(finish>drew,'observed once at finish_move');
  h.runtime.currentMove={kind:'guides',guides:1,started_at:new Date(Date.now()-7*60000).toISOString()};
  assert.equal(h.runtime.moveDone(),true,'past the Subject move\'s 6 minutes');
  h.runtime.currentMove={kind:'guides',guides:1,started_at:new Date().toISOString()};
  assert.equal(h.runtime.moveDone(),false);
  h.runtime.currentMove=undefined;
 } finally {await h.close();}
});

// A real transfer in an Agent move: the 24 px reference fixture onto a small focal target (no ground, no refusal).
const transferArgs=h=>({name:'Goal colours',reference_id:h.runtime.study.references[0].id,preset:'Test brush',source:[0,0,24,24],target:[10,10,48,48],steps:[6,2,1]});
async function transferMoves(respond) {
 let h, revision='revision-0', painted=0; const moves=[];
 h=await harness(async req=>{
  const names=req.tools.map(t=>t.function.name);
  if(!names.includes('paint_batch')) return {content:'Hello.'};
  moves.push(req);
  return respond(h,moves.length);
 },async(op,params)=>{
  if(op==='decode_reference')return {width:24,height:24,sha256:params.sha256,rgba_base64:Buffer.alloc(24*24*4,255).toString('base64')};
  if(op==='paint_pass'){painted++;revision='paint-'+painted;return {status:'ok',width:768,height:1024,revision,layer_id:params.continue_layer_id??'layer-'+painted,image_path:join(h.runtime.study.directory,'view.png'),layers:[],passes:[]};}
  if(op==='observe')return {status:'ok',width:768,height:1024,revision,image_path:join(h.runtime.study.directory,'view.png'),layers:[],painted_share:0};
  if(op==='review_pass')return {status:'ok',width:768,height:1024,revision,image_path:join(h.runtime.study.directory,'view.png'),layers:[],passes:[]};
 });
 const path=join(h.output,'final_goal.png'); await writeFile(path,png);
 await h.start('ask','Hello',{references:[{path}]});
 await h.runtime.setExecutionSettings({move_size:'quick'}); await h.runtime.setMode('agent');
 return {h,moves};
}
const moveText=req=>JSON.stringify(req.messages.at(-1));

test('reference first: the skills go in once a chat, later moves get a one-line reminder, and an Undo of the colour pass brings them back in full',{timeout:60000},async()=>{
 const {h,moves}=await transferMoves((h,n)=>n===1 ? call('paint_pass',pass) : n===3 ? call('paint_from_reference',transferArgs(h)) : n===2 || n===4 ? {content:'Done.'} : {content:'Done.'});
 try {
  await h.runtime.prompt('Paint the sky.');                     // move 1: no colour pass yet, skills in full
  assert.equal(skillCount(moveText(moves[0]),'reference-transfer'),1);
  await h.runtime.prompt('Now the moon.');                      // move 2: a reminder line, not the skills again
  const second=moveText(moves[1]);
  assert.equal(skillCount(second,'reference-transfer'),0); assert.match(second,/REFERENCE FIRST/); assert.match(second,/skill given earlier/);
  await h.runtime.prompt('Lay the reference colours.');         // move 3: the transfer
  await h.runtime.prompt('Refine the towers.');                 // move 4: a colour pass exists, nothing added
  assert.doesNotMatch(moveText(moves[3]),/REFERENCE FIRST/);
  await h.runtime.moveAction({action:'undo',move:3});           // the artist undoes the colour pass: move 5 retries
  const after=moveText(moves.at(-1));
  assert.equal(skillCount(after,'reference-transfer'),1,'the situation changed: the skills again in full');
  assert.match(after,/REFERENCE FIRST/);
  // An undone colour pass counts as not done (the artist's rule): the whole underpainting may be retried, so the lead names it again.
  assert.match(after.split('Follow these skills')[0],/Lay the reference's colours first with paint_from_reference/,'the undone transfer no longer blocks a whole one');
 } finally {await h.close();}
});

test('reference first: whether a whole transfer is available asks transferRefusal\'s own question',{timeout:30000},async()=>{
 const {transferRefusal,existingPainting}=await import('../src/reference-tool.mjs');
 const {h}=await transferMoves(()=>({content:'Done.'}));
 try {
  const fresh={width:768,height:1024,painted_share:0,layers:[],protected_areas:[]};
  const whole={source:[0,0,768,1024],target:[0,0,768,1024]};
  assert.equal(await h.runtime.wholeTransferAvailable(fresh),true);
  assert.equal(transferRefusal(h.runtime.goal,whole,fresh,0,{established:existingPainting(h.runtime,fresh)}),null);
  const folder=join(h.runtime.study.directory,'reference-paintings'); await mkdir(folder,{recursive:true});
  await writeFile(join(folder,'b'.repeat(32)+'.json'),JSON.stringify({id:'b'.repeat(32),recipe:{name:'Goal'},completed:50,scope:JSON.stringify([h.runtime.goal.revision])}));
  assert.equal(await h.runtime.wholeTransferAvailable(fresh),false,'a transfer already ran (undone or not): a second whole one is refused');
  assert.ok(transferRefusal(h.runtime.goal,whole,fresh,1,{established:false}));
  assert.equal(await h.runtime.wholeTransferAvailable({...fresh,protected_areas:[{id:'a'}]}),true,'protected areas lift the size caps, as in transferRefusal');
 } finally {await h.close();}
});

// Project folder B2: opening a folder attaches its goal and elements as references and tells the panel.
async function projectFolder(elements=['01-moonlit-sky','02-historic-buildings','04-kremlin-towers']) {
 const root=await mkdtemp(join(tmpdir(),'project-folder-studio-'));
 await writeFile(join(root,'ART_BRIEF.md'),'# New Moscow\n\nA snowy night; warm windows against a blue sky.\n');
 await writeFile(join(root,'final_goal.png'),png);
 await writeFile(join(root,'finished_review.png'),png);
 await writeFile(join(root,'old.kra'),'not read');
 await mkdir(join(root,'assets'));
 for (const name of elements) await writeFile(join(root,'assets',name+'.png'),png);
 return root;
}
const folderSnapshot=async root=>JSON.stringify(await Promise.all((await readdir(root,{recursive:true})).sort().map(async name=>[name,(await readFile(join(root,name)).catch(()=>Buffer.from('dir'))).toString('base64')])));

test('opening a folder attaches its images and tells the panel',{timeout:20000},async()=>{
 const h=await harness(()=>({content:'Hello.'}));
 const root=await projectFolder();
 try {
  await h.start('ask','Hello');
  const before=await folderSnapshot(root);
  await h.runtime.openFolder({path:root});
  const refs=h.runtime.study.references;
  const goal=refs.find(r=>r.role==='reference');
  assert.deepEqual([goal?.name,goal?.purpose,goal?.source],['final_goal.png','composition','folder']);
  const elements=refs.filter(r=>r.role==='asset');
  assert.deepEqual(elements.map(r=>r.folder_name),['assets/01-moonlit-sky.png','assets/02-historic-buildings.png','assets/04-kremlin-towers.png']);
  assert.ok(elements.every(r=>r.source==='folder' && r.path.startsWith(h.runtime.study.directory)),'copied into the chat like any reference');
  assert.ok(!refs.some(r=>r.name==='finished_review.png'),'other images are listed, not attached');
  const event=h.events.filter(e=>e.type==='folder').at(-1);
  assert.equal(event.index.goal.name,'final_goal.png');
  assert.deepEqual(event.index.elements.map(e=>e.guess),['Moonlit sky','Historic buildings','Kremlin towers']);
  assert.deepEqual(event.index.others.map(e=>e.name),['finished_review.png']);
  assert.ok(event.index.skipped.some(s=>s.name==='old.kra'));
  assert.ok(!JSON.stringify(event.index).includes(root+'/'),'the panel gets paths relative to the folder');
  assert.equal(event.references['assets/04-kremlin-towers.png'],elements[2].id);
  assert.equal(h.runtime.study.folder.root,event.index.root);
  const context=JSON.parse(h.runtime.context('agent').split('\n').find(line=>line.startsWith('{')));
  assert.equal(context.folder.goal.reference_id,goal.id);
  assert.deepEqual(context.folder.elements.map(e=>[e.name,e.reference_id]),elements.map(r=>[r.folder_name,r.id]));
  assert.deepEqual(context.folder.elements.map(e=>e.guess),['Moonlit sky','Historic buildings','Kremlin towers']);
  assert.match(context.folder.brief ?? '',/warm windows/,'the brief is read for the painter');
  assert.equal(await folderSnapshot(root),before,'opening writes nothing into the folder');
  await h.runtime.openFolder({path:root});
  assert.equal(h.runtime.study.references.length,refs.length,'opening it again attaches nothing twice');
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

test('a corrected guess reaches the painter\'s context; a folder chosen before the chat is attached when it starts',{timeout:20000},async()=>{
 const h=await harness(()=>({content:'Hello.'}));
 const root=await projectFolder();
 try {
  await h.runtime.openFolder({path:root});
  assert.equal(h.events.filter(e=>e.type==='folder').length,1,'the panel sees the folder before any chat');
  await h.start('ask','Hello');
  assert.equal(h.runtime.study.references.filter(r=>r.source==='folder').length,4);
  await h.runtime.folderGuess({name:'assets/02-historic-buildings.png',guess:'Lamps and trees'});
  const context=JSON.parse(h.runtime.context('agent').split('\n').find(line=>line.startsWith('{')));
  assert.equal(context.folder.elements[1].guess,'Lamps and trees');
  assert.equal(h.events.filter(e=>e.type==='folder').at(-1).index.elements[1].guess,'Lamps and trees');
  assert.match(h.runtime.study.references.find(r=>r.folder_name==='assets/02-historic-buildings.png').notes,/Lamps and trees/);
  await assert.rejects(h.runtime.folderGuess({name:'assets/99-nothing.png',guess:'x'}),/not an element/);
  const id=h.runtime.study.id; await h.runtime.end(); h.events.length=0;
  await h.runtime.resume(id);
  assert.equal(h.events.filter(e=>e.type==='folder').at(-1)?.index.elements[1].guess,'Lamps and trees','the folder and the correction follow the chat');
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

// Project folder B3: the element plan approved first, PLAN.md and NOTES.md, resume.
const PAINT_TOOLS=['paint_batch','paint_pass','paint_recipe','fill_region','draw_guide','paint_from_reference','paint_reference_surface','create_layer'];
const folderBrief={title:'New Moscow',objective:'A snowy night, one element per move.',requirements:['Keep the warm windows.'],freedom:[],completion:['Every element is painted.'],
 steps:[{title:'Underpainting from the goal image',done_when:'Everything placed.',scope:'whole composition'},
  {title:'Moonlit sky',done_when:'The sky is painted.',scope:'assets/01-moonlit-sky.png'},
  {title:'Historic buildings',done_when:'The buildings are painted.',scope:'assets/02-historic-buildings.png'},
  {title:'Kremlin towers',done_when:'The towers are painted.',scope:'assets/04-kremlin-towers.png'}]};
const paintResult=async(h,id)=>{const dir=h.runtime.study.directory; await writeFile(join(dir,'view.png'),png);
 return {status:'ok',document_id:'doc',name:'Untitled',filename:'',modified:true,width:768,height:1024,image_path:join(dir,'view.png'),layers:[],revision:'r-'+id,content_id:'c-'+id,passes:[]};};

test('with a folder, Agent mode proposes the element plan and paints nothing before approval',{timeout:30000},async()=>{
 const offered=[]; let proposals=0;
 const h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name); offered.push({names,text:latestUserText(req)});
  if(names.includes('propose_plan') && !proposals++) return call('propose_plan',folderBrief);
  return {content:'The plan is ready for you.'};
 });
 const root=await projectFolder();
 try {
  await h.runtime.openFolder({path:root});
  await h.start('agent','Paint this folder.');
  const planning=offered[0];
  assert.ok(planning.names.includes('propose_plan'),'the first turn proposes the plan');
  for (const name of PAINT_TOOLS) assert.ok(!planning.names.includes(name),name+' is not offered before approval');
  const draft=JSON.parse(planning.text.match(/folder_plan_draft: (\{.*\})/)[1]);
  assert.deepEqual(draft.steps.map(s=>s.title),['Underpainting from the goal image','Moonlit sky','Historic buildings','Kremlin towers'],'the whole-picture underpainting first, then the elements back to front by number');
  assert.doesNotMatch(JSON.stringify(draft.steps[0]),/guide/i,'no guides step unless the artist asks');
  assert.doesNotMatch(planning.text,/construction guides/i);
  assert.equal(draft.steps[2].scope,'assets/02-historic-buildings.png');
  assert.deepEqual(h.runtime.goal.brief.steps.map(s=>s.title),folderBrief.steps.map(s=>s.title));
  assert.equal(h.runtime.goal.approved_revision,null);
  assert.ok(!h.calls.some(c=>['begin','paint_pass','draw_guide','fill_region'].includes(c.operation)),'nothing touches the canvas');
  const plan=await readFile(join(root,'PLAN.md'),'utf8');
  assert.match(plan,/^- \[ \] 3\. Historic buildings \(assets\/02-historic-buildings\.png\) · layer "Historic buildings"$/m);
  await h.runtime.prompt('Only the sky today.');
  assert.ok(offered.at(-1).names.includes('propose_plan') && !offered.at(-1).names.includes('paint_batch'),'a direction before approval revises the plan');
  assert.ok(!h.calls.some(c=>c.operation==='begin'));
  assert.equal(h.runtime.goal.moves?.length ?? 0,0,'no move was started');
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

test('with a folder and a model that proposes nothing, the host proposes the element plan itself',{timeout:30000},async()=>{
 const h=await harness(()=>({content:'Let us look at the folder first.'}));
 const root=await projectFolder();
 try {
  await h.start('ask','Hello'); await h.runtime.openFolder({path:root}); await h.runtime.setMode('agent');
  await h.runtime.prompt('Paint it.');
  assert.deepEqual(h.runtime.goal.brief.steps.map(s=>[s.title,s.scope]),[['Underpainting from the goal image','whole composition'],
   ['Moonlit sky','assets/01-moonlit-sky.png'],['Historic buildings','assets/02-historic-buildings.png'],['Kremlin towers','assets/04-kremlin-towers.png']]);
  assert.match(h.events.filter(e=>e.type==='status').at(-1).message,/Start painting/);
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

test('after Keep the step is ticked, PLAN.md updated, NOTES.md gains a line and the element\'s guide is finished',{timeout:60000},async()=>{
 const turns=new Map(), painters=[];
 let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  if(names.includes('propose_plan')) return call('propose_plan',folderBrief);
  const move=h.runtime.currentMove;
  if(!names.includes('paint_batch') || !move || move.finished) return {content:'Done.'};
  const n=(turns.get(move.number) ?? 0)+1; turns.set(move.number,n);
  if(n===1) { painters.push(req); return call('paint_batch',{summary:'Element',actions:[{tool:'paint_pass',arguments:{...pass,name:'Element '+move.number}}]}); }
  return call('finish_move',{summary:'Painted step '+(move.step+1)});
 },async(operation,params,_study,id)=>{
  if(operation==='paint_pass') return paintResult(h,id);
  if(operation==='finish_guide') return {status:'ok',element:params.element,visible:false};
  return undefined;
 });
 const root=await projectFolder();
 try {
  await h.runtime.openFolder({path:root});
  await h.start('agent','Paint this folder.');
  h.runtime.forkTools=true; h.runtime.guidesView=true;
  await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.goal.approved_revision,h.runtime.goal.revision,'Start painting approves the plan');
  const [first]=h.runtime.goal.moves;
  assert.deepEqual([first.step,first.status],[0,'ready']);
  const firstText=latestUserText(painters[0]);
  assert.match(firstText,/Paint step 1 of the plan: Underpainting from the goal image/);
  assert.match(firstText,/PROJECT FOLDER MOVE[^\n]*paint_from_reference/,'the first step is the whole-picture underpainting');
  assert.doesNotMatch(firstText,/PROJECT FOLDER MOVE[^\n]*draw_guide/,'no guides by default');
  await h.runtime.moveAction({action:'keep',move:1});
  assert.deepEqual(h.runtime.goal.done_steps,[0]);
  const second=h.runtime.goal.moves[1];
  assert.deepEqual([second.step,second.status],[1,'ready'],'Keep starts the next element\'s move, which stops for Keep / Undo again');
  const skyText=latestUserText(painters[1]);
  assert.match(skyText,/Paint step 2 of the plan: Moonlit sky/);
  const sky=h.runtime.study.references.find(r=>r.folder_name==='assets/01-moonlit-sky.png');
  assert.ok(skyText.includes(sky.id),'the move names the element\'s reference');
  assert.doesNotMatch(skyText,/First draw_guide/,'an element move draws no guide unless asked');
  assert.match(skyText,/guide[^.]*only when the artist asks/i);
  assert.equal(imagesInLatestMessage(painters[1]).length,3,'the goal, this element and the canvas: not every element of the folder');
  await h.runtime.moveAction({action:'keep',move:2});
  assert.deepEqual(h.runtime.goal.done_steps,[0,1]);
  const finished=h.calls.filter(c=>c.operation==='finish_guide').map(c=>c.params.element);
  assert.ok(finished.includes('Moonlit sky'),'the ticked element\'s guide is hidden');
  const plan=await readFile(join(root,'PLAN.md'),'utf8');
  assert.match(plan,/^- \[x\] 1\. Underpainting/m); assert.match(plan,/^- \[x\] 2\. Moonlit sky/m); assert.match(plan,/^- \[ \] 3\. Historic buildings/m);
  const notes=(await readFile(join(root,'NOTES.md'),'utf8')).split('\n').filter(l=>l.startsWith('- '));
  assert.equal(notes.length,2); assert.match(notes[1],/Moonlit sky/);
  assert.equal(h.runtime.goal.current_step,2);
  assert.deepEqual((await readdir(root)).filter(n=>n.endsWith('.md')).sort(),['ART_BRIEF.md','NOTES.md','PLAN.md'],'only PLAN.md and NOTES.md were added');
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

test('resume with a hand-edited PLAN.md shows the difference and waits; a new chat on the folder picks the plan up',{timeout:60000},async()=>{
 const h=await harness(req=>req.tools.some(t=>t.function.name==='propose_plan') && !h.runtime.goal.brief ? call('propose_plan',folderBrief) : {content:'Noted.'});
 const root=await projectFolder();
 try {
  await h.runtime.openFolder({path:root});
  await h.start('agent','Paint this folder.');
  const id=h.runtime.study.id; await h.runtime.end();
  const lines=(await readFile(join(root,'PLAN.md'),'utf8')).split('\n');
  const edited=lines.filter(l=>!l.includes('Historic buildings'));
  const towers=edited.findIndex(l=>l.includes('Kremlin towers')), sky=edited.findIndex(l=>l.includes('Moonlit sky'));
  [edited[towers],edited[sky]]=[edited[sky],edited[towers]];
  await writeFile(join(root,'PLAN.md'),edited.join('\n'));
  const requests=h.requests.length; h.events.length=0;
  await h.runtime.resume(id);
  const question=h.events.find(e=>e.type==='question');
  assert.ok(question,'the artist is asked');
  assert.match(question.question,/Removed: Historic buildings/); assert.match(question.question,/Moved: Kremlin towers/);
  assert.deepEqual(question.options,['Follow the edited plan','Keep the current plan']);
  assert.equal(h.runtime.goal.brief.steps.length,4,'nothing is followed before the answer');
  await h.runtime.prompt('Follow the edited plan');
  assert.equal(h.requests.length,requests,'answering makes no model request and paints nothing');
  assert.deepEqual(h.runtime.goal.brief.steps.map(s=>s.title),['Underpainting from the goal image','Kremlin towers','Moonlit sky']);
  assert.equal(h.runtime.goal.brief.steps[1].done_when,'The towers are painted.');
  assert.equal(h.runtime.goal.approved_revision,null,'the edited plan is approved with Start painting');
  const backups=(await readdir(root)).filter(n=>n.includes('.backup-'));
  assert.equal(backups.length,1,'the artist\'s file is backed up before the plan is rewritten in its own format');
  assert.ok(!(await readFile(join(root,backups[0]),'utf8')).includes('Historic buildings'));
  await h.runtime.end();
  await h.start('ask','Hello');
  await h.runtime.openFolder({path:root});
  assert.deepEqual(h.runtime.goal.brief.steps.map(s=>s.title),['Underpainting from the goal image','Kremlin towers','Moonlit sky'],'a new chat reads PLAN.md');
  assert.match(h.events.filter(e=>e.type==='action').map(e=>e.message).join('\n'),/0 of 3 done, next: Underpainting/);
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

// Project folder review fixes.
async function folderMoves({finish=true, root}={}) {
 const turns=new Map(), offered=[]; let h;
 h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name); offered.push(names);
  if(names.includes('propose_plan')) return h.runtime.goal.brief ? {content:'Revised.'} : call('propose_plan',folderBrief);
  const move=h.runtime.currentMove;
  if(!names.includes('paint_batch') || !move || move.finished) return {content:'Done.'};
  const n=(turns.get(move.number) ?? 0)+1; turns.set(move.number,n);
  if(n===1) return call('paint_batch',{summary:'Element',actions:[{tool:'paint_pass',arguments:{...pass,name:'Element '+move.number}}]});
  return finish ? call('finish_move',{summary:'Painted step '+(move.step+1)}) : {content:'I painted some of it.'};
 },async(operation,params,_study,id)=>{
  if(operation==='paint_pass') return paintResult(h,id);
  if(operation==='finish_guide') return {status:'ok',element:params.element,visible:false};
  return undefined;
 });
 await h.runtime.openFolder({path:root});
 await h.start('agent','Paint this folder.');
 h.runtime.forkTools=true; h.runtime.guidesView=true;
 return {h,offered};
}

test('a move that ended without finish_move does not tick its step; Keep continues the same step (I1)',{timeout:60000},async()=>{
 const root=await projectFolder();
 const {h}=await folderMoves({finish:false,root});
 try {
  await h.runtime.prompt('',{start_plan:true});
  assert.equal(h.runtime.goal.moves[0].finished,undefined);
  await h.runtime.moveAction({action:'keep',move:1});
  assert.deepEqual(h.runtime.goal.done_steps,[]);
  assert.equal(h.runtime.goal.moves[1].step,0,'the next move works the same step');
  assert.ok(!(await readdir(root)).includes('NOTES.md'));
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

test('Keep after the plan was edited ticks the move\'s own step by identity and does not approve the new plan (C1)',{timeout:60000},async()=>{
 const root=await projectFolder();
 const {h}=await folderMoves({root});
 try {
  await h.runtime.prompt('',{start_plan:true});
  await h.runtime.moveAction({action:'keep',move:1});
  const sky=h.runtime.goal.moves[1];
  assert.deepEqual([sky.step,sky.status],[1,'ready']);
  const [block,skyStep,buildings,towers]=folderBrief.steps;
  await h.runtime.editPlan({...folderBrief,steps:[block,towers,buildings,skyStep]});
  assert.equal(h.runtime.goal.approved_revision,null);
  await h.runtime.moveAction({action:'keep',move:2});
  assert.deepEqual(h.runtime.goal.done_steps,[0,3],'the sky is ticked where it now is');
  assert.equal(h.runtime.goal.moves.length,2,'no move starts on an unapproved plan');
  assert.equal(h.runtime.goal.approved_revision,null,'Keep never approves a plan');
  assert.match(h.events.filter(e=>e.type==='status').at(-1).message,/Start painting/);
  assert.match(await readFile(join(root,'PLAN.md'),'utf8'),/^- \[x\] 4\. Moonlit sky/m);
  // A step that is gone is not ticked at all.
  await h.runtime.prompt('',{start_plan:true});
  const towersMove=h.runtime.goal.moves.at(-1);
  assert.equal(h.runtime.goal.brief.steps[towersMove.step].title,'Kremlin towers');
  await h.runtime.editPlan({...folderBrief,steps:[block,buildings,skyStep]});
  await h.runtime.moveAction({action:'keep',move:towersMove.number});
  assert.deepEqual(h.runtime.goal.done_steps,[0,2]);
  assert.match(h.events.filter(e=>e.type==='action').map(e=>e.message).join('\n'),/no longer in the plan/);
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

test('a PLAN.md the agent did not write is backed up on the first rewrite (I5)',{timeout:30000},async()=>{
 const h=await harness(()=>({content:'Hello.'}));
 const root=await projectFolder();
 try {
  await writeFile(join(root,'PLAN.md'),'# My plan\n\n## Moves\n\n- [x] 1. Moonlit sky (assets/01-moonlit-sky.png)\n- [ ] 2. Kremlin towers (assets/04-kremlin-towers.png)\n');
  await h.start('ask','Hello'); await h.runtime.openFolder({path:root});
  assert.deepEqual(h.runtime.goal.brief.steps.map(s=>s.title),['Moonlit sky','Kremlin towers']);
  await h.runtime.editPlan(h.runtime.goal.brief);
  const backups=(await readdir(root)).filter(n=>n.includes('.backup-'));
  assert.equal(backups.length,1);
  assert.match(await readFile(join(root,backups[0]),'utf8'),/# My plan/);
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

test('opening a folder in a chat with an approved plan that is not the folder\'s makes Agent plan the folder first (I6)',{timeout:30000},async()=>{
 const offered=[];
 const h=await harness(req=>{const names=req.tools.map(t=>t.function.name); offered.push(names); return {content:'Noted.'};});
 const root=await projectFolder();
 try {
  await h.start('ask','Hello'); await h.runtime.editPlan(brief);
  h.runtime.goal.approved_revision=h.runtime.goal.revision;
  await h.runtime.openFolder({path:root});
  assert.equal(h.runtime.goal.approved_revision,null);
  await h.runtime.setMode('agent'); await h.runtime.prompt('',{start_plan:true});
  assert.ok(offered.at(-1).includes('propose_plan') && !offered.at(-1).includes('paint_batch'),'a planning turn, not a move');
  assert.ok(!(h.runtime.goal.moves ?? []).length);
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

test('the folder\'s goal image does not count toward the four references; one unreadable element is skipped, not fatal',{timeout:30000},async()=>{
 const h=await harness(()=>({content:'Hello.'}));
 const root=await projectFolder();
 try {
  const references=[];
  for (let i=0;i<4;i++){const path=join(h.output,'ref'+i+'.png'); await writeFile(path,png); references.push({path});}
  await h.start('ask','Hello',{references});
  await h.runtime.openFolder({path:root});
  assert.ok(h.runtime.study.references.some(r=>r.name==='final_goal.png' && r.source==='folder'),'the goal is attached beside four references');
  const fifth=join(h.output,'ref5.png'); await writeFile(fifth,png);
  await assert.rejects(h.runtime.addReferences([{path:fifth}]),/four reference/,'the artist\'s own references still stop at four');
  const index=await scanFolder(root);
  index.elements.push({...index.elements[0],name:'assets/09-gone.png',path:join(root,'assets','09-gone.png')});
  await h.runtime.attachFolder(index);
  assert.match(h.events.filter(e=>e.type==='action').map(e=>e.message).join('\n'),/09-gone\.png was not attached/);
  assert.equal(h.runtime.study.references.filter(r=>r.source==='folder' && r.role==='asset').length,3);
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

test('more than fifteen elements: the plan says which were left out',{timeout:30000},async()=>{
 const h=await harness(()=>({content:'Let us see.'}));
 const root=await projectFolder(Array.from({length:17},(_,i)=>String(i+1).padStart(2,'0')+'-element-'+(i+1)));
 try {
  await h.start('ask','Hello'); await h.runtime.openFolder({path:root}); await h.runtime.setMode('agent');
  await h.runtime.prompt('Paint it.');
  assert.equal(h.runtime.goal.brief.steps.length,16);
  assert.match(h.events.filter(e=>e.type==='status').at(-1).message,/2 elements .*left out/);
  assert.equal(h.events.filter(e=>e.type==='folder').at(-1).plan_limit,15);
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

test('plan-edit answers: an edit that cannot be followed says so; another message drops the pending edit',{timeout:30000},async()=>{
 const h=await harness(()=>({content:'Noted.'}));
 const root=await projectFolder();
 try {
  await h.start('ask','Hello'); await h.runtime.openFolder({path:root}); await h.runtime.editPlan(folderBrief);
  h.runtime.goal.pending_plan_edit={text:'# x\n\n## Moves\n\n'};
  await h.runtime.prompt('Follow the edited plan');
  assert.match(h.events.filter(e=>e.type==='status').at(-1).message,/could not follow/i);
  assert.equal(h.runtime.goal.brief.steps.length,4);
  h.runtime.goal.pending_plan_edit={text:'# x\n'};
  await h.runtime.prompt('What do you see?');
  assert.equal(h.runtime.goal.pending_plan_edit,null);
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

test('propose_plan in a folder chat: bare file names resolve to the folder, unknown and repeated elements are refused; the planner reads the prompts',{timeout:30000},async()=>{
 const results=[]; let n=0; const texts=[];
 const h=await harness(req=>{
  const names=req.tools.map(t=>t.function.name);
  texts.push(latestUserText(req));
  for (const m of req.messages.filter(m=>m.role==='tool')) results.push(JSON.stringify(m.content));
  if(!names.includes('propose_plan')) return {content:'ok'};
  n++;
  const [block,sky,buildings]=folderBrief.steps;
  if(n===1) return call('propose_plan',{...folderBrief,steps:[block,{...sky,scope:'zz-unknown.png'}]});
  if(n===2) return call('propose_plan',{...folderBrief,steps:[block,sky,{...buildings,scope:'assets/01-moonlit-sky.png'}]});
  if(n===3) return call('propose_plan',{...folderBrief,steps:[block,{...sky,scope:'01-moonlit-sky.png'},buildings]});
  return {content:'Plan proposed.'};
 });
 const root=await projectFolder();
 try {
  await writeFile(join(root,'assets','generation-prompts.json'),JSON.stringify({assets:[{name:'01-moonlit-sky',prompt:'Subject: Only the moonlit blue night sky.'}]}));
  await h.runtime.openFolder({path:root});
  await h.start('agent','Paint this folder.');
  assert.match(texts[0],/Only the moonlit blue night sky/,'the planner reads the element prompts');
  assert.ok(results.some(r=>/zz-unknown\.png.*not an element/.test(r)),results.join('\n'));
  assert.ok(results.some(r=>/more than one step/.test(r)),results.join('\n'));
  assert.deepEqual(h.runtime.goal.brief.steps.map(s=>s.scope),['whole composition','assets/01-moonlit-sky.png','assets/02-historic-buildings.png']);
 } finally {await h.close(); await rm(root,{recursive:true,force:true});}
});

// Close-up references for detail (closeups.ts): the studio aligns a reference of other proportions to the goal, asks the
// artist once with the place drawn on the goal (the chat's question, with its picture), records the answer, and tells
// the painter which areas have a close-up.
function sizedPng(width, height) {
 const head=Buffer.alloc(13); head.writeUInt32BE(width,0); head.writeUInt32BE(height,4); head[8]=8;
 const chunk=(type,data)=>{const length=Buffer.alloc(4);length.writeUInt32BE(data.length);const body=Buffer.concat([Buffer.from(type),data]);
  const crc=Buffer.alloc(4);crc.writeUInt32BE(crc32(body));return Buffer.concat([length,body,crc]);};
 return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',head),chunk('IDAT',deflateSync(Buffer.from([0,1]))),chunk('IEND',Buffer.alloc(0))]);
}
test('a close-up is aligned once, confirmed by the artist through the chat’s question, and listed for the painter',{timeout:30000},async()=>{
 const aligned=[];
 const h=await harness(()=>({content:'Noted.'}),async(op,params)=>{
  if(op!=='align_closeup')return undefined;
  aligned.push(params);
  return {status:'ok',aligned:true,matrix:[0.5,0,100,0,0.5,200,0,0,1],quad:[[100,200],[300,200],[300,350],[100,350]],box:[100,200,200,150],scale:2,rotation:0,
   matches:200,inliers:190,score:.95,similarity:.97,ms:120,goal_size:[768,1024],closeup_size:[400,300],preview_jpeg_base64:Buffer.from('jpeg').toString('base64')};
 });
 try {
  const goal=join(h.output,'goal.png'), close=join(h.output,'face.png');
  await writeFile(goal,sizedPng(768,1024)); await writeFile(close,sizedPng(400,300));
  await h.start('ask','Hello',{references:[{path:goal},{path:close}]});
  h.runtime.decisionObservation={width:768,height:1024,revision:'revision-0'};
  await h.runtime.closeups.refresh(); await h.runtime.closeups.refresh();
  assert.equal(aligned.length,1,'aligned once');
  const [goalRef,closeRef]=h.runtime.study.references;
  assert.equal(await h.runtime.closeups.route({reference_id:goalRef.id,source:[150,250,40,30],target:[0,0,160,120]}),null,'not confirmed: the goal is sampled');
  assert.equal(h.runtime.goal.question,null,'nothing holds the run');
  assert.notEqual(h.runtime.goal.status,'needs_input');
  const asked=h.events.filter(e=>e.type==='closeup_question').at(-1);
  assert.match(asked.question,/face\.png/);
  assert.equal(await readFile(asked.image_path,'utf8'),'jpeg');
  assert.equal(h.runtime.goal.closeup_question.id,asked.id);
  await h.runtime.prompt('Use the close-up there');
  assert.equal(h.runtime.study.closeups[closeRef.id].confirmed,undefined,'a chat message is not the answer');
  await h.runtime.answerCloseup({question_id:'another',answer:'Use the close-up there'});
  assert.equal(h.runtime.study.closeups[closeRef.id].confirmed,undefined,'only the answer to this question counts');
  await h.runtime.answerCloseup({question_id:asked.id,answer:'Use the close-up there'});
  assert.equal(h.runtime.study.closeups[closeRef.id].confirmed,'yes');
  assert.equal(h.runtime.goal.closeup_question,null);
  const used=await h.runtime.closeups.route({reference_id:goalRef.id,source:[150,250,40,30],target:[0,0,160,120]});
  assert.deepEqual(used.recipe.source,[100,100,80,60]);
  assert.match(h.runtime.context('agent'),/Close-ups for detail: [^"]*face\.png, about 2x sharper/);
  await h.runtime.removeReference({id:closeRef.id});
  assert.equal(h.runtime.study.closeups[closeRef.id],undefined,'a removed close-up\u2019s record goes');
 } finally {await h.close();}
});

test('a folder plan step the artist approved that names guides is a guides step',async()=>{
 const runtime=Object.create(StudioRuntime.prototype);
 runtime.goal={brief:{steps:[{title:'Guides: block in the whole composition',done_when:'d',scope:'whole composition'},{title:'Underpainting from the goal image',done_when:'d',scope:'whole composition'}]}};
 runtime.study={references:[{id:'goal-1',source:'folder',role:'reference',folder_name:'final_goal.png'}]};
 const guides=runtime.folderMoveInstructions({step:0}), under=runtime.folderMoveInstructions({step:1});
 assert.match(guides,/draw_guide/); assert.doesNotMatch(guides,/paint_from_reference/);
 assert.match(under,/paint_from_reference/); assert.doesNotMatch(under,/draw_guide/);
});

test('a guides-only move draws what the artist named; the masses are an option, never the default',()=>{
 const text=agentMoveInstructions('subject',{guidesOnly:true});
 assert.doesNotMatch(text,/masses first|unless the artist said otherwise/);
 assert.match(text,/masses: true/,'masses stay an option');
});

test('the mass map runs once per chat: a run left from a closed chat does not hold up the next chat\'s',async()=>{
 const runtime=Object.create(StudioRuntime.prototype);
 const a={directory:'/nonexistent/a',references:[]}, b={directory:'/nonexistent/b',references:[]};
 runtime.study=a; runtime.startMassMaps(); const first=runtime.massMapsRunning;
 assert.equal(first?.study,a);
 runtime.startMassMaps(); assert.equal(runtime.massMapsRunning,first,'not twice for one chat');
 runtime.study=b; runtime.startMassMaps();
 assert.equal(runtime.massMapsRunning?.study,b,'the next chat starts its own');
 await first.done; await runtime.massMapsRunning?.done;
});

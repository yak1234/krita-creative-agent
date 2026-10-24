import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {generateReferencePlan,generateEdgePlan,generateSurfacePlan,estimateReferenceStrokes,EDGE_LIMIT,SURFACE_LIMIT} from '../src/reference-generator.mjs';
import {referenceTools,transferRefusal,stretchRefusal,partShare,existingPainting,PAINTED_SHARE,fitStepsToTime,fitStepsToBudget,AGENT_MOVE_STROKES,wholeReferenceRefusal,groundStops,STROKES_PER_SECOND,TRANSFER_TIME_SHARE,canvasSteps,underpaintingBudget,UNDERPAINTING_CANVAS_STEPS,UNDERPAINTING_STROKES,UNDERPAINTING_MINUTES,MEASURED_STROKES_PER_SECOND} from '../src/reference-tool.mjs';
import {PLAN_STROKES_MAX} from '../src/reference-limits.ts';
const recipe={name:'Portrait',reference_id:'ref',preset:'Basic',source:[0,0,24,24],target:[2,2,48,48],steps:[6,3,1.5],focal_regions:[[6,6,12,12]],seed:42};
const canvas={width:64,height:64,revision:'r0'};
const image={width:24,height:24,data:Buffer.alloc(24*24*4)};
for(let y=0;y<24;y++)for(let x=0;x<24;x++){const i=(y*24+x)*4;image.data.set(x<12?[200,20,10,255]:[10,20,200,255],i);}
test('reference generation preserves spatial colors, mapping, deterministic refinement and native bounds',()=>{
 const plan=generateReferencePlan(recipe,image,canvas);assert.deepEqual(plan,generateReferencePlan(recipe,image,canvas));assert.equal(plan.passes.length,3);assert.equal(plan.total,16+64+64);
 for(const pass of plan.passes)for(const s of pass.strokes){assert.ok(s.start.every(v=>v>=2&&v<=50));if(s.start[0]<18)assert.equal(s.color,'#c8140a');if(s.start[0]>34)assert.equal(s.color,'#0a14c8');}
 assert.notDeepEqual(plan,generateReferencePlan({...recipe,seed:43},image,canvas));
 assert.throws(()=>generateReferencePlan({...recipe,target:[0,0,48,24]},image,canvas),/aspect/);
 assert.throws(()=>generateReferencePlan({...recipe,steps:[3,6,1]},image,canvas),/decrease/);
 assert.throws(()=>generateReferencePlan({...recipe,focal_regions:[[20,20,12,12]]},image,canvas),/Focal/);
 const transparent={...image,data:Buffer.alloc(image.data.length)};assert.throws(()=>generateReferencePlan(recipe,transparent,canvas),/transparent/);
 const large={width:2000,height:2000,data:Buffer.alloc(16000000)};assert.throws(()=>generateReferencePlan({...recipe,source:[0,0,2000,2000],target:[0,0,2000,2000],steps:[1.5,1,.75]},large,{width:2000,height:2000}),/280,000/);
 assert.equal(PLAN_STROKES_MAX,280000,'room for the whole-picture underpainting budget');
});
async function harness(){const directory=await mkdtemp(join(tmpdir(),'reference-job-'));const ref=join(directory,'ref.png');await writeFile(ref,'fixture');let revision='r0',layer=0;const calls=[],receipts=new Map();
 const runtime={config:{reference_batch:128},mode:'agent',executionPhase:'agent',study:{directory,references:[{id:'ref',path:ref}]},decisionObservation:canvas,emit(){},
 async callNative(op,p){if(op==='decode_reference')return {...image,data:undefined,rgba_base64:image.data.toString('base64'),sha256:p.sha256};if(op==='observe')return {...canvas,revision};if(op==='operation_status')return {found:receipts.has(p.id),result:receipts.get(p.id)};throw new Error(op);}};
 let after=()=>{};
 const execute=async(id,args)=>{calls.push({id,args});const result={status:'ok',revision:'r'+calls.length,layer_id:args.continue_layer_id??'layer-'+(++layer)};revision=result.revision;receipts.set(id,result);await after(runtime,result);return {details:result};};
 const fills=[];
 const fill=async(id,args)=>{if(!receipts.has(id)){fills.push({id,args});const result={status:'ok',revision:'g'+fills.length,layer_id:'ground-'+fills.length};revision=result.revision;receipts.set(id,result);}return {details:receipts.get(id)};};
 const tools=referenceTools(runtime,execute,fill);return {runtime,calls,fills,receipts,tools,ref,setAfter:f=>after=f,setRevision:r=>revision=r,close:()=>rm(directory,{recursive:true,force:true})};}
test('a job stores no stroke plan; a resume rebuilds it and refuses one that differs',async()=>{
 const h=await harness();try{
  const big={...recipe,steps:[2,1.5,1]};h.setAfter(r=>r.cancelRequested=true);
  const first=await h.tools[0].execute('start',big);assert.equal(first.details.status,'paused');
  const {readdir}=await import('node:fs/promises');
  const files=await readdir(join(h.runtime.study.directory,'reference-paintings'));
  assert.deepEqual(files.filter(f=>f.endsWith('.plan.json')),[],'no plan file');
  const job=JSON.parse(await readFile(join(h.runtime.study.directory,'reference-paintings',first.details.job_id+'.json')));
  assert.deepEqual(job.canvas,{width:64,height:64});
  h.runtime.cancelRequested=false;h.setAfter(()=>{});
  image.data[0]=1;                                          // the decoded reference now differs
  try{await assert.rejects(h.tools[1].execute('continue',{job_id:first.details.job_id}),/rebuilt identically/);}finally{image.data[0]=200;}
  assert.equal(h.calls.length,1,'nothing repainted');
  const rest=await h.tools[1].execute('continue',{job_id:first.details.job_id});assert.equal(rest.details.status,'complete');
 }finally{await h.close();}
});

test('one call paints every scale on its own layer, resumes after stop on the same layer, and never restarts completed work',async()=>{
 const h=await harness();try{
 const big={...recipe,steps:[2,1.5,1]};h.setAfter(r=>r.cancelRequested=true);
 const first=await h.tools[0].execute('start',big);assert.equal(first.details.status,'paused');assert.equal(h.calls.length,1);
 const id=first.details.job_id;h.runtime.cancelRequested=false;h.setAfter(()=>{});
 // Resuming paints all remaining scales (coarse, fine, focal) without handing back to the model.
 const rest=await h.tools[1].execute('continue',{job_id:id});assert.equal(rest.details.status,'complete');assert.equal(h.calls[1].args.continue_layer_id,'layer-1');
 assert.equal(rest.details.completed_strokes,rest.details.total_strokes);
 assert.equal(new Set(h.calls.map(c=>c.args.continue_layer_id).filter(Boolean)).size,3,'each scale keeps its own layer');
 const n=h.calls.length;await h.tools[1].execute('again',{job_id:id});await h.tools[0].execute('start',big);assert.equal(h.calls.length,n);
 assert.equal((await h.tools[2].execute()).details.jobs[0].status,'complete');
 }finally{await h.close();}
});
test('lost acknowledgement reconciles a committed native chunk instead of duplicating it',async()=>{
 const h=await harness();try{h.setAfter(()=>{throw new Error('lost reply');});await assert.rejects(h.tools[0].execute('lost',recipe),/lost reply/);
 const id=createHash('sha256').update('lost').digest('hex').slice(0,32);h.setAfter(()=>{});
 const committed=h.calls[0].id, repainted=[];
 // The committed chunk is reconciled from Krita's receipt, never painted again; the rest of the job continues.
 const freshTools=referenceTools({...h.runtime},async(opId,args)=>{if(opId===committed)throw new Error('A committed chunk must not paint again');repainted.push(opId);return {details:{status:'ok',revision:'x'+repainted.length,layer_id:args.continue_layer_id??'layer-new-'+repainted.length}};});
 const r=await freshTools[1].execute('recover',{job_id:id});assert.equal(h.calls.length,1);assert.ok(!repainted.includes(committed));
 assert.equal(r.details.status,'complete');assert.equal(r.details.completed_strokes,r.details.total_strokes);
 }finally{await h.close();}
});
test('partial receipts, changed canvas/reference and Ask mode cannot resume painting',async()=>{
 const h=await harness();try{const r=await h.tools[0].execute('a',recipe);const id=r.details.job_id,n=h.calls.length;
 h.runtime.mode='ask';await assert.rejects(h.tools[1].execute('b',{job_id:id}),/active Agent/);h.runtime.mode='agent';
 h.setRevision('manual');await assert.rejects(h.tools[1].execute('b',{job_id:id}),/canvas changed/);h.setRevision('r1');
 await writeFile(h.ref,'changed');await assert.rejects(h.tools[1].execute('b',{job_id:id}),/reference changed/);assert.equal(h.calls.length,n);
 }finally{await h.close();}
 const p=await harness();try{p.setAfter(()=>{p.receipts.set(p.calls[0].id,{status:'partial',error:'interrupted'});throw new Error('lost');});await assert.rejects(p.tools[0].execute('partial',recipe));const id=createHash('sha256').update('partial').digest('hex').slice(0,32);await assert.rejects(p.tools[1].execute('retry',{job_id:id}),/uncertain outcome/);assert.equal(p.calls.length,1);}finally{await p.close();}
});

test('a transfer is underpainting: one full transfer per plan, then patches only, and none in the second half of the plan',async()=>{
 const goal=(current_step=0)=>({revision:1,current_step,brief:{steps:[{},{},{},{},{},{}]}});
 const full={...recipe,target:[0,0,64,64]},patch={...recipe,target:[0,0,24,24]};
 assert.equal(transferRefusal(goal(),full,canvas,0),null);
 assert.match(transferRefusal(goal(),full,canvas,1),/missing region of at most 20%.*this target is 100%/);
 assert.equal(transferRefusal(goal(2),patch,canvas,1),null,'a missing region early in the plan');
 assert.match(transferRefusal(goal(3),patch,canvas,0),/off from step 4 of 6/);
 assert.match(transferRefusal(goal(),full,canvas,0,{established:true}),/already exists.*this target is 100%/,'a finishing run on an existing painting');
 assert.equal(transferRefusal(goal(),patch,canvas,0,{established:true}),null,'a missing region of an existing painting');
 const e=await harness();try{
  e.runtime.goal=goal();e.runtime.study.canvas={mode:'current'};
  const observe=e.runtime.callNative;e.runtime.callNative=async(op,p)=>op==='observe'?{...await observe(op,p),layers:[{id:'a'},{id:'b'}]}:observe(op,p);
  await assert.rejects(e.tools[0].execute('finish',full),/already exists/);assert.equal(e.calls.length,0);
  e.runtime.callNative=async(op,p)=>op==='observe'?{...await observe(op,p),layers:[{id:'a'}],filename:'/paintings/finished.jpg'}:observe(op,p);
  await assert.rejects(e.tools[0].execute('finish jpeg',full),/already exists/,'an opened image is one layer but still a painting');
  e.runtime.callNative=async(op,p)=>op==='observe'?{...await observe(op,p),layers:[{id:'a'}],filename:''}:observe(op,p);
  assert.equal((await e.tools[0].execute('blank',full)).details.status,'complete','an unsaved blank document takes a full transfer');
 }finally{await e.close();}
 const h=await harness();try{
  h.runtime.goal=goal();
  assert.equal((await h.tools[0].execute('first',full)).details.status,'complete');
  const n=h.calls.length;
  await assert.rejects(h.tools[0].execute('second',{...full,seed:7}),/paint_contours/);
  assert.equal(h.calls.length,n,'nothing painted');
  assert.equal((await h.tools[0].execute('patch',{...patch,steps:[6,3,1.5]})).details.status,'complete');
  h.runtime.goal={...goal(),revision:2};
  assert.equal((await h.tools[0].execute('new plan',{...full,seed:9})).details.status,'complete','a new plan may transfer again');
 }finally{await h.close();}
});

test('edge strokes follow the reference\u2019s edges, one stroke per side in that side\u2019s colour, deterministically',()=>{
 const W=40,H=30,data=Buffer.alloc(W*H*4);
 for(let y=0;y<H;y++)for(let x=0;x<W;x++)data.set((x-20)**2+(y-15)**2<100?[230,115,40,255]:[30,15,40,255],(y*W+x)*4);
 const disc={width:W,height:H,data},edges={mode:'edges',name:'Rim',reference_id:'ref',preset:'b) Basic-6 Details',source:[0,0,40,30],target:[0,0,160,120]};
 const plan=generateEdgePlan(edges,disc,{width:160,height:120});
 assert.deepEqual(plan,generateEdgePlan(edges,disc,{width:160,height:120}));
 assert.deepEqual(new Set(plan.passes[0].strokes.map(s=>s.color)),new Set(['#e67328','#1e0f28']),'inside and outside colours, never a blend');
 for(const s of plan.passes[0].strokes){const r=Math.hypot(s.start[0]/4-20.5,s.start[1]/4-15.5);assert.ok(r>7&&r<13,'on the rim, not inside or outside: '+r);}
 assert.ok(plan.passes[0].strokes.some(s=>s.segments.length>1),'strokes run along the edge');
 assert.equal(plan.passes[0].strokes[0].size,1.5*4*1.05);
 assert.throws(()=>generateEdgePlan({...edges,min_contrast:1},disc,{width:160,height:120}),/No edges/);
 const noise={width:400,height:400,data:Buffer.from(Array.from({length:400*400*4},(_,i)=>i%4===3?255:(i*7919)%251))};
 assert.throws(()=>generateEdgePlan({...edges,source:[0,0,400,400],target:[0,0,400,400],spacing:.75,min_contrast:.02},noise,{width:400,height:400}),new RegExp(String(EDGE_LIMIT)));
 assert.throws(()=>generateEdgePlan({...edges,steps:[6,3,1]},disc,{width:160,height:120}),/Invalid edge recipe/);
});
test('edge refinement is the finishing tool: allowed on an existing painting where full transfers are refused, and resumable',async()=>{
 const h=await harness();try{
  h.runtime.goal={revision:1,current_step:5,brief:{steps:[{},{},{},{},{},{}]}};h.runtime.study.canvas={mode:'current'};
  const observe=h.runtime.callNative;h.runtime.callNative=async(op,p)=>op==='observe'?{...await observe(op,p),layers:[{id:'a'},{id:'b'}]}:observe(op,p);
  const edgeTool=h.tools.find(t=>t.name==='paint_reference_edges');
  const view=join(h.runtime.study.directory,'view.png');
  await writeFile(view,Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==','base64'));
  h.setAfter((_runtime,result)=>{result.image_path=view;});
  const done=await edgeTool.execute('edges',{name:'Rim',reference_id:'ref',preset:'b) Basic-6 Details',source:[0,0,24,24],target:[0,0,48,48],min_contrast:.05});
  assert.equal(done.details.status,'complete');assert.ok(h.calls.length>0);
  assert.equal(done.details.image_path,view,'Guide pacing sees the canvas after a reference job');
  assert.ok(h.calls.every(c=>c.args.name.startsWith('Rim · Edge refinement')));
  await assert.rejects(h.tools[0].execute('late transfer',{...recipe,target:[0,0,64,64]}),/off from step/);
 }finally{await h.close();}
});

// A soft top-to-bottom ramp (form flowing left to right) split by a hard vertical edge at x=30.
function rampWithEdge(){const W=60,H=40,data=Buffer.alloc(W*H*4);
 for(let y=0;y<H;y++)for(let x=0;x<W;x++){const v=110+y*3;data.set(x<30?[v,v,v,255]:[v/4,v/4,v/4,255],(y*W+x)*4);}
 return {width:W,height:H,data};}
const surface={mode:'surface',name:'Blend',reference_id:'ref',preset:'k) Blender Basic',source:[0,0,60,40],target:[0,0,240,160],spacing:2,length:24,edge_contrast:.3};
test('surface strokes follow the form flow and stay a brush radius clear of edges, deterministically',()=>{
 const ramp=rampWithEdge(),plan=generateSurfacePlan(surface,ramp,{width:240,height:160});
 assert.deepEqual(plan,generateSurfacePlan(surface,ramp,{width:240,height:160}));
 const strokes=plan.passes[0].strokes;assert.ok(strokes.length>50);
 for(const s of strokes){
  const xs=[s.start[0],...s.segments.map(g=>g[4])],ys=[s.start[1],...s.segments.map(g=>g[5])];
  assert.ok(xs.every(x=>x<30*4)||xs.every(x=>x>30*4),'never crosses the edge');
  assert.ok(xs.every(x=>Math.abs(x-30*4)>=2*4),'a brush radius clear of the edge');
  // Away from the edge the flow follows the ramp; within the smoothing reach it turns parallel to the edge.
  const along=Math.max(...xs)-Math.min(...xs),across=Math.max(...ys)-Math.min(...ys),gap=Math.min(...xs.map(x=>Math.abs(x-30*4)));
  if(gap>16*4)assert.ok(across<=along,'runs along the ramp (left to right), not across it');
 }
 assert.ok(strokes.some(s=>{const xs=[s.start[0],...s.segments.map(g=>g[4])],ys=[s.start[1],...s.segments.map(g=>g[5])];
  return Math.min(...xs.map(x=>Math.abs(x-30*4)))<8*4&&Math.max(...ys)-Math.min(...ys)>4*(Math.max(...xs)-Math.min(...xs));}),'next to the edge, strokes run alongside it');
 assert.ok(strokes.some(s=>s.segments.length>=3),'long strokes, not dabs');
 assert.equal(strokes[0].size,2*4*2);
 const noise={width:60,height:40,data:Buffer.from(Array.from({length:60*40*4},(_,i)=>i%4===3?255:(i*7919)%251))};
 assert.throws(()=>generateSurfacePlan({...surface,edge_contrast:.02},noise,{width:240,height:160}),/No smooth surface/,'all edges, no surface');
 assert.throws(()=>generateSurfacePlan({...surface,edge_contrast:1,max_detail:.02},noise,{width:240,height:160}),/No smooth surface/,'busy everywhere: nothing to smudge');
 // Half strength by default, then the edges the smudge stopped at, repainted crisp with a detail brush.
 assert.equal(plan.passes[0].smudge_rate,.5);assert.equal(generateSurfacePlan({...surface,strength:.3},ramp,{width:240,height:160}).passes[0].smudge_rate,.3);
 assert.deepEqual(plan.passes.map(p=>[p.name,p.preset]),[['Surface blending',undefined],['Edge refinement','b) Basic-6 Details']]);
 assert.equal(plan.total,plan.passes[0].strokes.length+plan.passes[1].strokes.length);
 assert.equal(generateSurfacePlan({...surface,edges:false},ramp,{width:240,height:160}).passes.length,1);
 assert.throws(()=>generateSurfacePlan({...surface,min_contrast:.1},ramp,{width:240,height:160}),/Invalid surface recipe/);
 const flat={width:600,height:600,data:Buffer.alloc(600*600*4,255)};
 assert.throws(()=>generateSurfacePlan({...surface,source:[0,0,600,600],target:[0,0,600,600],spacing:1},flat,{width:600,height:600}),new RegExp(String(SURFACE_LIMIT)));
});
test('the surface tool smudges in overlay mode on its own layer, also late on an existing painting',async()=>{
 const h=await harness();try{
  h.runtime.goal={revision:1,current_step:5,brief:{steps:[{},{},{},{},{},{}]}};h.runtime.study.canvas={mode:'current'};
  const observe=h.runtime.callNative;h.runtime.callNative=async(op,p)=>op==='observe'?{...await observe(op,p),layers:[{id:'a'},{id:'b'}]}:op==='decode_reference'?(()=>{const r=rampWithEdge();return {width:r.width,height:r.height,rgba_base64:r.data.toString('base64'),sha256:p.sha256};})():observe(op,p);
  const tool=h.tools.find(t=>t.name==='paint_reference_surface');
  const {mode,...args}=surface;
  const done=await tool.execute('surface',{...args,target:[0,0,60,40]});
  assert.equal(done.details.status,'complete');assert.ok(h.calls.length>0);
  const smudged=h.calls.filter(c=>c.args.smudge_overlay),edged=h.calls.filter(c=>!c.args.smudge_overlay);
  assert.ok(smudged.length&&smudged.every(c=>c.args.preset==='k) Blender Basic'&&c.args.smudge_rate===.5));
  assert.ok(edged.length&&edged.every(c=>c.args.preset==='b) Basic-6 Details'&&!('smudge_rate' in c.args)),'then crisp edges, without overlay');
  assert.ok(h.calls.indexOf(edged[0])>h.calls.indexOf(smudged.at(-1)),'edges after the smudge');
 }finally{await h.close();}
});
test('a repair patch fades out toward existing paint, not toward the canvas border',()=>{
 const centre=s=>[s.start[0]+s.segments[0][4],s.start[1]+s.segments[0][5]].map(v=>v/2);
 const big={width:200,height:200};
 const corner=generateReferencePlan({...recipe,focal_regions:undefined,target:[104,104,96,96]},image,big).passes.flatMap(p=>p.strokes);
 const near=corner.filter(s=>centre(s)[0]<110),far=corner.filter(s=>centre(s)[0]>120&&centre(s)[1]>120);
 assert.ok(near.length&&near.every(s=>s.opacity<.5),'the inner sides of a lower-right patch blend into the painting');
 assert.ok(far.length&&far.every(s=>s.opacity===1),'past the band the patch is opaque, up to the canvas border it touches');
 const whole=generateReferencePlan({...recipe,focal_regions:undefined,target:[0,0,64,64]},image,canvas).passes.flatMap(p=>p.strokes);
 assert.ok(whole.every(s=>s.opacity===1),'a full transfer has no inner edge');
});
test('a repair patch stretched past 2x is refused on an existing painting or after a transfer',()=>{
 const goal={revision:1,current_step:0,brief:{steps:[{},{},{},{},{},{}]}},big={width:6000,height:4500};
 const stretched={...recipe,source:[963,795,485,291],target:[4000,3300,2000,1200]},sharp={...recipe,source:[0,0,1000,600],target:[4000,3300,2000,1200]};
 assert.match(transferRefusal(goal,stretched,big,0,{established:true}),/stretches the reference 4.1x.*past 2x/,'the traced snow repair');
 assert.match(transferRefusal(goal,stretched,big,1),/stretches/);
 assert.equal(transferRefusal(goal,sharp,big,0,{established:true}),null,'2x from a sharper crop');
 assert.equal(transferRefusal(goal,{...stretched,target:[0,0,6000,3600],source:[0,0,1448,869]},big,0),null,'the first underpainting transfer may stretch');
});
test('a focal patch (one face or hand) is allowed at any step, even on an existing painting after a transfer',()=>{
 const late={revision:1,current_step:5,brief:{steps:[{},{},{},{},{},{}]}},big={width:1000,height:1000};
 const hand={...recipe,source:[0,0,100,100],target:[400,400,170,170]},head={...recipe,source:[0,0,100,100],target:[400,400,180,180]};
 assert.equal(transferRefusal(late,hand,big,1,{established:true}),null,'2.9% of the canvas');
 assert.match(transferRefusal(late,head,big,1,{established:true}),/off from step 4 of 6.*focal patch.*at most 3%/,'3.2% is not a focal patch');
});
test('busy areas (windows, reflections, fur) are not smudged',()=>{
 // Left half: a smooth ramp. Right half: a fine checkerboard of weak contrast, like lit windows or snow.
 const W=60,H=40,data=Buffer.alloc(W*H*4);
 for(let y=0;y<H;y++)for(let x=0;x<W;x++){const v=x<30?110+y*2:((x>>1)+(y>>1))%2?150:110;data.set([v,v,v,255],(y*W+x)*4);}
 const plan=generateSurfacePlan({...surface,edges:false},{width:W,height:H,data},{width:240,height:160});
 const xs=plan.passes[0].strokes.flatMap(s=>[s.start[0],...s.segments.map(g=>g[4])]);
 assert.ok(xs.length&&xs.every(x=>x<30*4),'only the smooth half');
});

test('a blank saved document is not an existing painting; what is visible decides',()=>{
 const current={study:{canvas:{mode:'current'}}};
 // Krita's new document, saved: Background plus an empty Paint Layer 1 (the live blood-moon run).
 const blank={layers:[{name:'Background'},{name:'Paint Layer 1'}],filename:'/art/Creative painting 31.kra',painted_share:0};
 assert.equal(existingPainting(current,blank),false);
 assert.equal(existingPainting(current,{...blank,painted_share:PAINTED_SHARE/2}),false,'a few marks on a blank canvas');
 assert.equal(existingPainting(current,{layers:[{name:'Background'}],painted_share:0.6}),true,'one flattened painting');
 assert.equal(existingPainting({study:{canvas:{mode:'new'}}},{...blank,painted_share:0.9}),false,'a new canvas the agent made');
 assert.equal(existingPainting(current,{layers:blank.layers,filename:blank.filename}),true,'an older plugin without painted_share keeps the old rule');
});

test('under a time allowance a transfer widens its steps to fit; without one, or when it fits, it is left alone',()=>{
 // The traced 20-minute Starry Night: 184,000 planned strokes, 24,576 painted when time ran out.
 const starry={...recipe,source:[10,10,1900,1500],target:[0,0,1520,1200],steps:[10,5,2.5],focal_regions:[[600,100,400,300],[1500,300,300,700]]};
 const left=18*60,fit=fitStepsToTime(starry,left);
 assert.ok(fit.strokes>180000);
 assert.ok(estimateReferenceStrokes(fit.recipe)<=left*TRANSFER_TIME_SHARE*STROKES_PER_SECOND*1.1,'about half the time left at the slow rate');
 assert.deepEqual(fit.from,[10,5,2.5]);
 const [a,b,c]=fit.recipe.steps;assert.ok(a>b&&b>c&&c>2.5,'still coarse to fine, every step wider');
 assert.equal(fitStepsToTime(starry,10*3600),null,'ten hours is enough');
 assert.ok(estimateReferenceStrokes(fitStepsToTime(starry,left,40).recipe)>estimateReferenceStrokes(fit.recipe),'a faster measured rate keeps finer steps');
 const capped=fitStepsToTime({...starry,steps:[160,80,40]},5).recipe.steps;
 assert.ok(capped[0]<=256&&capped[0]>capped[1]&&capped[1]>capped[2],'the STEP_MAX cap (256, for a goal sharpened 4x) keeps the order');
});
test('a job sized to the time left records what was asked, tells the painter, and replays under the same ID',async()=>{
 const h=await harness();try{
  h.runtime.goal={revision:1,current_step:0,brief:{steps:[{},{},{}]}};h.runtime.timeLeftMs=()=>3000;
  const native=h.runtime.callNative.bind(h.runtime);h.runtime.study.canvas={mode:'current'};h.runtime.callNative=async(op,p)=>op==='observe'?{...await native(op,p),layers:[{name:'Background'}],painted_share:.6,filename:'/art/a.kra'}:native(op,p);
  const asked={...recipe,source:[0,0,24,24],target:[0,0,24,24],steps:[2,1.5,1]};
  const first=await h.tools[0].execute('sized',asked);
  assert.match(first.details.fitted,/Steps widened from \[2,1.5,1\]/);
  const job=JSON.parse(await readFile(join(h.runtime.study.directory,'reference-paintings',first.details.job_id+'.json')));
  assert.deepEqual(job.requested.steps,[2,1.5,1]);assert.ok(job.recipe.steps[0]>2);
  const n=h.calls.length;assert.equal((await h.tools[0].execute('sized',asked)).details.job_id,first.details.job_id);assert.equal(h.calls.length,n,'the same call replays');
 }finally{await h.close();}
});
test('an Agent move sizes a transfer to one move: a traced clouds move planned 156,304 strokes and painted for ten minutes',()=>{
 const starry={...recipe,source:[10,10,1900,1500],target:[0,0,1520,1200],steps:[10,5,2.5],focal_regions:[[600,100,400,300],[1500,300,300,700]]};
 const fit=fitStepsToBudget(starry,AGENT_MOVE_STROKES);
 assert.ok(estimateReferenceStrokes(fit.recipe)<=AGENT_MOVE_STROKES*1.1);
 assert.equal(fitStepsToBudget(starry,10*AGENT_MOVE_STROKES),null,'a plan within the budget is left alone');
 assert.ok(AGENT_MOVE_STROKES>=20000&&AGENT_MOVE_STROKES<=60000,'about two minutes at a measured 300 strokes a second');
});
test('in an Agent move a transfer is sized to the move even without a time allowance, and the painter is told',async()=>{
 const h=await harness();try{
  h.runtime.goal={revision:1,current_step:0,brief:{steps:[{},{},{}]}};h.runtime.mode='agent';h.runtime.config={...h.runtime.config,agent_transfer_strokes:500};
  // Over an existing painting (not the whole-picture underpainting, which has its own budget: the tests below).
  const native=h.runtime.callNative.bind(h.runtime);h.runtime.study.canvas={mode:'current'};h.runtime.callNative=async(op,p)=>op==='observe'?{...await native(op,p),layers:[{name:'Background'}],painted_share:.6,filename:'/art/a.kra'}:native(op,p);
  const asked={...recipe,source:[0,0,24,24],target:[0,0,24,24],steps:[2,1.5,1]};
  const first=await h.tools[0].execute('move-sized',asked);
  assert.match(first.details.fitted,/Steps widened from \[2,1.5,1\].*one Agent move/);
  assert.ok(first.details.total_strokes<=550,first.details.total_strokes);
 }finally{await h.close();}
});
test('on a fresh canvas the first transfer from a reference with the canvas\u2019s proportions covers all of it',()=>{
 // The traced Great Wave: the wave alone first, then only 20% patches, so the sky, boats and Fuji never came.
 const wave={...recipe,source:[152,60,864,840],target:[119,48,684,665]},canvas={width:1520,height:1022},ref={width:1920,height:1291,role:'reference'};
 const refusal=wholeReferenceRefusal(wave,ref,canvas);
 assert.match(refusal,/source \[0,0,1920,1291\], target \[0,0,1520,1022\]/);
 const big={width:1920,height:1291,data:Buffer.alloc(1920*1291*4,255)};
 assert.equal(generateReferencePlan({...wave,source:[0,0,1920,1291],target:[0,0,1520,1022],steps:[60,30,15]},big,canvas).canvas.width,1520,'the suggested rectangles are accepted');
 assert.equal(wholeReferenceRefusal({...wave,source:[10,10,1900,1278],target:[0,0,1520,1022]},ref,canvas),null,'nearly all of it');
 assert.match(wholeReferenceRefusal({...wave,source:[600,300,760,511],target:[0,0,1520,1022]},ref,canvas),/all of it/,'a zoomed crop over the whole canvas');
 assert.equal(wholeReferenceRefusal(wave,{...ref,width:800,height:1200},canvas),null,'a part (a figure for a landscape) may go anywhere');
 assert.equal(wholeReferenceRefusal(wave,{...ref,role:'asset'},canvas),null,'an AI image asset is a part');
 assert.equal(wholeReferenceRefusal({...wave,target:[100,100,150,100]},ref,canvas),null,'a focal patch');
 // Starry Night and Pearl Earring, as the painter mapped them.
 assert.equal(wholeReferenceRefusal({...recipe,source:[10,10,1900,1500],target:[0,0,1520,1200]},{width:1920,height:1520},{width:1520,height:1200}),null);
 assert.match(wholeReferenceRefusal({...recipe,source:[4,0,1144,1352],target:[0,0,1100,1300]},{width:1920,height:2274},{width:1100,height:1300}),/all of it/,'a quarter of the Vermeer');
});
test('the toned ground grades through the reference\u2019s colours top to bottom, and none goes under a cut-out',()=>{
 const W=30,H=60,data=Buffer.alloc(W*H*4);
 for(let y=0;y<H;y++)for(let x=0;x<W;x++)data.set(y<H/2?[20,30,120,255]:[200,150,40,255],(y*W+x)*4);
 const stops=groundStops({width:W,height:H,data},[0,0,W,H]);
 assert.equal(stops[0].offset,0);assert.equal(stops.at(-1).offset,1);
 assert.equal(stops[0].color,'#141e78');assert.equal(stops.at(-1).color,'#c89628');
 assert.ok(stops.every((s,i)=>!i||s.offset>stops[i-1].offset));
 const cut=Buffer.from(data);for(let i=3;i<cut.length;i+=8)cut[i]=0;
 assert.equal(groundStops({width:W,height:H,data:cut},[0,0,W,H]),null);
});
test('the first full transfer lays the ground once, before any dab; patches and resumes do not',async()=>{
 const h=await harness();try{
  h.runtime.goal={revision:1,current_step:0,brief:{steps:[{},{},{},{},{},{}]}};
  const full={...recipe,target:[0,0,64,64],steps:[2,1.5,1]};h.setAfter(r=>r.cancelRequested=true);
  const first=await h.tools[0].execute('full',full);assert.equal(first.details.status,'paused');
  assert.equal(h.fills.length,1);assert.equal(h.fills[0].id,'reference-'+first.details.job_id+'-ground');
  assert.deepEqual(h.fills[0].args.area,[{shape:'rectangle',bounds:[0,0,64,64]}]);
  assert.equal(h.fills[0].args.gradient.stops[0].color,'#691469','the left red and right blue average in each band');
  assert.match(first.details.ground,/toned ground/);
  h.runtime.cancelRequested=false;h.setAfter(()=>{});
  assert.equal((await h.tools[1].execute('resume',{job_id:first.details.job_id})).details.status,'complete');
  assert.equal(h.fills.length,1,'a resume does not fill again');
  await h.tools[0].execute('patch',{...recipe,target:[0,0,24,24]});assert.equal(h.fills.length,1,'a patch goes over paint');
 }finally{await h.close();}
 const s=await harness();try{
  s.runtime.goal={revision:1,current_step:0,brief:{steps:[{},{}]}};s.runtime.cancelRequested=true;
  await assert.rejects(s.tools[0].execute('stopped',{...recipe,target:[0,0,64,64]}),/requires active Agent/);assert.equal(s.fills.length,0,'after Stop nothing is filled');
 }finally{await s.close();}
});

test('an active protected area lifts the transfer size caps; without one they hold',()=>{
 // New Moscow: a sky a third of a 6000x4500 canvas, on the existing painting.
 const goal={revision:1,current_step:0,brief:{steps:[{},{},{},{}]}},canvas={width:6000,height:4500};
 const sky={...recipe,source:[0,0,3000,750],target:[0,0,6000,1500]};          // 2x: sharp enough
 assert.match(transferRefusal(goal,sky,canvas,0,{established:true}),/already exists/);
 assert.equal(transferRefusal(goal,sky,canvas,0,{established:true,protectedAreas:1}),null,'the artist protected what matters');
 assert.equal(transferRefusal(goal,sky,canvas,1,{protectedAreas:2}),null,'a second transfer too');
 assert.match(transferRefusal({...goal,current_step:3},sky,canvas,0,{protectedAreas:1}),/off from step/,'the late-plan rule still holds');
});
test('a transfer passes the painting\u2019s active protected areas to the size rule',async()=>{
 const h=await harness();try{
  h.runtime.goal={revision:1,current_step:0,brief:{steps:[{},{},{},{},{},{}]}};h.runtime.study.canvas={mode:'current'};
  const observe=h.runtime.callNative;
  h.runtime.callNative=async(op,p)=>op==='observe'?{...await observe(op,p),painted_share:.9,protected_areas:[{id:'m',name:'Car',bounds:[0,0,8,8]}]}:observe(op,p);
  assert.equal((await h.tools[0].execute('protected',{...recipe,target:[0,0,48,48]})).details.status,'complete');   // 56%, at 2x
 }finally{await h.close();}
});

test('a transfer from a reference part is the artist\u2019s choice of area: measured by the part, not refused for its size',()=>{
 const goal={revision:1,current_step:0,brief:{steps:[{},{},{},{}]}},canvas={width:6000,height:4500};
 const sky={...recipe,source:[0,0,3000,2250],target:[0,0,6000,4500]},part={part_kind:'part',bounds:[0,0,3000,560]};
 assert.match(transferRefusal(goal,sky,canvas,0,{established:true}),/already exists/,'a whole-canvas transfer from the full reference');
 assert.equal(transferRefusal(goal,sky,canvas,0,{established:true,part}),null,'from the sky part: only the sky is painted');
 assert.equal(transferRefusal(goal,sky,canvas,1,{part}),null,'after an earlier transfer too');
 assert.ok(Math.abs(partShare(sky,part)-560/2250)<1e-9,'the share is the part\u2019s area within the source');
 assert.match(transferRefusal({...goal,current_step:3},sky,canvas,0,{part}),/off from step/,'late in an Autopilot plan a large part is still refused');
 assert.equal(wholeReferenceRefusal(sky,{width:3000,height:2250,role:'reference',part_kind:'part'},canvas),null,'a part is not the whole picture');
});
test('the painter is told what a reference part and a crop are',async()=>{
 const {PAINTING_INSTRUCTIONS}=await import('../src/prompt.mjs');
 assert.match(PAINTING_INSTRUCTIONS,/A part reference \(part_of\) is see-through outside the one area to follow; a transfer from it paints only that area, in the place it has in the original\. A crop is a close-up of bounds of the original\./);
});

test('a reference of up to 64 MB transfers (a goal sharpened 4x), a part or a whole picture; a larger one is refused',async()=>{
 const h=await harness();try{
  const big=join(h.runtime.study.directory,'big.png');await writeFile(big,Buffer.alloc(6*1024*1024));
  h.runtime.study.references.push({id:'part',path:big,part_kind:'part',bounds:[0,0,24,24]},{id:'plain',path:big});
  assert.equal((await h.tools[0].execute('part',{...recipe,reference_id:'part'})).details.status,'complete');
  assert.equal((await h.tools[0].execute('plain',{...recipe,reference_id:'plain'})).details.status,'complete','over the old 5 MB');
  const huge=join(h.runtime.study.directory,'huge.png');await writeFile(huge,Buffer.alloc(65*1024*1024));
  h.runtime.study.references.push({id:'huge',path:huge});
  await assert.rejects(h.tools[0].execute('huge',{...recipe,reference_id:'huge'}),/smaller than 64 MB/);
 }finally{await h.close();}
});
test('the painter protects what the artist says to leave alone, by name, before painting',async()=>{
 const {PAINTING_INSTRUCTIONS}=await import('../src/prompt.mjs');
 assert.match(PAINTING_INSTRUCTIONS,/When the request names things to leave alone \("without touching the buildings or the car"\), propose_protection each of them by name before the first pass near them/);
 assert.match(PAINTING_INSTRUCTIONS,/Never paint a test fill to check a selection/);
});

// after-the-underpainting goal 2: a traced chat stretched the goal 4x for the hair (210x180 onto 870x746) and 4x for the figure.
test('edges and surface transfers stretched past 2x are refused on a painted canvas, naming the area and the enlargement',()=>{
 const hair={mode:'surface',name:'Hair',source:[210,100,210,180],target:[2400,800,870,746]};
 const message=stretchRefusal(hair,{established:true});
 assert.match(message,/"Hair".*\[2400,800,870,746\]/,'names the area');
 assert.match(message,/4\.1x.*210 source px over 870 canvas px.*past 2x/,'names the enlargement');
 assert.match(message,/sharper or closer reference of this area.*or stop/i,'asks for a closer reference or to stop there');
 assert.match(stretchRefusal(hair,{paintedJobs:1}),/4\.1x/,'after any painted job too');
 assert.equal(stretchRefusal(hair,{}),null,'a fresh canvas with no transfer yet');
 assert.equal(stretchRefusal({...hair,source:[0,0,435,373]},{established:true}),null,'2x from a sharper crop');
 // No focal exemption: a 2.4% hair area is where the stretch shows most (the patch rule keeps its own).
 assert.match(stretchRefusal({...hair,mode:'edges'},{established:true}),/edges/);
});
test('the edges and surface tools apply the stretch limit after a painted transfer or on an existing painting, a part as any reference',async()=>{
 const h=await harness();try{
  const edgeTool=h.tools.find(t=>t.name==='paint_reference_edges'),surfaceTool=h.tools.find(t=>t.name==='paint_reference_surface');
  const stretched={name:'Rim',reference_id:'ref',preset:'b) Basic-6 Details',source:[6,6,12,12],target:[0,0,48,48],min_contrast:.05};
  const first=await edgeTool.execute('first edges',stretched);
  assert.equal(first.details.status,'complete','the first transfer on a fresh canvas may stretch');
  await assert.rejects(edgeTool.execute('second edges',{...stretched,name:'Rim again'}),/"Rim again".*stretches the reference 4x/,'after a painted job');
  await assert.rejects(surfaceTool.execute('surface',{name:'Blend',reference_id:'ref',preset:'k) Blender Basic',source:[6,6,12,12],target:[0,0,48,48]}),/stretches the reference 4x/);
  h.runtime.study.references[0]={...h.runtime.study.references[0],part_kind:'part',bounds:[6,6,12,12]};
  await assert.rejects(edgeTool.execute('part edges',{...stretched,name:'Part rim'}),/stretches/,'a part is measured like any reference');
 }finally{await h.close();}
 const fresh=await harness();try{
  fresh.runtime.study.canvas={mode:'current'};
  const observe=fresh.runtime.callNative;fresh.runtime.callNative=async(op,p)=>op==='observe'?{...await observe(op,p),painted_share:.8}:observe(op,p);
  await assert.rejects(fresh.tools.find(t=>t.name==='paint_reference_edges').execute('edges',{name:'Rim',reference_id:'ref',preset:'b) Basic-6 Details',source:[6,6,12,12],target:[0,0,48,48],min_contrast:.05}),/stretches/,'an existing painting');
 }finally{await fresh.close();}
});

test('a focal patch is not exempt from the stretch limit on a painted canvas: every transfer gets the same refusal',()=>{
 const late={revision:1,current_step:5,brief:{steps:[{},{},{},{},{},{}]}},big={width:1000,height:1000};
 const hand={...recipe,name:'Hand',source:[0,0,40,40],target:[400,400,170,170]};               // 4.3x, 2.9% of the canvas
 assert.equal(transferRefusal(late,hand,big,1,{established:true}),stretchRefusal(hand,{established:true}),'the same message as edges and surface');
 assert.match(transferRefusal(late,hand,big,0,{established:true}),/A patch transfer of "Hand" at \[400,400,170,170\] stretches the reference 4.3x/);
 assert.match(transferRefusal(late,hand,big,1),/stretches/,'after a painted transfer too');
 assert.equal(transferRefusal(late,hand,big,0),null,'a fresh canvas: the first transfer may stretch');
 assert.equal(transferRefusal(late,{...hand,source:[0,0,85,85]},big,1,{established:true}),null,'2x from a close-up: the focal exemption still lifts the size and late-plan rules');
});

// The artist's rule: an undone colour pass counts as not done. Its job file stays, so the tools ask the studio which jobs' moves were all undone.
test('a transfer whose moves were all undone counts as not painted: the whole underpainting may be retried and nothing is stretched against it',async()=>{
 const h=await harness();try{
  const undone=new Set();h.runtime.undoneReferenceJobs=()=>undone;
  h.runtime.goal={revision:1,current_step:0,brief:{steps:[{},{},{},{}]}};
  const whole={...recipe,source:[0,0,24,24],target:[0,0,64,64],focal_regions:undefined};
  assert.equal((await h.tools[0].execute('first',whole)).details.status,'complete');
  await assert.rejects(h.tools[0].execute('again',{...whole,name:'Again'}),/already has a reference transfer/,'a kept transfer still counts');
  const edges={name:'Rim',reference_id:'ref',preset:'b) Basic-6 Details',source:[6,6,12,12],target:[0,0,48,48],min_contrast:.05};
  await assert.rejects(h.tools.find(t=>t.name==='paint_reference_edges').execute('edges',edges),/stretches/);
  undone.add(createHash('sha256').update('first').digest('hex').slice(0,32));
  assert.equal((await h.tools.find(t=>t.name==='paint_reference_edges').execute('edges after undo',edges)).details.status,'complete','the undone transfer is not a painted job');
  undone.add(createHash('sha256').update('edges after undo').digest('hex').slice(0,32));
  assert.equal((await h.tools[0].execute('retry',{...whole,name:'Retry'})).details.status,'complete','the whole underpainting again after an Undo');
 }finally{await h.close();}
});
test('the stretch limit counts painted jobs of this plan revision, as the transfer rules do',async()=>{
 const h=await harness();try{
  h.runtime.goal={revision:1,current_step:0,brief:{steps:[{},{},{},{}]}};
  const edges={name:'Rim',reference_id:'ref',preset:'b) Basic-6 Details',source:[6,6,12,12],target:[0,0,48,48],min_contrast:.05};
  assert.equal((await h.tools.find(t=>t.name==='paint_reference_edges').execute('one',edges)).details.status,'complete');
  h.runtime.goal={...h.runtime.goal,revision:2};
  assert.equal((await h.tools.find(t=>t.name==='paint_reference_edges').execute('two',{...edges,name:'Rim 2'})).details.status,'complete','a job of an earlier plan revision');
 }finally{await h.close();}
});

// A goal sharpened 4x (goal-sharpen.ts): read whole, decoded in the companion, and a rect in its old pixels scaled.
test('a large plain PNG reference is decoded in the companion, not on Krita’s GUI thread; a stale rect of the old goal is scaled',async()=>{
 const {encodeRgb}=await import('../src/upscale/png.ts');
 const h=await harness();try{
  const W=2400,H=2000,rgb=new Uint8Array(W*H*3);for(let i=0;i<W*H;i++){rgb[i*3]=(i%W)<W/2?200:10;rgb[i*3+1]=20;rgb[i*3+2]=(i%W)<W/2?10:200;}
  await writeFile(h.ref,encodeRgb(W,H,rgb));
  const asked=[],native=h.runtime.callNative;h.runtime.callNative=async(op,p)=>{asked.push(op);return native(op,p);};
  const goal=h.runtime.study.references[0];Object.assign(goal,{width:W,height:H,sharpened:{from:{sha256:'old',width:600,height:500,path:h.ref}}});
  const done=await h.tools[0].execute('big',{...recipe,focal_regions:undefined,source:[0,0,600,600],target:[2,2,48,48],steps:[48,24,12]});
  assert.equal(done.details.status,'complete');
  assert.ok(!asked.includes('decode_reference'),'5 MP: not sent to Krita');
  const {readdir}=await import('node:fs/promises'),folder=join(h.runtime.study.directory,'reference-paintings');
  const jobs=async()=>Promise.all((await readdir(folder)).filter(n=>n.endsWith('.json')).map(async n=>JSON.parse(await readFile(join(folder,n),'utf8'))));
  assert.deepEqual((await jobs())[0].recipe.source,[0,0,600,600],'a new rect is taken as written');
  const stale=await h.tools[0].execute('stale',{...recipe,focal_regions:undefined,source:[0,0,600,500],target:[2,2,48,40],steps:[48,24,12]});
  assert.equal(stale.details.status,'complete');
  const scaled=(await jobs()).find(j=>j.requested?.source?.[2]===600&&j.requested.source[3]===500);
  assert.deepEqual(scaled?.recipe.source,[0,0,2400,2000],'the old picture’s whole rect, in the sharpened pixels');
 }finally{await h.close();}
});

test('edges and surface analyse a very large crop from a reduced copy, spacing and length scaled with it; the target is unchanged',async()=>{
 const {analysisCopy}=await import('../src/reference-generator.mjs');
 const big={width:3000,height:2000,data:Buffer.alloc(3000*2000*4,128)};
 const edges={name:'E',reference_id:'ref',preset:'Basic',mode:'edges',source:[0,0,3000,2000],target:[0,0,3000,2000]};
 const a=analysisCopy(edges,big,1_500_000);
 assert.deepEqual([a.image.width,a.image.height],[1500,1000]);
 assert.deepEqual(a.recipe.source,[0,0,1500,1000]); assert.deepEqual(a.recipe.target,[0,0,3000,2000]);
 assert.equal(a.recipe.spacing,.75,'the default 1.5 source pixels, halved');
 const surface=analysisCopy({...edges,mode:'surface',spacing:8,length:40},big,1_500_000);
 assert.deepEqual([surface.recipe.spacing,surface.recipe.length],[4,20]);
 assert.equal(analysisCopy({...edges,source:[0,0,1000,1000]},big,1_500_000).image,big,'a crop within the limit is read as it is');
 assert.equal(analysisCopy({...edges,mode:undefined},big,1_500_000).image,big,'the dab transfer reads it whole');
});

// Rehearsal finding 2 (Toska, 2026-10-24): the New Moscow underpainting (goal 1448 x 1086 onto 6000 x 4500) was fitted to
// the 40,000-stroke move budget, from [5,2,1] to [16.89,6.76,3.38] source px: 28 canvas px between fine dabs, 39,958
// strokes in 57 s. The whole-picture underpainting has its own budget, and its steps are set on the canvas.
test('the whole-picture underpainting: steps set in canvas pixels, so a sharpened goal is not given 4x larger steps',()=>{
 assert.deepEqual(UNDERPAINTING_CANVAS_STEPS,[24,5,2.5]);
 const original={source:[0,0,1448,1086],target:[0,0,6000,4500]},sharpened={source:[0,0,5792,4344],target:[0,0,6000,4500]};
 assert.deepEqual(canvasSteps(original),[5.79,1.21,.75],'a source pixel is 4.1 canvas px: the focal step stops at the schema minimum');
 assert.deepEqual(canvasSteps(sharpened),[23.17,4.83,2.41]);
 for(const r of [original,sharpened]){const k=r.target[2]/r.source[2];assert.ok(Math.abs(canvasSteps(r)[1]*k-5)<.05,'5 canvas px between fine dabs, whatever the goal’s size');}
 assert.deepEqual(canvasSteps({source:[0,0,600,450],target:[0,0,6000,4500]}),[2.4,1,.75],'a tiny goal: fine dabs a source pixel apart, never finer (no detail there)');
 const [a,b,c]=canvasSteps({source:[0,0,24,24],target:[0,0,6000,6000]});assert.ok(a>b&&b>c,'still coarse to fine');
});
test('the underpainting budget: five minutes at the measured rate, at most 250,000 strokes; New Moscow 2.4x finer than the rehearsal',()=>{
 assert.equal(MEASURED_STROKES_PER_SECOND,700,'39,958 strokes in 57 s in Toska');
 assert.equal(UNDERPAINTING_MINUTES,5);assert.equal(UNDERPAINTING_STROKES,250000);
 assert.equal(underpaintingBudget(),210000);assert.equal(underpaintingBudget(700),210000);
 assert.equal(underpaintingBudget(5000),250000,'a fast machine: the plan size cap');
 assert.equal(underpaintingBudget(100),30000,'a slow machine: still about five minutes');
 const fine=r=>{const fit=fitStepsToBudget({...r,steps:canvasSteps(r)},underpaintingBudget());return {canvas:fit.recipe.steps[1]*r.target[2]/r.source[2],strokes:estimateReferenceStrokes(fit.recipe)};};
 const original=fine({source:[0,0,1448,1086],target:[0,0,6000,4500]}),sharpened=fine({source:[0,0,5792,4344],target:[0,0,6000,4500]});
 assert.ok(original.canvas>11&&original.canvas<12.5,'about 11.7 canvas px between fine dabs, against 28 in the rehearsal: '+original.canvas);
 assert.ok(Math.abs(sharpened.canvas-original.canvas)<.5,'the sharpened goal paints the same dab grid, with sharper colours in each dab');
 for(const r of [original,sharpened])assert.ok(r.strokes<=underpaintingBudget()*1.02&&r.strokes>underpaintingBudget()*.9,String(r.strokes));
});
test('an Agent move’s whole-picture transfer takes the underpainting budget and canvas steps; the painter is told, patches keep the move budget',async()=>{
 const h=await harness();try{
  h.runtime.goal={revision:1,current_step:0,brief:{steps:[{},{},{}]}};h.runtime.mode='agent';
  const asked={...recipe,source:[0,0,24,24],target:[0,0,64,64],steps:[5,2,1]};delete asked.focal_regions;
  const first=await h.tools[0].execute('whole',asked);
  const job=JSON.parse(await readFile(join(h.runtime.study.directory,'reference-paintings',first.details.job_id+'.json')));
  assert.deepEqual(job.requested.steps,[5,2,1]);
  assert.deepEqual(job.recipe.steps,canvasSteps(asked),'the host sets the underpainting’s steps on the canvas');
  assert.match(first.details.fitted,/whole-picture underpainting/);assert.match(first.details.fitted,/5 canvas px between fine dabs/);
 }finally{await h.close();}
 const small=await harness();try{
  small.runtime.goal={revision:1,current_step:0,brief:{steps:[{},{},{}]}};small.runtime.mode='agent';small.runtime.config={...small.runtime.config,underpainting_strokes:60};
  const asked={...recipe,source:[0,0,24,24],target:[0,0,64,64],steps:[5,2,1]};delete asked.focal_regions;
  const first=await small.tools[0].execute('whole-small',asked);
  assert.match(first.details.fitted,/widened to fit the underpainting budget \(about 60 strokes/);
  assert.ok(first.details.total_strokes<=66,String(first.details.total_strokes));
 }finally{await small.close();}
});

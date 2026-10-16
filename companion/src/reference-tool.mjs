import { isPaintingMode } from './modes.mjs';
import {createHash} from 'node:crypto';
import {mkdir,readFile,writeFile,rename,readdir,stat} from 'node:fs/promises';
import {join} from 'node:path';
import {Type} from 'typebox';
import {containedFile,imageContent} from './files.mjs';
import {referenceSchema,edgeSchema,surfaceSchema,generateReferencePlan,generateEdgePlan,generateSurfacePlan,REFERENCE_GENERATOR_VERSION} from './reference-generator.mjs';
// Strokes per native call. Each call re-reads the canvas and journals its receipt; at 128 that
// overhead was ~80% of a 157k-stroke job. The plugin accepts up to 1024 per pass.
export const REFERENCE_BATCH=1024;
const hash=value=>createHash('sha256').update(value).digest('hex');
const atomic=async(path,value)=>{await writeFile(path+'.tmp',JSON.stringify(value)+'\n');await rename(path+'.tmp',path);};
// Jobs belong to a plan revision. Older jobs also recorded a stage; steps no longer gate work.
const scope=r=>r.goal?JSON.stringify([r.goal.revision]):null;
const sameScope=(job,r)=>{if(job.scope===scope(r))return true;try{return !!r.goal&&JSON.parse(job.scope)[0]===r.goal.revision;}catch{return false;}};
const allowed=r=>{if(!isPaintingMode(r.mode)||r.executionPhase!=='agent'||r.cancelRequested||r.faulted)throw new Error('Reference painting requires active Agent execution without pending recovery.');};
const summary=j=>({job_id:j.id,name:j.recipe.name,status:j.status,completed_strokes:j.completed,total_strokes:j.total,pass:j.pass+1,pass_count:j.pass_count,next_action:j.status==='complete'?'Review the finished canvas.':j.status==='awaiting_review'?'Inspect this pass image, then continue_reference_painting for the next refinement pass.':'Resume with continue_reference_painting after inspecting any interruption.'});
// A transfer is underpainting: on a large canvas its dabs are 25-60 px whatever the steps, so running
// it again re-rolls the same mosaic. A traced run spent 8 hours on five transfers and ten blur masks
// in the last steps and never painted the hands, mirror or materials. Past the first half of the plan
// it is refused; after one transfer has painted, or on a painting that already existed (a live finishing
// run's first move on the New Moscow mosaic was a whole-canvas transfer), only a patch of at most REGION_SHARE.
export const REGION_SHARE=0.2;
// A face or hands is a few percent of the canvas. A fine transfer from a close-up reference there,
// followed by edges, is how those get resolved, and that happens late, so a focal patch is never refused.
export const FOCAL_SHARE=0.03;
// A repair patch stretched from a small source crop paints its dabs as round blobs at actual pixels:
// a traced repair stretched 485 reference px over 2000 canvas px (4x) three times and never passed.
export const MAX_PATCH_SCALE=2;
// A painting the chat started on counts as existing unless it is an unsaved one-layer document (File > New).
// An opened JPEG of a finished painting is one layer too, so the layer count alone let a full transfer through.
const existingPainting=(runtime,observation)=>runtime.study?.canvas?.mode==='current'&&((observation.layers?.length??0)>1||!!observation.filename);
export function transferRefusal(goal,recipe,canvas,paintedJobs,{established=false}={}){
 const steps=goal?.brief?.steps?.length??0,step=goal?.current_step??0;
 const instead='Paint it yourself: paint_contours for silhouettes and overlaps, paint_pass with small brushes and long directed strokes for edges and detail, clipped create_layer for light and shadow.';
 const share=recipe.target[2]*recipe.target[3]/(canvas.width*canvas.height);
 if(share<=FOCAL_SHARE)return null;
 if(steps>1&&step>=Math.ceil(steps/2))return `Reference transfer is for underpainting and is off from step ${Math.ceil(steps/2)+1} of ${steps}: it only stamps the reference again as dabs. A focal patch (one face or hand) of at most ${Math.round(FOCAL_SHARE*100)}% of the canvas is still allowed. ${instead}`;
 if(established&&share>REGION_SHARE)return `This painting already exists, so a reference transfer may only fill a missing region of at most ${Math.round(REGION_SHARE*100)}% of the canvas (this target is ${Math.round(share*100)}%); a full transfer would stamp dabs over the finished surface. ${instead}`;
 if(paintedJobs>0&&share>REGION_SHARE)return `This plan already has a reference transfer. Another one may only fill a missing region of at most ${Math.round(REGION_SHARE*100)}% of the canvas (this target is ${Math.round(share*100)}%); a second full transfer re-rolls the same dabs. ${instead}`;
 const scale=recipe.target[2]/recipe.source[2];
 if((established||paintedJobs>0)&&scale>MAX_PATCH_SCALE)return `This patch stretches the reference ${Math.round(scale*10)/10}x (${recipe.source[2]} source px over ${recipe.target[2]} canvas px); past ${MAX_PATCH_SCALE}x its dabs read as blobs at actual pixels. Attach a sharper or closer reference of this area, or ${instead.charAt(0).toLowerCase()+instead.slice(1)}`;
 return null;
}
async function reference(runtime,id){const ref=runtime.study.references.find(r=>r.id===id);if(!ref)throw new Error('Use an attached reference ID.');const file=await containedFile(runtime.study.directory,ref.path);if((await stat(file)).size>5*1024*1024)throw new Error('Use a reference smaller than 5 MB for native reconstruction.');const data=await readFile(file);return {data,sha256:hash(data)};}
export function referenceTools(runtime,executePass){
 const folder=()=>join(runtime.study.directory,'reference-paintings');
 const path=id=>{if(!/^[a-f0-9]{32}$/.test(id))throw new Error('Invalid reference painting ID.');return join(folder(),id+'.json');};
 async function jobs(){let names;try{names=await readdir(folder());}catch(e){if(e.code!=='ENOENT')throw e;names=[];}const all=[];for(const name of names.filter(n=>/^[a-f0-9]{32}\.json$/.test(n)))all.push(JSON.parse(await readFile(join(folder(),name))));return all;}
 async function response(job,result){let images=[];if(result?.image_path){const im=await imageContent(runtime.study.directory,result.image_path);images=[im.content];}return {content:[{type:'text',text:JSON.stringify(summary(job))},...images],details:{...summary(job),...(result?.image_path?{image_path:result.image_path}:{})}};}
 // image_path lets Guide pacing check progress after a reference job (a traced finishing run had one pace check in 20 minutes).
 // The stroke plan is never stored: it follows from the recipe, the reference pixels and the canvas
 // size, so a resume rebuilds it and checks it against plan_hash. Stored plans were 25-37 MB a job.
 async function buildPlan(recipe,source,canvas){
  const decoded=await runtime.callNative('decode_reference',{image_base64:source.data.toString('base64'),sha256:source.sha256});
  if(decoded.sha256!==source.sha256)throw new Error('Decoded reference identity differs.');
  const pixels={width:decoded.width,height:decoded.height,data:Buffer.from(decoded.rgba_base64,'base64')};
  return ({edges:generateEdgePlan,surface:generateSurfacePlan}[recipe.mode]??generateReferencePlan)(recipe,pixels,{width:canvas.width,height:canvas.height});
 }
 async function start(id,recipe,signal){
  signal?.throwIfAborted();allowed(runtime);await mkdir(folder(),{recursive:true});const identifier=hash(id).slice(0,32);let old;try{old=JSON.parse(await readFile(path(identifier)));}catch(e){if(e.code!=='ENOENT')throw e;}
  if(old){if(JSON.stringify(old.recipe)!==JSON.stringify(recipe))throw new Error('Operation ID reused with different reference instructions.');return response(old,await runtime.callNative('observe'));}
  const source=await reference(runtime,recipe.reference_id);
  const observation=await runtime.callNative('observe');runtime.decisionObservation=observation;
  if(!recipe.mode&&scope(runtime)){const refusal=transferRefusal(runtime.goal,recipe,observation,(await jobs()).filter(j=>sameScope(j,runtime)&&j.completed>0&&!j.recipe.mode).length,{established:existingPainting(runtime,observation)});if(refusal)throw new Error(refusal);}
  const plan=await buildPlan(recipe,source,observation);
  const job={id:identifier,version:REFERENCE_GENERATOR_VERSION,recipe,reference_hash:source.sha256,plan_hash:hash(JSON.stringify(plan)+'\n'),canvas:{width:observation.width,height:observation.height},scope:scope(runtime),status:'ready',pass:0,pass_count:plan.passes.length,offset:0,completed:0,total:plan.total,last_revision:observation.revision,layer_id:null,pending:null};await atomic(path(identifier),job);return run(job,signal,plan);
 }
 async function run(job,signal,built){
  allowed(runtime);
  if(job.version!==REFERENCE_GENERATOR_VERSION)throw new Error('This reference job uses a different generator version. Keep its existing artwork and start a new job.');
  if(!sameScope(job,runtime))throw new Error('The plan changed. Reference jobs must finish within their original plan.');
  const source=await reference(runtime,job.recipe.reference_id);if(source.sha256!==job.reference_hash)throw new Error('The reference changed; this job cannot be resumed.');
  const save=()=>atomic(path(job.id),job);
  const accept=(result,pending)=>{if(result.error||result.status==='partial'||!result.revision||!result.layer_id)throw new Error('This chunk has an uncertain outcome. Inspect and recover it; do not repeat its strokes.');job.layer_id=result.layer_id;job.last_revision=result.revision;job.offset+=pending.count;job.completed+=pending.count;job.pending=null;};
  // Query the native journal before considering a dispatched-but-unacknowledged chunk.
  if(job.pending){const receipt=await runtime.callNative('operation_status',{id:job.pending.id});
   if(receipt.found){accept(receipt.result,job.pending);runtime.applyNativeRecovery?.(receipt);await save();}
  }
  let current=await runtime.callNative('observe');
  const plan=built??await buildPlan(job.recipe,source,job.canvas??current);
  if(hash(JSON.stringify(plan)+'\n')!==job.plan_hash)throw new Error('The stroke plan could not be rebuilt identically. Do not replay it.');
  if(plan.version!==job.version||JSON.stringify(plan.recipe)!==JSON.stringify(job.recipe))throw new Error('The saved reference job no longer matches its stroke plan.');
  if(current.width!==plan.canvas.width||current.height!==plan.canvas.height||current.revision!==job.last_revision)throw new Error('The canvas changed since this job checkpoint. Preserve the changes and inspect before starting a new job.');
  runtime.decisionObservation=current;
  if(job.status==='complete')return response(job,current);
  // The host paints the whole job (every pass, coarse to fine to focal) in one call. Handing control
  // back every 45 s or at each pass cost a model round trip per chunk just to say "continue"
  // (15 of 51 painter calls in one traced chat). It stops for Stop, a mode change or an allowance.
  try{
   for(;;){
    if(job.status==='awaiting_review'){job.pass++;job.offset=0;job.layer_id=null;}
    if(job.pass>=plan.passes.length){job.status='complete';break;}
    const pass=plan.passes[job.pass];job.status='running';await save();
    while(job.offset<pass.strokes.length){
     if(signal?.aborted||runtime.cancelRequested||!isPaintingMode(runtime.mode)||runtime.executionPhase!=='agent')break;
     if(!sameScope(job,runtime))throw new Error('The plan changed during reference painting.');
     const count=Math.min(runtime.config?.reference_batch??REFERENCE_BATCH,pass.strokes.length-job.offset);
     if(!job.pending){job.pending={id:'reference-'+job.id+'-'+job.pass+'-'+job.offset,count};await save();}
     const args={name:job.recipe.name+' · '+pass.name,preset:pass.preset??job.recipe.preset,region:job.recipe.target,
       strokes:pass.strokes.slice(job.offset,job.offset+count),...(pass.smudge_rate?{smudge_overlay:true,smudge_rate:pass.smudge_rate}:{}),...(job.layer_id?{continue_layer_id:job.layer_id}:{})};
     runtime.emit({type:'status',phase:'painting',message:job.recipe.name+' · '+pass.name+' · '+job.completed+'/'+job.total+' strokes'});
     const result=await executePass(job.pending.id,args,signal);accept(result.details,job.pending);current=result.details;await save();
    }
    if(job.offset<pass.strokes.length){job.status='paused';break;}
    job.status=job.pass===plan.passes.length-1?'complete':'awaiting_review';
    if(job.status==='complete')break;
   }
   await save();return response(job,current);
  }catch(error){job.status='interrupted';await save();throw error;}
 }
 return [
  {name:'paint_from_reference',label:'Painting from a reference',executionMode:'sequential',parameters:referenceSchema,
   description:'Underpainting only: start faithful reference-assisted reconstruction with locally sampled native brush strokes (small dabs, no edges or materials). One full transfer per plan, then only patches of a missing region, stretched at most 2x; a patch fades out over its outer edge, so extend the target about 15% past the damage on each side that meets existing paint; off in the second half of the plan, except a focal patch of one face or hand (at most 3% of the canvas), best from an attached close-up reference. Source/target/focal rectangles are [x,y,width,height]; aspect ratios must match. Plans coarse, fine and optional focal passes, with one editable layer per pass. Defaults: steps [6,2.5,1.2], seed 714. Paints the whole job (all passes) in one call and returns the finished canvas; use continue_reference_painting only to resume a job that was stopped or interrupted. Returns a job ID and actual canvas at a saved boundary; if it is paused, inspect and use continue_reference_painting until complete. Keep all refinement within the current planned stage. This transfers reference colors and positions; it is not independent drawing. Does not change the reference.',
   execute:(id,recipe,signal)=>start(id,recipe,signal)},
  {name:'continue_reference_painting',label:'Continuing reference painting',executionMode:'sequential',parameters:Type.Object({job_id:Type.String({pattern:'^[a-f0-9]{32}$'})},{additionalProperties:false}),
   description:'Resume a saved reference job in its original stage. Reconciles a pending chunk against Krita receipts before painting, checks reference/plan identity and canvas revision, and preserves one layer per refinement pass. Paints all remaining passes (coarse, fine, focal) in one call; it returns early only if painting was stopped. Unknown/partial native outcomes require recovery and are never blindly repainted.',
   execute:async(_id,{job_id},signal)=>{signal?.throwIfAborted();allowed(runtime);return run(JSON.parse(await readFile(path(job_id))),signal);}},
  {name:'list_reference_paintings',label:'Finding saved reference painting jobs',executionMode:'sequential',parameters:Type.Object({},{additionalProperties:false}),description:'List saved reference jobs and their completion counts for this study. Read-only; use their IDs to resume after a restart.',
   execute:async()=>{const list=(await jobs()).map(summary);return {content:[{type:'text',text:JSON.stringify(list)}],details:{jobs:list}};}},
  {name:'paint_reference_edges',label:'Sharpening edges from the reference',executionMode:'sequential',parameters:edgeSchema,
   description:'Finishing: paint the reference\u2019s own edges in a region as thin strokes that follow each edge, one in each side\u2019s colour, so forms, contours, highlights and reflections become crisp where the canvas is soft or mosaic-like. Source/target are [x,y,width,height] with matching aspect ratios; target the region on the canvas where that source content already sits. Choose focal regions (a figure, a vehicle, a railing, lit windows), not the whole picture. Use a crisp opaque preset (Basic-6 Details, Ink-2 Fineliner). One editable layer; resumable with continue_reference_painting.',
   execute:(id,args,signal)=>start(id,{...args,mode:'edges'},signal)},
  {name:'paint_reference_surface',label:'Blending surfaces along the forms',executionMode:'sequential',parameters:surfaceSchema,
   description:'Finishing: blend the dab or mosaic texture in smooth areas into continuous paint, then repaint the region\u2019s edges crisp, in one call. Short smudge strokes follow the reference\u2019s own form direction (sky, clouds, hair, skin, car body) at half strength and leave busy areas alone (lit windows, reflections, snow, fur: max_detail), which need paint_reference_edges and hand strokes instead. The smudge mixes the colours already on the canvas onto its own new layer and never repaints your layers. Use a Color Smudge blender preset (k) Blender Basic). Source/target are [x,y,width,height] with matching aspect ratios; target the canvas region where that source content already sits. Two editable layers (surface, edges); resumable with continue_reference_painting.',
   execute:(id,args,signal)=>start(id,{...args,mode:'surface'},signal)}
 ];
}

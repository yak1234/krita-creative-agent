// @ts-check
import { isPaintingMode } from './modes.mjs';
import {createHash} from 'node:crypto';
import {mkdir,readFile,writeFile,rename,readdir,stat} from 'node:fs/promises';
import {join} from 'node:path';
import { defineTool } from '@earendil-works/pi-coding-agent';
import {Type} from 'typebox';
import {containedFile,imageContent} from './files.mjs';
import {scopePlan,loadAreaMask,scopedShare,chipLine} from './paint-only-here.ts';
import {referenceSchema,edgeSchema,surfaceSchema,generateReferencePlan,generateEdgePlan,generateSurfacePlan,estimateReferenceStrokes,DEFAULT_STEPS,REFERENCE_GENERATOR_VERSION} from './reference-generator.mjs';
// Strokes per native call. Each call re-reads the canvas and journals its receipt; at 128 that
// overhead was ~80% of a 157k-stroke job. The plugin accepts up to 1024 per pass.
export const REFERENCE_BATCH=1024;
const hash=value=>createHash('sha256').update(value).digest('hex');
const atomic=async(path,value)=>{await writeFile(path+'.tmp',JSON.stringify(value)+'\n');await rename(path+'.tmp',path);};
// Jobs belong to a plan revision. Older jobs also recorded a stage; steps no longer gate work.
const scope=r=>r.goal?JSON.stringify([r.goal.revision]):null;
const sameScope=(job,r)=>{if(job.scope===scope(r))return true;try{return !!r.goal&&JSON.parse(job.scope)[0]===r.goal.revision;}catch{return false;}};
const allowed=r=>{if(!isPaintingMode(r.mode)||r.executionPhase!=='agent'||r.cancelRequested||r.faulted)throw new Error('Reference painting requires active Agent execution without pending recovery.');};
const summary=j=>({job_id:j.id,name:j.recipe.name,status:j.status,completed_strokes:j.completed,total_strokes:j.total,pass:j.pass+1,pass_count:j.pass_count,
 ...(j.closeup?{closeup:j.closeup}:{}),
 ...(j.fitted?{fitted:`Steps widened from [${j.fitted.from}] to [${j.recipe.steps}] so the transfer fits ${j.fitted.move?`one Agent move (about ${j.fitted.move} strokes)`:`about ${j.fitted.minutes} of the ${j.fitted.left} minutes left`}; the dabs are larger, so refine focal areas by hand, and make the picture crisp with paint_accents.`}:{}),
 ...(j.inside_label?{inside:j.inside_label+'. Only the dabs inside it were planned; Krita keeps every write there.'}:{}),
 ...(j.ground?{ground:'A toned ground layer in the reference\u2019s colours, top to bottom, lies under the transfer, so gaps between dabs show its tone, not white canvas.'}:{}),
 next_action:j.status==='complete'?'Review the finished canvas.':j.status==='awaiting_review'?'Inspect this pass image, then continue_reference_painting for the next refinement pass.':'Resume with continue_reference_painting after inspecting any interruption.'});
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
// Judged by what is visible: the plugin reports painted_share, the part of the canvas that differs from its
// dominant colour. A live run took a blank, saved new document (Background plus an empty Paint Layer 1)
// for a painting and refused the whole-canvas transfer of its sky asset. An older plugin without
// painted_share falls back to the layer count and filename.
export const PAINTED_SHARE=0.05;
export const existingPainting=(runtime,observation)=>runtime.study?.canvas?.mode==='current'&&
 (Number.isFinite(observation.painted_share)?observation.painted_share>=PAINTED_SHARE:((observation.layers?.length??0)>1||!!observation.filename));
// A part (cut out of a reference in the panel) is see-through outside the area the artist chose, so a transfer from it
// paints only there: the late-plan rule measures that area, and the size caps do not apply.
export function partShare(recipe,part){
 const [sx,sy,sw,sh]=recipe.source,[bx,by,bw,bh]=part.bounds;
 return Math.max(0,Math.min(sx+sw,bx+bw)-Math.max(sx,bx))*Math.max(0,Math.min(sy+sh,by+bh)-Math.max(sy,by))/(sw*sh);
}
// Where the artist has protected what matters, the size caps step aside: the plugin keeps every protected pixel.
// Inside the artist's Paint only here area (paint-only-here.ts, goal 6) a transfer is measured by the area (`inside.share`),
// and the size caps step aside until a transfer has painted that area (`inside.painted`).
export function transferRefusal(goal,recipe,canvas,paintedJobs,{established=false,protectedAreas=0,part=null,inside=null}={}){
 const steps=goal?.brief?.steps?.length??0,step=goal?.current_step??0;
 const instead='Paint it yourself: paint_contours for silhouettes and overlaps, paint_pass with small brushes and long directed strokes for edges and detail, clipped create_layer for light and shadow.';
 const share=inside?inside.share:recipe.target[2]*recipe.target[3]/(canvas.width*canvas.height)*(part?partShare(recipe,part):1),uncapped=protectedAreas||part||(inside&&!inside.painted);
 // A focal patch lifts the size and late-plan rules, not the stretch limit (every transfer has it).
 if(share<=FOCAL_SHARE)return stretchRefusal(recipe,{established,paintedJobs});
 // An untouched Paint only here area lifts the late-plan rule too: a folder plan's element steps come last (underpainting,
 // accents, then the elements the artist names) and paint their element inside the area the artist drew.
 if(steps>1&&step>=Math.ceil(steps/2)&&!(inside&&!inside.painted))return `Reference transfer is for underpainting and is off from step ${Math.ceil(steps/2)+1} of ${steps}: it only stamps the reference again as dabs. A focal patch (one face or hand) of at most ${Math.round(FOCAL_SHARE*100)}% of the canvas is still allowed. ${instead}`;
 if(!uncapped&&established&&share>REGION_SHARE)return `This painting already exists, so a reference transfer may only fill a missing region of at most ${Math.round(REGION_SHARE*100)}% of the canvas (this target is ${Math.round(share*100)}%); a full transfer would stamp dabs over the finished surface. ${instead}`;
 if(!uncapped&&paintedJobs>0&&share>REGION_SHARE)return `This plan already has a reference transfer. Another one may only fill a missing region of at most ${Math.round(REGION_SHARE*100)}% of the canvas (this target is ${Math.round(share*100)}%); a second full transfer re-rolls the same dabs. ${instead}`;
 return stretchRefusal(recipe,{established,paintedJobs});
}
// The finishing transfers re-sample the same reference too: a traced chat stretched the goal (1448 px wide on a 6000 px
// canvas) 4x for the hair and the figure with paint_reference_surface and paint_reference_edges, and the stretched edges
// and smudge flow read as blobs. On a painted canvas (an existing painting, or after any reference job has painted) an
// edges or surface transfer, or a patch, past MAX_PATCH_SCALE is refused. There is no focal exemption: a small area
// (hair, a face) is where a stretched edge shows most. A part is measured like any reference: the stretch is the same.
export function stretchRefusal(recipe,{established=false,paintedJobs=0}={}){
 const scale=recipe.target[2]/recipe.source[2];
 if(!(established||paintedJobs>0)||scale<=MAX_PATCH_SCALE)return null;
 const kind=recipe.mode==='edges'?'An edges':recipe.mode==='surface'?'A surface':'A patch';
 return `${kind} transfer of "${recipe.name}" at [${recipe.target}] stretches the reference ${Math.round(scale*10)/10}x (${recipe.source[2]} source px over ${recipe.target[2]} canvas px); past ${MAX_PATCH_SCALE}x its edges and strokes read as blobs at actual pixels. Attach a sharper or closer reference of this area (a close-up) and transfer from it, or stop refining this area here and ask the artist; hand strokes (paint_pass with small brushes) remain.`;
}
// A transfer paints 12-40 dabs a second (larger dabs are slower). A traced 20-minute Starry Night
// planned 184,000 strokes at steps [10,5,2.5], hours of work, and stopped inside its coarse pass with the
// canvas showing between the dabs. Under a time allowance the steps widen (strokes fall with the square
// of the step) so the job takes at most TRANSFER_TIME_SHARE of the time left, at the slowest measured
// rate, or the rate this chat has measured.
export const STROKES_PER_SECOND=12;
export const TRANSFER_TIME_SHARE=.5;
export function fitStepsToTime(recipe,seconds,rate=STROKES_PER_SECOND){
 return fitStepsToBudget(recipe,Math.max(500,seconds*TRANSFER_TIME_SHARE*rate));
}
// An Agent move is one visible step with no time allowance. A traced clouds move planned 156,304 strokes
// and painted for ten minutes (with a checkpoint save every chunk) before Luna could look at it. Its
// transfer gets about two minutes at the 300 strokes a second measured there.
export const AGENT_MOVE_STROKES=40000;
export function fitStepsToBudget(recipe,budget){
 const from=recipe.steps??DEFAULT_STEPS,strokes=estimateReferenceStrokes({...recipe,steps:from});
 if(strokes<=budget)return null;
 const k=Math.sqrt(strokes/budget),steps=from.map(s=>Math.min(64,Math.round(s*k*100)/100));
 for(let i=1;i<steps.length;i++)if(steps[i]>=steps[i-1])steps[i]=Math.round(steps[i-1]*50)/100;   // still coarse to fine at the 64 px cap
 return {recipe:{...recipe,steps},from,strokes,budget:Math.round(budget)};
}
// The first transfer on a fresh canvas is the underpainting of the whole picture. A traced Great Wave
// transferred only the wave (a third of the canvas) first; after that, transfers are patches of at
// most REGION_SHARE, so the sky, the boats and Fuji could never be transferred. When the artist's
// reference has the canvas's proportions (within ASPECT_TOLERANCE) it is the picture itself, so its whole area goes first.
export const WHOLE_SHARE=.9;
export const ASPECT_TOLERANCE=.03;
export function wholeReferenceRefusal(recipe,reference,canvas){
 if(reference.role&&reference.role!=='reference'||reference.part_kind)return null;          // an asset, a part or a crop is not the picture
 const [,,sw,sh]=recipe.source,[,,tw,th]=recipe.target,share=tw*th/(canvas.width*canvas.height);
 if(share<=FOCAL_SHARE)return null;
 // A reference of other proportions is a part (a figure for a landscape), and may go anywhere.
 if(Math.abs(reference.width/reference.height/(canvas.width/canvas.height)-1)>ASPECT_TOLERANCE)return null;
 if(share>=WHOLE_SHARE&&sw*sh>=WHOLE_SHARE*reference.width*reference.height)return null;
 // All of the reference over all of the canvas, trimmed by the few pixels the proportions differ.
 const source=reference.width/reference.height>canvas.width/canvas.height
  ?(w=>[Math.floor((reference.width-w)/2),0,w,reference.height])(Math.round(reference.height*canvas.width/canvas.height))
  :(h=>[0,Math.floor((reference.height-h)/2),reference.width,h])(Math.round(reference.width*canvas.height/canvas.width));
 return `This reference has the canvas\u2019s proportions, so the first transfer underpaints the whole picture from all of it: source [${source}], target [0,0,${canvas.width},${canvas.height}]. After the first transfer, transfers are patches of at most ${Math.round(REGION_SHARE*100)}% of the canvas, so a regional first transfer would leave the rest of the picture untransferable. Then refine regions with patches, make it crisp with paint_accents, and add hand strokes.`;
}
// The colours a toned ground grades through, top to bottom: the source crop's average in each band.
// A dab transfer leaves canvas between its dabs (white specks over a dark Vermeer); the ground shows there instead.
export const GROUND_BANDS=6;
export function groundStops(pixels,source){
 const [sx,sy,sw,sh]=source,stride=Math.max(1,Math.floor(Math.min(sw,sh)/200)),hex=rgb=>'#'+rgb.map(v=>Math.round(v).toString(16).padStart(2,'0')).join('');
 const bands=[];let alpha=0,n=0;
 for(let b=0;b<GROUND_BANDS;b++){
  const sum=[0,0,0];let weight=0;
  for(let y=sy+Math.floor(b*sh/GROUND_BANDS);y<sy+Math.floor((b+1)*sh/GROUND_BANDS);y+=stride)for(let x=sx;x<sx+sw;x+=stride){const i=(y*pixels.width+x)*4,a=pixels.data[i+3]/255;weight+=a;alpha+=a;n++;for(let k=0;k<3;k++)sum[k]+=pixels.data[i+k]*a;}
  bands.push(weight?hex(sum.map(v=>v/weight)):null);
 }
 // A cut-out (an asset on transparency) has no rectangle of colour to put under it.
 if(!n||alpha/n<.95||bands.includes(null))return null;
 return [{offset:0,color:bands[0]},...bands.map((color,b)=>({offset:Math.round((b+.5)/GROUND_BANDS*1000)/1000,color})),{offset:1,color:bands.at(-1)}];
}
// A part keeps its original's size, mostly transparent: it may be as large as any attached reference (12 MB).
async function reference(runtime,id){const ref=runtime.study.references.find(r=>r.id===id);if(!ref)throw new Error('Use an attached reference ID.');const file=await containedFile(runtime.study.directory,ref.path),limit=ref.part_kind==='part'?12:5;if((await stat(file)).size>limit*1024*1024)throw new Error('Use a reference smaller than '+limit+' MB for native reconstruction.');const data=await readFile(file);return {data,sha256:hash(data)};}
// The largest reference the plugin's finders take (find_accents): a full-size goal image.
export const TRACE_REFERENCE_MB=12;
// paint_accents' finder (accents-tool.ts): the plugin's find_accents reads the file as it is (same size limit as tracing)
// and sends back only the accents, in its listed pixels.
export async function findReferenceAccents(runtime,{reference_id,...request}){
 const ref=runtime.study.references.find(r=>r.id===reference_id);if(!ref)throw new Error('Use an attached reference ID.');
 const file=await containedFile(runtime.study.directory,ref.path);
 if((await stat(file)).size>TRACE_REFERENCE_MB*1024*1024)throw new Error(`This reference is too large to find accents in (over ${TRACE_REFERENCE_MB} MB). Attach a smaller copy.`);
 const data=await readFile(file);
 return runtime.callNative('find_accents',{image_base64:data.toString('base64'),sha256:hash(data),...request});
}
export function referenceTools(runtime,executePass,fillRegion){
 const folder=()=>join(runtime.study.directory,'reference-paintings');
 const path=id=>{if(!/^[a-f0-9]{32}$/.test(id))throw new Error('Invalid reference painting ID.');return join(folder(),id+'.json');};
 async function jobs(){let names;try{names=await readdir(folder());}catch(e){if(e.code!=='ENOENT')throw e;names=[];}const all=[];for(const name of names.filter(n=>/^[a-f0-9]{32}\.json$/.test(n)))all.push(JSON.parse(await readFile(join(folder(),name),'utf8')));return all;}
 // The jobs of this plan revision that painted, without those whose moves the artist all undid (runtime.undoneReferenceJobs,
 // from the studio's move record): the artist's rule is that an undone colour pass counts as not done, so the whole
 // underpainting may be retried after an Undo, and nothing is stretched against paint that is gone.
 async function paintedJobs(){const undone=runtime.undoneReferenceJobs?.()??new Set();return (await jobs()).filter(j=>sameScope(j,runtime)&&j.completed>0&&!undone.has(j.id));}
 async function response(job,result){let images=[];if(result?.image_path){const im=await imageContent(runtime.study.directory,result.image_path);images=[im.content];}return {content:[{type:'text',text:JSON.stringify(summary(job))},...images],details:{...summary(job),...(result?.image_path?{image_path:result.image_path}:{})}};}
 // image_path lets Guide pacing check progress after a reference job (a traced finishing run had one pace check in 20 minutes).
 // The stroke plan is never stored: it follows from the recipe, the reference pixels and the canvas
 // size, so a resume rebuilds it and checks it against plan_hash. Stored plans were 25-37 MB a job.
 async function decode(source){
  const decoded=await runtime.callNative('decode_reference',{image_base64:source.data.toString('base64'),sha256:source.sha256});
  if(decoded.sha256!==source.sha256)throw new Error('Decoded reference identity differs.');
  return {width:decoded.width,height:decoded.height,data:Buffer.from(decoded.rgba_base64,'base64')};
 }
 // A job inside a Paint only here area keeps only the dabs centred inside it, read from the job's own area: a resume
 // rebuilds the same plan whatever the chat's area is now.
 const buildPlan=async(recipe,pixels,canvas,inside)=>{
  const plan=({edges:generateEdgePlan,surface:generateSurfacePlan}[recipe.mode]??generateReferencePlan)(recipe,pixels,{width:canvas.width,height:canvas.height});
  return inside?scopePlan(plan,await loadAreaMask(inside,runtime.study.directory)):plan;
 };
 async function start(id,recipe,signal){
  signal?.throwIfAborted();allowed(runtime);await mkdir(folder(),{recursive:true});const identifier=hash(id).slice(0,32);let old;try{old=JSON.parse(await readFile(path(identifier),'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
  if(old){if(JSON.stringify(old.requested??old.recipe)!==JSON.stringify(recipe))throw new Error('Operation ID reused with different reference instructions.');return response(old,await runtime.callNative('observe'));}
  // A detail transfer from the goal samples a confirmed close-up of that area instead (closeups.ts); until the artist has
  // confirmed one, it samples the goal and the close-up is shown to them beside the run.
  const asked=recipe,routed=await runtime.closeups?.route(recipe);
  if(routed)recipe=routed.recipe;
  const source=await reference(runtime,recipe.reference_id);
  const observation=await runtime.callNative('observe');runtime.decisionObservation=observation;
  const pixels=await decode(source);
  let ground=null,fitted=null,requested=asked;
  // The artist's Paint only here area (paint-only-here.ts): every transfer while it is set paints inside it only.
  const area=runtime.goal?.paint_only_here??null,inside=area?{sha256:area.sha256,mask_path:area.mask_path,bounds:area.bounds}:null;
  if(area&&scopedShare(area,recipe.target)<=0)throw new Error(`The target [${recipe.target}] lies outside the area the artist chose (${chipLine(area).toLowerCase()}, bounds [${area.bounds}]): transfer the reference area that lies under it, or the whole reference over the whole canvas.`);
  if(!recipe.mode&&scope(runtime)){
   const all=await paintedJobs(),painted=all.filter(j=>!j.recipe.mode).length,established=existingPainting(runtime,observation);
   const ref=runtime.study.references.find(r=>r.id===recipe.reference_id),part=ref?.part_kind==='part'&&ref.bounds?ref:null;
   const scoped=area?{share:scopedShare(area,recipe.target),painted:all.some(j=>!j.recipe.mode&&j.inside?.sha256===area.sha256)}:null;
   const refusal=transferRefusal(runtime.goal,recipe,observation,painted,{established,protectedAreas:observation.protected_areas?.length??0,part,inside:scoped})
    ??(!painted&&!established&&!area?wholeReferenceRefusal(recipe,{...ref,width:pixels.width,height:pixels.height},observation):null);
   if(refusal)throw new Error(refusal);
   const left=runtime.timeLeftMs?.();
   if(Number.isFinite(left)){const fit=fitStepsToTime(recipe,left/1000,runtime.referenceStrokeRate);if(fit){recipe=fit.recipe;fitted={from:fit.from,minutes:Math.round(left*TRANSFER_TIME_SHARE/6000)/10,left:Math.round(left/6000)/10};}}
   if(runtime.mode==='agent'){const budget=runtime.config?.agent_transfer_strokes??AGENT_MOVE_STROKES,fit=fitStepsToBudget(recipe,budget);if(fit){recipe=fit.recipe;fitted={from:fitted?.from??fit.from,move:budget};}}
   const [tx,ty,tw,th]=recipe.target,stops=fillRegion&&!painted&&!established&&tw*th>REGION_SHARE*observation.width*observation.height?groundStops(pixels,recipe.source):null;
   if(stops)ground={status:'pending',args:{name:recipe.name+' \u00b7 ground',area:[{shape:'rectangle',bounds:recipe.target}],gradient:{type:'linear',start:[tx+tw/2,ty],end:[tx+tw/2,ty+th],stops}}};
  }
  if(recipe.mode){
   const refusal=stretchRefusal(recipe,{established:existingPainting(runtime,observation),paintedJobs:(await paintedJobs()).length});
   if(refusal)throw new Error(refusal);
  }
  const plan=await buildPlan(recipe,pixels,observation,inside);
  if(inside&&!plan.total)throw new Error(`No dab of this transfer lies inside the area the artist chose (${chipLine(area).toLowerCase()}): transfer the reference area that lies under it.`);
  const job={id:identifier,version:REFERENCE_GENERATOR_VERSION,recipe,...(inside?{inside,inside_label:chipLine(area)}:{}),...(requested!==recipe?{requested}:{}),...(routed?{closeup:routed.note}:{}),...(fitted?{fitted}:{}),...(ground?{ground}:{}),reference_hash:source.sha256,plan_hash:hash(JSON.stringify(plan)+'\n'),canvas:{width:observation.width,height:observation.height},scope:scope(runtime),status:'ready',pass:0,pass_count:plan.passes.length,offset:0,completed:0,total:plan.total,last_revision:observation.revision,layer_id:null,pending:null};await atomic(path(identifier),job);return run(job,signal,plan);
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
  // The ground goes down once, before the first dab, under a fixed operation ID: a retry replays its receipt.
  if(job.ground?.status==='pending'&&!signal?.aborted&&!runtime.cancelRequested){
   const done=(await fillRegion('reference-'+job.id+'-ground',job.ground.args,signal)).details;
   if(!done?.revision)throw new Error('The toned ground has an uncertain outcome. Inspect and recover it before transferring.');
   job.ground={status:'done',layer_id:done.layer_id??null};job.last_revision=done.revision;await save();
  }
  let current=await runtime.callNative('observe');
  const plan=built??await buildPlan(job.recipe,await decode(source),job.canvas??current,job.inside);
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
     const began=Date.now(),result=await executePass(job.pending.id,args,signal);accept(result.details,job.pending);current=result.details;await save();
     // The rate this machine paints at, for sizing the next transfer to the time left.
     if(count>=256&&Date.now()>began)runtime.referenceStrokeRate=count/((Date.now()-began)/1000);
    }
    if(job.offset<pass.strokes.length){job.status='paused';break;}
    job.status=job.pass===plan.passes.length-1?'complete':'awaiting_review';
    if(job.status==='complete')break;
   }
   await save();return response(job,current);
  }catch(error){job.status='interrupted';await save();throw error;}
 }
 return [
  defineTool({name:'paint_from_reference',label:'Painting from a reference',executionMode:'sequential',parameters:referenceSchema,
   description:'Underpainting only: start faithful reference-assisted reconstruction with locally sampled native brush strokes (small dabs, no edges or materials). One full transfer per plan, and on a fresh canvas it goes first: a reference with the canvas\u2019s proportions is transferred whole, onto the whole canvas, over a toned ground the host lays from its colours. Under a time allowance the host widens the steps so the job fits; then only patches of a missing region, stretched at most 2x; a patch fades out over its outer edge, so extend the target about 15% past the damage on each side that meets existing paint; off in the second half of the plan, except a focal patch of one face or hand (at most 3% of the canvas), also stretched at most 2x, so from an attached close-up reference. Source/target/focal rectangles are [x,y,width,height]; aspect ratios must match. Plans coarse, fine and optional focal passes, with one editable layer per pass. Defaults: steps [6,2.5,1.2], seed 714. Paints the whole job (all passes) in one call and returns the finished canvas; use continue_reference_painting only to resume a job that was stopped or interrupted. Returns a job ID and actual canvas at a saved boundary; if it is paused, inspect and use continue_reference_painting until complete. Keep all refinement within the current planned stage. This transfers reference colors and positions; it is not independent drawing. Does not change the reference.',
   execute:(id,recipe,signal)=>start(id,recipe,signal)}),
  defineTool({name:'continue_reference_painting',label:'Continuing reference painting',executionMode:'sequential',parameters:Type.Object({job_id:Type.String({pattern:'^[a-f0-9]{32}$'})},{additionalProperties:false}),
   description:'Resume a saved reference job in its original stage. Reconciles a pending chunk against Krita receipts before painting, checks reference/plan identity and canvas revision, and preserves one layer per refinement pass. Paints all remaining passes (coarse, fine, focal) in one call; it returns early only if painting was stopped. Unknown/partial native outcomes require recovery and are never blindly repainted.',
   execute:async(_id,{job_id},signal)=>{signal?.throwIfAborted();allowed(runtime);return run(JSON.parse(await readFile(path(job_id),'utf8')),signal);}}),
  defineTool({name:'list_reference_paintings',label:'Finding saved reference painting jobs',executionMode:'sequential',parameters:Type.Object({},{additionalProperties:false}),description:'List saved reference jobs and their completion counts for this study. Read-only; use their IDs to resume after a restart.',
   execute:async()=>{const list=(await jobs()).map(summary);return {content:[{type:'text',text:JSON.stringify(list)}],details:{jobs:list}};}}),
  defineTool({name:'paint_reference_edges',label:'Sharpening edges from the reference',executionMode:'sequential',parameters:edgeSchema,
   description:'Edges from the reference (not for finishing: paint_accents makes a painting crisp; these paired strokes look scratchy on painterly references): paint the reference\u2019s own edges in a region as thin strokes that follow each edge, one in each side\u2019s colour, so forms, contours, highlights and reflections become crisp where the canvas is soft or mosaic-like. Source/target are [x,y,width,height] with matching aspect ratios; target the region on the canvas where that source content already sits. Choose focal regions (a figure, a vehicle, a railing, lit windows), not the whole picture. On a painted canvas the target may be at most 2x the source; past that attach a closer reference of the area. Use a crisp opaque preset (Basic-6 Details, Ink-2 Fineliner). One editable layer; resumable with continue_reference_painting.',
   execute:(id,args,signal)=>start(id,{...args,mode:'edges'},signal)}),
  defineTool({name:'paint_reference_surface',label:'Blending surfaces along the forms',executionMode:'sequential',parameters:surfaceSchema,
   description:'Finishing: blend the dab or mosaic texture in smooth areas into continuous paint, then repaint the region\u2019s edges crisp, in one call. Short smudge strokes follow the reference\u2019s own form direction (sky, clouds, hair, skin, car body) at half strength and leave busy areas alone (lit windows, reflections, snow, fur: max_detail), which need paint_accents and hand strokes instead. The smudge mixes the colours already on the canvas onto its own new layer and never repaints your layers. Use a Color Smudge blender preset (k) Blender Basic). Source/target are [x,y,width,height] with matching aspect ratios; target the canvas region where that source content already sits. On a painted canvas the target may be at most 2x the source. Two editable layers (surface, edges); resumable with continue_reference_painting.',
   execute:(id,args,signal)=>start(id,{...args,mode:'surface'},signal)})
 ];
}

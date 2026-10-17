// @ts-check
import { isPaintingMode } from './modes.mjs';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import { join } from 'node:path';
import { generateStrokes, GENERATOR_VERSION, recipeSchema } from './stroke-generator.mjs';

export function recipeTool(runtime,executePass) {
  return {name:'paint_recipe',label:'Painting generated strokes',executionMode:'sequential',parameters:recipeSchema,
    description:'Generate native brush curves locally from a compact recipe. Use for broad coverage, irregular scumbling and overlapping texture instead of writing hundreds of coordinates. Region is a rectangular clip (brush marks cannot cross it); irregularity 0 is ordered placement, 1 adds jitter, clumps, wander and cross-strokes. Direction is horizontal/vertical/diagonal/random. Size, opacity and optional length are [min,max]; palette uses exactly the supplied colours. Seed makes the command plan repeatable. Runs saved, reversible paint_pass chunks of up to 256 curves; each chunk is a named layer, not an independent stage review. Stop prevents the next chunk. Returns the last canvas image and execution counts. Does not sample references automatically or guarantee a material effect; inspect the result.',
    execute:async(id,recipe,signal)=>{
      signal?.throwIfAborted();
      if(runtime.mode!==undefined && (!isPaintingMode(runtime.mode) || runtime.executionPhase!=='agent'))throw new Error('Painting recipes are only available in active Agent execution.');
      if(runtime.cancelRequested || runtime.faulted)throw new Error('Painting is stopped or needs recovery.');
      const strokes=generateStrokes(recipe,runtime.decisionObservation);
      const key=createHash('sha256').update(id).digest('hex');
      const fingerprint=createHash('sha256').update(JSON.stringify(recipe)).digest('hex');
      const folder=join(runtime.study.directory,'recipes');await mkdir(folder,{recursive:true});
      const filename=join(folder,key+'.json');
      const persist=async record=>{await writeFile(filename+'.tmp',JSON.stringify(record)+'\n');await rename(filename+'.tmp',filename);};
      let old;
      try{old=JSON.parse(await readFile(filename,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
      if(old){
        if(old.fingerprint!==fingerprint)throw new Error('Recipe operation ID was already used with different arguments.');
        // Never infer that a dispatched but unrecorded chunk is safe to repeat.
        if(old.status==='running' || old.status==='failed')throw new Error('This recipe has an interrupted execution record. Inspect its native operation receipts before starting more paint.');
        return {content:[{type:'text',text:JSON.stringify({...old.summary,replayed:true})}],details:{...old.summary,replayed:true}};
      }
      const record={version:GENERATOR_VERSION,fingerprint,recipe,canvas:{width:runtime.decisionObservation.width,height:runtime.decisionObservation.height},status:'running',chunks:[],summary:{requested_strokes:strokes.length,completed_strokes:0,completed_chunks:0,recipe_file:filename}};
      await persist(record);
      let last;
      try {
        for(let offset=0;offset<strokes.length;offset+=256){
          if(signal?.aborted || runtime.cancelRequested)break;
          const index=offset/256;
          const operationId='recipe-'+key.slice(0,48)+'-'+index;
          runtime.emit({type:'status',phase:'painting',message:recipe.name+' · '+offset+'/'+strokes.length+' strokes completed'});
          last=await executePass(operationId,{name:recipe.name+' · '+(index+1),preset:recipe.preset,region:recipe.region,layer_opacity:recipe.layer_opacity??1,...(recipe.panel?{panel:recipe.panel}:{}),...(recipe.blend_mode?{blend_mode:recipe.blend_mode}:{}),...(recipe.clip_to?{clip_to:recipe.clip_to}:{}),strokes:strokes.slice(offset,offset+256)},signal);
          record.chunks.push({operation_id:operationId,strokes:Math.min(256,strokes.length-offset),layer_id:last.details?.layer_id,checkpoint:last.details?.checkpoint});
          record.summary.completed_strokes+=Math.min(256,strokes.length-offset);record.summary.completed_chunks++;
          await persist(record);
        }
        record.status=record.summary.completed_strokes===strokes.length?'complete':'stopped';
        record.summary.status=record.status;record.summary.chunks=record.chunks;
        await persist(record);
      } catch(error){
        record.status='failed';record.summary.status='failed';
        await persist(record).catch(()=>{});
        throw error;
      }
      return {content:[{type:'text',text:JSON.stringify(record.summary)},...(last?.content??[]).filter(c=>c.type==='image')],details:record.summary};
    }};
}

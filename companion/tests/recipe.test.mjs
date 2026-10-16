import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Value} from 'typebox/value';
import {generateStrokes,recipeSchema} from '../src/stroke-generator.mjs';
import {paintingTools} from '../src/tools.mjs';
const recipe={name:'Dry scumble',preset:'Test brush',region:[40,50,700,500],palette:['#ef8d76','#ee8973'],stroke_count:1200,size:[20,45],opacity:[.15,.3],direction:'horizontal',irregularity:.8,seed:42};
const canvas={width:787,height:1000,revision:'before'};

test('recipe determinism, seed variation, palette and native geometry',()=>{
 const a=generateStrokes(recipe,canvas);assert.deepEqual(a,generateStrokes(recipe,canvas));assert.notDeepEqual(a,generateStrokes({...recipe,seed:43},canvas));
 assert.equal(a.length,1200);
 const pass=paintingTools({}).find(t=>t.name==='paint_pass').parameters;
 for(let i=0;i<a.length;i+=256)assert.ok(Value.Check(pass,{name:'test',preset:recipe.preset,region:recipe.region,strokes:a.slice(i,i+256)}));
 const ys=new Set();let cross=0;
 for(const s of a){assert.ok(recipe.palette.includes(s.color));assert.ok(s.size>=20&&s.size<=45);assert.ok(s.opacity>=.15&&s.opacity<=.3);const p=[...s.start,...s.segments[0]];for(let i=0;i<p.length;i++)assert.ok(p[i]>=(i%2?50:40)&&p[i]<=(i%2?550:740));ys.add(s.start[1].toFixed(2));if(Math.abs(p[7]-p[1])>Math.abs(p[6]-p[0]))cross++;}
 assert.ok(ys.size>1000,'marks must not form tidy horizontal rows');assert.ok(cross>50&&cross<500,'some strokes cross the dominant direction');
});
test('reject bad ranges and regions before painting; fit tiny/asymmetric canvases',()=>{
 for(const change of [{opacity:[.8,.2]},{size:[NaN,40]},{region:[0,0,900,10]},{region:[0,0,0,10]},{stroke_count:0},{seed:-1}])assert.throws(()=>generateStrokes({...recipe,...change},canvas));
 assert.ok(!Value.Check(recipeSchema,{...recipe,unexpected:true}));
 for(const region of [[0,0,1,1000],[0,0,787,1],[0,0,1,1]])assert.equal(generateStrokes({...recipe,region,stroke_count:1},canvas).length,1);
});
async function harness(action=()=>{}){
 const directory=await mkdtemp(join(tmpdir(),'paint-recipe-')),calls=[];
 const runtime={mode:'agent',executionPhase:'agent',study:{directory},decisionObservation:{...canvas},emit(){},async callNative(op,args,id){calls.push({op,args,id});await action(runtime,calls);return {layer_id:'layer-'+calls.length,checkpoint:'test.kra'};}};
 return {runtime,calls,tool:paintingTools(runtime).find(t=>t.name==='paint_recipe'),close:()=>rm(directory,{recursive:true,force:true})};
}
test('1200 marks use five native contributions and compact receipts; replay never paints twice',async()=>{
 const h=await harness();try{
 const result=await h.tool.execute('call-1',recipe);assert.equal(h.calls.length,5);assert.deepEqual(h.calls.map(c=>c.args.strokes.length),[256,256,256,256,176]);assert.equal(result.details.completed_strokes,1200);assert.equal(new Set(h.calls.map(c=>c.id)).size,5);
 assert.ok(result.content[0].text.length<3000,'result does not echo thousands of coordinates');
 const record=JSON.parse(await readFile(result.details.recipe_file));assert.equal(record.version,1);assert.deepEqual(record.recipe,recipe);assert.equal(record.status,'complete');
 await h.tool.execute('call-1',recipe);assert.equal(h.calls.length,5);
 await assert.rejects(h.tool.execute('call-1',{...recipe,seed:2}),/different arguments/);
 }finally{await h.close();}
});
test('Stop settles one batch and prevents later chunks; same receipt stays stopped',async()=>{
 const h=await harness(runtime=>{runtime.cancelRequested=true;});try{
 const r=await h.tool.execute('stop',recipe);assert.equal(h.calls.length,1);assert.equal(r.details.status,'stopped');assert.equal(r.details.completed_strokes,256);
 h.runtime.cancelRequested=false;const replay=await h.tool.execute('stop',recipe);assert.equal(replay.details.replayed,true);assert.equal(h.calls.length,1);
 }finally{await h.close();}
});
test('unknown outcome prevents continuation and replay; Ask/Plan cannot dispatch recipes',async()=>{
 const h=await harness(()=>{throw Object.assign(new Error('Unknown result'),{code:'outcome_unknown'});});try{
 await assert.rejects(h.tool.execute('unknown',recipe),/Unknown result/);assert.equal(h.calls.length,1);assert.equal(h.runtime.faulted,true);
 h.runtime.faulted=false;await assert.rejects(h.tool.execute('unknown',recipe),/interrupted execution/);assert.equal(h.calls.length,1);
 for(const mode of ['ask','plan']){h.runtime.mode=mode;h.runtime.executionPhase=mode;await assert.rejects(h.tool.execute(mode,recipe),/active Agent/);}
 assert.equal(h.calls.length,1);
 }finally{await h.close();}
});

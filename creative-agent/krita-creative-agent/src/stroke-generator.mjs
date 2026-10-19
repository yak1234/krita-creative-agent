// @ts-check
import { Type } from 'typebox';
import { Value } from 'typebox/value';

const range = (min,max) => Type.Array(Type.Number({minimum:min,maximum:max}),{minItems:2,maxItems:2});
export const recipeSchema = Type.Object({
  name:Type.String({minLength:1,maxLength:100}),preset:Type.String({minLength:1}),
  region:Type.Array(Type.Integer({minimum:0,maximum:8192}),{minItems:4,maxItems:4}),
  palette:Type.Array(Type.String({pattern:'^#[0-9a-fA-F]{6}$'}),{minItems:1,maxItems:32}),
  stroke_count:Type.Integer({minimum:1,maximum:20000}),
  size:range(1,10000),opacity:range(.01,1),
  length:Type.Optional(range(1,8192)),
  direction:Type.Union(['horizontal','vertical','diagonal','random'].map(v=>Type.Literal(v))),
  irregularity:Type.Number({minimum:0,maximum:1}),seed:Type.Integer({minimum:0,maximum:4294967295}),
  flow:Type.Optional(Type.Number({minimum:.01,maximum:1})),
  layer_opacity:Type.Optional(Type.Number({minimum:0,maximum:1})),
  panel:Type.Optional(Type.String({pattern:'^P[0-9]{1,2}$'})),
  blend_mode:Type.Optional(Type.String({maxLength:40,description:'overlay or soft_light for texture clipped to a flat; multiply for shadow; add or screen for light.'})),
  clip_to:Type.Optional(Type.String({description:'Clip every chunk to this layer, usually the area\u2019s flat.'})),
},{additionalProperties:false});

// Version recipes when changing this algorithm: persisted seeds are execution records.
export const GENERATOR_VERSION = 1;
export function generateStrokes(recipe, canvas) {
  if (!Value.Check(recipeSchema,recipe)) throw new Error('Invalid stroke recipe. Use the documented fields and numeric ranges.');
  for (const key of ['size','opacity','length']) if(recipe[key] && recipe[key][0]>recipe[key][1]) throw new Error(key+' range must be ordered minimum, maximum.');
  const [x,y,w,h]=recipe.region;
  if(!canvas || !Number.isFinite(canvas.width) || !Number.isFinite(canvas.height) || w<1 || h<1 || x+w>canvas.width || y+h>canvas.height) throw new Error('Recipe region must fit the observed canvas.');
  let state=recipe.seed>>>0;
  const random=()=>{state=(state+0x6D2B79F5)>>>0;let t=state;t=Math.imul(t^(t>>>15),t|1);t^=t+Math.imul(t^(t>>>7),t|61);return ((t^(t>>>14))>>>0)/4294967296;};
  const between=(/** @type {number[]} */ [a,b])=>a+(b-a)*random();
  const n=recipe.stroke_count,cols=Math.min(n,Math.ceil(Math.sqrt(n*w/h))),rows=Math.ceil(n/cols),j=recipe.irregularity;
  const clusters=Array.from({length:Math.max(1,Math.ceil(Math.sqrt(n)/2))},()=>[random(),random()]);
  const result=[];
  for(let i=0;i<n;i++) {
    let u=(i%cols+.5+(random()-.5)*j)/cols,v=(Math.floor(i/cols)+.5+(random()-.5)*j)/rows;
    if(random()<j*.22){const c=clusters[Math.floor(random()*clusters.length)];u=Math.max(.001,Math.min(.999,c[0]+(random()-.5)*.18));v=Math.max(.001,Math.min(.999,c[1]+(random()-.5)*.18));}
    const cx=x+u*w,cy=y+v*h,size=between(recipe.size);
    const base={horizontal:0,vertical:Math.PI/2,diagonal:Math.PI/4}[recipe.direction];
    let angle=base===undefined?random()*Math.PI*2:base+(random()-.5)*j*.9;
    if(base!==undefined && random()<j*.18)angle+=Math.PI/2;
    const length=recipe.length?between(recipe.length):size*(.55+random()*1.2);
    const dx=Math.cos(angle)*length/2,dy=Math.sin(angle)*length/2,bend=(random()-.5)*j*length*.35;
    const offsets=[[-dx,-dy],[-dx/3-Math.sin(angle)*bend,-dy/3+Math.cos(angle)*bend],[dx/3-Math.sin(angle)*bend,dy/3+Math.cos(angle)*bend],[dx,dy]];
    let fit=1;
    for(const [ox,oy] of offsets){if(ox)fit=Math.min(fit,(ox>0?x+w-cx:cx-x)/Math.abs(ox));if(oy)fit=Math.min(fit,(oy>0?y+h-cy:cy-y)/Math.abs(oy));}
    const points=offsets.map(([ox,oy])=>[Math.max(x,Math.min(x+w,cx+ox*fit)),Math.max(y,Math.min(y+h,cy+oy*fit))]);
    result.push({start:points[0],segments:[points.slice(1).flat()],size,opacity:between(recipe.opacity),flow:recipe.flow??1,color:recipe.palette[Math.floor(random()*recipe.palette.length)]});
  }
  // Irregular execution order avoids painting regular rows over one another.
  for(let i=result.length-1;i>0;i--){const k=Math.floor(random()*(i+1));[result[i],result[k]]=[result[k],result[i]];}
  return result;
}

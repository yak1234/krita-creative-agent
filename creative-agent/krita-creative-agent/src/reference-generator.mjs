// @ts-check
import { resizeBilinear } from './shapes/image.ts';
import { REFERENCE_PIXELS, PLUGIN_DECODE_PIXELS, STEP_MAX, EDGE_SPACING_MAX, SURFACE_SPACING_MAX, SURFACE_LENGTH_MAX, PLAN_STROKES_MAX } from './reference-limits.ts';
import {Type} from 'typebox';
import {Value} from 'typebox/value';
/** @template {import('typebox').TProperties} T @param {T} p */
const object=p=>Type.Object(p,{additionalProperties:false});
const rect=()=>Type.Array(Type.Integer({minimum:0,maximum:8192}),{minItems:4,maxItems:4,description:'[x,y,width,height], in source pixels for source/focal regions and canvas pixels for target.'});
// 2: transfer patches fade out toward the sides that meet existing paint.
export const REFERENCE_GENERATOR_VERSION=2;
// A patch painted to a hard rectangle leaves that rectangle as a seam: a traced repair's check
// "no rectangular boundary is left" scored 0 after every job. Dabs within PATCH_FEATHER of the
// patch's smaller side from an inner edge (not the canvas border) fade out, with a ragged boundary.
export const PATCH_FEATHER=.15;
export const referenceSchema=object({
 name:Type.String({minLength:1,maxLength:100}),reference_id:Type.String({minLength:1}),preset:Type.String({minLength:1,maxLength:200}),
 source:rect(),target:rect(),focal_regions:Type.Optional(Type.Array(rect(),{maxItems:12})),
 steps:Type.Optional(Type.Array(Type.Number({minimum:.75,maximum:STEP_MAX}),{minItems:3,maxItems:3,description:'Source-pixel sampling steps: coarse, fine, focal. Default [6,2.5,1.2]. Must decrease. The whole-picture underpainting\'s are set by the host on the canvas.'})),
 seed:Type.Optional(Type.Integer({minimum:0,maximum:4294967295})),
});
export const DEFAULT_STEPS=[6,2.5,1.2];
// Integer rectangles rarely share an exact ratio: the whole of a 1920x1291 reference over a 1520x1022 canvas
// is off by a fraction of a pixel. Within one target pixel the stretch cannot be seen.
export const sameAspect=(sw,sh,tw,th)=>Math.abs(sh*tw/sw-th)<=1;
/** A source of other proportions than its target, centre-cropped to the target's (LIVE 2026-10-23/24: five calls refused
 * for a few pixels' difference): {source, target}, or null when they already match. When whole source pixels cannot hit
 * the ratio within one target pixel (a large enlargement), the target is trimmed to the crop, centred, by under a scale's
 * worth of pixels. */
export function cropToAspect(source,target){
 const [sx,sy,sw,sh]=source,[tx,ty,tw,th]=target;
 if(!(sw>0&&sh>0&&tw>0&&th>0)||sameAspect(sw,sh,tw,th))return null;
 let crop;
 if(sw/sh>tw/th){const w=Math.max(1,Math.round(sh*tw/th));crop=[sx+Math.floor((sw-w)/2),sy,w,sh];}
 else{const h=Math.max(1,Math.round(sw*th/tw));crop=[sx,sy+Math.floor((sh-h)/2),sw,h];}
 let fitted=target;
 if(!sameAspect(crop[2],crop[3],tw,th)){
  if(sw/sh>tw/th){const w=Math.round(crop[2]*th/crop[3]);fitted=[tx+Math.floor((tw-w)/2),ty,w,th];}
  else{const h=Math.round(crop[3]*tw/crop[2]);fitted=[tx,ty+Math.floor((th-h)/2),tw,h];}
  if(fitted[2]>tw||fitted[3]>th||!sameAspect(crop[2],crop[3],fitted[2],fitted[3]))return null;
 }
 return {source:crop,target:fitted};
}
/** The source→target mapping of the reference tools, for other tools that place things from reference pixels (guides):
 * (x, y) in source pixels to canvas pixels, under the same aspect rule. Points outside the source map on, unclamped.
 * @param {number[]} source [x,y,w,h] in reference pixels @param {number[]} target [x,y,w,h] in canvas pixels
 * @returns {(x:number,y:number)=>[number,number]} */
export function mapReferencePoint(source,target){
 const [sx,sy,sw,sh]=source,[tx,ty,tw,th]=target;
 if(!(sw>0&&sh>0&&tw>0&&th>0)||!sameAspect(sw,sh,tw,th))throw new Error('Source and target must have matching aspect ratios; crop instead of stretching.');
 const scale=tw/sw;
 return (x,y)=>[tx+(x-sx)*scale,ty+(y-sy)*scale];
}
/** Strokes a dab transfer plans (an upper bound: transparent samples are skipped), from the recipe alone. */
export function estimateReferenceStrokes(recipe){
 const steps=recipe.steps??DEFAULT_STEPS,[,,sw,sh]=recipe.source;
 return steps.slice(0,2).reduce((n,s)=>n+Math.ceil(sw/s)*Math.ceil(sh/s),0)+(recipe.focal_regions??[]).reduce((n,r)=>n+Math.ceil(r[2]/steps[2])*Math.ceil(r[3]/steps[2]),0);
}
const rectInside=(r,w,h)=>r[2]>0&&r[3]>0&&r[0]+r[2]<=w&&r[1]+r[3]<=h;
const inside=(x,y,r)=>x>=r[0]&&y>=r[1]&&x<r[0]+r[2]&&y<r[1]+r[3];
function random(seed){let a=seed>>>0;return()=>{a+=0x6D2B79F5;let t=a;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296;};}
export function generateReferencePlan(recipe,image,canvas){
 if(!Value.Check(referenceSchema,recipe))throw new Error('Invalid reference recipe. Use source/target rectangles and three decreasing sampling steps.');
 if(!canvas||!Number.isInteger(canvas.width)||!Number.isInteger(canvas.height)||!rectInside(recipe.target,canvas.width,canvas.height))throw new Error('Target must fit the observed canvas.');
 if(!Number.isInteger(image.width)||!Number.isInteger(image.height)||image.width*image.height>REFERENCE_PIXELS||image.data.length!==image.width*image.height*4)throw new Error('Invalid decoded reference.');
 if(!rectInside(recipe.source,image.width,image.height))throw new Error('Source crop must fit the reference.');
 const [sx,sy,sw,sh]=recipe.source,[tx,ty,tw,th]=recipe.target,scale=tw/sw;
 if(!sameAspect(sw,sh,tw,th))throw new Error('Source and target must have matching aspect ratios; crop instead of stretching.');
 const steps=recipe.steps??DEFAULT_STEPS;
 if(!(steps[0]>steps[1]&&steps[1]>steps[2]))throw new Error('Sampling steps must decrease from coarse to fine to focal.');
 for(const r of recipe.focal_regions??[])if(!rectInside(r,image.width,image.height)||r[0]<sx||r[1]<sy||r[0]+r[2]>sx+sw||r[1]+r[3]>sy+sh)throw new Error('Focal regions must fit the source crop.');
 // Bound work before allocating or scanning potentially enormous grids.
 if(estimateReferenceStrokes(recipe)>PLAN_STROKES_MAX)throw new Error(`Recipe exceeds ${PLAN_STROKES_MAX.toLocaleString('en-US')} samples. Increase steps or reduce the crop.`);
 const sample=(x,y,r)=>{let sum=[0,0,0],alpha=0,n=0;for(let yy=Math.max(sy,Math.floor(y)-r);yy<=Math.min(sy+sh-1,Math.floor(y)+r);yy++)for(let xx=Math.max(sx,Math.floor(x)-r);xx<=Math.min(sx+sw-1,Math.floor(x)+r);xx++){const i=(yy*image.width+xx)*4,a=image.data[i+3]/255;alpha+=a;n++;for(let k=0;k<3;k++)sum[k]+=image.data[i+k]*a;}return {rgb:sum.map(v=>alpha?v/alpha:0),alpha:n?alpha/n:0};};
 const luminance=(x,y)=>{const {rgb,alpha}=sample(Math.max(sx,Math.min(sx+sw-1,x)),Math.max(sy,Math.min(sy+sh-1,y)),0);return(rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722)*alpha;};
 const inner=[tx>0,ty>0,tx+tw<canvas.width,ty+th<canvas.height],band=PATCH_FEATHER*Math.min(tw,th);
 const edgeDistance=(x,y)=>Math.min(...[x-tx,y-ty,tx+tw-x,ty+th-y].filter((_,i)=>inner[i]),Infinity);
 const passes=[];
 for(let stage=0;stage<3;stage++){
  if(stage===2&&!recipe.focal_regions?.length)break;
  const step=steps[stage],rand=random((recipe.seed??714)+stage),strokes=[],seen=new Set();
  const regions=stage===2?recipe.focal_regions:[recipe.source];
  for(const region of regions)for(let y=region[1]+step/2;y<region[1]+region[3];y+=step)for(let x=region[0]+step/2;x<region[0]+region[2];x+=step){
   // Deduplicate overlapping focal rectangles, without painting outside them.
   const key=Math.floor((x-sx)/step)+','+Math.floor((y-sy)/step);if(seen.has(key))continue;seen.add(key);
   const px=Math.max(region[0],Math.min(region[0]+region[2]-.001,x+(rand()-.5)*.44*step));
   const py=Math.max(region[1],Math.min(region[1]+region[3]-.001,y+(rand()-.5)*.44*step));
   const {rgb,alpha}=sample(px,py,stage===2?0:Math.max(1,Math.floor(step*.38)));if(alpha<.01)continue;
   const radius=Math.max(1,Math.floor(step*.38)),gx=luminance(px+radius,py)-luminance(px-radius,py),gy=luminance(px,py+radius)-luminance(px,py-radius);
   const angle=Math.abs(gx)+Math.abs(gy)>3?Math.atan2(gy,gx)+Math.PI/2:rand()*Math.PI;
   const dx=Math.cos(angle)*step*.21,dy=Math.sin(angle)*step*.21;
   const point=(x,y)=>[Math.max(tx,Math.min(tx+tw,tx+(x-sx)*scale)),Math.max(ty,Math.min(ty+th,ty+(y-sy)*scale))];
   const a=point(px-dx,py-dy),b=point(px+dx,py+dy);
   const d=edgeDistance((a[0]+b[0])/2,(a[1]+b[1])/2);
   let opacity=alpha;
   if(d<band){const t=Math.min(1,d/band*(.75+.5*rand()));opacity*=t*t*(3-2*t);if(opacity<.02)continue;}
   strokes.push({start:a,segments:[[...a,...b,...b]],size:Math.max(1,step*scale*1.5),opacity,flow:1,color:'#'+rgb.map(v=>Math.round(v).toString(16).padStart(2,'0')).join('')});
  }
  for(let i=strokes.length-1;i>0;i--){const j=Math.floor(rand()*(i+1));[strokes[i],strokes[j]]=[strokes[j],strokes[i]];}
  if(strokes.length)passes.push({name:['Coarse coverage','Fine detail','Focal refinement'][stage],step,strokes});
 }
 if(!passes.length)throw new Error('Reference region is transparent; no paint is needed.');
 return {version:REFERENCE_GENERATOR_VERSION,recipe,canvas:{width:canvas.width,height:canvas.height},passes,total:passes.reduce((n,p)=>n+p.strokes.length,0)};
}

// Edge refinement: strokes that follow the reference's own edges, for finishing. The dab transfer
// above paints a grid of 25-60 px dabs on a large canvas, which cannot make a crisp edge; these
// strokes trace each edge along its tangent and paint it as two thin strokes, one in each side's
// colour, which is how a painter sharpens an edge. The plan depends only on the recipe, the
// reference pixels and the canvas size, so a stopped job rebuilds it identically.
export const edgeSchema=object({
 name:Type.String({minLength:1,maxLength:100}),reference_id:Type.String({minLength:1}),preset:Type.String({minLength:1,maxLength:200}),
 source:rect(),target:rect(),
 spacing:Type.Optional(Type.Number({minimum:.75,maximum:EDGE_SPACING_MAX,description:'Source pixels between neighbouring edge strokes, and each stroke’s width. Default 1.5.'})),
 min_contrast:Type.Optional(Type.Number({minimum:.02,maximum:1,description:'Weakest edge to paint, as a share of full black-to-white contrast. Default 0.1; raise it for fewer, stronger edges.'})),
 max_length:Type.Optional(Type.Integer({minimum:2,maximum:60,description:'Longest stroke, in steps of spacing. Default 16.'})),
 seed:Type.Optional(Type.Integer({minimum:0,maximum:4294967295})),
});
export const EDGE_LIMIT=60000;
// The crop of a source/target recipe: its luminance (0-1, transparent counts as dark) and Sobel gradient.
function cropGradient(recipe,image,canvas){
 if(!canvas||!Number.isInteger(canvas.width)||!Number.isInteger(canvas.height)||!rectInside(recipe.target,canvas.width,canvas.height))throw new Error('Target must fit the observed canvas.');
 if(!Number.isInteger(image.width)||!Number.isInteger(image.height)||image.width*image.height>REFERENCE_PIXELS||image.data.length!==image.width*image.height*4)throw new Error('Invalid decoded reference.');
 if(!rectInside(recipe.source,image.width,image.height))throw new Error('Source crop must fit the reference.');
 const [sx,sy,sw,sh]=recipe.source,[tx,ty,tw,th]=recipe.target,scale=tw/sw;
 if(!sameAspect(sw,sh,tw,th))throw new Error('Source and target must have matching aspect ratios; crop instead of stretching.');
 const L=new Float32Array(sw*sh);
 for(let y=0;y<sh;y++)for(let x=0;x<sw;x++){const i=((sy+y)*image.width+sx+x)*4;L[y*sw+x]=(image.data[i]*.2126+image.data[i+1]*.7152+image.data[i+2]*.0722)*image.data[i+3]/65025;}
 const GX=new Float32Array(sw*sh),GY=new Float32Array(sw*sh),M=new Float32Array(sw*sh);
 const l=(x,y)=>L[Math.max(0,Math.min(sh-1,y))*sw+Math.max(0,Math.min(sw-1,x))];
 for(let y=0;y<sh;y++)for(let x=0;x<sw;x++){
  const gx=(l(x+1,y-1)+2*l(x+1,y)+l(x+1,y+1)-l(x-1,y-1)-2*l(x-1,y)-l(x-1,y+1))/4,gy=(l(x-1,y+1)+2*l(x,y+1)+l(x+1,y+1)-l(x-1,y-1)-2*l(x,y-1)-l(x+1,y-1))/4;
  const k=y*sw+x;GX[k]=gx;GY[k]=gy;M[k]=Math.hypot(gx,gy);}
 const at=(x,y)=>{const xi=Math.round(x),yi=Math.round(y);return xi<0||yi<0||xi>=sw||yi>=sh?-1:yi*sw+xi;};
 const pixel=(x,y)=>{const k=at(x,y);if(k<0)return null;const i=((sy+Math.floor(k/sw))*image.width+sx+k%sw)*4;return {rgb:[image.data[i],image.data[i+1],image.data[i+2]],alpha:image.data[i+3]/255};};
 const point=(x,y)=>[Math.max(tx,Math.min(tx+tw,tx+(x+.5)*scale)),Math.max(ty,Math.min(ty+th,ty+(y+.5)*scale))];
 return {sw,sh,scale,GX,GY,M,at,pixel,point};
}
const hex=rgb=>'#'+rgb.map(v=>Math.round(v).toString(16).padStart(2,'0')).join('');
// A polyline as straight cubic segments, the shape a native pass takes.
const curve=pts=>({start:pts[0],segments:pts.slice(1).map((q,i)=>{const p=pts[i];return [p[0]+(q[0]-p[0])/3,p[1]+(q[1]-p[1])/3,p[0]+2*(q[0]-p[0])/3,p[1]+2*(q[1]-p[1])/3,q[0],q[1]];})});
export function generateEdgePlan(recipe,image,canvas,{limit=EDGE_LIMIT}={}){
 const {mode,...fields}=recipe;
 if(mode!=='edges'||!Value.Check(edgeSchema,fields))throw new Error('Invalid edge recipe. Use source/target rectangles and optional spacing, min_contrast and max_length.');
 const {sw,sh,scale,GX,GY,M,at,pixel,point}=cropGradient(recipe,image,canvas);
 const s=recipe.spacing??1.5,threshold=recipe.min_contrast??.1,maxLength=recipe.max_length??16;
 const cols=Math.ceil(sw/s),rows=Math.ceil(sh/s),taken=new Uint8Array(cols*rows);
 const cell=(x,y)=>Math.min(rows-1,Math.max(0,Math.floor(y/s)))*cols+Math.min(cols-1,Math.max(0,Math.floor(x/s)));
 // Strongest edges first; equal strengths in pixel order, so the plan is deterministic.
 const seeds=[];for(let k=0;k<M.length;k++)if(M[k]>=threshold)seeds.push(k);
 seeds.sort((a,b)=>M[b]-M[a]||a-b);
 const strokes=[];
 for(const [seen,seed] of seeds.entries()){
  const x0=seed%sw,y0=Math.floor(seed/sw);if(taken[cell(x0,y0)])continue;
  const tangent=k=>[-GY[k]/M[k],GX[k]/M[k]];
  const path=[[x0,y0]];
  for(const direction of [1,-1]){
   let [x,y]=[x0,y0],[dx,dy]=tangent(seed).map(v=>v*direction);
   for(let n=0;n<maxLength;n++){
    const nx=x+dx*s,ny=y+dy*s,k=at(nx,ny);
    if(k<0||M[k]<threshold*.6||taken[cell(nx,ny)])break;
    let [ex,ey]=tangent(k);if(ex*dx+ey*dy<0){ex=-ex;ey=-ey;}
    if(ex*dx+ey*dy<.64)break;                               // turned more than 50 degrees: a corner ends the stroke
    direction>0?path.push([nx,ny]):path.unshift([nx,ny]);x=nx;y=ny;dx=ex;dy=ey;
   }
  }
  for(const [x,y] of path)taken[cell(x,y)]=1;
  // Normal toward the brighter side at the seed; each side gets a stroke in its own colour.
  const [nx,ny]=[GX[seed]/M[seed],GY[seed]/M[seed]];
  const line=path.length>1?path:(([tx_,ty_])=>[[x0-tx_*s/2,y0-ty_*s/2],[x0+tx_*s/2,y0+ty_*s/2]])(tangent(seed));
  for(const side of [-1,1]){
   const colour=pixel(x0+side*nx*(s/2+1),y0+side*ny*(s/2+1));if(!colour||colour.alpha<.01)continue;
   const pts=line.map(([x,y])=>point(x+side*nx*s/2,y+side*ny*s/2));
   strokes.push({...curve(pts),size:Math.max(1,s*scale*1.05),opacity:colour.alpha,flow:1,color:hex(colour.rgb)});
  }
  if(strokes.length>limit)throw Object.assign(new Error(`More than ${limit} edge strokes. Raise min_contrast or spacing, or choose a smaller region (focal areas, not the whole picture).`),
   {limit,estimate:Math.round(strokes.length*seeds.length/(seen+1))});   // strokes so far, scaled to every seed: the count the pass would make
 }
 if(!strokes.length)throw new Error('No edges at this contrast; lower min_contrast or choose a region with edges.');
 const rand=random(recipe.seed??714);
 for(let i=strokes.length-1;i>0;i--){const j=Math.floor(rand()*(i+1));[strokes[i],strokes[j]]=[strokes[j],strokes[i]];}
 return {version:REFERENCE_GENERATOR_VERSION,recipe,canvas:{width:canvas.width,height:canvas.height},passes:[{name:'Edge refinement',step:s,strokes}],total:strokes.length};
}

// Surface pass: smudge strokes that follow the reference's form flow in the smooth areas between
// edges, so the transfer's grid of dabs blends into continuous paint, then the same region's edges
// repainted crisp on top. The smudge runs in overlay mode, picking up the colours already on the
// canvas; each stroke's colour is the reference's at its start, used only by presets that also
// deposit paint. Strokes stay a brush radius clear of edges and skip busy areas (lit windows,
// reflections, snow, fur), which a live run smeared into blobs. At full strength a smudge carries
// its first colour the whole stroke, so the default is half strength and short strokes.
export const surfaceSchema=object({
 name:Type.String({minLength:1,maxLength:100}),reference_id:Type.String({minLength:1}),preset:Type.String({minLength:1,maxLength:200}),
 source:rect(),target:rect(),
 spacing:Type.Optional(Type.Number({minimum:1,maximum:SURFACE_SPACING_MAX,description:'Source pixels between neighbouring strokes; the brush is twice as wide. Default 3, or 3 canvas pixels when the canvas is smaller than the reference.'})),
 length:Type.Optional(Type.Number({minimum:2,maximum:SURFACE_LENGTH_MAX,description:'Longest stroke, in source pixels. Default 12.'})),
 strength:Type.Optional(Type.Number({minimum:.1,maximum:1,description:'How far a stroke carries paint: 1 drags its first colour the whole way, 0.3 barely mixes. Default 0.5.'})),
 edge_contrast:Type.Optional(Type.Number({minimum:.02,maximum:1,description:'Edges at least this strong stop a stroke and are repainted crisp afterwards (same scale as min_contrast). Default 0.3.'})),
 max_detail:Type.Optional(Type.Number({minimum:.02,maximum:1,description:'Areas busier than this are left alone. Measured: sky 0.04, clouds and hair 0.07, windows, reflections and fur 0.11, wet road 0.17. Default 0.07.'})),
 smoothing:Type.Optional(Type.Integer({minimum:1,maximum:12,description:'Radius in source pixels over which the form direction is averaged; raise it where texture hides the form (glass, water). Default 3.'})),
 edges:Type.Optional(Type.Boolean({description:'Repaint the region\u2019s edges crisp after blending. Default true.'})),
 edge_preset:Type.Optional(Type.String({minLength:1,maxLength:200,description:'Preset for the edge pass. Default b) Basic-6 Details.'})),
 seed:Type.Optional(Type.Integer({minimum:0,maximum:4294967295})),
});
export const SURFACE_LIMIT=60000;
// Two passes of a separable box blur, close to a Gaussian.
function smooth(values,w,h,r){
 const tmp=new Float32Array(values.length);let out=values;
 for(let pass=0;pass<2;pass++){
  for(let y=0;y<h;y++){let sum=0;for(let x=-r;x<=r;x++)sum+=out[y*w+Math.max(0,Math.min(w-1,x))];
   for(let x=0;x<w;x++){tmp[y*w+x]=sum/(2*r+1);sum+=out[y*w+Math.min(w-1,x+r+1)]-out[y*w+Math.max(0,x-r)];}}
  const next=new Float32Array(values.length);
  for(let x=0;x<w;x++){let sum=0;for(let y=-r;y<=r;y++)sum+=tmp[Math.max(0,Math.min(h-1,y))*w+x];
   for(let y=0;y<h;y++){next[y*w+x]=sum/(2*r+1);sum+=tmp[Math.min(h-1,y+r+1)*w+x]-tmp[Math.max(0,y-r)*w+x];}}
  out=next;
 }
 return out;
}
export function generateSurfacePlan(recipe,image,canvas){
 const {mode,...fields}=recipe;
 if(mode!=='surface'||!Value.Check(surfaceSchema,fields))throw new Error('Invalid surface recipe. Use source/target rectangles and optional spacing, length, strength, edge_contrast, max_detail, smoothing, edges and edge_preset.');
 const {sw,sh,scale,GX,GY,M,at,pixel,point}=cropGradient(recipe,image,canvas);
 // Default spacing: 3 source px, but never closer than 3 canvas px when the canvas is smaller than the reference.
 const s=recipe.spacing??Math.min(SURFACE_SPACING_MAX,Math.max(3,3/scale)),edge=recipe.edge_contrast??.3,maxLength=recipe.length??12,r=recipe.smoothing??3,busy=recipe.max_detail??.07;
 // Structure tensor: the averaged gradient orientation, whose perpendicular is the form's flow.
 const XX=new Float32Array(sw*sh),XY=new Float32Array(sw*sh),YY=new Float32Array(sw*sh);
 for(let k=0;k<M.length;k++){XX[k]=GX[k]*GX[k];XY[k]=GX[k]*GY[k];YY[k]=GY[k]*GY[k];}
 const [A,B,C]=[XX,XY,YY].map(v=>smooth(v,sw,sh,r));
 // Edges, grown by the brush radius (one spacing), are off limits.
 const near=new Uint8Array(sw*sh),rows=new Uint8Array(sw*sh),grow=Math.ceil(s);
 for(let y=0;y<sh;y++){let count=0;for(let x=0;x<Math.min(sw,grow);x++)count+=+(M[y*sw+x]>=edge);
  for(let x=0;x<sw;x++){if(x+grow<sw)count+=+(M[y*sw+x+grow]>=edge);rows[y*sw+x]=+(count>0);if(x-grow>=0)count-=+(M[y*sw+x-grow]>=edge);}}
 for(let x=0;x<sw;x++){let count=0;for(let y=0;y<Math.min(sh,grow);y++)count+=rows[y*sw+x];
  for(let y=0;y<sh;y++){if(y+grow<sh)count+=rows[(y+grow)*sw+x];near[y*sw+x]=+(count>0);if(y-grow>=0)count-=rows[(y-grow)*sw+x];}}
 // Busy areas: the mean edge strength around each pixel, over about four spacings.
 const detail=smooth(M,sw,sh,Math.max(2,Math.round(s)));
 for(let k=0;k<near.length;k++)if(detail[k]>busy)near[k]=1;
 const flow=k=>{if(A[k]+C[k]<1e-7)return null;const t=.5*Math.atan2(2*B[k],A[k]-C[k]);return [-Math.sin(t),Math.cos(t)];};
 const rand=random(recipe.seed??714),step=Math.max(.75,s/2),strokes=[];
 for(let y=s/2;y<sh;y+=s)for(let x=s/2;x<sw;x+=s){
  const x0=Math.min(sw-1,x+(rand()-.5)*.6*s),y0=Math.min(sh-1,y+(rand()-.5)*.6*s),seed=at(x0,y0);
  const fallback=rand()*Math.PI;
  if(seed<0||near[seed])continue;
  const colour=pixel(x0,y0);if(!colour||colour.alpha<.01)continue;
  const start=flow(seed)??[Math.cos(fallback),Math.sin(fallback)],path=[[x0,y0]];
  for(const direction of [1,-1]){
   let [px,py]=[x0,y0],[dx,dy]=start.map(v=>v*direction);
   for(let n=0;n<maxLength/2/step;n++){
    const nx=px+dx*step,ny=py+dy*step,k=at(nx,ny);
    if(k<0||near[k])break;
    let next=flow(k)??[dx,dy];if(next[0]*dx+next[1]*dy<0)next=[-next[0],-next[1]];
    if(next[0]*dx+next[1]*dy<.7)break;                       // turned more than 45 degrees
    direction>0?path.push([nx,ny]):path.unshift([nx,ny]);px=nx;py=ny;[dx,dy]=next;
   }
  }
  if(path.length<2)continue;
  strokes.push({...curve(path.map(([x,y])=>point(x,y))),size:Math.max(2,s*scale*2),opacity:1,flow:1,color:hex(colour.rgb)});
  if(strokes.length>SURFACE_LIMIT)throw new Error(`More than ${SURFACE_LIMIT} surface strokes. Raise spacing or choose a smaller region.`);
 }
 if(!strokes.length)throw new Error('No smooth surface here; raise max_detail or edge_contrast, or choose a broader region.');
 for(let i=strokes.length-1;i>0;i--){const j=Math.floor(rand()*(i+1));[strokes[i],strokes[j]]=[strokes[j],strokes[i]];}
 const plan={version:REFERENCE_GENERATOR_VERSION,recipe,canvas:{width:canvas.width,height:canvas.height},passes:[{name:'Surface blending',step:s,smudge_rate:recipe.strength??.5,strokes},...surfaceEdges(recipe,image,canvas,edge,Math.min(16,Math.max(1.5,1.5/scale)))]};
 plan.total=plan.passes.reduce((n,p)=>n+p.strokes.length,0);
 return plan;
}
// The edge pass that follows a surface pass: the edges the smudge stopped at, raised until the
// region fits the edge limit (a live cockpit region was refused at the default contrast).
function surfaceEdges(recipe,image,canvas,edge,spacing){
 if(recipe.edges===false)return [];
 const preset=recipe.edge_preset??'b) Basic-6 Details';
 for(let contrast=edge;;contrast=Math.min(1,contrast*1.25)){
  try{const plan=generateEdgePlan({mode:'edges',name:recipe.name,reference_id:recipe.reference_id,preset,source:recipe.source,target:recipe.target,min_contrast:contrast,spacing,...(recipe.seed!==undefined?{seed:recipe.seed}:{})},image,canvas);
   return [{...plan.passes[0],preset}];}
  catch(error){if(/^No edges/.test(error.message))return [];if(!/^More than/.test(error.message)||contrast>=1)throw error;}
 }
}

// Edges and surface read every source pixel of the crop (gradients, a flow field): on a goal sharpened 4x that was 2 s and
// 10 s, and 0.5-0.75 GB more, against 0.25-0.36 s on the original. A crop of more than ANALYSIS_PIXELS is analysed from a
// copy reduced to that many, its spacing and length scaled with it, so the strokes on the canvas keep their size and the
// target is unchanged. The dab transfer (generateReferencePlan) samples the crop sparsely and reads it whole.
export const ANALYSIS_PIXELS=PLUGIN_DECODE_PIXELS;
export function analysisCopy(recipe,image,maxPixels=ANALYSIS_PIXELS){
 const [sx,sy,sw,sh]=recipe.source??[];
 if(!['edges','surface'].includes(recipe.mode)||!(sw*sh>maxPixels)||!rectInside(recipe.source,image.width,image.height))return {recipe,image};
 const f=Math.sqrt(maxPixels/(sw*sh)),w=Math.max(1,Math.floor(sw*f)),h=Math.max(1,Math.floor(sh*f)),k=w/sw;
 const crop=Buffer.alloc(sw*sh*4);
 for(let y=0;y<sh;y++)image.data.copy(crop,y*sw*4,((sy+y)*image.width+sx)*4,((sy+y)*image.width+sx+sw)*4);
 const small={width:w,height:h,data:Buffer.from(resizeBilinear(crop,sw,sh,4,w,h))};
 const scale=recipe.target[2]/sw,round=v=>Math.round(v*100)/100;
 const spacing=recipe.mode==='edges'?recipe.spacing??1.5:recipe.spacing??Math.min(SURFACE_SPACING_MAX,Math.max(3,3/scale));
 const out={...recipe,source:[0,0,w,h],spacing:Math.max(recipe.mode==='edges'?.75:1,round(spacing*k))};
 if(recipe.mode==='surface')out.length=Math.max(2,round((recipe.length??12)*k));
 return {recipe:out,image:small};
}

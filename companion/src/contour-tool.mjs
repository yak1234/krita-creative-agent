// @ts-check
import { isPaintingMode } from './modes.mjs';
import {Type} from 'typebox';
import {Value} from 'typebox/value';

const object=properties=>Type.Object(properties,{additionalProperties:false});
const point=Type.Array(Type.Number({minimum:0,maximum:8192}),{minItems:2,maxItems:2});
export const contourSchema=object({
  name:Type.String({minLength:1,maxLength:120}),
  preset:Type.String({minLength:1,maxLength:200}),
  shapes:Type.Array(object({
    color:Type.String({pattern:'^#[0-9a-fA-F]{6}$'}),
    points:Type.Array(point,{minItems:3,maxItems:128}),
  }),{minItems:1,maxItems:32}),
});

/** Translate explicitly drawn outlines into native selection-clipped brush fills.
 * No reference sampling, raster imports, random geometry, or inferred likeness.
 */
export function contourCommands(value,canvas) {
  if(!Value.Check(contourSchema,value))throw new Error('Supply named contours, an installed preset, colors and at least three points per shape.');
  if(!canvas || !Number.isFinite(canvas.width) || !Number.isFinite(canvas.height) || canvas.width<=0 || canvas.height<=0)
    throw new Error('Observe the current canvas before drawing contours.');
  const command=(tool,parameters)=>({tool,parameters_json:JSON.stringify(parameters)});
  const commands=[command('set_brush',{preset:value.preset,opacity:1,flow:1})];
  // Validate every contour before returning any commands to the bridge.
  for(const {color,points} of /** @type {{color: string, points: number[][]}[]} */ (value.shapes)) {
    if(points.some(([x,y])=>x>canvas.width || y>canvas.height))throw new Error('Contour points must lie inside the observed canvas.');
    const area=Math.abs(points.reduce((sum,[x,y],i)=>{const next=points[(i+1)%points.length];return sum+x*next[1]-next[0]*y;},0))/2;
    if(area<1)throw new Error('Contour must enclose at least one square pixel; use a brush curve for lines.');
    // Self-intersections make the intended interior ambiguous. Reject rather than guess.
    const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
    const on=(a,b,p)=>Math.abs(cross(a,b,p))<1e-9 && p[0]>=Math.min(a[0],b[0]) && p[0]<=Math.max(a[0],b[0]) && p[1]>=Math.min(a[1],b[1]) && p[1]<=Math.max(a[1],b[1]);
    for(let i=0;i<points.length;i++) {
      const a=points[i],b=points[(i+1)%points.length];
      if(a[0]===b[0] && a[1]===b[1])throw new Error('Do not repeat contour points; the outline closes automatically.');
      for(let j=i+1;j<points.length;j++) {
        if(j===i+1 || (i===0 && j===points.length-1))continue;
        const c=points[j],d=points[(j+1)%points.length];
        if((cross(a,b,c)*cross(a,b,d)<0 && cross(c,d,a)*cross(c,d,b)<0) || on(a,b,c)||on(a,b,d)||on(c,d,a)||on(c,d,b))
          throw new Error('Contour edges must not cross or touch nonadjacent edges.');
      }
    }
    const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
    const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys),y=(y0+y1)/2;
    commands.push(command('selection',{shape:'polygon',points,mode:'replace'}),
      command('curve_stroke',{start:[x0,y],segments:[[x0,y,x1,y,x1,y]],size:y1-y0+8,color,opacity:1,flow:1}),
      command('selection',{mode:'clear'}));
  }
  return {name:value.name,commands};
}

export function contourTool(runtime,executeToolbox) {
  return {name:'paint_contours',label:'Painting drawn contours',executionMode:'sequential',parameters:contourSchema,
    description:'Paint 1–32 deliberately drawn closed outlines in back-to-front order on one new editable layer. Supply each outline as ordered canvas-pixel points and a color. Uses native polygon selections and brush fills, not raster imports. Choose an opaque pigment-depositing installed preset. Draw actual silhouette changes (forehead, nose, lips, chin, collar, hand overlap); an ellipse or bounding box does not establish likeness. No automatic smoothing or reference tracing: add contour points where needed. No holes or crossing edges. Preserves prior canvas selection through the native toolbox transaction, obeys stage region restrictions, saves and returns the resulting image.',
    execute:async(id,value,signal)=>{
      signal?.throwIfAborted();
      if(runtime.mode!==undefined && (!isPaintingMode(runtime.mode)||runtime.executionPhase!=='agent'))throw new Error('Contours are only available in active Agent execution.');
      if(runtime.cancelRequested||runtime.faulted)throw new Error('Painting is stopped or needs recovery.');
      return executeToolbox(id,contourCommands(value,runtime.decisionObservation),signal);
    }};
}

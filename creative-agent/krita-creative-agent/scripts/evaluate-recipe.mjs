/** Live native smoke test; no model request. Creates a separate, clearly named test document. */
import {PaintingBridge} from '../src/bridge.mjs';
import {paintingTools} from '../src/tools.mjs';
import {mkdir,writeFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {resolve,join} from 'node:path';
const id=randomUUID();const directory=join(resolve(process.argv[2]),id);await mkdir(directory,{recursive:true});
const bridge=new PaintingBridge('',{bridge_url:'http://127.0.0.1:5678'});
const health=await bridge.call('health');if(health.session_active)throw new Error('A painting session is active; leave it alone.');
const previous=await bridge.call('context');
const before=await bridge.call('begin',{mode:'new',name:'Stroke recipe validation',width:640,height:480,background:'#ece3d4',output_dir:directory,painting_path:join(directory,'recipe-test.kra')},id,'begin');
const calls=[];
const runtime={mode:'agent',executionPhase:'agent',study:{id,directory},decisionObservation:before,cancelRequested:false,emit(){},async callNative(operation,args,operationId){
 const started=performance.now();
 const result=await bridge.call(operation,{...args,expected_revision:runtime.decisionObservation.revision,stage_id:'stage-1-0'},id,operationId);
 calls.push({operation,operationId,strokes:args.strokes.length,ms:performance.now()-started,layer_id:result.layer_id});
 if(runtime.stopAfter && calls.length===runtime.stopAfter)runtime.cancelRequested=true;
 return result;
}};
try{
 const tool=paintingTools(runtime).find(t=>t.name==='paint_recipe');
 const recipe={name:'Recipe · dry coral scumble',preset:'h) Chalk Grainy',region:[60,65,520,350],palette:['#c64d38','#da674c','#e88d6b'],stroke_count:1200,size:[18,42],opacity:[.15,.3],direction:'horizontal',irregularity:.85,seed:42,layer_opacity:.8};
 const started=performance.now();const result=await tool.execute('native-recipe-1200',recipe);const elapsed=performance.now()-started;
 if(result.details.completed_strokes!==1200 || calls.length!==5)throw new Error('Unexpected generated execution count.');
 const completedImage=runtime.decisionObservation.image_path;
 runtime.stopAfter=6;const stopped=await tool.execute('native-stop-test',{...recipe,name:'Recipe · Stop verification',stroke_count:600,opacity:[.02,.04],seed:99});
 if(stopped.details.status!=='stopped'||stopped.details.completed_strokes!==256||calls.length!==6)throw new Error('Stop failed to prevent the next chunk.');
 const evidence={health,previous_document:previous,before_image:before.image_path,completed_image:completedImage,after_stop_image:runtime.decisionObservation.image_path,recipe,result:result.details,stopped:stopped.details,elapsed_ms:elapsed,calls};
 await writeFile(join(directory,'validation.json'),JSON.stringify(evidence,null,2)+'\n');
 console.log(JSON.stringify({completed:result.details.completed_strokes,chunks:5,elapsed_ms:elapsed,stop_completed:stopped.details.completed_strokes,completed_image:completedImage,directory}));
}finally{await bridge.call('end',{},id);}

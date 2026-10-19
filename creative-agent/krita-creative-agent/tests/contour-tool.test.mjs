import test from 'node:test';
import assert from 'node:assert/strict';
import {contourCommands,contourTool} from '../src/contour-tool.mjs';

const sample={name:'Profile silhouette',preset:'b) Basic-2 Opacity',shapes:[{color:'#ab886a',points:[[20,10],[60,10],[55,25],[65,35],[53,40],[50,55],[25,48]]}]};
const canvas={width:100,height:100};
test('concave profile keeps its contour, fills through a native selection, and clears only inside the toolbox transaction',()=>{
  const result=contourCommands(sample,canvas);
  const rows=result.commands.map(c=>({tool:c.tool,p:JSON.parse(c.parameters_json)}));
  assert.deepEqual(rows.map(r=>r.tool),['set_brush','selection','curve_stroke','selection']);
  assert.deepEqual(rows[1].p.points,sample.shapes[0].points);
  assert.equal(rows[1].p.mode,'replace');assert.equal(rows[3].p.mode,'clear');
  assert.equal(rows[2].p.color,'#ab886a');assert.ok(rows[2].p.size>=45);
  assert.deepEqual(rows[2].p.start,[20,32.5]);
  assert.equal(result.name,sample.name);
});
test('invalid later contour rejects the whole request before any native call',async()=>{
  let calls=0;const runtime={mode:'agent',executionPhase:'agent',decisionObservation:canvas};
  const tool=contourTool(runtime,async()=>{calls++;});
  for(const points of [[[10,10],[110,20],[20,30]],[[10,10],[20,20],[30,30]],[[10,10],[80,70],[10,80],[70,10],[90,30]],[[10,10],[20,10],[20,30],[10,10]]]) {
    await assert.rejects(tool.execute('operation',{...sample,shapes:[...sample.shapes,{color:'#000000',points}]}));
  }
  assert.equal(calls,0);
});
test('contours use existing operation identity and propagate uncertain outcomes once, without replay',async()=>{
  const runtime={mode:'agent',executionPhase:'agent',decisionObservation:canvas};let calls=0;
  const tool=contourTool(runtime,async(id,params)=>{calls++;assert.equal(id,'native-1');assert.equal(params.name,sample.name);throw Object.assign(new Error('unknown result'),{code:'outcome_unknown'});});
  await assert.rejects(tool.execute('native-1',sample),{code:'outcome_unknown'});assert.equal(calls,1);
  runtime.mode='ask';await assert.rejects(tool.execute('native-2',sample),/active Agent/);assert.equal(calls,1);
  runtime.mode='agent';runtime.cancelRequested=true;await assert.rejects(tool.execute('native-3',sample),/stopped/);assert.equal(calls,1);
});

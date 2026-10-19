import test from 'node:test';
import assert from 'node:assert/strict';
import { comicContext, comicPlanProblems } from '../src/comic.mjs';

const panels = ['P1','P2','P3','P4'].map((id,i)=>({id,bounds:[i*100,0,90,90],order:i+1}));
const beat = panel => ({panel,beat:'Seeker watches the plain.',shot:'wide',characters:['Seeker']});
const brief = (story, steps=[{title:'Panels',done_when:'Painted.',panels:['P1','P2','P3','P4']},{title:'Lettering',done_when:'Lettered.'}]) => ({story,steps});

test('a comic plan tells every panel once and paints every panel', () => {
  assert.equal(comicPlanProblems(brief({logline:'A troop leaves the forest.',panels:['P1','P2','P3','P4'].map(beat)}), panels), null);
  assert.match(comicPlanProblems({steps:[]}, panels), /needs a story.*P1, P2, P3, P4/);
  const gaps = comicPlanProblems(brief({logline:'x',panels:[beat('P1'),beat('P2'),beat('P4'),beat('P4'),beat('P9')]},
    [{title:'Some',done_when:'x',panels:['P1','P7']}]), panels);
  assert.match(gaps, /P3 has no beat/);
  assert.match(gaps, /the page has no P9/);
  assert.match(gaps, /P4 told more than once/);
  assert.match(gaps, /no step paints P2, P3, P4/);
  assert.match(gaps, /steps name unknown panels P7/);
});

test('the comic context lists panels without host ids', () => {
  const context = comicContext({built:true,layout:{preset:'grid-2x2',reading:'rtl'},panels:panels.map(p=>({...p,group_id:'node-1'}))});
  assert.deepEqual(context.panels[0], {id:'P1',bounds:[0,0,90,90],order:1});
  assert.deepEqual([context.built,context.reading], [true,'rtl']);
  assert.equal(comicContext(null), null);
});

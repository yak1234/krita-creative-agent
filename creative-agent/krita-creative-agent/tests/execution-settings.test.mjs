import test from 'node:test';
import assert from 'node:assert/strict';
import { executionSettings, thinkingLevel } from '../src/execution-settings.mjs';
import { StudioRuntime } from '../src/studio.mjs';
test('execution defaults preserve one painter and capability-aware reasoning',()=>{
 assert.deepEqual(executionSettings(),{concurrency:1,reasoning:'auto',routing:'off',native_craft:true,move_size:'subject',merge_kept:true,guides:true,reference_first:true,assets:'codex',ai_images:0,keep_screen_awake:false,sharpen_goal:'ask',view_size:'auto',planner_model:'painter',decisions:{endpoint:'openrouter',model:'openai/gpt-6-luna-decisions'}});
 assert.equal(thinkingLevel(executionSettings(),{reasoning:true}),'low');
 assert.equal(thinkingLevel(executionSettings({reasoning:'high'}),{reasoning:true}),'high');
 assert.equal(thinkingLevel(executionSettings({reasoning:'high'}),{reasoning:false}),'off');
 assert.equal(thinkingLevel(executionSettings({reasoning:'max'}),{reasoning:true}),'max');
 assert.throws(()=>executionSettings({concurrency:8}));assert.throws(()=>executionSettings({reasoning:'unlimited'}));
 assert.equal(executionSettings({move_size:'large'}).move_size,'large');assert.throws(()=>executionSettings({move_size:'huge'}),/move size/);
 assert.equal(executionSettings({native_craft:false}).native_craft,false);assert.throws(()=>executionSettings({native_craft:'no'}),/native_craft/);
 assert.equal('computer_use' in executionSettings({computer_use:true}),false,'a setting saved when computer use existed is dropped');
 assert.equal(executionSettings({assets:'openrouter'}).assets,'openrouter');assert.throws(()=>executionSettings({assets:'dall-e'}),/image assets/);
 assert.equal(executionSettings().ai_images,0,'a new install starts with no AI images');assert.equal(executionSettings({ai_images:'unlimited'}).ai_images,'unlimited');
 assert.equal(executionSettings({ai_images:3}).ai_images,3);assert.throws(()=>executionSettings({ai_images:2}),/AI images/);assert.throws(()=>executionSettings({ai_images:'3'}),/AI images/);
});

test('settings are declared once: validation, defaults and the panel schema come from the declarations', async () => {
 const { SETTINGS, panelSchema } = await import('../src/settings-schema.mjs');
 const keys=SETTINGS.map(s=>s.key);
 assert.deepEqual(Object.keys(executionSettings()).filter(k=>k!=='decisions'),keys,'every declared setting, and nothing else, is in the settings');
 for (const setting of SETTINGS) {
  assert.ok(setting.error,setting.key+' has an error message');
  assert.throws(()=>executionSettings({[setting.key]:'not-an-option'}),new RegExp(setting.error.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
  if (setting.panel==='generic') assert.ok(setting.label && setting.accessible && setting.options.length>=(setting.type==='model' ? 1 : 2),setting.key+' can be built by the panel');
 }
 const schema=panelSchema();
 assert.deepEqual(schema.map(f=>f.key),['concurrency','move_size','merge_kept','guides','reference_first','assets','ai_images','keep_screen_awake','sharpen_goal','view_size','planner_model','routing'],'reasoning is custom and native_craft hidden');
 assert.deepEqual(schema.find(f=>f.key==='merge_kept').options,[{value:true,label:'Merge kept passes'},{value:false,label:'Keep every pass'}]);
 assert.deepEqual(Object.keys(schema[0]).sort(),['accessible','control','key','label','note','options','tooltip']);
 assert.equal(schema.find(f=>f.key==='keep_screen_awake').control,'checkbox');assert.equal(schema[0].control,'combo');
 assert.equal(executionSettings().keep_screen_awake,false,'a screen that never sleeps is the artist\'s choice');
});

test('Start from the reference\'s colours is on by default, a combo, and says when it applies and when to turn it off', async () => {
 const { SETTINGS, panelSchema } = await import('../src/settings-schema.mjs');
 assert.equal(executionSettings().reference_first,true);
 assert.equal(executionSettings({reference_first:false}).reference_first,false);
 assert.throws(()=>executionSettings({reference_first:'yes'}),/reference_first must be true or false/);
 const field=panelSchema().find(f=>f.key==='reference_first');
 assert.equal(field.control,'combo','a default-on setting is a combo, as guides');
 assert.equal(field.accessible,'Start from the reference\'s colours');
 assert.deepEqual(field.options.map(o=>o.value),[true,false]);
 const tooltip=SETTINGS.find(s=>s.key==='reference_first').tooltip;
 assert.match(tooltip,/goal reference is attached/);
 assert.match(tooltip,/stylised/); assert.match(tooltip,/yourself/);
});

test('Auto reasons at medium for the plan and the review and at low while painting; a chosen level holds in every phase',()=>{
 const auto=executionSettings(),high=executionSettings({reasoning:'high'}),model={reasoning:true};
 assert.deepEqual(['ask','plan','agent','review','preparation'].map(p=>thinkingLevel(auto,model,p)),['low','medium','low','medium','low']);
 assert.deepEqual(['plan','agent','review'].map(p=>thinkingLevel(high,model,p)),['high','high','high']);
 assert.equal(thinkingLevel(auto,{reasoning:false},'plan'),'off');
 // The painter session follows the phase, and is only told when the level changes.
 const set=[];
 const studio={executionSettings:auto,study:{provider:'p',model:'m'},models:{getModel:()=>model},
  session:{thinkingLevel:'low',setThinkingLevel(level){set.push(level);this.thinkingLevel=level;}}};
 for(const phase of ['agent','plan','plan','agent','ask'])StudioRuntime.prototype.applyPhaseReasoning.call(studio,phase);
 assert.deepEqual(set,['medium','low']);
});

test('Sharpen small goal images: Ask by default, Always or Never; one schema entry the panel builds from',async()=>{
 const { panelSchema } = await import('../src/settings-schema.mjs');
 assert.equal(executionSettings().sharpen_goal,'ask');
 assert.equal(executionSettings({sharpen_goal:'never'}).sharpen_goal,'never');
 assert.throws(()=>executionSettings({sharpen_goal:'sometimes'}),/Sharpen small goal images: choose Ask, Always or Never/);
 const field=panelSchema().find(f=>f.key==='sharpen_goal');
 assert.equal(field.label,'Sharpen small goal images');
 assert.deepEqual(field.options.map(o=>o.value),['ask','always','never']);
 assert.match(field.tooltip,/nothing is uploaded/i);
});

test('canvas view size (luna-goal-reviewer goal 3, eyes-and-history 1): Auto by default, or 1024, 1568 or 2000 px', async () => {
 const { panelSchema } = await import('../src/settings-schema.mjs');
 assert.equal(executionSettings().view_size, 'auto');
 assert.equal(executionSettings({view_size:2000}).view_size, 2000);
 // Pi shrinks any image over 2000 px a side, so 2048 was never seen: a saved 2048 becomes 2000.
 assert.equal(executionSettings({view_size:2048}).view_size, 2000);
 assert.throws(() => executionSettings({view_size:'2000'}), /canvas view size/);
 const field = panelSchema().find(f => f.key === 'view_size');
 assert.deepEqual(field.options.map(o => o.value), ['auto', 1024, 1568, 2000]);
 assert.doesNotMatch(field.tooltip, /2048/);
});

// A planner model (plan-from-request goal 4, the artist 2026-10-24): plan turns may use another model than the painter.
test('Planner model: the painter by default; a provider/model route; the panel lists the routes it is given, and the saved one', async () => {
 const { panelSchema } = await import('../src/settings-schema.mjs');
 assert.equal(executionSettings().planner_model,'painter');
 assert.equal(executionSettings({planner_model:'openrouter/z-ai/glm-5.3-flash'}).planner_model,'openrouter/z-ai/glm-5.3-flash');
 assert.throws(()=>executionSettings({planner_model:'glm'}),/Planner model/);
 assert.throws(()=>executionSettings({planner_model:42}),/Planner model/);
 assert.deepEqual(panelSchema().find(f=>f.key==='planner_model').options,[{value:'painter',label:'Same as the painter'}]);
 const field=panelSchema({models:[{route:'openrouter/qwen/qwen3.8-flash',label:'Qwen3.8 Flash (openrouter)'}]}).find(f=>f.key==='planner_model');
 assert.deepEqual(field.options,[{value:'painter',label:'Same as the painter'},{value:'openrouter/qwen/qwen3.8-flash',label:'Qwen3.8 Flash (openrouter)'}]);
 assert.match(field.tooltip,/plan/i);
});

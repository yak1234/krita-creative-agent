import test from 'node:test';
import assert from 'node:assert/strict';
import { executionSettings, thinkingLevel } from '../src/execution-settings.mjs';
import { StudioRuntime } from '../src/studio.mjs';
test('execution defaults preserve one painter and capability-aware reasoning',()=>{
 assert.deepEqual(executionSettings(),{concurrency:1,reasoning:'auto',routing:'off',native_craft:true,move_size:'subject',merge_kept:true,guides:true,assets:'codex',ai_images:0,keep_screen_awake:false,decisions:{endpoint:'openrouter',model:'openai/gpt-6-luna-decisions'}});
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
  if (setting.panel==='generic') assert.ok(setting.label && setting.accessible && setting.options.length>=2,setting.key+' can be built by the panel');
 }
 const schema=panelSchema();
 assert.deepEqual(schema.map(f=>f.key),['concurrency','move_size','merge_kept','guides','assets','ai_images','keep_screen_awake','routing'],'reasoning is custom and native_craft hidden');
 assert.deepEqual(schema.find(f=>f.key==='merge_kept').options,[{value:true,label:'Merge kept passes'},{value:false,label:'Keep every pass'}]);
 assert.deepEqual(Object.keys(schema[0]).sort(),['accessible','control','key','label','note','options','tooltip']);
 assert.equal(schema.find(f=>f.key==='keep_screen_awake').control,'checkbox');assert.equal(schema[0].control,'combo');
 assert.equal(executionSettings().keep_screen_awake,false,'a screen that never sleeps is the artist\'s choice');
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

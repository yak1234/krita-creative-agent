import test from 'node:test';
import assert from 'node:assert/strict';
import { executionSettings, thinkingLevel } from '../src/execution-settings.mjs';
test('execution defaults preserve one painter and capability-aware reasoning',()=>{
 assert.deepEqual(executionSettings(),{concurrency:1,reasoning:'auto',routing:'off',native_craft:true,move_size:'subject',merge_kept:true,assets:'codex',decisions:{endpoint:'openrouter',model:'openai/gpt-6-luna-decisions'}});
 assert.equal(thinkingLevel(executionSettings(),{reasoning:true}),'low');
 assert.equal(thinkingLevel(executionSettings({reasoning:'high'}),{reasoning:true}),'high');
 assert.equal(thinkingLevel(executionSettings({reasoning:'high'}),{reasoning:false}),'off');
 assert.equal(thinkingLevel(executionSettings({reasoning:'max'}),{reasoning:true}),'max');
 assert.throws(()=>executionSettings({concurrency:8}));assert.throws(()=>executionSettings({reasoning:'unlimited'}));
 assert.equal(executionSettings({move_size:'large'}).move_size,'large');assert.throws(()=>executionSettings({move_size:'huge'}),/move size/);
 assert.equal(executionSettings({native_craft:false}).native_craft,false);assert.throws(()=>executionSettings({native_craft:'no'}),/native_craft/);
 assert.equal('computer_use' in executionSettings({computer_use:true}),false,'a setting saved when computer use existed is dropped');
 assert.equal(executionSettings({assets:'openrouter'}).assets,'openrouter');assert.throws(()=>executionSettings({assets:'dall-e'}),/image assets/);
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
 assert.deepEqual(schema.map(f=>f.key),['concurrency','move_size','merge_kept','assets','routing'],'reasoning is custom and native_craft hidden');
 assert.deepEqual(schema.find(f=>f.key==='merge_kept').options,[{value:true,label:'Merge kept passes'},{value:false,label:'Keep every pass'}]);
 assert.deepEqual(Object.keys(schema[0]).sort(),['accessible','key','label','note','options','tooltip']);
});

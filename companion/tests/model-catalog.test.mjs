import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,readFile,writeFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {inheritPiCatalog} from '../src/model-catalog.mjs';
import {PaintingRuntime} from '../src/runtime.mjs';

const model=(id,input=['text','image'])=>({id,name:id,provider:'deepseek',api:'openai-completions',baseUrl:'https://api.deepseek.com',input,reasoning:false,
  contextWindow:64000,maxTokens:4096,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}});

test('Pi catalog inheritance refreshes matching routes and preserves private custom records without writing Pi files',async()=>{
  const root=await mkdtemp(join(tmpdir(),'creative-catalog-')),pi=join(root,'pi'),output=join(root,'output');
  try{
    await mkdir(pi);await mkdir(output);
    const inherited={deepseek:{lastModified:Number.MAX_SAFE_INTEGER,models:[model('deepseek-flash'),model('deepseek-v4-pro',['text'])]}};
    const privateCatalog={deepseek:{models:[model('deepseek-flash',['text']),model('private-custom')]},privateProvider:{models:[{id:'local-model'}]}};
    const original=JSON.stringify(inherited);await writeFile(join(pi,'models-store.json'),original);
    await writeFile(join(output,'model-catalog.json'),JSON.stringify(privateCatalog));
    const file=await inheritPiCatalog(pi,output),saved=JSON.parse(await readFile(file,'utf8'));
    assert.deepEqual(saved.deepseek.models.find(m=>m.id==='deepseek-flash').input,['text','image']);
    assert.ok(saved.deepseek.models.some(m=>m.id==='private-custom'));
    assert.deepEqual(saved.privateProvider,privateCatalog.privateProvider);
    assert.equal(await readFile(join(pi,'models-store.json'),'utf8'),original);
    await inheritPiCatalog(pi,output);assert.equal(JSON.parse(await readFile(file,'utf8')).deepseek.models.length,3);
    await writeFile(join(pi,'models-store.json'),'{broken');
    const before=await readFile(file,'utf8');await assert.rejects(inheritPiCatalog(pi,output),/model catalog/);assert.equal(await readFile(file,'utf8'),before);
  }finally{await rm(root,{recursive:true,force:true});}
});

test('real SDK initialization inherits official Pi routes, exposes text and batch entries, and restores additional custom connections',async()=>{
  const root=await mkdtemp(join(tmpdir(),'creative-model-runtime-')),pi=join(root,'pi'),output=join(root,'output');
  const events=[],bridge={async connect(){},async call(){return {status:'ok',protocol_version:2};}};
  const create=()=>new PaintingRuntime({root,config:{output,pi_agent_dir:pi},bridge,emit:e=>events.push(e)});
  let runtime;
  try{
    await mkdir(pi);await mkdir(output);
    await writeFile(join(pi,'auth.json'),JSON.stringify({deepseek:{type:'api_key',key:'test-only-auth'}}));
    await writeFile(join(pi,'models-store.json'),JSON.stringify({deepseek:{lastModified:Number.MAX_SAFE_INTEGER,models:[model('deepseek-flash'),model('deepseek-v4-pro',['text']),model('test-batch')]}}));
    await writeFile(join(pi,'models.json'),JSON.stringify({providers:{'pi-custom':{api:'openai-completions',baseUrl:'http://127.0.0.1:1/v1',apiKey:'test-config-only',models:[{...model('pi-custom-model'),provider:undefined}]}}}));
    runtime=create();await runtime.initialize();
    const rows=runtime.listModels();
    assert.ok(rows.some(m=>m.provider==='deepseek'&&m.id==='deepseek-flash'&&m.configured&&m.declared_images_supported));
    assert.ok(rows.some(m=>m.id==='deepseek-v4-pro'&&!m.declared_images_supported&&!m.painting_eligible&&m.interactive));
    assert.ok(rows.some(m=>m.id==='test-batch'&&!m.interactive));
    assert.ok(rows.some(m=>m.provider==='pi-custom'&&m.id==='pi-custom-model'));
    assert.ok(runtime.listProviders().some(p=>p.id==='deepseek'&&p.configured));
    await runtime.configureProvider({provider:'companion-custom',model:'first',base_url:'http://127.0.0.1:1/v1',api_key:'custom-test-only'});
    await runtime.configureProvider({provider:'companion-custom',model:'second',base_url:'http://127.0.0.1:1/v1',api_key:'custom-test-only'});
    assert.ok(!String(await readFile(join(output,'model-connections.json'))).includes('custom-test-only'));
    await runtime.releaseLock();runtime=create();await runtime.initialize();
    assert.ok(runtime.models.getModel('companion-custom','first'));assert.ok(runtime.models.getModel('companion-custom','second'));
    assert.ok(runtime.models.getModel('deepseek','deepseek-flash'));assert.ok(runtime.models.hasConfiguredAuth('companion-custom'));
  }finally{await runtime?.releaseLock();await rm(root,{recursive:true,force:true});}
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {LunaRouter,OPERATIONS,BRUSHES,routingState,routingAdvice,contextIdentity} from '../src/routing.mjs';
import {LunaClient,LUNA_URL,LUNA_MODEL} from '../src/luna-decisions.ts';
import {executionSettings} from '../src/execution-settings.mjs';
import { CRAFT_TOOLS } from '../src/craft.mjs';
const answer=(options,selected,confidence=.95)=>({type:'choice',choice:selected,confidence,probabilities:Object.fromEntries(Object.keys(options).map(k=>[k,k===selected?1:0]))});
const body=(op='move')=>({model:'openai/gpt-6-luna-decisions-20261006',usage:{input_tokens:10,output_tokens:0,cost:.00001},answers:{operation:answer(OPERATIONS,op),brush:answer(BRUSHES,'none')}});
const state=()=>({references:[],capabilities:{gradient:{available:true},smart_patch:{available:true}}});
// fetch stand-in: records requests, honors abort signals like the real fetch.
function fakeFetch(reply) {
 const requests=[];
 const fetch=(url,init)=>{requests.push({url,init,body:JSON.parse(init.body)});
  return new Promise((resolve,reject)=>{
   init.signal?.addEventListener('abort',()=>reject(init.signal.reason),{once:true});
   const r=reply(requests.at(-1));if(r)resolve(r);
  });};
 return {fetch,requests};
}
const json=(status,value)=>new Response(typeof value==='string'?value:JSON.stringify(value),{status});
const image={type:'image',data:'aGVsbG8=',mimeType:'image/png'};

test('one OpenRouter Decisions request yields gated advice without executable arguments',async()=>{
 const {fetch,requests}=fakeFetch(()=>json(200,body()));
 const router=new LunaRouter({apiKey:'sk-or-test',fetch});
 const d=await router.evaluate(state(),{identity:'revision'});
 assert.equal(d.status,'recommended');assert.equal(d.context_identity,'revision');assert.equal(d.image_sent,false);
 assert.equal(requests[0].url,LUNA_URL);assert.equal(requests[0].body.model,LUNA_MODEL);
 assert.equal(requests[0].init.headers.Authorization,'Bearer sk-or-test');
 assert.deepEqual(Object.keys(requests[0].body.questions),['operation','brush']);
 assert.deepEqual(requests[0].body.questions.operation.criteria,OPERATIONS);
 assert.deepEqual(requests[0].body.state.map(p=>p.type),['text']);
 assert.deepEqual(routingAdvice(d).tools,['transform_layer','krita_action','painting_toolbox']);assert.equal(routingAdvice(d).arguments,undefined);
});
test('the attached canvas is sent as a chat-style image_url data URL after the text state',async()=>{
 const {fetch,requests}=fakeFetch(()=>json(200,body()));
 const d=await new LunaRouter({apiKey:'k',fetch}).evaluate(state(),{image});
 assert.equal(d.image_sent,true);
 const parts=requests[0].body.state;
 assert.deepEqual(parts.map(p=>p.type),['text','text','image_url']);
 assert.equal(parts[2].image_url.url,'data:image/png;base64,aGVsbG8=');
 assert.ok(!JSON.stringify(parts).includes('input_image'));
});
test('Agent inspection advice is a preliminary check, not a stop',()=>{
 const decision={status:'recommended',operation:{choice:'inspect'},brush:{choice:'none',confidence:1}};
 const advice=routingAdvice(decision,{phase:'agent'});
 assert.deepEqual(advice.tools,['observe_canvas','split_by_color']);
 assert.match(advice.instruction,/continue painting in this turn/);
 assert.match(advice.instruction,/not a stop/);
});
test('uncertain, mixed, unavailable and malformed recommendations do not guide',async()=>{
 for(const kind of ['uncertain','mixed','unsupported','missing_reference','malformed']) {
  const value=body(kind==='mixed'?'mixed_unknown':kind==='unsupported'?'repair':kind==='missing_reference'?'reference_reconstruct':'draw');
  if(kind==='uncertain')value.answers.operation.confidence=.7;
  if(kind==='malformed')value.answers.operation.probabilities.draw=NaN;
  const {fetch}=fakeFetch(()=>json(200,value));
  const d=await new LunaRouter({apiKey:'k',fetch}).evaluate({...state(),capabilities:{}});assert.equal(d.status,'fallback',kind);assert.equal(routingAdvice(d),null);
 }
});
test('refusal, missing key, errors, cancellation and deadline are bounded fallbacks',async()=>{
 assert.equal((await new LunaRouter().evaluate(state())).reason,'not_connected');
 const refused=fakeFetch(()=>json(502,{error:{message:'OpenAI refused to answer question "operation"',code:502}}));
 assert.equal((await new LunaRouter({apiKey:'k',fetch:refused.fetch}).evaluate(state())).reason,'refused');
 const refusalAnswer=fakeFetch(()=>json(200,{...body(),answers:{operation:{type:'refusal'},brush:answer(BRUSHES,'none')}}));
 assert.equal((await new LunaRouter({apiKey:'k',fetch:refusalAnswer.fetch}).evaluate(state())).reason,'refused');
 for(const reply of [()=>json(401,{error:{message:'Incorrect API key provided: sk-proj-secret'}}),()=>json(200,'not json'),()=>{throw new Error('secret token');}]) {
  const d=await new LunaRouter({apiKey:'k',fetch:fakeFetch(reply).fetch}).evaluate(state());
  assert.equal(d.reason,'service_or_response_error');assert.ok(!JSON.stringify(d).includes('secret'));
 }
 const hanging=fakeFetch(()=>null);
 const controller=new AbortController();controller.abort();
 assert.equal((await new LunaRouter({apiKey:'k',fetch:hanging.fetch}).evaluate(state(),{signal:controller.signal})).reason,'cancelled');
 assert.equal((await new LunaRouter({apiKey:'k',fetch:hanging.fetch,timeout:10}).evaluate(state())).reason,'timeout');
});
test('client rejects non-inline images',async()=>{
 const client=new LunaClient({apiKey:'k',fetch:fakeFetch(()=>json(200,body())).fetch});
 assert.equal((await client.decide({parts:['x','https://example.com/a.png'],questions:{}})).answers!==undefined,true,'plain https text is treated as text, never fetched');
 assert.equal((await client.decide({parts:[{data:'x',mimeType:'text/html'}],questions:{}})).fallback,'service_or_response_error');
});
test('state is bounded, omits pixels and paths, and identities track target changes',()=>{
 const r={secrets:['private-secret'],mode:'agent',goal:{current_step:0,user_updates:['move'],locked_requirements:[]},study:{id:'a',references:[{id:'r',path:'/private/file.png',purpose:'material'}]},canvasSelection:{selected:true},decisionObservation:{document_id:'d',revision:'v',image:'data:image/png;base64,xxx',layers:[{id:'l',name:'/private/layer private-secret'}]}};
 const s=routingState(r,'move /home/artist/file.png private-secret'); const encoded=JSON.stringify(s);
 assert.ok(!encoded.includes('/Users/'));assert.ok(!encoded.includes('/private/'));assert.ok(!encoded.includes('private-secret'));assert.ok(!encoded.includes('base64'));
 const first=contextIdentity(r);r.decisionObservation.revision='new';assert.notEqual(contextIdentity(r),first);
 assert.equal(executionSettings().routing,'guide');assert.throws(()=>executionSettings({routing:'execute'}),/decisions mode/);
});
test('craft intents route to the native craft tools with a how-to hint',async()=>{
 const expected={fill:['fill_region','split_by_color','colorize_flats','painting_toolbox'],gradient:['fill_region','painting_toolbox'],shade:['create_layer','fill_region'],
  light:['create_layer','fill_region'],grade:['apply_filter'],soften:['apply_filter','painting_toolbox'],
  move:['transform_layer','krita_action','painting_toolbox'],transform:['transform_layer','krita_action','painting_toolbox']};
 for(const [op,tools] of Object.entries(expected)) {
  const {fetch}=fakeFetch(()=>json(200,body(op)));
  const d=await new LunaRouter({apiKey:'k',fetch}).evaluate({...state(),capabilities:{}});
  assert.equal(d.status,'recommended',op+' needs no native gradient or patch tool');
  const advice=routingAdvice(d);
  assert.deepEqual(advice.tools,tools,op);
  assert.match(advice.hint,new RegExp(tools[0]),op);
  const strokesOnly=routingAdvice(d,{offered:name=>!CRAFT_TOOLS.includes(name)});
  assert.ok(!strokesOnly.tools.some(t=>tools.includes(t) && t!=='painting_toolbox') && !strokesOnly.hint,op+': native_craft off drops craft tools and hints');
 }
 assert.equal(routingAdvice({status:'recommended',operation:{choice:'draw'},brush:{choice:'none',confidence:1}}).hint,undefined);
});

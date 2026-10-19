// Luna routing accuracy on the intent fixtures (text-only, like the previous
// router's baseline). Pass bar: >= 0.9 on the held-out fixture.
//   doppler run -- node scripts/evaluate-routing.mjs [report.json]
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {getAgentDir,ModelRuntime} from '@earendil-works/pi-coding-agent';
import {LunaRouter} from '../src/routing.mjs';

export async function routingKey() {
 if(process.env.OPENROUTER_API_KEY)return process.env.OPENROUTER_API_KEY;
 try {
  const models=await ModelRuntime.create({authPath:join(getAgentDir(),'auth.json'),modelsPath:null,refreshOnCreate:false});
  return (await models.getAuth('openrouter'))?.auth?.apiKey ?? null;
 } catch {return null;}
}
const capabilities={gradient:{available:true},smart_patch:{available:true}};
export async function evaluateFixture(router,name) {
 const cases=JSON.parse(await readFile(new URL(`../tests/fixtures/${name}.json`,import.meta.url),'utf8'));
 const results=[];
 for(const item of cases) {
  const decision=await router.evaluate({direction:item.text,mode:'agent',references:item.reference?[{id:'fixture',purpose:'likeness'}]:[],capabilities});
  results.push({request:item.text,expected:item.route,status:decision.status,reason:decision.reason,operation:decision.operation,elapsed_ms:decision.elapsed_ms,
   usage:decision.usage,correct:decision.operation?.choice===item.route});
 }
 const answered=results.filter(r=>r.operation).length;
 return {fixture:name,cases:results.length,answered,accuracy:results.filter(r=>r.correct).length/results.length,
  cost:results.reduce((sum,r)=>sum+(r.usage?.cost ?? 0),0),results};
}

if(import.meta.url===`file://${process.argv[1]}`) {
 const key=await routingKey();
 if(!key){console.error('No OpenRouter credential: connect OpenRouter in the Creative Agent or set OPENROUTER_API_KEY. No evaluation was run.');process.exit(2);}
 const router=new LunaRouter({apiKey:key});
 const fixtures=[await evaluateFixture(router,'routing-cases'),await evaluateFixture(router,'routing-heldout-v1'),await evaluateFixture(router,'routing-craft-v1')];
 // The held-out set and the craft intents (shade, light, grade, soften and their near misses) must both meet the bar.
 const gated=fixtures.slice(1);
 const report={at:new Date().toISOString(),router:'openai/gpt-6-luna-decisions via OpenRouter',bar:.9,
  passes:gated.every(f=>f.answered===f.cases && f.accuracy>=.9),fixtures};
 if(process.argv[2])await writeFile(process.argv[2],JSON.stringify(report,null,2)+'\n');
 for(const f of fixtures) {
  console.log(`${f.fixture}: ${Math.round(f.accuracy*f.cases)}/${f.cases} correct (${f.answered} answered), $${f.cost.toFixed(5)}`);
  for(const r of f.results.filter(r=>!r.correct))console.log(`  miss: "${r.request}" expected ${r.expected}, got ${r.operation?.choice ?? r.reason}`);
 }
 console.log(report.passes ? 'PASS: held-out and craft accuracy meet the 0.9 bar.' : 'FAIL: held-out or craft accuracy below the 0.9 bar, or unanswered cases.');
 if(!report.passes)process.exitCode=1;
}

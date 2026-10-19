import test from 'node:test';import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';import {tmpdir} from 'node:os';import {join} from 'node:path';
import {exportDiagnostics} from '../src/diagnostics.mjs';
test('single local report collects chat and errors, excludes secrets/images, tolerates partial session line',async()=>{
 const root=await mkdtemp(join(tmpdir(),'painting-diagnostics-'));try{
 const id='12345678-1234-1234-1234-123456789abc',dir=join(root,'studies',id);await mkdir(join(dir,'sessions'),{recursive:true});
 await writeFile(join(dir,'goal.json'),JSON.stringify({title:'Finish texture'}));
 await writeFile(join(dir,'sessions','chat.jsonl'),JSON.stringify({text:'Paint red',apiKey:'private',content:[{type:'image',data:'largepixels'}]})+'\n{"partial":');
 await writeFile(join(dir,'auth.json'),'SHOULD NEVER READ');await writeFile(join(root,'errors.log'),'RuntimeError: deleted QLabel');
 const result=await exportDiagnostics({stateDirectory:root,studyId:id,logPath:join(root,'errors.log'),snapshot:{target:'painting.kra',token:'known-secret'},redact:s=>s.replaceAll('known-secret','[redacted]')});
 const text=await readFile(result.path,'utf8'),report=JSON.parse(text);
 assert.equal(report.records['goal.json'].title,'Finish texture');assert.match(text,/deleted QLabel/);assert.match(text,/Paint red/);
 for(const secret of ['private','largepixels','known-secret','SHOULD NEVER READ'])assert.ok(!text.includes(secret));
 assert.ok(report.omissions.some(s=>s.includes('incomplete')));assert.equal(result.path,join(root,'diagnostics/latest.json'));
 }finally{await rm(root,{recursive:true,force:true});}
});

import {readFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {exportDiagnostics} from '../../src/diagnostics.mjs';
const stateDirectory=resolve(process.argv[2] || '.creative-agent');
const active=await readFile(join(stateDirectory,'active-session.json'),'utf8').then(JSON.parse).catch(()=>({}));
const result=await exportDiagnostics({stateDirectory,studyId:process.argv[3] || active.id,snapshot:{capture:'Saved files only; active-session marker may differ from the conversation currently displayed.'}});
console.log(result.path);

// @ts-check
/** Inherit Pi's cached route catalog without modifying Pi's files. */
import { readFile, writeFile, rename, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { randomUUID } from 'node:crypto';

async function readObject(path) {
  try {
    const value=JSON.parse((await readFile(path,'utf8')).replace(/^\uFEFF/,''));
    if(!value || typeof value!=='object' || Array.isArray(value))throw new Error('Invalid model catalog object.');
    return value;
  } catch(error) {
    if(error.code==='ENOENT')return {};
    throw new Error('Could not read the local model catalog. Repair its JSON before reconnecting.');
  }
}

export async function inheritPiCatalog(piAgentDirectory,outputDirectory) {
  const destination=join(outputDirectory,'model-catalog.json');
  const [inherited,local]=await Promise.all([readObject(join(piAgentDirectory,'models-store.json')),readObject(destination)]);
  const merged={...local};
  for(const [provider,entry] of Object.entries(inherited)) {
    if(!entry || typeof entry!=='object' || !Array.isArray(entry.models))continue;
    // Pi is authoritative for matching route IDs. Companion-only cached routes
    // survive; models.json overrides are still applied by the SDK afterwards.
    const models=new Map((local[provider]?.models ?? []).map(model=>[model.id,model]));
    for(const model of entry.models)models.set(model.id,model);
    merged[provider]={...local[provider],...entry,models:[...models.values()]};
  }
  await mkdir(dirname(destination),{recursive:true});
  const temporary=destination+'.'+randomUUID()+'.tmp';
  await writeFile(temporary,JSON.stringify(merged,null,2)+'\n',{mode:0o600});
  await rename(temporary,destination);
  return destination;
}

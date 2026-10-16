/** A single local report. Never calls Krita, the model, or a network service. */
import {mkdir,open,readdir,readFile,rename,writeFile} from 'node:fs/promises';
import {join,basename} from 'node:path';
import {homedir} from 'node:os';
import {randomUUID} from 'node:crypto';

export function sanitize(value, redact = text => text) {
  if (Array.isArray(value)) return value.map(item => sanitize(item,redact));
  if (value && typeof value === 'object') {
    if (value.type === 'image' || value.type === 'image_url') return {type:value.type,omitted:'Image bytes omitted from diagnostics'};
    return Object.fromEntries(Object.entries(value).map(([key,item]) => [key,
      /^(api_?key|authorization|access_?token|refresh_?token|password|secret|credentials)$/i.test(key) ? '[redacted]' : sanitize(item,redact)]));
  }
  return typeof value === 'string' ? redact(value).replace(/\bsk-[\w-]{8,}/g,'[redacted]').replace(/Bearer\s+[^\s"']+/gi,'Bearer [redacted]').replace(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/g,'[image omitted]') : value;
}
export async function exportDiagnostics({stateDirectory,studyId,record,sessions=[],snapshot={},redact,logPath=join(homedir(),'Library/Logs/Creative Agent/krita-python-errors.log')}) {
  if (studyId && !/^[a-f0-9-]{36}$/i.test(studyId)) throw new Error('Invalid conversation identifier');
  const report={format:1,captured_at:new Date().toISOString(),conversation_id:studyId ?? null,
    note:'Local snapshot; painting may continue during capture. Image bytes and artwork are excluded. Read omissions for truncated records.',
    live:sanitize(snapshot,redact),records:{},omissions:[]};
  let remaining=16*1024*1024;
  async function capture(path,label,jsonLines=false) {
    let handle;
    try {
      handle=await open(path,'r'); const info=await handle.stat();
      const size=Math.min(info.size,4*1024*1024,remaining);
      if(size<=0){report.omissions.push(label+': report size limit');return;}
      remaining-=size; const bytes=Buffer.alloc(size); const start=info.size-size;
      const {bytesRead}=await handle.read(bytes,0,size,start); let text=bytes.subarray(0,bytesRead).toString('utf8');
      if(start){report.omissions.push(label+': older bytes omitted'); if(jsonLines)text=text.slice(text.indexOf('\n')+1);}
      if(jsonLines) {
        const rows=[]; for(const line of text.split('\n').filter(Boolean)){try{rows.push(JSON.parse(line));}catch{report.omissions.push(label+': incomplete or invalid line omitted');}}
        report.records[label]=sanitize(rows,redact);
      } else {
        try{report.records[label]=sanitize(JSON.parse(text),redact);}catch{report.records[label]=sanitize(text,redact);}
      }
    } catch(error){report.omissions.push(label+': '+error.code);} finally{await handle?.close();}
  }
  if(studyId){
    const chats=join(stateDirectory,'chats',studyId);
    const directory=await readdir(chats).then(()=>chats,()=>join(stateDirectory,'studies',studyId));
    // The chat record lives in SQLite since storage-layout; older chats still have record.json.
    if(record){try{report.records['record.json']=sanitize(JSON.parse(record),redact);}catch{report.omissions.push('record.json: unreadable');}}
    // The plugin's journal database (phase C): receipts and passes.
    {
      const {readRows}=await import('./db.mjs'), journal=join(directory,'journal.sqlite');
      const operations=readRows(journal,'SELECT operation_id, fingerprint, receipt FROM operations ORDER BY updated_at');
      const passes=readRows(journal,'SELECT entry FROM passes ORDER BY seq');
      if(operations.length)report.records['journal/operations']=sanitize(Object.fromEntries(operations.slice(-500).map(r=>[r.operation_id,[r.fingerprint,JSON.parse(r.receipt)]])),redact);
      if(passes.length)report.records['journal/passes']=sanitize(passes.slice(-500).map(r=>JSON.parse(r.entry)),redact);
    }
    // Chat logs from the records database (images are references there), newest first, newest entries kept.
    for(const {label,entries} of [...sessions].sort((a,b)=>b.label.localeCompare(a.label))){
      let kept=entries; while(kept.length && JSON.stringify(kept).length>Math.min(4*1024*1024,remaining)) kept=kept.slice(Math.ceil(kept.length/4));
      if(!kept.length){report.omissions.push(label+': report size limit');continue;}
      if(kept.length<entries.length)report.omissions.push(label+': older entries omitted');
      remaining-=JSON.stringify(kept).length; report.records[label]=sanitize(kept,redact);
    }
    for(const name of ['study.json','goal.json','record.json','resume.json','.progress.json','.operations.json','.passes.json'])if(!(record && name==='record.json'))await capture(join(directory,name),name);
    // Only known diagnostic folders; never traverse references, credentials, or artwork.
    for(const folder of ['sessions','reviews','preparations','recipes']){
      const entries=await readdir(join(directory,folder),{withFileTypes:true}).catch(()=>[]);
      for(const entry of entries.sort((a,b)=>b.name.localeCompare(a.name)))if(entry.isFile() && /\.jsonl?$/.test(entry.name))await capture(join(directory,folder,entry.name),folder+'/'+entry.name,entry.name.endsWith('.jsonl'));
    }
  }
  await capture(join(stateDirectory,'diagnostic-events.jsonl'),'diagnostic-events.jsonl',true);
  await capture(join(stateDirectory,'diagnostic-events.jsonl.previous'),'diagnostic-events.jsonl.previous',true);
  await capture(logPath,'krita-python-errors.log');
  const output=join(stateDirectory,'diagnostics');await mkdir(output,{recursive:true});
  const path=join(output,'latest.json');const temporary=join(output,randomUUID()+'.tmp');
  await writeFile(temporary,JSON.stringify(report,null,2)+'\n',{mode:0o600});await rename(temporary,path);
  return {path,conversation_id:studyId ?? null,omissions:report.omissions.length};
}
